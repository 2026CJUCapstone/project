"""The v11 learning migration backfills durable progress exactly once."""

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

import app.models.database as m
import app.initialize as initialize_module
from app.initialize import RUNTIME_SCHEMA_VERSION, initialize
from tests.test_durable_queue import replicas


def test_learning_migration_backfills_terminal_submissions_once_and_preserves_edits(
    replicas, monkeypatch
):
    engine = replicas[0].kw["bind"]
    # Start from the actual pre-v11 shape: the new table does not exist.
    # The fixture owns an isolated SQLite file or a nonce PostgreSQL schema.
    m.ProblemLearningRecord.__table__.drop(engine)
    assert "problem_learning_records" not in inspect(engine).get_table_names()
    monkeypatch.setattr(initialize_module, "bootstrap_application_data", lambda _db: None)

    created_at = datetime(2026, 1, 2, 3, 4, 5)
    with Session(engine) as db:
        user = m.User(
            id="learning-user",
            username="learning-user",
            hashed_password="",
            total_score=73,
        )
        db.add(user)
        db.flush()
        terminal_problem = m.Problem(
            id="learning-terminal",
            creator_id=user.id,
            title="Terminal",
            difficulty="iron5",
            tags=[],
            description="",
            test_cases=[],
        )
        running_problem = m.Problem(
            id="learning-running",
            creator_id=user.id,
            title="Running",
            difficulty="iron5",
            tags=[],
            description="",
            test_cases=[],
        )
        queued_problem = m.Problem(
            id="learning-queued",
            creator_id=user.id,
            title="Queued",
            difficulty="iron5",
            tags=[],
            description="",
            test_cases=[],
        )
        db.add_all([terminal_problem, running_problem, queued_problem])
        db.add_all(
            [
                m.ExecutionJob(
                    id="learning-running-job",
                    owner_key="account:learning-user",
                    quota_key="account:learning-user",
                    request_id="learning-running-request",
                    payload_hash="learning-running-hash",
                    kind="grading",
                    payload={},
                    status="running",
                ),
                m.ExecutionJob(
                    id="learning-queued-job",
                    owner_key="account:learning-user",
                    quota_key="account:learning-user",
                    request_id="learning-queued-request",
                    payload_hash="learning-queued-hash",
                    kind="grading",
                    payload={},
                    status="queued",
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                m.Submission(
                    id="learning-wrong-answer",
                    user_id=user.id,
                    problem_id=terminal_problem.id,
                    language="python",
                    code="source before migration",
                    status="completed",
                    verdict="wrong_answer",
                    created_at=created_at,
                ),
                m.Submission(
                    id="learning-running-submission",
                    user_id=user.id,
                    problem_id=running_problem.id,
                    language="python",
                    code="running source",
                    status="running",
                    verdict="pending",
                    execution_job_id="learning-running-job",
                    created_at=created_at,
                ),
                m.Submission(
                    id="learning-queued-submission",
                    user_id=user.id,
                    problem_id=queued_problem.id,
                    language="python",
                    code="queued source",
                    status="queued",
                    verdict="pending",
                    execution_job_id="learning-queued-job",
                    created_at=created_at,
                ),
            ]
        )
        db.commit()

    initialize(bind=engine)

    with Session(engine) as db:
        record = db.get(m.ProblemLearningRecord, ("learning-user", "learning-terminal"))
        assert record is not None
        assert record.last_submission_id == "learning-wrong-answer"
        assert record.last_verdict == "wrong_answer"
        assert record.last_attempt_at == created_at
        assert record.bookmarked is False
        assert record.note == ""
        assert record.version == 0
        assert record.reviewed_at is None
        assert db.get(m.ProblemLearningRecord, ("learning-user", "learning-running")) is None
        assert db.get(m.ProblemLearningRecord, ("learning-user", "learning-queued")) is None
        assert db.get(m.User, "learning-user").total_score == 73
        source = db.get(m.Submission, "learning-wrong-answer")
        assert (source.code, source.status, source.verdict) == (
            "source before migration",
            "completed",
            "wrong_answer",
        )

        record.bookmarked = True
        record.note = "Review after the migration"
        record.version = 7
        record.reviewed_at = datetime(2026, 1, 3, 4, 5, 6)
        db.commit()

    initialize(bind=engine)

    inspector = inspect(engine)
    assert "problem_learning_records" in inspector.get_table_names()
    assert inspector.get_pk_constraint("problem_learning_records")["constrained_columns"] == [
        "user_id",
        "problem_id",
    ]
    with Session(engine) as db:
        record = db.get(m.ProblemLearningRecord, ("learning-user", "learning-terminal"))
        assert record is not None
        assert (record.bookmarked, record.note, record.version, record.reviewed_at) == (
            True,
            "Review after the migration",
            7,
            datetime(2026, 1, 3, 4, 5, 6),
        )
        assert db.query(m.ProblemLearningRecord).count() == 1
        assert db.get(m.User, "learning-user").total_score == 73
        source = db.get(m.Submission, "learning-wrong-answer")
        assert (source.code, source.status, source.verdict) == (
            "source before migration",
            "completed",
            "wrong_answer",
        )

    with engine.connect() as connection:
        versions = connection.execute(
            text("SELECT version FROM schema_migrations WHERE version = :version"),
            {"version": RUNTIME_SCHEMA_VERSION},
        ).fetchall()
    assert len(versions) == 1


def test_failed_learning_backfill_rolls_back_table_and_readiness_then_retries(replicas, monkeypatch):
    import app.services.learning as learning_service

    engine = replicas[0].kw["bind"]
    m.ProblemLearningRecord.__table__.drop(engine)
    monkeypatch.setattr(initialize_module, "bootstrap_application_data", lambda _db: None)
    original = learning_service.backfill_progress

    def fail_after_ddl(db):
        assert "problem_learning_records" in inspect(db.connection()).get_table_names()
        raise RuntimeError("injected backfill interruption")

    monkeypatch.setattr(learning_service, "backfill_progress", fail_after_ddl)
    with pytest.raises(RuntimeError, match="injected backfill interruption"):
        initialize(bind=engine)
    assert "problem_learning_records" not in inspect(engine).get_table_names()
    if "schema_migrations" in inspect(engine).get_table_names():
        with engine.connect() as connection:
            assert not connection.execute(text("SELECT 1 FROM schema_migrations WHERE version=:v"),
                                          {"v": RUNTIME_SCHEMA_VERSION}).first()
    monkeypatch.setattr(learning_service, "backfill_progress", original)
    initialize(bind=engine)
    assert "problem_learning_records" in inspect(engine).get_table_names()


def test_parallel_initializers_backfill_once_under_the_database_lock(replicas, monkeypatch):
    import app.services.learning as learning_service

    engine = replicas[0].kw["bind"]
    m.ProblemLearningRecord.__table__.drop(engine)
    monkeypatch.setattr(initialize_module, "bootstrap_application_data", lambda _db: None)
    calls = []
    original = learning_service.backfill_progress

    def counted(db):
        calls.append(1)
        original(db)

    monkeypatch.setattr(learning_service, "backfill_progress", counted)
    barrier = Barrier(2)

    def run(factory):
        barrier.wait(timeout=10)
        initialize(bind=factory.kw["bind"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, factory) for factory in replicas]
        for future in futures:
            future.result(timeout=30)
    assert calls == [1]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM schema_migrations WHERE version=:v"),
                                 {"v": RUNTIME_SCHEMA_VERSION}) == 1
