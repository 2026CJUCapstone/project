from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import terminal
from app.core.database import Base
from app.models import database as models
from app.services import execution_runtime
from app.services.auth import create_access_token


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'terminal-receipt.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(terminal, "SessionLocal", factory)
    monkeypatch.setattr(execution_runtime, "SessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()


def test_authenticated_terminal_receipt_stores_code_without_token_before_worker(sessions):
    with sessions() as db:
        db.add(models.User(id="user-1", username="terminal-user", hashed_password="unused"))
        db.commit()

    sid = "a" * 32
    broker = Mock()
    payload = {
        "token": create_access_token({"sub": "terminal-user"}),
        "code": "print(42)",
        "language": "python",
        "optimize": True,
    }

    job_id, owner = terminal.accept_terminal(sid, payload, "192.0.2.1", broker)

    with sessions() as db:
        job = db.get(models.ExecutionJob, job_id)
        assert job.status == "queued"
        assert job.kind == "terminal"
        assert job.owner_key == owner == "account:user-1"
        assert job.quota_key == "account:user-1"
        assert job.payload == {
            "terminal_session": sid,
            "code": "print(42)",
            "language": "python",
            "optimize": True,
        }
        assert "token" not in job.payload
    broker.bind_user.assert_called_once_with(sid, "user-1")


def test_anonymous_terminal_receipt_uses_terminal_owner_and_normalized_ip_quota(sessions):
    sid = "b" * 32
    broker = Mock()
    normalized_ip = terminal.execution_ip(SimpleNamespace(client=SimpleNamespace(host="::ffff:192.0.2.9")))

    job_id, owner = terminal.accept_terminal(
        sid,
        {"code": "print(1)", "language": "python"},
        normalized_ip,
        broker,
    )

    with sessions() as db:
        job = db.get(models.ExecutionJob, job_id)
        assert job.owner_key == owner == f"terminal:{sid}"
        assert job.quota_key == "ip:192.0.2.9"
        assert job.payload["terminal_session"] == sid
        assert job.payload["code"] == "print(1)"
        assert "token" not in job.payload
    broker.bind_user.assert_not_called()


def test_invalid_terminal_jwt_rejects_without_creating_job(sessions):
    broker = Mock()

    with pytest.raises(HTTPException) as error:
        terminal.accept_terminal(
            "c" * 32,
            {"token": "not-a-jwt", "code": "print(1)", "language": "python"},
            "192.0.2.1",
            broker,
        )

    assert error.value.status_code == 401
    with sessions() as db:
        assert db.query(models.ExecutionJob).count() == 0
    broker.bind_user.assert_not_called()
