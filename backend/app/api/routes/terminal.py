import asyncio
import contextlib
import socket

import docker
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.config import settings

router = APIRouter()

@router.websocket("/ws/terminal")
async def terminal_endpoint(websocket: WebSocket):
    await websocket.accept()

    client = docker.from_env()
    container = await asyncio.to_thread(
        client.containers.run,
        settings.SANDBOX_IMAGE,
        ["-i", "-u"],
        entrypoint="python3",
        stdin_open=True,
        tty=True,
        network_disabled=True,
        detach=True,
        remove=False,
    )
    sock = await asyncio.to_thread(
        container.attach_socket,
        params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1},
    )
    raw_sock = getattr(sock, "_sock", sock)
    raw_sock.settimeout(0.5)

    async def side_reader(ws: WebSocket):
        """Docker 컨테이너의 출력을 웹소켓으로 전달"""
        while True:
            try:
                data = await asyncio.to_thread(raw_sock.recv, 1024)
            except (TimeoutError, socket.timeout):
                continue
            if not data:
                break
            await ws.send_text(data.decode())

    async def side_writer(ws: WebSocket):
        """웹소켓의 입력을 Docker의 stdin으로 전달"""
        try:
            while True:
                user_input = await ws.receive_text()
                await asyncio.to_thread(raw_sock.sendall, user_input.replace("\n", "\r").encode())
        except WebSocketDisconnect:
            pass

    reader = asyncio.create_task(side_reader(websocket))
    writer = asyncio.create_task(side_writer(websocket))
    try:
        await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
    except Exception as e:
        print(f"Terminal Error: {e}")
    finally:
        reader.cancel()
        writer.cancel()
        with contextlib.suppress(Exception):
            raw_sock.close()
        with contextlib.suppress(Exception):
            await asyncio.to_thread(container.kill)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(container.remove, force=True)
        with contextlib.suppress(Exception):
            await websocket.close()
