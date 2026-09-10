"""Isolated identity/limiter probe only; never imported by the product app."""
import os

from fastapi import FastAPI, HTTPException, Request, WebSocket

from app.core.config import settings
from app.services.execution_admission import admit_execution, execution_ip
from app.services.trusted_ingress import TrustedIngressMiddleware

app = FastAPI()
app.add_middleware(TrustedIngressMiddleware, networks=settings.TRUSTED_PROXY_CIDRS)


def identity(connection):
    return {'ip': execution_ip(connection), 'scheme': connection.scope['scheme'], 'pid': os.getpid()}


@app.get('/audit/identity')
def inspect_identity(request: Request):
    return identity(request)


@app.get('/api/audit/limited')
def limited(request: Request):
    admit_execution(request)
    return identity(request)


@app.websocket('/ws/terminal')
async def websocket_identity(websocket: WebSocket):
    try:
        admit_execution(websocket)
    except HTTPException:
        await websocket.close(code=1013)
        return
    await websocket.accept()
    await websocket.send_json(identity(websocket))
    await websocket.close()
