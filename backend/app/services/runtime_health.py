"""Dependency readiness is distinct from process liveness; never expose errors."""
from threading import RLock

from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.initialize import RUNTIME_SCHEMA_VERSION
from app.services.redis_client import get_redis, redis_key
from app.services.runtime_identity import RuntimeIdentity
from app.services.runtime_registry import runtime_accepting
from app.services.worker_process import WorkerProcessState, read_live_identity

WORKER_HEALTH_SECONDS = 30
_process_state = None
_process_lock = RLock()


def worker_owners_key():
    return worker_health_key()+':owners'


def process_slot(identity):
    # Separate explicitly configured local worker directories without merging
    # their ownership merely because they share a machine hostname. Docker's
    # private /tmp and container hostname keep replica slots distinct.
    return identity.hostname+'-'+identity.scope


def worker_health_key():
    # A target pool must have its own worker even when both colors run the same
    # SHA. Keep sandbox labels/queue namespaces shared for old-claim recovery.
    # This gate alone does not prove per-instance drain or version compatibility.
    return redis_key('health', 'workers-v2', settings.RUNTIME_POOL_ID,
                     settings.DEPLOYMENT_SHA or 'unversioned',
                     settings.RUNTIME_INSTANCE_ID or 'local')


def dependencies_ready(*, require_worker=True):
    try:
        with engine.connect() as connection:
            if connection.execute(text('SELECT 1 FROM schema_migrations WHERE version=:version'),
                    {'version':RUNTIME_SCHEMA_VERSION}).first() is None:
                return False
            if settings.RUNTIME_INSTANCE_ID and not runtime_accepting(connection,RuntimeIdentity.configured()):
                return False
        client = get_redis()
        if client is None or not client.ping():
            return False
        if require_worker:
            return bool(client.eval("""local t=redis.call('TIME');
                local members=redis.call('ZRANGEBYSCORE',KEYS[1],tonumber(t[1])+1,'+inf');
                for _,member in ipairs(members) do
                    local host,epoch=string.match(member,'^([^:]+):([a-f0-9]+)$');
                    if host and redis.call('HGET',KEYS[2],host)==epoch then return 1 end;
                end; return 0""",2,worker_health_key(),worker_owners_key()))
        return True
    except Exception:
        return False


def _owned_identity():
    if _process_state is None:
        raise RuntimeError('Worker process identity not initialized')
    return _process_state.current()


def _publishing_identity():
    if getattr(_process_state,'readiness_revoked',False):
        raise RuntimeError('Worker process readiness revoked')
    return _owned_identity()


def worker_process_identity():
    """Bind lanes to this owned process, never to a new import-time UUID."""
    with _process_lock:
        return _publishing_identity()


def _register(client, identity, *, replace_owner=False):
    return client.eval("""local old=redis.call('HGET',KEYS[2],ARGV[1]);
        if old and old~=ARGV[2] and ARGV[4]~='1' then return 0 end;
        if old and old~=ARGV[2] then redis.call('ZREM',KEYS[1],ARGV[1]..':'..old) end;
        if not old then redis.call('ZREM',KEYS[1],ARGV[1]..':'..ARGV[2]) end;
        redis.call('HSET',KEYS[2],ARGV[1],ARGV[2]);
        redis.call('EXPIRE',KEYS[2],tonumber(ARGV[3])*2); return 1""",
        2,worker_health_key(),worker_owners_key(),process_slot(identity),identity.epoch,
        WORKER_HEALTH_SECONDS,'1' if replace_owner else '0')


def start_worker_process():
    global _process_state
    with _process_lock:
        if _process_state is not None:
            raise RuntimeError('Worker process already initialized')
        state = WorkerProcessState()
        try:
            identity = state.start()
            client = get_redis()
            if client is not None:
                if not _register(client,identity,replace_owner=True):
                    raise RuntimeError('Worker process ownership unavailable')
            elif settings.ENVIRONMENT == 'production':
                raise RuntimeError('Worker process requires shared readiness store')
            _process_state = state
            return identity
        except BaseException:
            state.close()
            raise


def ensure_worker_process_registered():
    with _process_lock:
        identity = _publishing_identity()
        client = get_redis()
        if client is None or not _register(client,identity):
            raise RuntimeError('Worker process no longer owns readiness')


def report_worker_ready():
    with _process_lock:
        identity = _publishing_identity()
        client = get_redis()
        if client is None:
            raise RuntimeError('Shared readiness store unavailable')
        published = client.eval("""if redis.call('HGET',KEYS[2],ARGV[1])~=ARGV[2] then return 0 end;
            local t=redis.call('TIME'); local now=tonumber(t[1]);
            redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now);
            redis.call('ZADD',KEYS[1],now+tonumber(ARGV[3]),ARGV[1]..':'..ARGV[2]);
            redis.call('EXPIRE',KEYS[1],tonumber(ARGV[3])*2);
            redis.call('EXPIRE',KEYS[2],tonumber(ARGV[3])*2); return 1""",
            2,worker_health_key(),worker_owners_key(),process_slot(identity),identity.epoch,WORKER_HEALTH_SECONDS)
        if not published:
            raise RuntimeError('Worker process publication fenced')


def _withdraw(identity, *, revoke=False):
    client = get_redis()
    if client is not None:
        client.eval("""redis.call('ZREM',KEYS[1],ARGV[1]..':'..ARGV[2]);
            if ARGV[3]=='1' and redis.call('HGET',KEYS[2],ARGV[1])==ARGV[2] then
                redis.call('HSET',KEYS[2],ARGV[1],'revoked:'..ARGV[2]);
                redis.call('EXPIRE',KEYS[2],tonumber(ARGV[4])*2);
            end; return 1""",2,worker_health_key(),worker_owners_key(),
            process_slot(identity),identity.epoch,'1' if revoke else '0',WORKER_HEALTH_SECONDS)


def withdraw_worker():
    with _process_lock:
        if _process_state is not None:
            _withdraw(_owned_identity())


def stop_worker_process(*, expected=None):
    global _process_state
    # Await any in-flight threaded publish before revoking. A delayed task
    # entering afterward sees no owner; it cannot recreate a ready marker.
    with _process_lock:
        if expected is not None and (_process_state is None or _process_state.identity != expected):
            return False
        state, _process_state = _process_state, None
        if state is not None:
            try:
                _withdraw(state.identity,revoke=True)
            finally:
                state.close()


def revoke_worker_readiness():
    # Revoke before waiting for long-running claims. The lifetime lock remains
    # held until actual process shutdown, but no queued report can reopen it.
    with _process_lock:
        if _process_state is not None:
            _process_state.readiness_revoked = True
            _withdraw(_process_state.identity,revoke=True)


def this_worker_ready():
    try:
        identity = read_live_identity()
        if settings.RUNTIME_INSTANCE_ID and not runtime_accepting(engine,RuntimeIdentity.configured()):
            return False
        client = get_redis()
        return bool(client and client.eval("""if redis.call('HGET',KEYS[2],ARGV[1])~=ARGV[2] then return 0 end;
            local t=redis.call('TIME'); local until_at=redis.call('ZSCORE',KEYS[1],ARGV[1]..':'..ARGV[2]);
            return until_at and tonumber(until_at)>tonumber(t[1]) and 1 or 0""",
            2,worker_health_key(),worker_owners_key(),process_slot(identity),identity.epoch))
    except Exception:
        return False
