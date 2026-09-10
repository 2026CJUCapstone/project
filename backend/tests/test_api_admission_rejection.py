"""Safe ASGI rejection behavior for unavailable runtime admission."""

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.api_admission import RuntimeAdmissionMiddleware


@pytest.fixture(autouse=True)
def managed_runtime(monkeypatch):
    monkeypatch.setattr(settings, "RUNTIME_INSTANCE_ID", "a" * 32)


def asgi_scope(service=None, *, kind="http", origin=None):
    headers = [] if origin is None else [(b"origin", origin.encode())]
    scope = {
        "type": kind,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/test",
        "raw_path": b"/api/v1/test",
        "query_string": b"",
        "headers": headers,
        "client": ("test-client", 1234),
        "server": ("test-server", 8000),
    }
    if service is not None:
        scope["app"] = SimpleNamespace(
            state=SimpleNamespace(runtime_requests=service)
        )
    return scope


async def receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def response_headers(messages):
    start = next(message for message in messages if message["type"] == "http.response.start")
    return {
        key.decode().lower(): value.decode()
        for key, value in start["headers"]
    }


def response_body(messages):
    return b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )


class FailingAdmission:
    def __init__(self, secret):
        self.secret = secret

    def begin(self, kind):
        raise RuntimeError(f"fixture secret: {self.secret}")


@pytest.mark.asyncio
async def test_begin_runtime_error_is_safe_http_503_without_secret(caplog):
    secret = "fixture-admission-secret-8b2d"
    called = []
    messages = []

    async def inner(*args):
        called.append(True)

    async def send(message):
        messages.append(message)

    middleware = RuntimeAdmissionMiddleware(inner)
    with caplog.at_level("WARNING", logger="app.services.api_admission"):
        await middleware(asgi_scope(FailingAdmission(secret)), receive, send)

    headers = response_headers(messages)
    assert next(message for message in messages if message["type"] == "http.response.start")[
        "status"
    ] == 503
    assert headers["retry-after"] == "1"
    assert headers["cache-control"] == "no-store"
    assert secret not in repr(messages)
    assert secret not in caplog.text
    assert not called


@pytest.mark.asyncio
async def test_begin_runtime_error_rejects_websocket_without_calling_inner():
    secret = "fixture-websocket-secret-39c1"
    called = []
    messages = []

    async def inner(*args):
        called.append(True)

    async def send(message):
        messages.append(message)

    await RuntimeAdmissionMiddleware(inner)(
        asgi_scope(FailingAdmission(secret), kind="websocket"),
        receive,
        send,
    )

    assert messages == [
        {
            "type": "websocket.close",
            "code": 1013,
            "reason": "서버가 새 연결을 받을 수 없습니다.",
        }
    ]
    assert secret not in repr(messages)
    assert not called


@pytest.mark.asyncio
async def test_rejected_request_with_disallowed_origin_has_no_allow_origin_header():
    messages = []

    async def inner(*args):
        raise AssertionError("rejected request reached inner app")

    async def send(message):
        messages.append(message)

    await RuntimeAdmissionMiddleware(inner)(
        asgi_scope(
            FailingAdmission("fixture-origin-secret"),
            origin="https://not-allowed.example",
        ),
        receive,
        send,
    )

    headers = response_headers(messages)
    assert next(message for message in messages if message["type"] == "http.response.start")[
        "status"
    ] == 503
    assert "access-control-allow-origin" not in headers
    assert response_body(messages)


@pytest.mark.asyncio
async def test_lifespan_is_forwarded_to_inner_app_without_runtime_service():
    called = []
    messages = []

    async def inner(scope, receive_fn, send):
        called.append(scope["type"])
        event = await receive_fn()
        assert event["type"] == "lifespan.startup"
        await send({"type": "lifespan.startup.complete"})

    async def lifespan_receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        messages.append(message)

    await RuntimeAdmissionMiddleware(inner)(
        {"type": "lifespan", "state": {}}, lifespan_receive, send
    )

    assert called == ["lifespan"]
    assert messages == [{"type": "lifespan.startup.complete"}]
