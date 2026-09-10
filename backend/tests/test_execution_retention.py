"""SQLite/PostgreSQL content-retention boundaries and receipt/score invariants."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models import database as m
from app.services.durable_queue import DurableQueue, ExecutionExpired
from app.services.execution_retention import expire_execution_content
from tests.test_durable_queue import replicas


AT = datetime(2030, 1, 20)
PAYLOAD = {'code': 'private source', 'language': 'python', 'hidden': [{'output': 'hidden answer'}]}


def completed(factory, *, kind='run', age=8, status='completed', **fields):
    key = uuid4().hex
    queue = DurableQueue(factory, capacity=100)
    job_id = queue.enqueue(owner_key='owner', request_id=key, kind=kind, payload=PAYLOAD, at=AT-timedelta(days=age))
    with factory() as db:
        job = db.get(m.ExecutionJob, job_id)
        job.status, job.finished_at = status, AT-timedelta(days=age)
        job.result = {'value': {'stdout': 'private output'}, 'verdict': 'accepted'}
        for name, value in fields.items():
            setattr(job, name, value)
        db.commit()
    return job_id, key


def expire(factory, **kwargs):
    with factory() as db:
        count = expire_execution_content(db, at=AT, retention_days=7, **kwargs)
        db.commit()
        return count


def test_bounded_expiration_keeps_receipt_hash_and_blocks_all_same_key_replays(replicas):
    first, second = [completed(replicas[0]) for _ in range(2)]
    with replicas[0]() as db:
        hashes = {job.id: job.payload_hash for job in db.query(m.ExecutionJob).all()}
    assert expire(replicas[1], batch_size=1) == 1
    assert expire(replicas[0], batch_size=1) == 1
    assert expire(replicas[1]) == 0
    queue = DurableQueue(replicas[0])
    for job_id, key in (first, second):
        with replicas[1]() as db:
            job = db.get(m.ExecutionJob, job_id)
            assert job.payload == {} and job.result is None and job.content_expired_at == AT
            assert job.payload_hash == hashes[job_id] and job.status == 'completed'
            assert job.request_id == key
        for payload in (PAYLOAD, {'code': 'changed'}):
            with pytest.raises(ExecutionExpired):
                queue.enqueue(owner_key='owner', request_id=key, kind='run', payload=payload)
        with pytest.raises(ExecutionExpired):
            queue.read(job_id, owner_key='owner')
        assert queue.read(job_id, owner_key='someone-else') is None
    with replicas[1]() as db:
        assert db.query(m.ExecutionJob).count() == 2
    assert queue.claim() is None


def test_cutoff_active_uncertain_contest_and_unknown_jobs_are_preserved(replicas):
    protected = [
        completed(replicas[0], age=7), completed(replicas[0], age=6),
        completed(replicas[0], status='queued'), completed(replicas[0], status='running'),
        completed(replicas[0], status='unrecognized'), completed(replicas[0], kind='contest'),
        completed(replicas[0], kind='unknown-kind'),
        completed(replicas[0], lease_token='pending-token'),
        completed(replicas[0], lease_until=AT-timedelta(days=8)),
        completed(replicas[0], sandbox_operation={'kind': 'cleanup', 'id': 'pending'}),
        completed(replicas[0], finished_at=None),
    ]
    for kind in ('run', 'compile', 'practice', 'terminal'):
        completed(replicas[0], kind=kind, status='failed')
    assert expire(replicas[1]) == 4
    with replicas[0]() as db:
        for job_id, _ in protected:
            job = db.get(m.ExecutionJob, job_id)
            assert job.payload == PAYLOAD and job.content_expired_at is None


def test_contest_link_and_normal_score_history_are_untouched(replicas):
    contest_job, _ = completed(replicas[0], kind='practice')  # Defensive FK protection despite an inconsistent kind.
    practice_job, _ = completed(replicas[0], kind='practice')
    with replicas[0]() as db:
        db.add(m.User(id='solver', username='solver', hashed_password='', total_score=100))
        db.flush()
        db.add(m.Problem(id='p', creator_id='solver', title='p', difficulty='iron5', tags=[], description='', test_cases=[]))
        db.add(m.Contest(id='c', creator_id='solver', title='c', starts_at=AT-timedelta(days=10), ends_at=AT-timedelta(days=9)))
        db.flush()
        db.add(m.ContestProblem(id='cp', contest_id='c', problem_id='p', position=0, points=100, snapshot={'hidden': ['preserve']}))
        db.flush()
        db.add(m.ContestSubmission(id='cs', execution_job_id=contest_job, contest_id='c', contest_problem_id='cp', user_id='solver',
            request_id='contest-key', code='contest source', language='python', received_at=AT-timedelta(days=9), status='completed', verdict='accepted'))
        db.add(m.Submission(id='s', execution_job_id=practice_job, user_id='solver', problem_id='p', language='python', code='normal history', status='Accepted'))
        db.add(m.UserProblemScore(user_id='solver', challenge_id='p', points_awarded=100))
        db.commit()
    assert expire(replicas[1]) == 1
    with replicas[0]() as db:
        assert db.get(m.ExecutionJob, contest_job).payload == PAYLOAD
        assert db.get(m.ExecutionJob, practice_job).payload == {}
        assert db.get(m.ContestSubmission, 'cs').code == 'contest source'
        assert db.get(m.ContestProblem, 'cp').snapshot == {'hidden': ['preserve']}
        assert db.get(m.Submission, 's').code == 'normal history'
        assert db.get(m.User, 'solver').total_score == db.query(m.UserProblemScore).one().points_awarded == 100


def test_rollback_and_two_maintenance_instances_are_safe_without_loading_content(replicas):
    ids = [completed(replicas[0])[0] for _ in range(4)]
    with replicas[0]() as db:
        assert expire_execution_content(db, at=AT, retention_days=7) == 4
        db.rollback()
    with replicas[1]() as db:
        assert all(db.get(m.ExecutionJob, job_id).payload == PAYLOAD for job_id in ids)
    statements = []
    def capture(_connection, _cursor, sql, *_args):
        statements.append(sql.lower())
    engines = {factory.kw['bind'] for factory in replicas}
    for engine in engines:
        event.listen(engine, 'before_cursor_execute', capture)
    barrier = Barrier(2)
    def run(factory):
        barrier.wait(timeout=5)
        return expire(factory, batch_size=2)
    try:
        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(run, replicas)) == [2, 2]
    finally:
        for engine in engines:
            event.remove(engine, 'before_cursor_execute', capture)
    assert not any('select' in sql[:10] and ('execution_jobs.payload' in sql or 'execution_jobs.result' in sql) for sql in statements)
    assert expire(replicas[0]) == 0


def test_expiration_does_not_release_an_old_active_claim_or_overwrite_late_result(replicas):
    queue = DurableQueue(replicas[0], lease_seconds=20)
    received = AT-timedelta(days=8)
    job = queue.enqueue(owner_key='owner', request_id='active', kind='run', payload=PAYLOAD, at=received)
    claim = queue.claim(at=received)
    entered, release = Event(), Event()
    def paused_terminal(db, _job_id, _result):
        entered.set()
        assert release.wait(5)
    finishing = DurableQueue(replicas[0], on_terminal=paused_terminal)
    with ThreadPoolExecutor(2) as pool:
        done = pool.submit(finishing.finish, job, claim.token, {'verdict': 'finished'}, at=received+timedelta(seconds=1))
        try:
            assert entered.wait(3)
            scrub = pool.submit(expire, replicas[1])
        finally:
            release.set()
        assert done.result(timeout=5)
        assert scrub.result(timeout=5) == 1
    assert not queue.finish(job, claim.token, {'verdict': 'accepted'})
    with replicas[0]() as db:
        record = db.get(m.ExecutionJob, job)
        assert record.payload == {} and record.result is None and record.content_expired_at == AT


def test_no_content_is_removed_without_an_explicit_policy(replicas):
    job, _ = completed(replicas[0])
    with replicas[1]() as db:
        assert expire_execution_content(db, retention_days=0, at=AT) == 0
        db.commit()
        assert db.get(m.ExecutionJob, job).payload == PAYLOAD
    for invalid in (-1, 3651, True, '7'):
        with replicas[0]() as db, pytest.raises(ValueError):
            expire_execution_content(db, retention_days=invalid)
