from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import inspect, text

from app.core.config import settings
from app.initialize import initialize, LegacyRecoveryRequired, RUNTIME_SCHEMA_VERSION, LEARNING_SCHEMA_VERSION
from app.models import database as m
from app.services.contest_access import private_problem_ids
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
        assert LEARNING_SCHEMA_VERSION not in versions
        assert RUNTIME_SCHEMA_VERSION in versions
        assert db.execute(text('SELECT 1 FROM runtime_schema_history WHERE version=:v'),
                          {'v':LEARNING_SCHEMA_VERSION}).first()
        assert db.query(m.Comment).count() == 1
    initialize(bind=replicas[1].kw['bind'])
    with replicas[0]() as db:
        assert db.query(m.User).filter_by(username=settings.ADMIN_USERNAME).one().hashed_password == before
        assert db.query(m.Comment).count() == 1


def test_runtime_activation_retires_old_readiness_markers_atomically(replicas, monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_PASSWORD', 'initial-test-password')
    engine = replicas[0].kw['bind']
    initialize(bind=engine)
    old = '20260927_authoring_attestation_v22'
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO schema_migrations (version) VALUES (:v)'), {'v':old})
    initialize(bind=engine)
    with engine.connect() as connection:
        active = set(connection.execute(text("SELECT version FROM schema_migrations WHERE version LIKE '%_v%'" )).scalars())
        retired = set(connection.execute(text('SELECT version FROM runtime_schema_history')).scalars())
    assert active == {RUNTIME_SCHEMA_VERSION}
    assert {old, LEARNING_SCHEMA_VERSION, RUNTIME_SCHEMA_VERSION} <= retired


def test_v24_adds_empty_legacy_resolution_audit_without_backfilling_scores(replicas, monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_PASSWORD', 'initial-test-password')
    engine = replicas[0].kw['bind']
    initialize(bind=engine)
    with replicas[0]() as db:
        admin = db.query(m.User).filter_by(username=settings.ADMIN_USERNAME).one()
        db.add(m.Problem(id='migration-score-problem', creator_id=admin.id, title='기존 문제',
            description='', difficulty='iron5', tags=[], test_cases={'sample':[], 'hidden':[]}, points=77))
        db.add(m.UserProblemScore(id='migration-score', user_id=admin.id,
            challenge_id='migration-score-problem', points_awarded=77, solved_at=datetime(2026, 1, 1)))
        admin.total_score = 77
        db.commit()
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE legacy_solve_resolutions'))
        connection.execute(text('ALTER TABLE contest_rejudge_applications DROP COLUMN legacy_resolution_provenance'))
    initialize(bind=engine)
    with replicas[0]() as db:
        score = db.get(m.UserProblemScore, 'migration-score')
        admin = db.query(m.User).filter_by(username=settings.ADMIN_USERNAME).one()
        assert score.points_awarded == admin.total_score == 77
        assert db.query(m.LegacySolveResolution).count() == 0
        columns = {row[1] for row in db.execute(text('PRAGMA table_info(contest_rejudge_applications)'))} if (
            db.bind.dialect.name == 'sqlite') else {
                row[0] for row in db.execute(text("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='contest_rejudge_applications'"))}
        assert 'legacy_resolution_provenance' in columns


def test_v25_creates_empty_legacy_execution_resolutions_without_changing_contractless_jobs(replicas, monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_PASSWORD', 'initial-test-password')
    engine = replicas[0].kw['bind']
    initialize(bind=engine)
    payload = {'code': 'legacy source', 'language': 'python', 'stdin': 'legacy input'}
    with replicas[0]() as db:
        db.add(m.ExecutionJob(id='pre-v25-contractless-job', owner_key='account:legacy', quota_key='account:legacy',
            request_id='pre-v25-request', payload_hash='pre-v25-payload-hash', kind='run',
            payload=payload, status='running', attempts=7))
        db.commit()

    with engine.begin() as connection:
        connection.execute(text('DROP TABLE legacy_execution_resolutions'))
        connection.execute(text('DELETE FROM schema_migrations WHERE version=:v'), {'v':RUNTIME_SCHEMA_VERSION})
        connection.execute(text('DELETE FROM runtime_schema_history WHERE version=:v'), {'v':RUNTIME_SCHEMA_VERSION})
    assert not inspect(engine).has_table('legacy_execution_resolutions')
    with engine.connect() as connection:
        assert connection.execute(text('''SELECT 1 FROM schema_migrations WHERE version=:v
            UNION ALL SELECT 1 FROM runtime_schema_history WHERE version=:v'''), {'v':RUNTIME_SCHEMA_VERSION}).first() is None

    expected = (payload, 'pre-v25-payload-hash', 'running', 7)
    for _ in range(2):
        initialize(bind=engine)
        assert inspect(engine).has_table('legacy_execution_resolutions')
        with replicas[0]() as db:
            job = db.get(m.ExecutionJob, 'pre-v25-contractless-job')
            assert (job.payload, job.payload_hash, job.status, job.attempts) == expected
            assert db.query(m.LegacyExecutionResolution).count() == 0
            assert db.execute(text('SELECT COUNT(*) FROM schema_migrations WHERE version=:v'),
                {'v':RUNTIME_SCHEMA_VERSION}).scalar() == 1


def test_v26_adds_nullable_publication_columns_without_hiding_legacy_problem(replicas, monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_PASSWORD', 'initial-test-password')
    engine = replicas[0].kw['bind']
    initialize(bind=engine)
    with replicas[0]() as db:
        admin = db.query(m.User).filter_by(username=settings.ADMIN_USERNAME).one()
        db.add(m.Problem(
            id='pre-v26-legacy-problem', creator_id=admin.id, title='Existing public problem',
            description='', difficulty='iron5', tags=[], test_cases={'sample': [], 'hidden': []}, points=100,
        ))
        db.commit()

    with engine.begin() as connection:
        connection.execute(text('DROP INDEX IF EXISTS ix_problems_publication_gate'))
        connection.execute(text('ALTER TABLE problems DROP COLUMN publication_review_required'))
        connection.execute(text('ALTER TABLE problems DROP COLUMN publication_approved_at'))
        connection.execute(text('DELETE FROM schema_migrations WHERE version=:v'),
            {'v': RUNTIME_SCHEMA_VERSION})
        connection.execute(text('DELETE FROM runtime_schema_history WHERE version=:v'),
            {'v': RUNTIME_SCHEMA_VERSION})

    pre_v26_columns = {column['name'] for column in inspect(engine).get_columns('problems')}
    assert {'publication_review_required', 'publication_approved_at'}.isdisjoint(pre_v26_columns)

    for _ in range(2):
        initialize(bind=engine)

        columns = {column['name']: column for column in inspect(engine).get_columns('problems')}
        assert columns['publication_review_required']['nullable'] is True
        assert columns['publication_approved_at']['nullable'] is True
        with replicas[0]() as db:
            problem = db.get(m.Problem, 'pre-v26-legacy-problem')
            assert problem.publication_review_required is None
            assert problem.publication_approved_at is None
            assert tuple(db.execute(text('''SELECT publication_review_required, publication_approved_at
                FROM problems WHERE id=:id'''), {'id': problem.id}).one()) == (None, None)
            assert db.query(m.Problem.id).filter(
                m.Problem.id == problem.id,
                m.Problem.id.in_(private_problem_ids()),
            ).first() is None
            assert db.execute(text('SELECT COUNT(*) FROM schema_migrations WHERE version=:v'),
                {'v': RUNTIME_SCHEMA_VERSION}).scalar() == 1

    with engine.connect() as connection:
        active = set(connection.execute(text(
            "SELECT version FROM schema_migrations WHERE version LIKE '%_v%'"
        )).scalars())
    assert RUNTIME_SCHEMA_VERSION == '20260927_problem_publication_gate_v26'
    assert active == {RUNTIME_SCHEMA_VERSION}


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
