"""Real isolated SQLite/API/queue, synthetic protected phase execution only."""
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, text

from app.main import app
from app.models import database as m
from app.models.contest_rejudge import RejudgeCreate
from app.services import contest_rejudge as service
from app.services import contests, execution_runtime
from app.services.judge_policy import content_hash
from app.services.judging import judge_code
from app.services.execution_worker import ExecutionWorker
from app.services.durable_queue import WorkerIdentity
from app.initialize import initialize, RUNTIME_SCHEMA_VERSION
from tests.test_contests import env, headers
from tests.test_judge_policy import policy_fixture
from tests.test_judge_metrics import phase_result, full_report


@pytest.fixture
def seeded(env, monkeypatch):
    monkeypatch.setattr(service, 'now_utc', lambda: env.clock[0])
    sample = [dict(input='', expectedOutput='42')]
    hidden = [dict(input='private-rejudge-input', expectedOutput='42')]
    snap = dict(title='Original problem', description='Original statement', difficulty='bronze5',
        tags=['io'], practicePoints=120, sample=sample, hidden=hidden, judgePolicy=policy_fixture(sample, hidden))
    with env.factory() as db:
        db.add(m.Problem(id='p', creator_id='admin', title=snap['title'], description=snap['description'],
            difficulty=snap['difficulty'], tags=snap['tags'], points=120, test_cases=dict(sample=sample, hidden=hidden),
            judge_policy=snap['judgePolicy']))
        db.add(m.Contest(id='c', creator_id='admin', title='Ended', description='', published=True,
            starts_at=env.clock[0]-timedelta(hours=1), ends_at=env.clock[0]-timedelta(seconds=1), finalized_at=env.clock[0]))
        db.flush()
        db.add(m.ContestProblem(id='cp', contest_id='c', problem_id='p', position=0, points=500, snapshot=snap))
        db.flush()
        for index, user in enumerate(('alice', 'bob')):
            db.add(m.ContestParticipant(contest_id='c', user_id=user))
            db.add(m.ContestSubmission(id='s'+str(index), contest_id='c', contest_problem_id='cp', user_id=user,
                request_id=user, language='python', code='print(42)' if index == 0 else 'print(43)',
                received_at=env.clock[0]-timedelta(seconds=30-index), finished_at=env.clock[0], status='completed',
                verdict='accepted' if index == 0 else 'wrong_answer'))
        db.add(m.UserProblemScore(user_id='alice', challenge_id='p', points_awarded=120, solved_at=env.clock[0]))
        db.query(m.User).filter_by(id='alice').update({'total_score':120})
        db.commit()
    candidate_sample = [dict(input='', expectedOutput='43')]
    candidate_hidden = [dict(input='corrected-private-input', expectedOutput='43')]
    policy = policy_fixture(candidate_sample, candidate_hidden); policy['revision'] = 2
    return dict(requestId='test-correction-1', contestProblemId='cp', expectedSnapshotHash=content_hash(snap),
        reason='합성 테스트의 정답과 제한 정책을 수정합니다.', sample=candidate_sample, hidden=candidate_hidden, judgePolicy=policy)


def create(env, data):
    with env.factory() as db:
        return service.create_batch(db, 'c', RejudgeCreate.model_validate(data), env.admin)


def worker(env, queue, monkeypatch):
    from app.services import execution_worker
    monkeypatch.setattr(execution_worker, 'judge_code', judge_code)
    # This fixture proves queue/publication behavior with a synthetic runner.
    # Runtime-registry replay itself is covered by dedicated Docker-runner tests.
    monkeypatch.setattr(ExecutionWorker, '_replay_eligibility', staticmethod(
        lambda *_args, **_kwargs: (lambda _kind, _payload, _job_id=None: True)))
    class Runner:
        def measured_submission(self, payload):
            self.code = payload['code']; return self
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def _execute(self, **_): return phase_result('compile')
        async def run(self, **kwargs):
            assert kwargs['stdin'] in ('', 'corrected-private-input')
            result = phase_result(); result['stdout'] = '43' if self.code == 'print(43)' else '42'
            return result
    return ExecutionWorker(queue, pool=SimpleNamespace(labels=lambda *_:{}, reap=lambda *_:None),
        runner_factory=lambda **_:Runner())


