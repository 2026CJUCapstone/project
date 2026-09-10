"""The housekeeping pass composes bounded retention in one transaction."""

from datetime import datetime, timedelta

import pytest

from app.core.config import settings
from app.models import database as m
from app.services import execution_retention, housekeeping
from tests.test_durable_queue import replicas


AT = datetime(2030, 1, 20)
OLD = AT - timedelta(days=8)
PAYLOAD = {"code": "private source", "language": "python"}
RESULT = {"value": {"stdout": "private output"}, "verdict": "accepted"}


def configure_retention(monkeypatch, replicas, *, content_days, anonymous_days=7, history_limit=500):
    monkeypatch.setattr(housekeeping, "SessionLocal", replicas[0])
    monkeypatch.setattr(housekeeping, "now_utc", lambda: AT)
    monkeypatch.setattr(execution_retention, "now_utc", lambda: AT)
    monkeypatch.setattr(settings, "EXECUTION_CONTENT_RETENTION_DAYS", content_days)
    monkeypatch.setattr(settings, "ANONYMOUS_SUBMISSION_RETENTION_DAYS", anonymous_days)
    monkeypatch.setattr(settings, "COMPILER_QUEUE_HISTORY_LIMIT", history_limit)


def execution_job(
    job_id,
    *,
    status="completed",
    finished_at=OLD,
    lease_token=None,
    lease_until=None,
    sandbox_operation=None,
):
    return m.ExecutionJob(
        id=job_id,
        owner_key=f"owner:{job_id}",
        quota_key=f"quota:{job_id}",
        request_id=f"request:{job_id}",
        payload_hash=f"hash:{job_id}",
        kind="run",
        payload=PAYLOAD,
        result=RESULT,
        status=status,
        received_at=OLD,
        started_at=OLD,
        finished_at=finished_at,
        lease_token=lease_token,
        lease_until=lease_until,
        sandbox_operation=sandbox_operation,
    )


def public_record(record_id, *, finished_at=OLD):
    return m.CompileQueueRecord(
        id=record_id,
        kind="run",
        status="completed",
        verdict="accepted",
        language="python",
        queued_at=finished_at,
        finished_at=finished_at,
    )


def add_problem(db):
    db.add(m.User(id="retention-owner", username="retention-owner", hashed_password=""))
    db.flush()
    db.add(
        m.Problem(
            id="retention-problem",
            creator_id="retention-owner",
            title="retention",
            difficulty="iron5",
            tags=[],
            description="",
            test_cases=[],
        )
    )
    db.flush()
    return "retention-problem"


def anonymous_submission(submission_id, *, problem_id, execution_job_id=None):
    return m.Submission(
        id=submission_id,
        execution_job_id=execution_job_id,
        problem_id=problem_id,
        language="python",
        code="anonymous source",
        status="Accepted",
        verdict="accepted",
        created_at=OLD,
    )


def test_zero_content_policy_still_runs_anonymous_and_public_history_retention(
    monkeypatch, replicas
):
    configure_retention(monkeypatch, replicas, content_days=0, history_limit=0)
    with replicas[0]() as db:
        problem_id = add_problem(db)
        job = execution_job("zero-content-job")
        job_id = job.id
        db.add_all([
            job,
            anonymous_submission(
                "zero-content-submission",
                problem_id=problem_id,
                execution_job_id=job.id,
            ),
            public_record(job_id),
        ])
        db.commit()

    events = []
    real_expire = housekeeping.expire_execution_content
    real_purge_queue = housekeeping.purge_queue_history

    def record_expire(db, **kwargs):
        events.append(("expire", kwargs))
        return real_expire(db, **kwargs)

    def record_purge_queue(db, **kwargs):
        events.append(("queue", kwargs))
        return real_purge_queue(db, **kwargs)

    monkeypatch.setattr(housekeeping, "expire_execution_content", record_expire)
    monkeypatch.setattr(housekeeping, "purge_queue_history", record_purge_queue)

    assert housekeeping.retention_pass() == 2
    assert events == [
        ("expire", {"retention_days": 0}),
        ("queue", {"history_limit": 0}),
    ]

    with replicas[1]() as db:
        retained_job = db.get(m.ExecutionJob, job_id)
        assert retained_job.payload == PAYLOAD
        assert retained_job.result == RESULT
        assert retained_job.content_expired_at is None
        assert db.get(m.Submission, "zero-content-submission") is None
        assert db.get(m.CompileQueueRecord, job_id) is None


