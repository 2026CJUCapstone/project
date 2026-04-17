import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.config import settings

router = APIRouter()

@router.websocket("/ws/terminal")
async def terminal_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # 예시로 파이썬 인터프리터를 실행한다고 가정
    proc = await asyncio.create_subprocess_exec(
        "docker", "run", "--rm", "-i", "--network", "none",
        settings.SANDBOX_IMAGE, "python3", "-u", "-c", "import sys; exec(sys.stdin.read())",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def side_reader(stream, ws: WebSocket):
        """Docker의 출력을 웹소켓으로 전달"""
        while True:
            data = await stream.read(1024)
            if not data:
                break
            await ws.send_text(data.decode())

    async def side_writer(ws: WebSocket, stdin):
        """웹소켓의 입력을 Docker의 stdin으로 전달"""
        try:
            while True:
                user_input = await ws.receive_text()
                stdin.write(user_input.encode())
                await stdin.drain()
        except WebSocketDisconnect:
            pass

    try:
        await asyncio.gather(
            side_reader(proc.stdout, websocket),
            side_reader(proc.stderr, websocket),
            side_writer(websocket, proc.stdin)
        )
    except Exception as e:
        print(f"Terminal Error: {e}")
    finally:
        if proc.returncode is None:
            proc.terminate()
        await websocket.close()