@pytest.mark.asyncio
async def test_admin_access_idempotency_and_no_private_projection(env, seeded):
    root = '/api/v1/contests/c/rejudges'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for path in (root, root+'/context?contestProblemId=cp', root+'/unknown'):
            assert (await client.get(path, headers=headers(env.alice))).status_code == 403
            assert (await client.get(path)).status_code == 401
        assert (await client.post(root, json=seeded, headers=headers(env.alice))).status_code == 403
        ctx = await client.get(root+'/context?contestProblemId=cp', headers=headers(env.admin))
        assert ctx.json()['snapshotHash'] == seeded['expectedSnapshotHash']
        assert ctx.headers['Cache-Control'] == 'no-store'
        first = await client.post(root, json=seeded, headers=headers(env.admin))
        assert first.status_code == 202, first.text
        repeat = await client.post(root, json=seeded, headers=headers(env.admin))
        assert repeat.json() == first.json()
        conflict = await client.post(root, json={**seeded, 'reason':'다른 변경 이유를 사용하는 잘못된 재시도입니다.'}, headers=headers(env.admin))
        assert conflict.status_code == 409
        assert (await client.post(root, json={**seeded, 'requestId':'another'}, headers=headers(env.admin))).status_code == 409
        detail = await client.get(root+'/'+first.json()['id']+'?limit=1&offset=1', headers=headers(env.admin))
        assert detail.json()['totalItems'] == 2 and len(detail.json()['items']) == 1
        listed = await client.get(root, headers=headers(env.admin))
        assert listed.json()['total'] == 1
        for response in (first, detail, listed):
            assert response.headers['Cache-Control'] == 'no-store'
            assert all(secret not in response.text for secret in ('corrected-private-input', 'print(42)', 'judgePolicy', 'sample', 'hidden'))
        assert (await client.get('/api/v1/contests/wrong/rejudges/'+first.json()['id'], headers=headers(env.admin))).status_code == 404
    with env.factory() as db:
        assert db.query(m.ContestRejudgeBatch).count() == 1
        assert db.query(m.ContestRejudgeItem).count() == 2
        assert db.query(m.ExecutionJob).count() == 0


@pytest.mark.parametrize('change', ['upcoming', 'not_final', 'pending_submission', 'stale', 'old_revision', 'different_policy', 'bad_evidence', 'missing_language', 'empty_reason'])
def test_invalid_correction_atomic(env, seeded, change):
    data = deepcopy(seeded)
    with env.factory() as db:
        if change == 'upcoming': db.get(m.Contest,'c').ends_at = env.clock[0]+timedelta(hours=1)
        elif change == 'not_final': db.get(m.Contest,'c').finalized_at = None
        elif change == 'pending_submission': db.get(m.ContestSubmission,'s0').status = 'running'
        db.commit()
    if change == 'stale': data['expectedSnapshotHash'] = 'sha256:'+'f'*64
    elif change == 'old_revision': data['judgePolicy']['revision'] = 1
    elif change == 'different_policy': data['judgePolicy']['policyId'] = 'other'
    elif change == 'bad_evidence': data['judgePolicy']['testSuiteHash'] = 'sha256:'+'f'*64
    elif change == 'missing_language':
        data['judgePolicy'] = policy_fixture(data['sample'], data['hidden'], ('c',)); data['judgePolicy']['revision'] = 2
    elif change == 'empty_reason': data['reason'] = ' '*20
    with pytest.raises((ValueError, service.HTTPException)):
        create(env, data)
    with env.factory() as db:
        assert db.query(m.ContestRejudgeBatch).count() == db.query(m.ContestRejudgeItem).count() == 0


@pytest.mark.asyncio
async def test_restart_bounded_dispatch_measured_results_do_not_change_live_scores(env, seeded, monkeypatch):
    with env.factory() as db:
        before = contests.scoreboard(db, db.get(m.Contest,'c'), at=env.clock[0])
        original = {s.id:service.submission_fingerprint(s) for s in db.query(m.ContestSubmission)}
    batch = create(env, seeded)
    first_queue = execution_runtime.execution_queue(); first_queue.per_owner = 1
    assert service.dispatch_pending(first_queue) == 1
    assert service.dispatch_pending(first_queue) == 0
    assert await worker(env, first_queue, monkeypatch).run_once()
    with env.factory() as db:
        assert db.get(m.ContestRejudgeBatch,batch['id']).status == 'running'
    # A fresh queue and worker resume the undispatched second item, without new source reads.
    restarted = execution_runtime.execution_queue(); restarted.per_owner = 1
    assert service.dispatch_pending(restarted) == 1
    assert await worker(env, restarted, monkeypatch).run_once()
    assert service.dispatch_pending(restarted) == 0
    with env.factory() as db:
        detail = service.batch_detail(db,'c',batch['id'])
        assert detail['status'] == 'ready' and detail['changed'] == detail['completed'] == 2
        assert [r['afterVerdict'] for r in detail['items']] == ['wrong_answer','accepted']
        assert contests.scoreboard(db,db.get(m.Contest,'c'),at=env.clock[0]) == before
        assert {s.id:service.submission_fingerprint(s) for s in db.query(m.ContestSubmission)} == original
        assert db.get(m.User,'alice').total_score == 120 and db.get(m.User,'bob').total_score == 0
        assert db.query(m.UserProblemScore).count() == 1
        assert db.query(m.ExecutionJob).count() == 2
        assert all(i.resource_report for i in db.query(m.ContestRejudgeItem))


