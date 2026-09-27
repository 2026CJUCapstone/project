"""Explicit, serialized database preparation; never run by production APIs.

Legacy recovery is an offline operation: stop all old APIs/workers and verify
their sandboxes are gone before using --allow-legacy-recovery. No Docker
authority is given to this command, and it never guesses that a lease means
an old process has stopped.
"""
import argparse
import hashlib
import re
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

LEARNING_SCHEMA_VERSION = '20260911_learning_v11'
RUNTIME_SCHEMA_VERSION = '20260927_problem_publication_gate_v26'
_RUNTIME_MARKER = re.compile(r'_v[0-9]+$')


class LegacyRecoveryRequired(RuntimeError):
    pass


def _prepare_runtime_history(db):
    db.execute(text('''CREATE TABLE IF NOT EXISTS runtime_schema_history (
        version VARCHAR PRIMARY KEY,
        retired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
    )'''))


def _migration_applied(db, version):
    return bool(db.execute(text('''SELECT 1 FROM schema_migrations WHERE version=:v
        UNION ALL SELECT 1 FROM runtime_schema_history WHERE version=:v LIMIT 1'''), {'v':version}).first())


def _activate_runtime_marker(db):
    """Atomically retire every old readiness marker before enabling this binary.

    Previous binaries only know how to look up their own marker in
    ``schema_migrations``. Keeping historical runtime markers there would leave
    stale API replicas ready during a rolling deployment.
    """
    versions=list(db.execute(text('SELECT version FROM schema_migrations')).scalars())
    for version in versions:
        if not _RUNTIME_MARKER.search(version):
            continue
        db.execute(text('INSERT INTO runtime_schema_history (version) VALUES (:v) ON CONFLICT (version) DO NOTHING'),
                   {'v':version})
        db.execute(text('DELETE FROM schema_migrations WHERE version=:v'), {'v':version})
    db.execute(text('INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT (version) DO NOTHING'),
               {'v':RUNTIME_SCHEMA_VERSION})


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


def initialize(*, bind=None, allow_legacy_recovery=False, skip_bootstrap=False):
    validate_runtime_security()
    with database.schema_transaction(bind) as connection:
        database.init_db(connection)
        with Session(bind=connection, autoflush=False, join_transaction_mode='rollback_only') as db:
            _prepare_runtime_history(db)
            recover_legacy(db, allowed=allow_legacy_recovery)
            if not _migration_applied(db, LEARNING_SCHEMA_VERSION):
                from app.services.learning import backfill_progress
                backfill_progress(db)
                db.execute(text('INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT (version) DO NOTHING'),
                           {'v': LEARNING_SCHEMA_VERSION})
            if skip_bootstrap:
                # Existing installations may have edited their admin/system
                # content. An additive migration must not silently rewrite it.
                if not db.query(m.User.id).filter(m.User.role == 'admin').first():
                    raise RuntimeError('Skipping bootstrap requires an existing administrator')
            else:
                bootstrap_application_data(db)
            # Session.commit above cannot commit the enclosing connection.
            _activate_runtime_marker(db)
            db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-legacy-recovery', action='store_true',
        help='Operator confirms all old producers/workers stopped and old sandboxes removed.')
    parser.add_argument('--skip-bootstrap', action='store_true',
        help='Migrate an existing installation without changing administrator or system content.')
    args = parser.parse_args()
    try:
        initialize(allow_legacy_recovery=args.allow_legacy_recovery, skip_bootstrap=args.skip_bootstrap)
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
