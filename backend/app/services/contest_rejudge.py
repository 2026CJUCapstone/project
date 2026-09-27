"""Staged corrections on the durable queue, never implicit score changes.

Live submissions and scores stay intact until a separate audited apply step.
Every candidate keeps original source/time plus the exact corrected policy.
"""
from copy import deepcopy
import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import func, cast, String
from sqlalchemy.orm import load_only
from app.core.config import settings
from app.models import database as m
from app.services.contest_access import now_utc, utc_naive, iso
from app.services.judge_policy import content_hash, stored_policy, freeze_stored_submission, validate_stored_publication
from app.services.judge_test_manifest import validate_stored_cases
from app.models.judge_test_manifest import canonical_suite
from app.services.runtime_registry import execution_lock
from app.services.durable_queue import QueueFull
from app.services import contest_rejudge_review as correction_review

MAX_SUBMISSIONS = 1000
MAX_SOURCE_BYTES = 64 * 1024**2
MAX_CAMPAIGN_SUBMISSIONS = 10_000
MAX_CAMPAIGN_SOURCE_BYTES = 512 * 1024**2
OPEN_STATES = ('pending', 'running', 'ready')


def submission_fingerprint(row):
    return _submission_fingerprint_values(row.id, row.user_id, row.contest_problem_id,
        row.code, row.language, row.received_at, row.status, row.verdict,
        row.finished_at, row.execution_job_id, row.resource_report)


def _submission_fingerprint_values(identifier, user_id, problem_id, code, language, received_at,
        status, verdict, finished_at, execution_job_id, resource_report):
    return content_hash(dict(id=identifier, userId=user_id, problemId=problem_id,
        code=code, language=language, receivedAt=iso(received_at), status=status,
        verdict=verdict, finishedAt=iso(finished_at), executionJobId=execution_job_id,
        resourceReport=resource_report))


def _manifest_hash(entries):
    return content_hash(dict(version=1, items=entries))


def _campaign_hash(shards):
    return content_hash(dict(version=1, shards=[dict(sequence=s.sequence, itemCount=s.item_count,
        sourceBytes=s.source_bytes, manifestHash=s.manifest_hash) for s in shards]))


def _candidate_receipt_hash(verdict, report, finished_at):
    return content_hash(dict(version=1, verdict=verdict,
        resourceReport=report, finishedAt=iso(finished_at)))


def _contest(db, contest_id):
    contest = db.get(m.Contest, contest_id)
    if contest is None:
        raise HTTPException(404, '대회를 찾을 수 없습니다.')
    return contest


def context(db, contest_id, problem_id):
    _contest(db, contest_id)
    row = db.query(m.ContestProblem).filter_by(id=problem_id, contest_id=contest_id).first()
    if row is None:
        raise HTTPException(404, '대회 문제를 찾을 수 없습니다.')
    return dict(contestProblemId=row.id, snapshotHash=content_hash(row.snapshot), snapshot=deepcopy(row.snapshot))


def summary(db, batch):
    rows = db.query(m.ContestRejudgeItem.status, m.ContestRejudgeItem.before_verdict,
                    m.ContestRejudgeItem.after_verdict).filter_by(batch_id=batch.id).all()
    shards = db.query(m.ContestRejudgeShard).filter_by(batch_id=batch.id).order_by(
        m.ContestRejudgeShard.sequence).all()
    return dict(id=batch.id, contestProblemId=batch.contest_problem_id, actorId=batch.actor_id,
        reason=batch.reason, revision=batch.revision, status=batch.status, createdAt=iso(batch.created_at),
        finishedAt=iso(batch.finished_at), total=len(rows), completed=sum(r.status == 'completed' for r in rows),
        changed=sum(r.status == 'completed' and r.before_verdict != r.after_verdict for r in rows),
        failed=sum(r.after_verdict in ('system_error', 'canceled') for r in rows),
        shardCount=len(shards) if shards else 1,
        completedShards=sum(s.status in ('ready', 'failed') for s in shards) if shards else (
            1 if batch.status in ('ready', 'failed', 'cancelled', 'applied') else 0))


def list_batches(db, contest_id, *, offset=0, limit=20):
    _contest(db, contest_id)
    query = db.query(m.ContestRejudgeBatch).filter_by(contest_id=contest_id)
    return dict(total=query.count(), batches=[summary(db, row) for row in query.order_by(
        m.ContestRejudgeBatch.created_at.desc(), m.ContestRejudgeBatch.id.desc()).offset(offset).limit(limit)])


