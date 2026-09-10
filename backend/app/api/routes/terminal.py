"""WebSocket admission and Redis relay only; Docker is worker-owned."""
import asyncio
import contextlib
import json
import uuid
from typing import get_args

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schemas import CompilerLanguage
from app.services.execution_admission import admit_execution, admit_execution_user, execution_ip
from app.services.execution_runtime import execution_queue
from app.services.durable_queue import QueueFull
from app.services.terminal_broker import TerminalBroker, TerminalClosed, TerminalLimit, TerminalUnavailable

router = APIRouter()


async def _receive_start_payload(websocket):
    raw = await asyncio.wait_for(websocket.receive_text(), timeout=settings.TERMINAL_START_TIMEOUT)
    if len(raw.encode('utf-8')) > settings.SUBMISSION_CODE_MAX_BYTES + 4096:
        raise ValueError('터미널 시작 메시지가 너무 큽니다.')
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError('터미널 시작 메시지가 올바르지 않습니다.') from None
    if not isinstance(payload,dict) or payload.get('type') != 'start':
        raise ValueError('터미널 시작 메시지가 필요합니다.')
    code, language = payload.get('code',''), payload.get('language','bpp')
    if not isinstance(code,str) or not code.strip():
        raise ValueError('실행할 코드가 없습니다.')
    if len(code.encode('utf-8')) > settings.SUBMISSION_CODE_MAX_BYTES:
        raise ValueError('실행할 코드가 너무 큽니다.')
    if language not in get_args(CompilerLanguage):
        raise ValueError('지원하지 않는 언어입니다.')
    token = payload.get('token')
    if token is not None and (not isinstance(token,str) or len(token)>2048):
        raise ValueError('로그인 토큰이 올바르지 않습니다.')
    return payload


def accept_terminal(sid, payload, ip, broker):
    from app.api.routes.auth import get_current_user
    with SessionLocal() as db:
        user = get_current_user(payload['token'], db) if payload.get('token') else None
        if user:
            admit_execution_user(user.id)
            broker.bind_user(sid,user.id)
        owner = f'account:{user.id}' if user else 'terminal:'+sid
        quota = f'account:{user.id}' if user else 'ip:'+ip
        job = execution_queue().enqueue_in_session(db, owner_key=owner, quota_key=quota, request_id='terminal:'+sid,
            kind='terminal', payload={'terminal_session':sid, 'code':payload['code'],
                'language':payload.get('language','bpp'), 'optimize':bool(payload.get('optimize',False))})
        db.commit()
        return job.id, owner


@router.websocket('/terminal')
async def terminal_endpoint(websocket: WebSocket):
    if websocket.headers.get('origin') not in settings.CORS_ORIGINS:
        await websocket.close(code=1008)
        return
    sid, broker = uuid.uuid4().hex, None
    try:
        await asyncio.to_thread(admit_execution, websocket)
        broker = await asyncio.to_thread(TerminalBroker)
        await asyncio.to_thread(broker.reserve,sid,execution_ip(websocket))
    except (HTTPException,TerminalUnavailable,TerminalLimit):
        await websocket.close(code=1013)
        return
    tasks, close_code = [], 1011
    async def send(value):
        await asyncio.wait_for(websocket.send_text(value), timeout=3)
    try:
        await websocket.accept()
        payload = await _receive_start_payload(websocket)
        job_id, owner = await asyncio.to_thread(accept_terminal,sid,payload,execution_ip(websocket),broker)
        await send('> 실행 대기열에 등록되었습니다.\n')

        async def incoming():
            while True:
                value = await websocket.receive_text()
                await asyncio.to_thread(broker.send_input,sid,value)

        async def outgoing():
            cursor = '0-0'
            queue = execution_queue()
            while True:
                rows = await asyncio.to_thread(broker.read_output,sid,cursor)
                for cursor, fields in rows:
                    await send(fields['text'])
                state = await asyncio.to_thread(queue.read,job_id,owner_key=owner)
                if state and state['status'] in ('completed','failed'):
                    # Completion follows publication. Drain the last output first.
                    while True:
                        tail = await asyncio.to_thread(broker.read_output,sid,cursor)
                        if not tail:
                            break
                        for cursor, fields in tail:
                            await send(fields['text'])
                    result = state['result'] or {}
                    code = (result.get('value') or {}).get('exit_code')
                    if code is not None:
                        await send(f'\n> 프로그램이 종료되었습니다. (exit code {code})\n')
                    else:
                        await send('\n> '+result.get('message','터미널 실행이 중단되었습니다. 자동으로 다시 실행하지 않습니다.')+'\n')
                    return 1000 if code is not None else 1011
                await asyncio.sleep(.15)

        async def heartbeat():
            while True:
                await asyncio.sleep(max(.05,settings.TERMINAL_CONNECTION_LEASE_SECONDS/3))
                if not await asyncio.to_thread(broker.renew,sid):
                    raise TerminalClosed()

        reader, writer, pulse = [asyncio.create_task(coro) for coro in (incoming(),outgoing(),heartbeat())]
        tasks = [reader,writer,pulse]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED,
                                     timeout=settings.TERMINAL_SESSION_TIMEOUT)
        if not done:
            raise TimeoutError()
        if writer in done:
            close_code = writer.result()
        else:
            next(iter(done)).result()
    except WebSocketDisconnect:
        close_code = 1001
    except TimeoutError:
        with contextlib.suppress(Exception):
            await send('> 터미널 시작 대기 시간 또는 세션 시간이 초과되었습니다.\n')
    except (ValueError,TerminalLimit) as exc:
        close_code = 1008
        with contextlib.suppress(Exception):
            await send('> '+str(exc)+'\n')
    except (QueueFull,TerminalUnavailable,TerminalClosed,HTTPException):
        with contextlib.suppress(Exception):
            await send('> 터미널 연결을 계속할 수 없습니다. 자동으로 다시 실행하지 않습니다.\n')
    except Exception:
        with contextlib.suppress(Exception):
            await send('> 터미널 서비스를 사용할 수 없습니다.\n')
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)
        # A crashed API is detected by Redis lease expiry. Releasing a socket
        # never releases the independent SQL execution capacity.
        with contextlib.suppress(Exception):
            await asyncio.to_thread(broker.close,sid)
        with contextlib.suppress(Exception):
            await websocket.close(code=close_code)
