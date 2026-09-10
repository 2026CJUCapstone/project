from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.initialize import initialize, LegacyRecoveryRequired, RUNTIME_SCHEMA_VERSION
from app.models import database as m
from app.services.durable_queue import QueueFull
from tests.test_durable_queue import replicas


def test_two_initializers_serialize_schema_bootstrap_and_repeat_safely(replicas, monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_PASSWORD', 'initial-test-password')
    barrier = Barrier(2)
    def run(factory):
        barrier.wait()
        initialize(bind=factory.kw['bind'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, replicas))
    with replicas[0]() as db:
        admin = db.query(m.User).filter_by(username=settings.ADMIN_USERNAME).one()
        before = admin.hashed_password
        versions = list(db.execute(text('SELECT version FROM schema_migrations')).scalars())
        assert len(versions) == len(set(versions)) == 5
        assert RUNTIME_SCHEMA_VERSION in versions
        assert db.query(m.Comment).count() == 1
    initialize(bind=replicas[1].kw['bind'])
    with replicas[0]() as db:
        assert db.query(m.User).filter_by(username=settings.ADMIN_USERNAME).one().hashed_password == before
        assert db.query(m.Comment).count() == 1


def legacy_rows(factory, *, count=1):
    at = datetime(2026, 1, 1)
    with factory() as db:
        user = m.User(id='legacy-user', username='legacy-user', hashed_password='not-used', total_score=0)
        db.add(user)
        db.flush()
        db.add(m.Problem(id='legacy-problem', creator_id=user.id, title='later title', difficulty='iron5',
            description='later text', tags=[], test_cases={'sample':[], 'hidden':[]}, points=42))
        db.add(m.Contest(id='legacy-contest', creator_id=user.id, title='legacy contest', description='',
            starts_at=at, ends_at=at+timedelta(hours=1), published=True, finalized_at=at+timedelta(hours=2)))
        db.flush()
        db.add(m.ContestProblem(id='legacy-cp', contest_id='legacy-contest', problem_id='legacy-problem',
            position=0, points=100, is_new=False,
            snapshot={'sample':[{'input':'frozen input', 'output':'frozen output'}], 'hidden':[]}))
        db.flush()
        for number in range(count):
            db.add(m.ContestSubmission(id=f'old-{number}', contest_id='legacy-contest', contest_problem_id='legacy-cp',
                user_id=user.id, request_id=f'request-{number}', code='print(42)', language='python',
                received_at=at+timedelta(minutes=number+1), status='running', verdict='running',
                lease_token='old-claim', lease_until=at, attempts=1))
        db.add(m.Submission(id='old-practice', user_id=user.id, problem_id='legacy-problem',
            language='python', code='print(1)', status='running', verdict='running'))
        db.add(m.CompileQueueRecord(id='old-public',kind='run',status='running',verdict='running',language='python'))
        db.commit()


def test_legacy_requires_offline_confirmation_then_recovers_frozen_contest_once(replicas):
    legacy_rows(replicas[0])
    with pytest.raises(LegacyRecoveryRequired):
        initialize(bind=replicas[0].kw['bind'])
    with replicas[0]() as db:
        assert db.query(m.ExecutionJob).count() == 0
        assert db.get(m.ContestSubmission, 'old-0').status == 'running'
        assert db.get(m.Submission, 'old-practice').status == 'running'
        assert db.query(m.User).count() == 1  # no partial bootstrap
    initialize(bind=replicas[0].kw['bind'], allow_legacy_recovery=True)
    initialize(bind=replicas[1].kw['bind'])
    with replicas[0]() as db:
        old = db.get(m.ContestSubmission, 'old-0')
        job = db.query(m.ExecutionJob).one()
        assert old.execution_job_id == job.id
        assert old.status == job.status == 'queued'
        assert old.lease_token is old.lease_until is None
        assert job.received_at == old.received_at
        assert job.payload['sample'][0]['input'] == 'frozen input'
        assert job.payload['code'] == old.code
        assert db.get(m.Contest, 'legacy-contest').finalized_at is None
        assert db.get(m.Contest, 'legacy-contest').scoreboard_revision == 1
        assert db.get(m.Submission, 'old-practice').verdict == 'system_error'
        assert db.get(m.CompileQueueRecord, 'old-public').status == 'failed'
        assert db.query(m.UserProblemScore).count() == 0


def test_legacy_capacity_failure_rolls_back_every_receipt_and_status(replicas, monkeypatch):
    legacy_rows(replicas[0], count=2)
    monkeypatch.setattr(settings, 'EXECUTION_QUEUE_CAPACITY', 1)
    with pytest.raises(QueueFull):
        initialize(bind=replicas[0].kw['bind'], allow_legacy_recovery=True)
    with replicas[0]() as db:
        assert db.query(m.ExecutionJob).count() == 0
        assert all(row.execution_job_id is None and row.status == 'running' for row in db.query(m.ContestSubmission))
        assert db.get(m.Submission, 'old-practice').status == 'running'
        assert db.get(m.CompileQueueRecord, 'old-public').status == 'running'
        assert db.get(m.Contest, 'legacy-contest').scoreboard_revision == 0