def batch_detail(db, contest_id, batch_id, *, offset=0, limit=50):
    batch = db.query(m.ContestRejudgeBatch).filter_by(id=batch_id, contest_id=contest_id).first()
    if batch is None:
        raise HTTPException(404, '재채점 기록을 찾을 수 없습니다.')
    query = db.query(m.ContestRejudgeItem).filter_by(batch_id=batch.id)
    rows = query.order_by(m.ContestRejudgeItem.received_at, m.ContestRejudgeItem.submission_id).offset(offset).limit(limit)
    applied = db.get(m.ContestRejudgeApplication, batch.id)
    application = None if applied is None else dict(actorId=applied.actor_id, appliedAt=iso(applied.applied_at),
        publicNote=applied.public_note, beforeRevision=applied.before_revision, afterRevision=applied.after_revision,
        legacyResolutionProvenance=deepcopy(applied.legacy_resolution_provenance))
    shard_sequence = {s.id:s.sequence for s in db.query(m.ContestRejudgeShard).filter_by(batch_id=batch.id)}
    return {**summary(db, batch), 'requestHash':batch.request_hash,
        'beforeScoreboardRevision':batch.before_scoreboard_revision, 'application':application,
        'totalItems':query.count(), 'offset':offset, 'limit':limit,
        'items':[dict(id=r.id, submissionId=r.submission_id, shardSequence=shard_sequence.get(r.shard_id, 0),
            language=r.language, receivedAt=iso(r.received_at),
            status=r.status, beforeVerdict=r.before_verdict, afterVerdict=r.after_verdict,
            finishedAt=iso(r.finished_at)) for r in rows]}