def test_positive_content_retention_scrubs_only_eligible_completed_jobs(monkeypatch, replicas):
    configure_retention(monkeypatch, replicas, content_days=7, anonymous_days=3650)
    eligible_id = "eligible-completed"
    recent_id = "recent-completed"
    active_id = "active-job"
    leased_id = "leased-job"
    pending_id = "pending-operation-job"
    with replicas[0]() as db:
        db.add_all([
            execution_job(eligible_id),
            execution_job(recent_id, finished_at=AT - timedelta(days=6)),
            execution_job(active_id, status="running"),
            execution_job(leased_id, lease_token="lease-token"),
            execution_job(pending_id, sandbox_operation={"kind": "cleanup", "id": "pending"}),
        ])
        db.commit()

    assert housekeeping.retention_pass() == 1

    with replicas[1]() as db:
        eligible = db.get(m.ExecutionJob, eligible_id)
        assert eligible.payload == {}
        assert eligible.result is None
        assert eligible.content_expired_at == AT
        for job_id in (recent_id, active_id, leased_id, pending_id):
            retained = db.get(m.ExecutionJob, job_id)
            assert retained.payload == PAYLOAD
            assert retained.result == RESULT
            assert retained.content_expired_at is None


def test_retention_pass_rolls_back_all_changes_when_later_helper_fails(monkeypatch, replicas):
    configure_retention(monkeypatch, replicas, content_days=7, history_limit=0)
    with replicas[0]() as db:
        problem_id = add_problem(db)
        db.add_all([
            execution_job("rollback-content-job"),
            anonymous_submission("rollback-submission", problem_id=problem_id),
            public_record("rollback-public"),
        ])
        db.commit()

    real_purge_queue = housekeeping.purge_queue_history

    def fail_queue_purge(db, **kwargs):
        assert real_purge_queue(db, **kwargs) == 1
        raise RuntimeError("fixture queue retention failure")

    monkeypatch.setattr(housekeeping, "purge_queue_history", fail_queue_purge)
    with pytest.raises(RuntimeError, match="fixture queue retention failure"):
        housekeeping.retention_pass()

    with replicas[1]() as db:
        job = db.get(m.ExecutionJob, "rollback-content-job")
        assert job.payload == PAYLOAD
        assert job.result == RESULT
        assert job.content_expired_at is None
        assert db.get(m.Submission, "rollback-submission") is not None
        assert db.get(m.CompileQueueRecord, "rollback-public") is not None


def test_anonymous_terminal_submissions_keep_links_to_active_leased_and_pending_jobs(
    monkeypatch, replicas
):
    configure_retention(monkeypatch, replicas, content_days=0)
    protected_ids = (
        "anonymous-active",
        "anonymous-leased",
        "anonymous-pending",
    )
    with replicas[0]() as db:
        problem_id = add_problem(db)
        db.add_all([
            execution_job("active-linked-job", status="running"),
            execution_job("leased-linked-job", lease_token="lease-token"),
            execution_job(
                "pending-linked-job",
                sandbox_operation={"version": 1, "kind": "cleanup", "id": "pending"},
            ),
            anonymous_submission(
                protected_ids[0], problem_id=problem_id, execution_job_id="active-linked-job"
            ),
            anonymous_submission(
                protected_ids[1], problem_id=problem_id, execution_job_id="leased-linked-job"
            ),
            anonymous_submission(
                protected_ids[2], problem_id=problem_id, execution_job_id="pending-linked-job"
            ),
            anonymous_submission("anonymous-free", problem_id=problem_id),
        ])
        db.commit()

    assert housekeeping.retention_pass() == 1

    with replicas[1]() as db:
        assert all(db.get(m.Submission, submission_id) is not None for submission_id in protected_ids)
        assert db.get(m.Submission, "anonymous-free") is None
