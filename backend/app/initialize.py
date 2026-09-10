"""Explicit, serialized database preparation; never run by production APIs.

Legacy recovery is an offline operation: stop all old APIs/workers and verify
their sandboxes are gone before using --allow-legacy-recovery. No Docker
authority is given to this command, and it never guesses that a lease means
an old process has stopped.
"""
import argparse
import hashlib
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import database
from app.core.bootstrap import bootstrap_application_data
from app.models import database as m
from app.services.auth import validate_runtime_security
from app.services.contest_access import now_utc
from app.services.durable_queue import DurableQueue, QueueFull
from app.core.config import settings

RUNTIME_SCHEMA_VERSION = '20260910_execution_retention_v10'


class LegacyRecoveryRequired(RuntimeError):
    pass


def recover_legacy(db, *, allowed=False):
    contests = db.query(m.ContestSubmission).filter(
        m.ContestSubmission.execution_job_id.is_(None),
        m.ContestSubmission.status.in_(['queued', 'running'])).order_by(
            m.ContestSubmission.received_at, m.ContestSubmission.id).all()
    practice = db.query(m.Submission).filter(
        m.Submission.execution_job_id.is_(None), m.Submission.status.in_(['queued', 'running'])).all()
    public = db.query(m.CompileQueueRecord).filter(
        m.CompileQueueRecord.status.in_(['queued', 'running']),
        ~m.CompileQueueRecord.id.in_(db.query(m.ExecutionJob.id))).all()
    if not (contests or practice or public):
        return
    if not allowed:
        raise LegacyRecoveryRequired('Unfinished legacy executions exist. Stop old producers/workers and confirm sandbox cleanup before explicit legacy recovery.')
    queue = DurableQueue(lambda: db, capacity=settings.EXECUTION_QUEUE_CAPACITY,
        per_owner=settings.EXECUTION_QUEUE_PER_OWNER)
    for record in contests:
        problem = db.get(m.ContestProblem, record.contest_problem_id)
        key = 'contest:' + hashlib.sha256(f'{record.contest_id}:{record.request_id}'.encode()).hexdigest()
        job = queue.enqueue_in_session(db, owner_key=f'account:{record.user_id}', request_id=key,
            kind='contest', at=record.received_at,
            payload={'code':record.code, 'language':record.language, 'contest_id':record.contest_id,
                'contest_problem_id':record.contest_problem_id,
                'sample':problem.snapshot['sample'], 'hidden':problem.snapshot['hidden']})
        record.execution_job_id = job.id
        record.status, record.verdict = 'queued', 'pending'
        record.lease_token = record.lease_until = record.finished_at = None
        contest = db.get(m.Contest, record.contest_id)
        contest.finalized_at = None
    if contests:
        from app.services.scoreboard_cache import bump_scoreboard_revision
        for contest_id in sorted({record.contest_id for record in contests}):
            bump_scoreboard_revision(db, contest_id)
    # Legacy ordinary executions did not preserve immutable grading inputs.
    # Rejudging against today's tests would silently change their meaning.
    for record in practice:
        record.status, record.verdict = 'Rejected', 'system_error'
        record.grading_completed = record.grading_passed = False
    for record in public:
        record.status, record.verdict = 'failed', 'system_error'
        record.finished_at = now_utc()
        record.error = '이전 실행의 입력을 복구할 수 없습니다. 코드를 다시 제출하세요.'
    db.flush()


def initialize(*, bind=None, allow_legacy_recovery=False):
    validate_runtime_security()
    with database.schema_transaction(bind) as connection:
        database.init_db(connection)
        with Session(bind=connection, autoflush=False, join_transaction_mode='rollback_only') as db:
            recover_legacy(db, allowed=allow_legacy_recovery)
            bootstrap_application_data(db)
            # Session.commit above cannot commit the enclosing connection.
            db.execute(text('INSERT INTO schema_migrations (version) VALUES (:version) ON CONFLICT (version) DO NOTHING'),
                {'version':RUNTIME_SCHEMA_VERSION})
            db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-legacy-recovery', action='store_true',
        help='Operator confirms all old producers/workers stopped and old sandboxes removed.')
    args = parser.parse_args()
    try:
        initialize(allow_legacy_recovery=args.allow_legacy_recovery)
    except LegacyRecoveryRequired as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except QueueFull:
        print('Legacy recovery exceeds configured queue capacity. No changes committed; review capacity before retrying.', file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        # SQL exception text can include submitted code or database credentials.
        print('Database initialization failed; no runtime schema readiness was granted.', file=sys.stderr)
        raise SystemExit(1) from None
    print('Database initialization completed.')


if __name__ == '__main__':
    main()
