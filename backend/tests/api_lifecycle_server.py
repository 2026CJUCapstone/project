"""Test-only held streaming/WS routes on the real production app lifecycle."""
import asyncio

from fastapi import WebSocket
from fastapi.responses import StreamingResponse

from app.main import app

released = asyncio.Event()


@app.get('/audit-stream')
async def held_stream():
    async def chunks():
        yield b'first\n'
        await asyncio.wait_for(released.wait(), 20)
        yield b'last\n'
    return StreamingResponse(chunks(), media_type='text/plain')


@app.websocket('/audit-socket')
async def held_socket(socket: WebSocket):
    await socket.accept()
    await socket.send_text('connected')
    while True:
        message = await socket.receive_text()
        if message == 'release':
            released.set()
            await socket.send_text('released')
        elif message == 'close':
            await socket.close(code=1000)
            return


@app.get('/audit-ping')
async def ping():
    return {'ok':True}