def test_result_fence_corrupt_report_and_discard_audit(env, seeded, monkeypatch):
    from app.models.contest_rejudge import RejudgeDiscard
    monkeypatch.setattr(service, 'MAX_SUBMISSIONS', 1)
    batch = create(env, seeded)
    queue = execution_runtime.execution_queue(); queue.max_attempts = 1
    service.dispatch_pending(queue)
    identity = WorkerIdentity(uuid4().hex,'test-pool','','test-sandboxes')
    claim = queue.claim(worker=identity)
    assert claim
    protected = full_report(claim.payload)
    bad = deepcopy(protected); bad['identity']['revision'] = 99
    assert not queue.finish(claim.id,'wrong-token',dict(verdict='accepted',value={'_resource_report':protected}))
    for report in (None, bad):
        with pytest.raises(ValueError):
            queue.finish(claim.id,claim.token,dict(verdict='accepted',value={'_resource_report':report}))
    # Valid measurements contradict WA; transaction must remain uncompleted.
    with pytest.raises(ValueError):
        queue.finish(claim.id,claim.token,dict(verdict='wrong_answer',value={'_resource_report':protected}))
    assert queue.finish(claim.id,claim.token,dict(verdict='accepted',value={'_resource_report':protected}))
    assert not queue.finish(claim.id,claim.token,dict(verdict='wrong_answer',value={}))
    other = queue.claim(worker=identity); assert other
    assert queue.finish(other.id,other.token,dict(verdict='system_error',value={}))
    with env.factory() as db:
        record = db.get(m.ContestRejudgeBatch,batch['id'])
        assert record.status == 'failed'
        assert sorted(s.status for s in db.query(m.ContestRejudgeShard).filter_by(
            batch_id=batch['id'])) == ['failed', 'ready']
        request = RejudgeDiscard(expectedRequestHash=record.request_hash)
        result = service.discard_candidate(db,'c',record.id,request,env.admin)
        assert result['status'] == 'cancelled'
    with env.factory() as db:
        record = db.get(m.ContestRejudgeBatch,batch['id'])
        assert record.discarded_by == 'admin' and record.discarded_at == env.clock[0]
        assert db.get(m.ContestSubmission,'s0').verdict == 'accepted'


