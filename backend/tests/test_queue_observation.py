import uuid

import pytest
from sqlalchemy import event

from app.core.database import engine, SessionLocal
from app.main import app  # initialize isolated test database
from app.models.database import CompileQueueRecord
from app.services.compile_queue import CompileQueue


@pytest.mark.asyncio
async def test_other_api_snapshot_never_fails_a_live_job_or_writes_to_database():
    observer = CompileQueue(1, 50)
    username = f"observer_{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(CompileQueueRecord(
            id=uuid.uuid4().hex,
            kind="run",
            status="running",
            verdict="running",
            language="python",
            username=username,
            source_size_bytes=8,
        ))
        db.commit()
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        snapshot = await observer.snapshot(username=username)
        assert snapshot['jobs'][0]['status'] == 'running'
        assert set(statements) <= {'SELECT'}
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        with SessionLocal() as db:
            db.query(CompileQueueRecord).filter_by(username=username).delete()
            db.commit()


@pytest.mark.asyncio
async def test_snapshot_has_no_execution_or_redis_recovery_api():
    queue = CompileQueue(1, 50)
    assert not hasattr(queue, "run")
    assert not any(name.startswith("_redis") for name in dir(queue))
    await queue.snapshot()
