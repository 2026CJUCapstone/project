"""ASGI-level drain gate: account for the entire response/connection lifetime."""
import asyncio
import logging
from threading import Lock

from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)


class PendingAdmission:
    """Cancellation may race a thread that has committed the active record."""
    def __init__(self,service,kind):
        self.service,self.kind = service,kind
        self._lock = Lock()
        self._abandoned = False
        self._request_id = None

    def start(self):
        request_id = self.service.begin(self.kind)
        with self._lock:
            abandoned = self._abandoned
            if not abandoned:
                self._request_id = request_id
        if abandoned and request_id is not None:
            self.service.finish(request_id)
        return None if abandoned else request_id

    def abandon(self):
        with self._lock:
            self._abandoned = True
            request_id,self._request_id = self._request_id,None
        if request_id is not None:
            self.service.finish(request_id)


class RuntimeAdmissionMiddleware:
    def __init__(self,app):
        self.app = app
        self.rejection_cors = CORSMiddleware(self._reject, allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True, allow_methods=['*'], allow_headers=['*'],
            expose_headers=['X-Total-Count','Retry-After'])

    async def reject(self,scope,receive,send):
        headers = Headers(scope=scope)
        if scope['type'] == 'http' and 'origin' in headers:
            # Add the same CORS response policy without dispatching preflight:
            # a denied OPTIONS must remain 503, not turn into CORS's own 200.
            return await self.rejection_cors.simple_response(scope,receive,send,request_headers=headers)
        return await self._reject(scope,receive,send)

    async def _reject(self,scope,receive,send):
        if scope['type'] == 'websocket':
            await send({'type':'websocket.close','code':1013,'reason':'서버가 새 연결을 받을 수 없습니다.'})
        else:
            response = JSONResponse({'detail':'서버가 새 요청을 받을 수 없습니다. 잠시 후 다시 시도해 주세요.'},
                status_code=503,headers={'Cache-Control':'no-store','Retry-After':'1','Connection':'close'})
            await response(scope,receive,send)

    async def __call__(self,scope,receive,send):
        kind = scope['type']
        if kind not in ('http','websocket'):
            return await self.app(scope,receive,send)
        if kind == 'http' and scope.get('method') in ('GET','HEAD') and scope.get('path') in ('/health','/ready'):
            return await self.app(scope,receive,send)
        if not settings.RUNTIME_INSTANCE_ID and settings.ENVIRONMENT != 'production':
            return await self.app(scope,receive,send)  # Unmanaged local mode has no retirement evidence.
        service = getattr(getattr(scope.get('app'),'state',None),'runtime_requests',None)
        if service is None:
            return await self.reject(scope,receive,send)
        pending = PendingAdmission(service,kind)
        try:
            request_id = await asyncio.to_thread(pending.start)
        except asyncio.CancelledError:
            # The underlying thread is not canceled. Whichever side observes
            # abandonment second releases its committed record, never a peer's.
            await asyncio.shield(asyncio.to_thread(pending.abandon))
            raise
        except Exception:
            logger.warning('Runtime request admission unavailable')
            return await self.reject(scope,receive,send)
        if request_id is None:
            return await self.reject(scope,receive,send)
        try:
            await self.app(scope,receive,send)
        finally:
            try:
                await asyncio.shield(asyncio.to_thread(service.finish,request_id))
            except asyncio.CancelledError:
                raise  # Shielded finish keeps running; a crash remains unresolved evidence.
            except Exception:
                logger.warning('Runtime request completion could not be recorded')