def test_frozen_sources_survive_edits_and_queue_failure_rolls_back(env, seeded, monkeypatch):
    create(env, seeded)
    with env.factory() as db:
        row = db.get(m.ContestSubmission,'s0'); row.code = 'mutated after batch'
        cp = db.get(m.ContestProblem,'cp'); cp.snapshot = {**cp.snapshot, 'hidden':[]}; db.commit()
    queue = execution_runtime.execution_queue()
    original = queue.enqueue_in_session
    calls = []
    def fail_second(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2: raise RuntimeError('Synthetic DB/dispatch failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(queue,'enqueue_in_session',fail_second)
    with pytest.raises(RuntimeError): service.dispatch_pending(queue)
    with env.factory() as db:
        assert db.query(m.ExecutionJob).count() == 0
        assert all(i.execution_job_id is None for i in db.query(m.ContestRejudgeItem))
    monkeypatch.setattr(queue,'enqueue_in_session',original)
    assert service.dispatch_pending(queue) == 2
    with env.factory() as db:
        jobs = list(db.query(m.ExecutionJob))
        assert {j.payload['code'] for j in jobs} == {'print(42)','print(43)'}
        assert all(j.payload['hidden'] == seeded['hidden'] for j in jobs)


def test_campaign_shards_are_deterministic_and_exact_retry_reuses_boundaries(env, seeded, monkeypatch):
    monkeypatch.setattr(service, 'MAX_SUBMISSIONS', 1)
    first = create(env, seeded)
    with env.factory() as db:
        shards = db.query(m.ContestRejudgeShard).filter_by(batch_id=first['id']).order_by(
            m.ContestRejudgeShard.sequence).all()
        boundaries = [(shard.id, shard.sequence, [item.submission_id for item in
            db.query(m.ContestRejudgeItem).filter_by(shard_id=shard.id).order_by(
                m.ContestRejudgeItem.received_at, m.ContestRejudgeItem.submission_id)])
            for shard in shards]

    repeated = create(env, seeded)

    assert first['id'] == repeated['id']
    assert first == repeated
    assert first['total'] == 2 and first['shardCount'] == 2
    assert [(sequence, members) for _, sequence, members in boundaries] == [
        (0, ['s0']), (1, ['s1'])]
    with env.factory() as db:
        assert db.query(m.ContestRejudgeShard).filter_by(batch_id=first['id']).count() == 2
        assert db.query(m.ContestRejudgeItem).filter_by(batch_id=first['id']).count() == 2
        assert [(shard.id, shard.sequence, [item.submission_id for item in
            db.query(m.ContestRejudgeItem).filter_by(shard_id=shard.id).order_by(
                m.ContestRejudgeItem.received_at, m.ContestRejudgeItem.submission_id)])
            for shard in db.query(m.ContestRejudgeShard).filter_by(batch_id=first['id']).order_by(
                m.ContestRejudgeShard.sequence)] == boundaries


def test_campaign_splits_before_source_byte_limit(env, seeded, monkeypatch):
    monkeypatch.setattr(service, 'MAX_SOURCE_BYTES', len('print(42)'.encode('utf-8')) + 1)
    batch = create(env, seeded)
    with env.factory() as db:
        shards = db.query(m.ContestRejudgeShard).filter_by(batch_id=batch['id']).order_by(
            m.ContestRejudgeShard.sequence).all()
        assert [(s.sequence, s.item_count, s.source_bytes) for s in shards] == [
            (0, 1, len('print(42)'.encode('utf-8'))),
            (1, 1, len('print(43)'.encode('utf-8'))),
        ]
        assert db.get(m.ContestRejudgeBatch, batch['id']).source_bytes == sum(s.source_bytes for s in shards)


def test_campaign_source_byte_exact_boundary_stays_in_one_shard(env, seeded, monkeypatch):
    total = len('print(42)'.encode('utf-8')) + len('print(43)'.encode('utf-8'))
    monkeypatch.setattr(service, 'MAX_SOURCE_BYTES', total)
    batch = create(env, seeded)
    with env.factory() as db:
        shard = db.query(m.ContestRejudgeShard).filter_by(batch_id=batch['id']).one()
        assert shard.item_count == 2 and shard.source_bytes == total


def test_campaign_oversized_single_source_rolls_back_all_rows(env, seeded, monkeypatch):
    monkeypatch.setattr(service, 'MAX_SOURCE_BYTES', len('print(42)'.encode('utf-8')) - 1)
    with pytest.raises(service.HTTPException) as error:
        create(env, seeded)
    assert error.value.status_code == 413
    with env.factory() as db:
        assert db.query(m.ContestRejudgeBatch).count() == 0
        assert db.query(m.ContestRejudgeShard).count() == 0
        assert db.query(m.ContestRejudgeItem).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('corruption', ['manifest', 'membership', 'candidate', 'before_verdict'])
async def test_campaign_frozen_or_candidate_corruption_blocks_first_preview(env, seeded, monkeypatch, corruption):
    monkeypatch.setattr(service, 'MAX_SUBMISSIONS', 1)
    batch = create(env, seeded)
    queue = execution_runtime.execution_queue()
    assert service.dispatch_pending(queue) == 2
    runner = worker(env, queue, monkeypatch)
    assert await runner.run_once()
    assert await runner.run_once()

    with env.factory() as db:
        shards = db.query(m.ContestRejudgeShard).filter_by(batch_id=batch['id']).order_by(
            m.ContestRejudgeShard.sequence).all()
        assert [shard.status for shard in shards] == ['ready', 'ready']
        if corruption == 'manifest':
            shards[0].manifest_hash = 'sha256:' + 'f' * 64
        elif corruption == 'membership':
            item = db.query(m.ContestRejudgeItem).filter_by(
                batch_id=batch['id'], submission_id='s0').one()
            item.shard_id = shards[1].id
        elif corruption == 'candidate':
            item = db.query(m.ContestRejudgeItem).filter_by(
                batch_id=batch['id'], submission_id='s0').one()
            item.after_verdict = 'accepted' if item.after_verdict != 'accepted' else 'wrong_answer'
        else:
            item = db.query(m.ContestRejudgeItem).filter_by(
                batch_id=batch['id'], submission_id='s0').one()
            item.before_verdict = 'wrong_answer'
        db.commit()

    for candidate_call in ('ready_candidate', 'preview_candidate'):
        with env.factory() as db, pytest.raises(service.HTTPException) as error:
            if candidate_call == 'ready_candidate':
                service.ready_candidate(db, 'c', db.get(m.ContestRejudgeBatch, batch['id']))
            else:
                service.preview_candidate(db, 'c', batch['id'])
        assert error.value.status_code == 409


def test_v21_additive_initialization_from_physical_legacy_shape_keeps_records(env, seeded):
    batch = create(env, seeded)
    engine = env.db.get_bind()
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'))
        connection.execute(text("INSERT INTO schema_migrations (version) VALUES ('20260926_judge_test_data_v16')"))
        # Reconstruct the physical pre-v21 shape instead of merely inserting an
        # old marker into tables already created from current metadata.
        if engine.dialect.name == 'sqlite':
            # SQLite cannot drop an FK column, so rebuild the old item table.
            connection.execute(text('ALTER TABLE contest_rejudge_items RENAME TO contest_rejudge_items_v21'))
            connection.execute(text('''CREATE TABLE contest_rejudge_items (
                id VARCHAR NOT NULL PRIMARY KEY,
                batch_id VARCHAR NOT NULL REFERENCES contest_rejudge_batches(id),
                submission_id VARCHAR NOT NULL REFERENCES contest_submissions(id),
                execution_job_id VARCHAR UNIQUE REFERENCES execution_jobs(id),
                language VARCHAR NOT NULL, code TEXT NOT NULL, received_at DATETIME NOT NULL,
                before_verdict VARCHAR NOT NULL, before_fingerprint VARCHAR NOT NULL,
                judge_contract JSON NOT NULL, status VARCHAR NOT NULL,
                after_verdict VARCHAR, resource_report JSON, finished_at DATETIME,
                UNIQUE(batch_id, submission_id))'''))
            connection.execute(text('''INSERT INTO contest_rejudge_items
                (id,batch_id,submission_id,execution_job_id,language,code,received_at,
                 before_verdict,before_fingerprint,judge_contract,status,after_verdict,
                 resource_report,finished_at)
                SELECT id,batch_id,submission_id,execution_job_id,language,code,received_at,
                 before_verdict,before_fingerprint,judge_contract,status,after_verdict,
                 resource_report,finished_at FROM contest_rejudge_items_v21'''))
            connection.execute(text('DROP TABLE contest_rejudge_items_v21'))
            for column in ('batch_id','submission_id','status'):
                connection.execute(text(
                    f'CREATE INDEX ix_contest_rejudge_items_{column} ON contest_rejudge_items ({column})'))
        else:
            # PostgreSQL can remove the additive columns directly while
            # preserving every pre-v21 item and its existing constraints.
            connection.execute(text('ALTER TABLE contest_rejudge_items DROP COLUMN shard_id'))
            connection.execute(text('ALTER TABLE contest_rejudge_items DROP COLUMN candidate_receipt_hash'))
        connection.execute(text('DROP TABLE contest_rejudge_shards'))
        connection.execute(text('ALTER TABLE contest_rejudge_batches DROP COLUMN submission_set_hash'))
        connection.execute(text('ALTER TABLE contest_rejudge_batches DROP COLUMN shard_count'))
        connection.execute(text('ALTER TABLE contest_rejudge_batches DROP COLUMN source_bytes'))
    initialize(bind=engine,skip_bootstrap=True); initialize(bind=engine,skip_bootstrap=True)
    assert {'contest_rejudge_batches','contest_rejudge_shards','contest_rejudge_items'} <= set(inspect(engine).get_table_names())
    assert {'submission_set_hash','shard_count','source_bytes'} <= {
        c['name'] for c in inspect(engine).get_columns('contest_rejudge_batches')}
    assert {'shard_id','candidate_receipt_hash'} <= {
        c['name'] for c in inspect(engine).get_columns('contest_rejudge_items')}
    with env.factory() as db:
        assert db.get(m.ContestRejudgeBatch,batch['id']).reason == seeded['reason']
        assert db.query(m.ContestRejudgeItem).count() == 2
        versions = list(db.execute(text('SELECT version FROM schema_migrations')).scalars())
        assert versions.count(RUNTIME_SCHEMA_VERSION) == 1
        assert versions.count('20260926_judge_test_data_v16') == 0
        assert db.execute(text('SELECT 1 FROM runtime_schema_history WHERE version=:v'),
                          {'v':'20260926_judge_test_data_v16'}).first()