def create_batch(db, contest_id, data, actor):
    if actor.role != 'admin':
        raise HTTPException(403, '관리자 권한이 필요합니다.')
    execution_lock(db)
    request_data = data.model_dump(mode='json', by_alias=True)
    if data.authoring is None: request_data.pop('authoring')  # Keep old exact-retry hashes stable.
    request_hash = content_hash(dict(contestId=contest_id, **request_data))
    old = db.query(m.ContestRejudgeBatch).filter_by(actor_id=actor.id, request_id=data.request_id).first()
    if old is not None:
        if old.request_hash != request_hash:
            raise HTTPException(409, '같은 요청 ID를 다른 재채점에 사용할 수 없습니다.')
        return summary(db, old)
    contest = _contest(db, contest_id)
    if not contest.published or contest.finalized_at is None or utc_naive(contest.ends_at) > now_utc():
        raise HTTPException(409, '종료 후 기존 채점이 확정된 대회만 재채점할 수 있습니다.')
    if db.query(m.ContestRejudgeBatch.id).filter(m.ContestRejudgeBatch.contest_id == contest_id,
            m.ContestRejudgeBatch.status.in_(OPEN_STATES)).first():
        raise HTTPException(409, '아직 처리 중이거나 반영 대기 중인 재채점이 있습니다.')
    problem = db.query(m.ContestProblem).filter_by(id=data.contest_problem_id, contest_id=contest_id).first()
    if problem is None:
        raise HTTPException(404, '대회 문제를 찾을 수 없습니다.')
    if content_hash(problem.snapshot) != data.expected_snapshot_hash:
        raise HTTPException(409, '대회 문제 버전이 변경되었습니다. 최신 내용을 확인하세요.')
    snapshot = deepcopy(problem.snapshot)
    suite = canonical_suite([x.model_dump(by_alias=True) for x in data.sample],
                            [x.model_dump(by_alias=True) for x in data.hidden])
    sample, hidden = suite['sample'], suite['hidden']
    try:
        policy = stored_policy(data.judge_policy, previous=snapshot.get('judgePolicy'))
        if policy == snapshot.get('judgePolicy'):
            raise ValueError('재채점에는 새 정책 버전과 측정 근거가 필요합니다.')
        validate_stored_cases(db, sample, hidden, integrity=True)
        validate_stored_publication(policy, sample, hidden, settings=settings)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    snapshot.update(sample=sample, hidden=hidden, judgePolicy=policy)
    if data.authoring is not None:
        snapshot['authoring'] = data.authoring.model_dump(mode='json', by_alias=True)
    query = db.query(m.ContestSubmission).filter_by(contest_problem_id=problem.id)
    count = query.count()
    if not count:
        raise HTTPException(409, '재채점할 제출이 없습니다.')
    if count > MAX_CAMPAIGN_SUBMISSIONS:
        raise HTTPException(413, '재채점 캠페인의 제출 수 안전 한도를 초과했습니다.')
    ordered_ids = [row[0] for row in query.with_entities(m.ContestSubmission.id).order_by(
        m.ContestSubmission.received_at, m.ContestSubmission.id).all()]
    revision = (db.query(func.max(m.ContestRejudgeBatch.revision)).filter_by(contest_problem_id=problem.id).scalar() or 0) + 1
    batch = m.ContestRejudgeBatch(id=str(uuid4()), contest_id=contest_id,
        contest_problem_id=problem.id, actor_id=actor.id, request_id=data.request_id,
        request_hash=request_hash, reason=data.reason, revision=revision,
        before_snapshot_hash=data.expected_snapshot_hash,
        before_scoreboard_revision=contest.scoreboard_revision, snapshot=snapshot,
        review_basis=correction_review.freeze_basis(db, problem, snapshot), created_at=now_utc(),
        status='pending', submission_set_hash='', shard_count=0, source_bytes=0)
    contracts, shards = {}, []
    shard_items, shard_entries, shard_bytes = [], [], 0
    campaign_bytes = 0

    def freeze_shard():
        nonlocal shard_items, shard_entries, shard_bytes
        if not shard_items:
            return
        shard = m.ContestRejudgeShard(id=str(uuid4()), batch_id=batch.id, sequence=len(shards),
            item_count=len(shard_items), source_bytes=shard_bytes,
            manifest_hash=_manifest_hash(shard_entries), status='pending')
        db.add(shard)
        # ContestRejudgeItem stores only the scalar shard_id, so SQLAlchemy has
        # no relationship edge from which to derive INSERT ordering. PostgreSQL
        # enforces the FK immediately; persist the bounded parent row first.
        db.flush([shard])
        for values in shard_items:
            db.add(m.ContestRejudgeItem(batch_id=batch.id, shard_id=shard.id, **values))
        # Flush one bounded shard at a time so source text from earlier shards is
        # not retained as pending ORM state for the whole campaign.
        db.flush()
        shards.append(shard)
        shard_items, shard_entries, shard_bytes = [], [], 0

    # One savepoint prevents a validation error half-way through a large source
    # scan from leaving a partial campaign in a caller-owned transaction.
    with db.begin_nested():
        db.add(batch); db.flush()
        for start in range(0, len(ordered_ids), 25):
            chunk = ordered_ids[start:start + 25]
            found = {row.id:row for row in query.filter(m.ContestSubmission.id.in_(chunk)).all()}
            if len(found) != len(chunk):
                raise HTTPException(409, '재채점 생성 중 제출 집합이 변경되었습니다.')
            for identifier in chunk:
                row = found[identifier]
                if row.status != 'completed':
                    raise HTTPException(409, '아직 완료되지 않은 원래 제출이 있습니다.')
                source_bytes = len(row.code.encode('utf-8'))
                if source_bytes > MAX_SOURCE_BYTES:
                    raise HTTPException(413, '단일 제출이 재채점 shard의 코드 보관 한도를 초과했습니다.')
                campaign_bytes += source_bytes
                if campaign_bytes > MAX_CAMPAIGN_SOURCE_BYTES:
                    raise HTTPException(413, '재채점 캠페인의 코드 보관 안전 한도를 초과했습니다.')
                if shard_items and (len(shard_items) >= MAX_SUBMISSIONS
                        or shard_bytes + source_bytes > MAX_SOURCE_BYTES):
                    freeze_shard()
                try:
                    if row.language not in contracts:
                        contracts[row.language] = freeze_stored_submission(
                            policy, row.language, sample, hidden, settings=settings)
                    # Reserve headroom for fixed IDs, preventing a partially dispatchable shard.
                    if len(json.dumps(dict(kind='contest', payload=dict(code=row.code, sample=sample, hidden=hidden,
                            judge_contract=contracts[row.language])), ensure_ascii=False).encode('utf-8')) > 1_900_000:
                        raise ValueError('테스트가 너무 큽니다. 대용량 숨김 테스트 저장 참조를 사용하세요.')
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from None
                values = dict(id=str(uuid4()), submission_id=row.id, language=row.language, code=row.code,
                    received_at=row.received_at, before_verdict=row.verdict,
                    before_fingerprint=submission_fingerprint(row),
                    judge_contract=deepcopy(contracts[row.language]), status='pending')
                shard_items.append(values)
                shard_entries.append(dict(submissionId=values['submission_id'],
                    beforeFingerprint=values['before_fingerprint'], beforeVerdict=values['before_verdict'],
                    language=values['language'],
                    receivedAt=iso(values['received_at']), sourceBytes=source_bytes,
                    sourceHash=content_hash(values['code']), contractHash=content_hash(values['judge_contract'])))
                shard_bytes += source_bytes
        freeze_shard()
        batch.shard_count = len(shards)
        batch.source_bytes = campaign_bytes
        batch.submission_set_hash = _campaign_hash(shards)
        db.flush()
    result = summary(db, batch); db.commit()
    return result


