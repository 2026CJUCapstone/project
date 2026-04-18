import asyncio
import contextlib
import json
import shutil
import socket
import tempfile
import uuid
from pathlib import Path
from typing import Any

from docker.errors import APIError, DockerException
from docker.types import Ulimit
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services.compiler import SUPPORTED_LANGUAGES, DockerCompilerRunner, SandboxExecutionError

router = APIRouter()


async def _receive_start_payload(websocket: WebSocket) -> dict[str, Any]:
    try:
        raw_payload = await websocket.receive_text()
        payload = json.loads(raw_payload)
    except WebSocketDisconnect:
        raise
    except json.JSONDecodeError:
        raise ValueError("터미널 시작 메시지가 올바르지 않습니다.")

    if payload.get("type") != "start":
        raise ValueError("터미널 시작 메시지가 필요합니다.")

    code = payload.get("code", "")
    language = payload.get("language", "bpp")

    if not isinstance(code, str) or not code.strip():
        raise ValueError("실행할 코드가 없습니다.")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"지원하지 않는 언어입니다: {language}")

    return payload


@router.websocket("/ws/terminal")
async def terminal_endpoint(websocket: WebSocket):
    await websocket.accept()

    runner = DockerCompilerRunner()
    temp_dir: Path | None = None
    container = None
    raw_sock = None

    try:
        payload = await _receive_start_payload(websocket)
        language = payload.get("language", "bpp")
        source_code = payload["code"]
        optimize = bool(payload.get("optimize", False))

        sandbox_root = Path(settings.SANDBOX_WORKDIR_ROOT)
        sandbox_root.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="terminal-", dir=sandbox_root))
        temp_dir.chmod(0o755)

        source_path = temp_dir / runner._resolve_filename(language, source_code)
        source_path.write_text(source_code, encoding="utf-8")
        source_path.chmod(0o644)

        await websocket.send_text(f"> {language.upper()} 컴파일 및 실행을 시작합니다.\n")

        client = runner._get_client()
        container = await asyncio.to_thread(
            client.containers.create,
            image=settings.SANDBOX_IMAGE,
            command=["run", language, f"/workspace/{source_path.name}"],
            detach=True,
            name=f"compiler-terminal-{uuid.uuid4().hex[:12]}",
            stdin_open=True,
            tty=True,
            network_disabled=True,
            read_only=True,
            tmpfs={"/tmp": f"rw,exec,nosuid,size={settings.SANDBOX_MEMORY_MB}m"},
            mem_limit=f"{settings.SANDBOX_MEMORY_MB}m",
            nano_cpus=max(1, int(settings.SANDBOX_CPU_LIMIT * 1_000_000_000)),
            pids_limit=settings.SANDBOX_PIDS_LIMIT,
            ulimits=[Ulimit(name="nofile", soft=settings.SANDBOX_NOFILE_LIMIT, hard=settings.SANDBOX_NOFILE_LIMIT)],
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            volumes={str(temp_dir): {"bind": "/workspace", "mode": "ro"}},
            environment={
                "COMPILER_OPTIMIZE": "1" if optimize else "0",
                "HOME": "/tmp",
            },
        )

        sock = await asyncio.to_thread(
            container.attach_socket,
            params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1},
        )
        raw_sock = getattr(sock, "_sock", sock)
        raw_sock.settimeout(0.5)
        await asyncio.to_thread(container.start)

        async def side_reader() -> None:
            while True:
                try:
                    data = await asyncio.to_thread(raw_sock.recv, 4096)
                except (TimeoutError, socket.timeout):
                    continue
                except OSError:
                    break
                if not data:
                    break
                await websocket.send_text(data.decode("utf-8", errors="replace"))

        async def side_writer() -> None:
            try:
                while True:
                    user_input = await websocket.receive_text()
                    await asyncio.to_thread(raw_sock.sendall, user_input.encode("utf-8"))
            except WebSocketDisconnect:
                pass
            except OSError:
                pass

        async def exit_watcher() -> None:
            result = await asyncio.to_thread(container.wait)
            exit_code = int(result.get("StatusCode", 1))
            await asyncio.sleep(0.2)
            await websocket.send_text(f"\n> 프로그램이 종료되었습니다. (exit code {exit_code})\n")

        async def timeout_watcher() -> None:
            await asyncio.sleep(max(1, settings.TERMINAL_SESSION_TIMEOUT))
            await websocket.send_text("\n> 터미널 세션 시간이 초과되었습니다.\n")
            with contextlib.suppress(DockerException, APIError):
                await asyncio.to_thread(container.kill)

        reader_task = asyncio.create_task(side_reader())
        session_tasks = {
            asyncio.create_task(side_writer()),
            asyncio.create_task(exit_watcher()),
            asyncio.create_task(timeout_watcher()),
        }
        _, pending = await asyncio.wait(session_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        reader_task.cancel()
    except (ValueError, SandboxExecutionError) as exc:
        await websocket.send_text(f"> {exc}\n")
    except WebSocketDisconnect:
        pass
    except (DockerException, APIError) as exc:
        await websocket.send_text(f"> Docker 샌드박스 실행 중 오류가 발생했습니다: {exc}\n")
    except Exception as exc:
        await websocket.send_text(f"> 터미널 실행 중 오류가 발생했습니다: {exc}\n")
    finally:
        with contextlib.suppress(Exception):
            if raw_sock is not None:
                raw_sock.close()
        with contextlib.suppress(Exception):
            if container is not None:
                await asyncio.to_thread(container.kill)
        with contextlib.suppress(Exception):
            if container is not None:
                await asyncio.to_thread(container.remove, force=True)
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
        with contextlib.suppress(Exception):
            await websocket.close()
