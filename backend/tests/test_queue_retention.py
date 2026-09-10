"""Public queue-history retention never owns durable execution or score data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import select, text

from app.models import database as m
from app.services.queue_retention import purge_queue_history, _ordered_history
from tests.test_durable_queue import replicas


AT = datetime(2030, 1, 1, 12, 0, 0)


def queue_record(record_id, *, status="completed", queued_at=AT, finished_at=AT):
    return m.CompileQueueRecord(
        id=record_id,
        kind="run",
        status=status,
        verdict="accepted" if status == "completed" else "system_error",
        language="python",
        queued_at=queued_at,
        finished_at=finished_at,
    )


def execution_job(record_id, *, status="completed", lease_token=None,
                  lease_until=None, sandbox_operation=None):
    return m.ExecutionJob(
        id=record_id,
        owner_key=f"owner:{record_id}",
        quota_key=f"owner:{record_id}",
        request_id=f"request:{record_id}",
        payload_hash="a" * 64,
        kind="run",
        payload={},
        status=status,
        received_at=AT,
        lease_token=lease_token,
        lease_until=lease_until,
        sandbox_operation=sandbox_operation,
    )


def queue_ids(factory):
    with factory() as db:
        return {record_id for (record_id,) in db.query(m.CompileQueueRecord.id).all()}


def test_terminal_history_cap_is_bounded_and_repeatable(replicas):
    with replicas[0]() as db:
        for index in range(5):
            db.add(queue_record(
                f"terminal-{index}",
                status="completed" if index % 2 else "failed",
                queued_at=AT + timedelta(seconds=index),
                finished_at=AT + timedelta(minutes=index),
            ))
        db.commit()

    with replicas[0]() as db:
        assert purge_queue_history(db, history_limit=2, batch_size=2) == 2
        db.commit()
    assert queue_ids(replicas[1]) == {"terminal-2", "terminal-3", "terminal-4"}

    with replicas[1]() as db:
        assert purge_queue_history(db, history_limit=2, batch_size=2) == 1
        db.commit()
    assert queue_ids(replicas[0]) == {"terminal-3", "terminal-4"}

    with replicas[0]() as db:
        assert purge_queue_history(db, history_limit=2, batch_size=2) == 0
        db.commit()


def test_terminal_history_boundary_and_order_are_deterministic(replicas):
    with replicas[0]() as db:
        # All terminal timestamps tie; ID is the final, explicit tie-breaker.
        for record_id in ("tie-a", "tie-b", "tie-c"):
            db.add(queue_record(record_id, queued_at=AT, finished_at=AT))
        db.commit()

    with replicas[0]() as db:
        assert purge_queue_history(db, history_limit=1) == 2
        db.commit()
    assert queue_ids(replicas[1]) == {"tie-c"}

    with replicas[1]() as db:
        assert purge_queue_history(db, history_limit=1) == 0
        db.commit()


def test_active_public_and_private_execution_records_are_preserved(replicas):
    with replicas[0]() as db:
        db.add_all([
            # Legacy public observations have no private job, but live status
            # alone must keep them out of history pruning.
            queue_record("legacy-queued", status="queued", finished_at=None),
            queue_record("legacy-running", status="running", finished_at=None),
            queue_record("orphan-terminal", status="completed"),
            queue_record("job-queued", status="completed"),
            queue_record("job-running", status="failed"),
            queue_record("job-lease", status="completed"),
            queue_record("job-intent", status="failed"),
        ])
        db.add_all([
            execution_job("job-queued", status="queued"),
            execution_job("job-running", status="running"),
            execution_job(
                "job-lease", status="completed", lease_until=AT + timedelta(minutes=1),
            ),
            execution_job(
                "job-intent", status="completed",
                sandbox_operation={"version": 1, "kind": "create"},
            ),
        ])
        db.commit()

    with replicas[0]() as db:
        assert purge_queue_history(db, history_limit=0) == 1
        db.commit()

    assert queue_ids(replicas[1]) == {
        "legacy-queued", "legacy-running", "job-queued", "job-running",
        "job-lease", "job-intent",
    }
    with replicas[1]() as db:
        assert db.query(m.ExecutionJob).count() == 4


def test_caller_rollback_restores_public_history_and_lock_update(replicas):
    with replicas[0]() as db:
        db.add_all([
            queue_record("rollback-old", finished_at=AT),
            queue_record("rollback-new", finished_at=AT + timedelta(seconds=1)),
        ])
        db.commit()

    with replicas[0]() as db:
        assert purge_queue_history(db, history_limit=0) == 2
        # The helper does not commit; the caller's rollback includes its lock
        # row creation/update and every public-record deletion.
        db.rollback()

    assert queue_ids(replicas[1]) == {"rollback-old", "rollback-new"}


def test_retention_never_mutates_submission_contest_or_score_ledger(replicas):
    job_id = "ledger-job"
    with replicas[0]() as db:
        user = m.User(id="ledger-user", username="ledger-user", hashed_password="")
        db.add(user)
        db.flush()
        problem = m.Problem(
            id="ledger-problem", creator_id=user.id, title="ledger", difficulty="iron5",
            tags=[], description="", test_cases=[],
        )
        db.add(problem)
        contest = m.Contest(
            id="ledger-contest", creator_id=user.id, title="ledger",
            starts_at=AT - timedelta(hours=1), ends_at=AT + timedelta(hours=1),
            scoreboard_revision=7,
        )
        db.add(contest)
        db.flush()
        contest_problem = m.ContestProblem(
            id="ledger-contest-problem", contest_id=contest.id, problem_id=problem.id,
            position=0, points=100, snapshot={},
        )
        db.add(contest_problem)
        db.flush()
        db.add(execution_job(job_id))
        db.flush()
        db.add_all([
            queue_record(job_id, finished_at=AT - timedelta(days=1)),
            m.Submission(
                id="ledger-submission", execution_job_id=job_id, user_id=user.id,
                problem_id=problem.id, language="python", code="keep practice receipt",
                status="Accepted", verdict="accepted", awarded_points=100,
            ),
            m.ContestSubmission(
                id="ledger-contest-submission", execution_job_id=job_id,
                contest_id=contest.id, contest_problem_id=contest_problem.id,
                user_id=user.id, request_id="ledger-request", language="python",
                code="keep contest receipt", received_at=AT, status="completed",
                verdict="accepted",
            ),
            m.UserProblemScore(
                id="ledger-score", user_id=user.id, challenge_id=problem.id,
                points_awarded=100, solved_at=AT,
            ),
        ])
        user.total_score = 100
        db.commit()

    with replicas[0]() as db:
        assert purge_queue_history(db, history_limit=0) == 1
        db.commit()

    with replicas[1]() as db:
        assert db.get(m.CompileQueueRecord, job_id) is None
        assert db.get(m.ExecutionJob, job_id).status == "completed"
        assert db.get(m.Submission, "ledger-submission").code == "keep practice receipt"
        assert db.get(m.ContestSubmission, "ledger-contest-submission").code == "keep contest receipt"
        assert db.get(m.Contest, "ledger-contest").scoreboard_revision == 7
        assert db.get(m.User, "ledger-user").total_score == 100
        assert db.get(m.UserProblemScore, "ledger-score").points_awarded == 100


def test_concurrent_maintenance_serializes_to_the_same_history_cap(replicas):
    with replicas[0]() as db:
        for index in range(8):
            db.add(queue_record(
                f"concurrent-{index}",
                queued_at=AT + timedelta(seconds=index),
                finished_at=AT + timedelta(minutes=index),
            ))
        db.commit()

    barrier = Barrier(2)

    def purge(factory):
        with factory() as db:
            barrier.wait(timeout=5)
            removed = purge_queue_history(db, history_limit=2, batch_size=3)
            db.commit()
            return removed

    with ThreadPoolExecutor(max_workers=2) as pool:
        removed = list(pool.map(purge, replicas))

    assert sorted(removed) == [3, 3]
    assert queue_ids(replicas[0]) == {"concurrent-6", "concurrent-7"}


@pytest.mark.parametrize("history_limit,batch_size", [
    (-1, 1), (10001, 1), (True, 1), (0, 0), (0, 501), (0, True),
])
def test_retention_limits_reject_ambiguous_or_unbounded_values(replicas, history_limit, batch_size):
    with replicas[0]() as db:
        with pytest.raises(ValueError):
            purge_queue_history(db, history_limit=history_limit, batch_size=batch_size)


def test_history_matches_receipt_order_even_when_completion_is_reversed_or_missing(replicas):
    with replicas[0]() as db:
        db.add_all([
            queue_record('old-slow', queued_at=AT, finished_at=AT + timedelta(days=1)),
            queue_record('middle-legacy', status='failed', queued_at=AT + timedelta(seconds=1), finished_at=None),
            queue_record('new-fast', queued_at=AT + timedelta(seconds=2), finished_at=AT + timedelta(seconds=3)),
        ])
        db.commit()
        assert purge_queue_history(db, history_limit=1, batch_size=1) == 1
        db.commit()
    assert queue_ids(replicas[1]) == {'middle-legacy', 'new-fast'}
    with replicas[1]() as db:
        assert purge_queue_history(db, history_limit=1, batch_size=1) == 1
        db.commit()
    assert queue_ids(replicas[0]) == {'new-fast'}


def test_cross_status_merge_uses_database_collation_for_legacy_ids(replicas):
    with replicas[0]() as db:
        for index, record_id in enumerate(('a', 'A', 'z', 'Z', 'é', 'ê', '한')):
            db.add(queue_record(record_id, status='completed' if index % 2 else 'failed'))
        db.commit()
        expected = set(db.execute(select(m.CompileQueueRecord.id).order_by(
            m.CompileQueueRecord.queued_at.desc(), m.CompileQueueRecord.id.desc(),
        ).limit(3)).scalars())
        assert purge_queue_history(db, history_limit=3) == 4
        db.commit()
    assert queue_ids(replicas[1]) == expected


def test_history_queries_bound_each_status_before_merging_and_use_order_index(replicas):
    with replicas[0]() as db:
        for newest in (True, False):
            statement = _ordered_history(newest=newest, limit=7)
            compiled = str(statement.compile(db.bind, compile_kwargs={'literal_binds': True}))
            assert compiled.count('LIMIT 7') == 3  # each status and the bounded merge
            assert 'coalesce' not in compiled.lower()
            assert 'payload' not in compiled.lower() and 'result' not in compiled.lower()
            if db.bind.dialect.name == 'sqlite':
                details = [row[3] for row in db.execute(text('EXPLAIN QUERY PLAN ' + compiled))]
                index_scans = [detail for detail in details if 'ix_compile_queue_history_order' in detail]
                assert len(index_scans) == 2, details
                assert not any('SCAN compile_queue_jobs' in detail for detail in details), details
