"""Bounded transient terminal transport. Durable code/claims remain in SQL.

Redis loss closes sessions; it never releases SQL execution slots or replays
interactive input. All admission and byte/message budgets use atomic scripts.
"""
import hashlib
import re

from app.core.config import settings
from app.services.redis_client import get_redis, redis_key


class TerminalUnavailable(Exception):
    pass


class TerminalLimit(Exception):
    pass


class TerminalClosed(Exception):
    pass


TIME = "local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000); "
LIVE = TIME + "if redis.call('HGET',KEYS[1],'state')~='live' or tonumber(redis.call('HGET',KEYS[1],'lease') or 0)<=now then return 0 end; "


class TerminalBroker:
    def __init__(self, client=None):
        self.client = client or get_redis()
        if self.client is None:
            raise TerminalUnavailable('Terminal transport unavailable')

    def keys(self, sid):
        if not re.fullmatch('[a-f0-9]{32}', sid):
            raise ValueError('Invalid terminal session')
        base = redis_key('terminal', sid)
        return base+':meta', base+':input', base+':output'

    def eval(self, script, keys, *args):
        try:
            return self.client.eval(script, len(keys), *keys, *args)
        except Exception:
            raise TerminalUnavailable('Terminal transport unavailable') from None

    def reserve(self, sid, ip):
        meta, _, _ = self.keys(sid)
        global_key = redis_key('terminal','connections')
        ip_key = redis_key('terminal','ip',hashlib.sha256(ip.encode()).hexdigest())
        result = self.eval(TIME + """
            redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now)
            redis.call('ZREMRANGEBYSCORE',KEYS[2],'-inf',now)
            if redis.call('EXISTS',KEYS[3])==1 then return -1 end
            if redis.call('ZCARD',KEYS[1])>=tonumber(ARGV[2]) or redis.call('ZCARD',KEYS[2])>=tonumber(ARGV[3]) then return 0 end
            local deadline=now+tonumber(ARGV[4]); local lease=math.min(deadline,now+tonumber(ARGV[5]))
            redis.call('ZADD',KEYS[1],lease,ARGV[1]); redis.call('ZADD',KEYS[2],lease,ARGV[1])
            redis.call('HSET',KEYS[3],'state','live','deadline',deadline,'lease',lease,'ipkey',KEYS[2],'globalkey',KEYS[1])
            for _,key in ipairs(KEYS) do redis.call('PEXPIRE',key,tonumber(ARGV[4])+60000) end
            return 1
        """, [global_key,ip_key,meta], sid, settings.TERMINAL_MAX_CONNECTIONS,
            settings.TERMINAL_MAX_CONNECTIONS_PER_IDENTITY, settings.TERMINAL_SESSION_TIMEOUT*1000,
            settings.TERMINAL_CONNECTION_LEASE_SECONDS*1000)
        if result != 1:
            raise TerminalLimit('터미널 연결이 많습니다. 잠시 후 다시 시도하세요.')

    def bind_user(self, sid, user_id):
        meta, _, _ = self.keys(sid)
        key = redis_key('terminal','user',hashlib.sha256(user_id.encode()).hexdigest())
        result = self.eval(LIVE + """
            redis.call('ZREMRANGEBYSCORE',KEYS[2],'-inf',now)
            local old=redis.call('HGET',KEYS[1],'userkey')
            if old then return old==KEYS[2] and 1 or 0 end
            if redis.call('ZCARD',KEYS[2])>=tonumber(ARGV[2]) then return 0 end
            redis.call('ZADD',KEYS[2],redis.call('HGET',KEYS[1],'lease'),ARGV[1])
            redis.call('HSET',KEYS[1],'userkey',KEYS[2]); redis.call('PEXPIRE',KEYS[2],tonumber(ARGV[3])+60000)
            return 1
        """, [meta,key], sid, settings.TERMINAL_MAX_CONNECTIONS_PER_IDENTITY, settings.TERMINAL_SESSION_TIMEOUT*1000)
        if result != 1:
            raise TerminalLimit('계정의 터미널 연결 한도를 초과했습니다.')

    def renew(self, sid):
        meta, _, _ = self.keys(sid)
        return self.eval(LIVE + """
            local lease=math.min(tonumber(redis.call('HGET',KEYS[1],'deadline')),now+tonumber(ARGV[2]))
            if lease<=now then return 0 end
            redis.call('HSET',KEYS[1],'lease',lease)
            for _,field in ipairs({'globalkey','ipkey','userkey'}) do
                local key=redis.call('HGET',KEYS[1],field); if key then redis.call('ZADD',key,lease,ARGV[1]) end
            end
            return 1
        """, [meta], sid, settings.TERMINAL_CONNECTION_LEASE_SECONDS*1000) == 1

    def active(self, sid):
        return self.eval(LIVE+'return 1', [self.keys(sid)[0]]) == 1

    def close(self, sid):
        meta, _, _ = self.keys(sid)
        self.eval("""
            if redis.call('EXISTS',KEYS[1])==0 then return 0 end
            redis.call('HSET',KEYS[1],'state','closed')
            for _,field in ipairs({'globalkey','ipkey','userkey'}) do
                local key=redis.call('HGET',KEYS[1],field); if key then redis.call('ZREM',key,ARGV[1]) end
            end
            redis.call('PEXPIRE',KEYS[1],60000); return 1
        """, [meta], sid)

    def send_input(self, sid, value):
        meta, inputs, _ = self.keys(sid)
        result = self.eval(LIVE+"""
            if tonumber(redis.call('HGET',KEYS[1],'input_bytes') or 0)+string.len(ARGV[1])>tonumber(ARGV[2]) or redis.call('LLEN',KEYS[2])>=1024 then return -1 end
            redis.call('HINCRBY',KEYS[1],'input_bytes',string.len(ARGV[1]))
            redis.call('RPUSH',KEYS[2],ARGV[1]); redis.call('PEXPIRE',KEYS[2],tonumber(ARGV[3])+60000); return 1
        """, [meta,inputs], value, settings.TERMINAL_INPUT_MAX_BYTES, settings.TERMINAL_SESSION_TIMEOUT*1000)
        self._accepted(result, '입력 용량 제한을 초과했습니다.')

    def take_input(self, sid):
        meta, inputs, _ = self.keys(sid)
        result = self.eval(LIVE+"return {1,redis.call('LPOP',KEYS[2]) or ''}", [meta,inputs])
        if not isinstance(result,list):
            raise TerminalClosed()
        return result[1]

    def publish(self, sid, value):
        meta, _, output = self.keys(sid)
        result = self.eval(LIVE+"""
            if tonumber(redis.call('HGET',KEYS[1],'output_bytes') or 0)+string.len(ARGV[1])>tonumber(ARGV[2]) or redis.call('XLEN',KEYS[2])>=4096 then return -1 end
            redis.call('HINCRBY',KEYS[1],'output_bytes',string.len(ARGV[1]))
            redis.call('XADD',KEYS[2],'*','text',ARGV[1]); redis.call('PEXPIRE',KEYS[2],tonumber(ARGV[3])+60000); return 1
        """, [meta,output], value, settings.SANDBOX_OUTPUT_MAX_BYTES, settings.TERMINAL_SESSION_TIMEOUT*1000)
        self._accepted(result, '출력 용량 제한을 초과했습니다.')

    def read_output(self, sid, cursor='0-0'):
        try:
            values = self.client.xread({self.keys(sid)[2]:cursor}, count=64)
            return values[0][1] if values else []
        except Exception:
            raise TerminalUnavailable('Terminal transport unavailable') from None

    @staticmethod
    def _accepted(result, message):
        if result == -1:
            raise TerminalLimit(message)
        if result != 1:
            raise TerminalClosed()