def dispatch_pending(queue, *, limit=4):
    """Restart-safe pump; shared maintenance quota cannot bypass normal capacity."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('Bounded dispatch limit required')
    with queue.sessions() as db:
        queue._lock(db)
        items = db.query(m.ContestRejudgeItem).join(m.ContestRejudgeBatch).filter(
            m.ContestRejudgeItem.status == 'pending', m.ContestRejudgeItem.execution_job_id.is_(None),
            m.ContestRejudgeBatch.status.in_(('pending', 'running'))).order_by(
                m.ContestRejudgeBatch.created_at, m.ContestRejudgeItem.received_at,
                m.ContestRejudgeItem.submission_id).limit(limit).all()
        count = 0
        for item in items:
            batch = db.get(m.ContestRejudgeBatch, item.batch_id)
            payload = dict(rejudge_item_id=item.id, code=item.code, language=item.language,
                contest_id=batch.contest_id, contest_problem_id=batch.contest_problem_id,
                sample=deepcopy(batch.snapshot['sample']), hidden=deepcopy(batch.snapshot['hidden']),
                judge_contract=deepcopy(item.judge_contract))
            try:
                job = queue.enqueue_in_session(db, owner_key='rejudge:'+batch.id, quota_key='rejudge:maintenance',
                    request_id=item.id, kind='contest', payload=payload, at=now_utc())
            except QueueFull:
                break
            item.execution_job_id = job.id; item.status = 'queued'; batch.status = 'running'
            count += 1
        db.commit()
        return count


def publish_candidate(db, job_id, verdict, report):
    item = db.query(m.ContestRejudgeItem).filter_by(execution_job_id=job_id).first()
    if item is None:
        return False
    if item.status == 'completed':
        return True
    if verdict not in ('system_error', 'canceled') and report is None:
        raise ValueError('Rejudge results require protected resource measurements')
    if report is not None:
        from app.services.compile_queue import classify_compile_stage_result
        compiled = report['compile']
        compile_verdict = classify_compile_stage_result(dict(exit_code=compiled['exitCode'],
            failure_reason=compiled['failureReason'], execution_phase='compile'))
        cases = report['cases']
        payload = db.get(m.ExecutionJob, job_id).payload
        expected = len(payload['sample']) + len(payload['hidden'])
        derived = compile_verdict if compile_verdict != 'compile_success' else next(
            (c['verdict'] for c in cases if c['verdict'] != 'accepted'),
            'accepted' if len(cases) == expected else 'system_error')
        if verdict != derived:
            raise ValueError('Rejudge verdict disagrees with protected phase results')
    item.status = 'completed'; item.after_verdict = verdict
    item.resource_report = deepcopy(report); item.finished_at = now_utc()
    item.candidate_receipt_hash = _candidate_receipt_hash(
        item.after_verdict, item.resource_report, item.finished_at)
    db.flush()
    batch = db.get(m.ContestRejudgeBatch, item.batch_id)
    if item.shard_id:
        shard = db.get(m.ContestRejudgeShard, item.shard_id)
        if shard is None or shard.batch_id != batch.id:
            raise ValueError('Rejudge shard ownership is invalid')
        if not db.query(m.ContestRejudgeItem.id).filter(
                m.ContestRejudgeItem.shard_id == shard.id,
                m.ContestRejudgeItem.status != 'completed').first():
            shard_failed = db.query(m.ContestRejudgeItem.id).filter(
                m.ContestRejudgeItem.shard_id == shard.id,
                m.ContestRejudgeItem.after_verdict.in_(('system_error', 'canceled'))).first()
            shard.status = 'failed' if shard_failed else 'ready'
            shard.finished_at = now_utc()
    if not db.query(m.ContestRejudgeItem.id).filter(m.ContestRejudgeItem.batch_id == batch.id,
            m.ContestRejudgeItem.status != 'completed').first():
        failed = db.query(m.ContestRejudgeItem.id).filter(m.ContestRejudgeItem.batch_id == batch.id,
            m.ContestRejudgeItem.after_verdict.in_(('system_error', 'canceled'))).first()
        shard_incomplete = db.query(m.ContestRejudgeShard.id).filter(
            m.ContestRejudgeShard.batch_id == batch.id,
            ~m.ContestRejudgeShard.status.in_(('ready', 'failed'))).first()
        shard_failed = db.query(m.ContestRejudgeShard.id).filter_by(
            batch_id=batch.id, status='failed').first()
        batch.status = 'failed' if failed or shard_failed or shard_incomplete else 'ready'
        batch.finished_at = now_utc()
    return True


def discard_candidate(db, contest_id, batch_id, data, actor):
    if actor.role != 'admin':
        raise HTTPException(403, '관리자 권한이 필요합니다.')
    execution_lock(db)
    batch = db.query(m.ContestRejudgeBatch).filter_by(id=batch_id, contest_id=contest_id).first()
    if batch is None:
        raise HTTPException(404, '재채점 기록을 찾을 수 없습니다.')
    if batch.request_hash != data.expected_request_hash:
        raise HTTPException(409, '재채점 버전을 다시 확인하세요.')
    # Never forget in-flight work or pretend that canceled means containers are gone.
    if batch.status not in ('ready', 'failed', 'cancelled'):
        raise HTTPException(409, '채점이 모두 끝난 뒤 결과 묶음을 폐기할 수 있습니다.')
    if batch.status != 'cancelled':
        batch.status = 'cancelled'
        batch.discarded_by, batch.discarded_at = actor.id, now_utc()
    result = summary(db, batch); db.commit()
    return result


def public_corrections(db, contest_id):
    """Deliberately excludes operator reason, candidate verdicts and hidden data."""
    query = db.query(m.ContestRejudgeApplication).join(m.ContestRejudgeBatch).filter(
        m.ContestRejudgeBatch.contest_id == contest_id)
    return dict(total=query.count(), items=[dict(revision=a.after_revision, appliedAt=iso(a.applied_at),
        note=a.public_note) for a in query.order_by(m.ContestRejudgeApplication.after_revision.desc()).limit(20)])


def application_audit(db, contest_id, batch_id, *, offset=0, limit=50):
    """Bounded administrator comparison, with no source or hidden test material."""
    audit = db.query(m.ContestRejudgeApplication).join(m.ContestRejudgeBatch).filter(
        m.ContestRejudgeApplication.batch_id == batch_id, m.ContestRejudgeBatch.contest_id == contest_id).first()
    if audit is None:
        raise HTTPException(404, '반영된 정정 기록을 찾을 수 없습니다.')
    after = {r['userId']:r for r in audit.after_board['rows']}
    deltas = {r['userId']:r['delta'] for r in audit.score_changes}
    rows = audit.before_board['rows']
    return dict(total=len(rows), offset=offset, limit=limit, beforeRevision=audit.before_revision,
        afterRevision=audit.after_revision, reviewProvenance=deepcopy(audit.review_provenance), rows=[dict(userId=r['userId'], before=r,
            after=after.get(r['userId']), practicePointDelta=deltas.get(r['userId'],0)) for r in rows[offset:offset+limit]])


def _validate_campaign_manifest(db, batch, submission_query, item_query):
    """Stream source-bearing validation; later apply queries can defer source text."""
    shards = db.query(m.ContestRejudgeShard).filter_by(batch_id=batch.id).order_by(
        m.ContestRejudgeShard.sequence).all()
    if not shards or batch.shard_count != len(shards) or [s.sequence for s in shards] != list(range(len(shards))):
        raise HTTPException(409, '재채점 shard 구성이 변경되었습니다.')
    if any(s.status != 'ready' for s in shards):
        raise HTTPException(409, '모든 재채점 shard가 정상 완료되지 않았습니다.')
    by_shard = {s.id:[] for s in shards}
    columns = (
        m.ContestRejudgeItem.shard_id, m.ContestRejudgeItem.submission_id,
        m.ContestRejudgeItem.before_fingerprint, m.ContestRejudgeItem.before_verdict,
        m.ContestRejudgeItem.language,
        m.ContestRejudgeItem.received_at, m.ContestRejudgeItem.code,
        m.ContestRejudgeItem.judge_contract, m.ContestRejudgeItem.status,
        m.ContestRejudgeItem.after_verdict, m.ContestRejudgeItem.resource_report,
        m.ContestRejudgeItem.finished_at, m.ContestRejudgeItem.candidate_receipt_hash,
        m.ContestSubmission.id, m.ContestSubmission.user_id,
        m.ContestSubmission.contest_problem_id, m.ContestSubmission.code,
        m.ContestSubmission.language, m.ContestSubmission.received_at,
        m.ContestSubmission.status, m.ContestSubmission.verdict,
        m.ContestSubmission.finished_at, m.ContestSubmission.execution_job_id,
        m.ContestSubmission.resource_report,
    )
    joined = db.query(*columns).join(m.ContestSubmission,
        m.ContestSubmission.id == m.ContestRejudgeItem.submission_id).filter(
            m.ContestRejudgeItem.batch_id == batch.id).order_by(
                m.ContestRejudgeItem.received_at, m.ContestRejudgeItem.submission_id).yield_per(25)
    seen = 0
    for values in joined:
        (shard_id, submission_id, before_fingerprint, before_verdict,
         item_language, item_received_at, item_code, judge_contract, item_status,
         after_verdict, item_report, item_finished_at, candidate_receipt_hash,
         current_id, user_id, problem_id, current_code, current_language,
         current_received_at, current_status, current_verdict, current_finished_at,
         execution_job_id, current_report) = values
        entries = by_shard.get(shard_id)
        if entries is None:
            raise HTTPException(409, '재채점 항목의 shard 소유권이 변경되었습니다.')
        current_fingerprint = _submission_fingerprint_values(current_id, user_id, problem_id,
            current_code, current_language, current_received_at, current_status, current_verdict,
            current_finished_at, execution_job_id, current_report)
        if (submission_id != current_id or current_fingerprint != before_fingerprint
                or before_verdict != current_verdict):
            raise HTTPException(409, '원래 제출이 변경되었습니다. 다시 재채점하세요.')
        if item_status != 'completed' or after_verdict in (None, 'system_error', 'canceled') or item_report is None:
            raise HTTPException(409, '검증된 재채점 결과가 부족합니다.')
        if candidate_receipt_hash != _candidate_receipt_hash(after_verdict, item_report, item_finished_at):
            raise HTTPException(409, '재채점 결과 영수증이 변경되었습니다.')
        entries.append(dict(submissionId=submission_id, beforeFingerprint=before_fingerprint,
            beforeVerdict=before_verdict, language=item_language, receivedAt=iso(item_received_at),
            sourceBytes=len(item_code.encode('utf-8')), sourceHash=content_hash(item_code),
            contractHash=content_hash(judge_contract)))
        seen += 1
    submission_count, item_count = submission_query.count(), item_query.count()
    if not seen or seen != submission_count or seen != item_count:
        raise HTTPException(409, '제출 집합이 변경되었습니다.')
    total_bytes = 0
    for shard in shards:
        entries = by_shard[shard.id]
        source_bytes = sum(e['sourceBytes'] for e in entries)
        if (len(entries) != shard.item_count or source_bytes != shard.source_bytes
                or len(entries) > MAX_SUBMISSIONS or source_bytes > MAX_SOURCE_BYTES
                or _manifest_hash(entries) != shard.manifest_hash):
            raise HTTPException(409, '재채점 shard 내용이 변경되었습니다.')
        total_bytes += source_bytes
    if (batch.source_bytes != total_bytes or batch.submission_set_hash != _campaign_hash(shards)):
        raise HTTPException(409, '재채점 캠페인 제출 집합이 변경되었습니다.')


def ready_candidate(db, contest_id, batch):
    """Read-only bounded validation, shared by preview and locked apply."""
    from app.services.scoreboard_cache import current_revision
    if batch.status != 'ready':
        raise HTTPException(409, '정상적으로 완료된 재채점만 반영할 수 있습니다.')
    contest = _contest(db, contest_id)
    revision = current_revision(db, contest_id)
    if revision != batch.before_scoreboard_revision:
        raise HTTPException(409, '점수판 버전이 변경되었습니다. 다시 재채점하세요.')
    if not contest.published or not contest.finalized_at or utc_naive(contest.ends_at) > now_utc():
        raise HTTPException(409, '종료가 확정된 대회만 정정할 수 있습니다.')
    problem = db.get(m.ContestProblem, batch.contest_problem_id)
    if problem is None or content_hash(problem.snapshot) != batch.before_snapshot_hash:
        raise HTTPException(409, '원래 대회 문제 버전이 변경되었습니다.')
    submission_query = db.query(m.ContestSubmission).filter_by(contest_problem_id=problem.id)
    item_query = db.query(m.ContestRejudgeItem).filter_by(batch_id=batch.id)
    legacy = batch.submission_set_hash is None
    if legacy and (submission_query.count() > MAX_SUBMISSIONS or item_query.count() > MAX_SUBMISSIONS):
        raise HTTPException(413, '이전 형식의 재채점 묶음은 제출 수 한도를 초과할 수 없습니다.')
    # Bound protected JSON before ORM loading/deepcopy, not after allocating it.
    # SQL character counts conservatively reserve four UTF-8 bytes per character.
    report_chars = (submission_query.with_entities(func.sum(func.length(cast(m.ContestSubmission.resource_report, String)))).scalar() or 0)
    report_chars += (item_query.with_entities(func.sum(func.length(cast(m.ContestRejudgeItem.resource_report, String)))).scalar() or 0)
    if report_chars > 2*1024**2:
        raise HTTPException(413, '재채점 계측 감사 자료의 보관 한도를 초과했습니다.')
    if not legacy:
        _validate_campaign_manifest(db, batch, submission_query, item_query)
        rows = submission_query.options(load_only(m.ContestSubmission.id, m.ContestSubmission.user_id,
            m.ContestSubmission.contest_problem_id, m.ContestSubmission.verdict,
            m.ContestSubmission.resource_report, m.ContestSubmission.finished_at,
            m.ContestSubmission.received_at, m.ContestSubmission.execution_job_id)).all()
        items = item_query.options(load_only(m.ContestRejudgeItem.id,
            m.ContestRejudgeItem.submission_id, m.ContestRejudgeItem.before_verdict,
            m.ContestRejudgeItem.after_verdict, m.ContestRejudgeItem.resource_report,
            m.ContestRejudgeItem.finished_at, m.ContestRejudgeItem.status,
            m.ContestRejudgeItem.shard_id)).all()
    else:
        rows = submission_query.all()
        items = item_query.all()
    participants_with_submissions = {row.user_id for row in rows}
    registered = {row[0] for row in db.query(m.ContestParticipant.user_id).filter_by(contest_id=contest_id).filter(
        m.ContestParticipant.user_id.in_(participants_with_submissions))}
    if registered != participants_with_submissions:
        raise HTTPException(409, '참가 기록이 없는 제출이 있습니다. 참가 기록 검수가 필요합니다.')
    by_id = {r.id:r for r in rows}
    if len(rows) != len(items) or not items:
        raise HTTPException(409, '제출 집합이 변경되었습니다.')
    if legacy:
        for item in items:
            row = by_id.get(item.submission_id)
            if row is None or submission_fingerprint(row) != item.before_fingerprint:
                raise HTTPException(409, '원래 제출이 변경되었습니다. 다시 재채점하세요.')
            if item.status != 'completed' or item.after_verdict in (None, 'system_error', 'canceled') or item.resource_report is None:
                raise HTTPException(409, '검증된 재채점 결과가 부족합니다.')
    # Bound audit material before constructing full board snapshots.
    participants = db.query(m.ContestParticipant).filter_by(contest_id=contest_id).count()
    problem_count = db.query(m.ContestProblem).filter_by(contest_id=contest_id).count()
    if participants * max(1, problem_count) > 20_000:
        raise HTTPException(413, '점수판 감사 기록 한도를 초과했습니다.')
    return contest, problem, rows, items, revision


def preview_candidate(db, contest_id, batch_id, *, offset=0, limit=50):
    from app.services.contest_rejudge_preview import compute_preview
    batch = db.query(m.ContestRejudgeBatch).filter_by(id=batch_id, contest_id=contest_id).first()
    if batch is None:
        raise HTTPException(404, '재채점 기록을 찾을 수 없습니다.')
    contest, problem, rows, items, revision = ready_candidate(db, contest_id, batch)
    result = compute_preview(db, contest, batch, problem, rows, items)
    return dict(previewHash=result['hash'], requestHash=batch.request_hash, beforeScoreboardRevision=revision,
        total=len(result['rows']), offset=offset, limit=limit, blockedCount=result['blockedCount'],
        reviewBlocked=result['reviewBlocked'],
        rows=result['rows'][offset:offset+limit])


def apply_candidate(db, contest_id, batch_id, data, actor):
    """Explicit atomic apply: original receipts unchanged, preview and facts fenced."""
    from app.services import contests, solve_evidence
    from app.services.contest_rejudge_preview import compute_preview
    from app.services.scoreboard_cache import current_revision, bump_scoreboard_revision
    if actor.role != 'admin':
        raise HTTPException(403, '관리자 권한이 필요합니다.')
    execution_lock(db)
    batch = db.query(m.ContestRejudgeBatch).filter_by(id=batch_id, contest_id=contest_id).first()
    if batch is None:
        raise HTTPException(404, '재채점 기록을 찾을 수 없습니다.')
    if batch.request_hash != data.expected_request_hash:
        raise HTTPException(409, '재채점 버전을 다시 확인하세요.')
    previous = db.get(m.ContestRejudgeApplication, batch_id)
    if previous:
        if ((previous.public_note, previous.before_revision) != (data.public_note, data.expected_scoreboard_revision)
                or (previous.preview_hash is not None and previous.preview_hash != data.expected_preview_hash)):
            raise HTTPException(409, '이미 반영된 재채점의 요청 내용을 변경할 수 없습니다.')
        return summary(db, batch)
    contest, problem, rows, items, revision = ready_candidate(db, contest_id, batch)
    if revision != data.expected_scoreboard_revision:
        raise HTTPException(409, '점수판 버전을 다시 확인하세요.')
    by_id = {r.id:r for r in rows}
    users = sorted({r.user_id for r in rows})
    # Manual awards also acquire this lock. Hold it before checking the preview.
    for user_id in users:
        db.query(m.User).filter_by(id=user_id).update({'id':user_id}, synchronize_session=False)
    preview = compute_preview(db, contest, batch, problem, rows, items)
    if preview['hash'] != data.expected_preview_hash:
        raise HTTPException(409, '미리보기 이후 해결 기록이나 점수가 바뀌었습니다. 다시 확인하세요.')
    if preview['blockedCount']:
        raise HTTPException(409, '과거 해결 기록의 출처 검수가 필요합니다. 점수는 변경되지 않았습니다.')
    review_provenance = correction_review.approved_provenance(db, batch)
    from app.services.problem_authoring import assert_reference_validated
    assert_reference_validated(db, problem.problem_id, batch.snapshot, contest_id=contest_id)
    before_board = contests._scoreboard_projection(db, contest)
    before_snapshot = deepcopy(problem.snapshot)
    before_submissions = [dict(id=r.id, verdict=r.verdict, finishedAt=iso(r.finished_at),
        resourceReport=deepcopy(r.resource_report), executionJobId=r.execution_job_id) for r in rows]
    # Same user lock order as finalization and normal awards. Practice results
    # arriving while staging are deliberately included, never overwritten.
    for user_id in users:
        solve_evidence.preserve_legacy(db, user_id, problem.problem_id)
    for item in items:
        row = by_id[item.submission_id]
        row.verdict, row.resource_report, row.finished_at = item.after_verdict, deepcopy(item.resource_report), item.finished_at
        claim = db.query(m.SolveEvidence).filter_by(source_kind='contest', source_id=row.id).first()
        if item.after_verdict == 'accepted':
            solve_evidence.record(db, user_id=row.user_id, problem_id=problem.problem_id,
                source_kind='contest', source_id=row.id, points=problem.snapshot['practicePoints'], solved_at=row.received_at)
        elif claim:
            claim.active = False
    db.flush()
    score_changes = []
    for user_id in users:
        revoking = any(by_id[i.submission_id].user_id == user_id and i.before_verdict == 'accepted'
            and i.after_verdict != 'accepted' for i in items)
        delta = solve_evidence.reconcile(db, user_id, problem.problem_id, revoking=revoking,
            legacy_resolution_plans=preview['resolutionPlans'].get(user_id, ()))
        score_changes.append(dict(userId=user_id, problemId=problem.problem_id, delta=delta))
    problem.snapshot = deepcopy(batch.snapshot)
    batch.status = 'applied'
    bump_scoreboard_revision(db, contest_id)
    db.flush()
    after_board = contests._scoreboard_projection(db, contest)
    # Audit holds the previous protected reports as well as old ranking facts.
    if len(json.dumps([before_board, after_board, before_submissions, before_snapshot], ensure_ascii=False).encode('utf-8')) > 16*1024**2:
        raise HTTPException(413, '재채점 감사 자료의 보관 한도를 초과했습니다.')
    db.add(m.ContestRejudgeApplication(batch_id=batch.id, actor_id=actor.id, public_note=data.public_note,
        preview_hash=data.expected_preview_hash, review_provenance=review_provenance,
        legacy_resolution_provenance=preview['resolutionProvenance'],
        applied_at=now_utc(), before_revision=revision, after_revision=current_revision(db, contest_id),
        before_snapshot=before_snapshot, before_submissions=before_submissions, before_board=before_board,
        after_board=after_board, score_changes=score_changes))
    db.flush(); result = summary(db, batch); db.commit()
    return result
