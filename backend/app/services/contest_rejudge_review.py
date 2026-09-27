"""Batch-scoped exact-content approval, never inferred from old source reviews."""
from copy import deepcopy
from fastapi import HTTPException
from sqlalchemy import func
from app.models import database as m
from app.services import problem_authoring as authoring
from app.services.contest_access import iso
from app.services.judge_policy import content_hash
from app.services.runtime_registry import execution_lock


def event_read(row):
    return dict(id=row.id, actorId=row.actor_id, fingerprint=row.fingerprint,
        category=row.category, decision=row.decision, note=row.note,
        sequence=row.sequence, createdAt=iso(row.created_at))


def freeze_basis(db, problem, snapshot):
    before = authoring.fingerprint(problem.snapshot)
    previous = db.query(m.ContestRejudgeApplication).join(m.ContestRejudgeBatch).filter(
        m.ContestRejudgeBatch.contest_problem_id == problem.id,
        m.ContestRejudgeBatch.status == 'applied').order_by(m.ContestRejudgeBatch.revision.desc()).first()
    # These are historical references ONLY. They do not approve the correction.
    return dict(version=1, beforeFingerprint=before, fingerprint=authoring.fingerprint(snapshot),
        sourceReviews=[event_read(e) for _, e in sorted(authoring.decisions(db, problem.problem_id, before).items())],
        previousApplicationBatchId=previous.batch_id if previous else None)


def state(db, batch):
    stamp = authoring.fingerprint(batch.snapshot)
    latest = {}
    # Bound the query by category using SQL, not by loading arbitrary history.
    for category in authoring.CATEGORIES:
        row = db.query(m.ContestRejudgeReviewEvent).filter_by(batch_id=batch.id,
            fingerprint=stamp, category=category).order_by(m.ContestRejudgeReviewEvent.sequence.desc()).first()
        if row: latest[category] = row
    basis_valid = bool(batch.review_basis and batch.review_basis.get('version') == 1
        and batch.review_basis.get('fingerprint') == stamp)
    categories = {k:latest[k].decision if k in latest else 'pending' for k in authoring.CATEGORIES}
    return dict(fingerprint=stamp, categories=categories,
        ready=basis_valid and bool(batch.snapshot.get('authoring')) and all(v == 'approved' for v in categories.values()),
        basis=deepcopy(batch.review_basis), approvals=[event_read(latest[k]) for k in authoring.CATEGORIES if k in latest])


def require_batch(db, contest_id, batch_id):
    batch = db.query(m.ContestRejudgeBatch).filter_by(id=batch_id, contest_id=contest_id).first()
    if batch is None: raise HTTPException(404, '재채점 기록을 찾을 수 없습니다.')
    return batch


def read(db, contest_id, batch_id):
    batch = require_batch(db, contest_id, batch_id)
    current = state(db, batch)
    events = db.query(m.ContestRejudgeReviewEvent).filter_by(batch_id=batch.id).order_by(
        m.ContestRejudgeReviewEvent.sequence.desc()).limit(100).all()
    application = db.get(m.ContestRejudgeApplication, batch.id)
    return dict(batchId=batch.id, requestHash=batch.request_hash, **current,
        snapshot=deepcopy(batch.snapshot), metadata=deepcopy(batch.snapshot.get('authoring')),
        canReview=batch.status in ('pending', 'running', 'ready') and bool(batch.review_basis)
            and batch.review_basis.get('fingerprint') == current['fingerprint'],
        events=[event_read(e) for e in events],
        applicationProvenance=deepcopy(application.review_provenance) if application else None)


def append(db, contest_id, batch_id, data, actor):
    if actor.role != 'admin': raise HTTPException(403, '관리자 권한이 필요합니다.')
    execution_lock(db)
    batch = require_batch(db, contest_id, batch_id)
    request_hash = content_hash(dict(contestId=contest_id, batchId=batch_id,
        **data.model_dump(mode='json', by_alias=True)))
    old = db.query(m.ContestRejudgeReviewEvent).filter_by(actor_id=actor.id, request_id=data.request_id).first()
    if old:
        if old.request_hash != request_hash: raise HTTPException(409, '같은 요청 ID를 다른 검수에 사용할 수 없습니다.')
        return read(db, contest_id, batch_id)
    current = state(db, batch)
    if batch.request_hash != data.expected_request_hash or current['fingerprint'] != data.expected_fingerprint:
        raise HTTPException(409, '재채점 후보 버전이 변경되었습니다. 다시 확인하세요.')
    if (batch.status not in ('pending', 'running', 'ready') or not batch.review_basis
            or batch.review_basis.get('fingerprint') != current['fingerprint']):
        raise HTTPException(409, '검수할 수 없는 후보입니다. 이전 형식의 후보는 폐기 후 다시 생성하세요.')
    authoring.validate_review(db, batch.snapshot, data.category, data.decision)
    sequence = (db.query(func.max(m.ContestRejudgeReviewEvent.sequence)).filter_by(batch_id=batch.id).scalar() or 0) + 1
    db.add(m.ContestRejudgeReviewEvent(batch_id=batch.id, actor_id=actor.id, request_id=data.request_id,
        request_hash=request_hash, fingerprint=current['fingerprint'], category=data.category,
        decision=data.decision, note=data.note, sequence=sequence))
    db.commit()
    return read(db, contest_id, batch_id)


def approved_provenance(db, batch):
    current = state(db, batch)
    if not current['ready']:
        raise HTTPException(409, '수정본의 출처·지문·테스트·실행 제한 검수가 필요합니다. 점수는 변경되지 않았습니다.')
    # Recheck mutable runtime availability / stored data integrity under apply lock.
    for category in authoring.CATEGORIES:
        authoring.validate_review(db, batch.snapshot, category, 'approved')
    return deepcopy(current)
