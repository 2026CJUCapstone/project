"""Audited, append-only disposition of unattributed legacy solve awards."""
from types import SimpleNamespace

from fastapi import HTTPException

from app.models import database as m
from app.services.contest_access import iso
from app.services.judge_policy import content_hash
from app.services.runtime_registry import execution_lock


RETAIN = 'retain_unattributed'
LINK = 'link_verified_receipt'


def _legacy_payload(evidence):
    return dict(userId=evidence.user_id, problemId=evidence.problem_id,
        sourceId=evidence.source_id, points=evidence.points, solvedAt=iso(evidence.solved_at))


def legacy_fingerprint(evidence):
    return content_hash(_legacy_payload(evidence))


def _source(db, kind, source_id, legacy):
    if kind == 'practice':
        row = db.get(m.Submission, source_id)
        if row is None or row.user_id != legacy.user_id or row.problem_id != legacy.problem_id:
            raise HTTPException(409, '검증 영수증의 사용자 또는 문제가 과거 점수와 다릅니다.')
        if row.verdict != 'accepted' or not row.grading_passed or row.status != 'Accepted':
            raise HTTPException(409, '정답으로 완료된 일반 문제 영수증만 연결할 수 있습니다.')
        if row.awarded_points != legacy.points:
            raise HTTPException(409, '검증 영수증의 배점이 과거 점수와 다릅니다.')
        payload = dict(kind=kind, id=row.id, userId=row.user_id, problemId=row.problem_id,
            points=row.awarded_points, solvedAt=iso(row.created_at), verdict=row.verdict,
            status=row.status, gradingPassed=row.grading_passed,
            executionJobId=row.execution_job_id, sourceHash=content_hash(row.code),
            reportHash=content_hash(row.resource_report))
    elif kind == 'contest':
        row = db.get(m.ContestSubmission, source_id)
        problem = None if row is None else db.get(m.ContestProblem, row.contest_problem_id)
        points = None if problem is None else problem.snapshot.get('practicePoints')
        if row is None or problem is None or row.user_id != legacy.user_id or problem.problem_id != legacy.problem_id:
            raise HTTPException(409, '검증 영수증의 사용자 또는 문제가 과거 점수와 다릅니다.')
        if row.verdict != 'accepted' or row.status != 'completed':
            raise HTTPException(409, '정답으로 완료된 대회 영수증만 연결할 수 있습니다.')
        if points != legacy.points:
            raise HTTPException(409, '검증 영수증의 배점이 과거 점수와 다릅니다.')
        payload = dict(kind=kind, id=row.id, userId=row.user_id, problemId=problem.problem_id,
            points=points, solvedAt=iso(row.received_at), verdict=row.verdict,
            status=row.status, executionJobId=row.execution_job_id,
            sourceHash=content_hash(row.code), reportHash=content_hash(row.resource_report))
    else:
        raise HTTPException(409, '지원하지 않는 해결 영수증 종류입니다.')
    return SimpleNamespace(source_kind=kind, source_id=source_id, points=payload['points'],
        solved_at=row.created_at if kind == 'practice' else row.received_at,
        fingerprint=content_hash(payload))


def _event(row):
    return dict(id=row.id, userId=row.user_id, problemId=row.problem_id,
        legacyFingerprint=row.legacy_fingerprint, decision=row.decision,
        sourceKind=row.source_kind, sourceId=row.source_id,
        sourceFingerprint=row.source_fingerprint, actorId=row.actor_id,
        note=row.note, createdAt=iso(row.created_at))


def plans_for_user(db, batch, user_id, problem_id, active, overrides):
    """Project exact resolutions into preview evidence without mutating facts."""
    resolutions = {row.legacy_evidence_id: row for row in db.query(m.LegacySolveResolution).filter_by(
        batch_id=batch.id, user_id=user_id, problem_id=problem_id)}
    projected = list(active)
    plans = []
    for legacy in [item for item in list(projected) if item.source_kind == 'legacy']:
        row = resolutions.get(getattr(legacy, 'id', None))
        if row is None:
            continue
        if row.legacy_fingerprint != legacy_fingerprint(legacy):
            raise HTTPException(409, '과거 해결 기록이 검수 이후 변경되었습니다.')
        plan = dict(**_event(row), legacyEvidenceId=legacy.id, remainsActive=False,
            points=legacy.points, solvedAt=iso(legacy.solved_at))
        if row.decision == RETAIN:
            plan['remainsActive'] = True
        elif row.decision == LINK:
            source = _source(db, row.source_kind, row.source_id, legacy)
            if source.fingerprint != row.source_fingerprint:
                raise HTTPException(409, '연결한 해결 영수증이 검수 이후 변경되었습니다.')
            projected.remove(legacy)
            remains = not (row.source_kind == 'contest' and row.source_id in overrides
                and overrides[row.source_id] != 'accepted')
            plan['remainsActive'] = remains
            if remains:
                projected.append(SimpleNamespace(id='resolved:'+row.id, active=True,
                    source_kind=row.source_kind, source_id=row.source_id,
                    points=source.points, solved_at=source.solved_at))
        else:
            raise HTTPException(409, '알 수 없는 과거 해결 기록 결정입니다.')
        plans.append(plan)
    active_legacy = [item for item in projected if item.source_kind == 'legacy']
    retain_ids = {plan['legacyEvidenceId'] for plan in plans if plan['decision'] == RETAIN}
    allow_legacy_only = bool(active_legacy) and all(item.id in retain_ids for item in active_legacy)
    return projected, allow_legacy_only, plans


def apply_plans(active, plans):
    """Apply the already-previewed plan after live receipt verdicts are updated."""
    projected = list(active)
    by_legacy = {plan['legacyEvidenceId']: plan for plan in plans}
    for legacy in [item for item in list(projected) if item.source_kind == 'legacy']:
        plan = by_legacy.get(legacy.id)
        if plan and plan['decision'] == LINK:
            projected.remove(legacy)
            if plan['remainsActive']:
                projected.append(SimpleNamespace(id='resolved:'+plan['id'], active=True,
                    source_kind=plan['sourceKind'], source_id=plan['sourceId'],
                    points=plan['points'], solved_at=legacy.solved_at))
    active_legacy = [item for item in projected if item.source_kind == 'legacy']
    retain_ids = {plan['legacyEvidenceId'] for plan in plans if plan['decision'] == RETAIN}
    allow_legacy_only = bool(active_legacy) and all(item.id in retain_ids for item in active_legacy)
    return projected, allow_legacy_only


def _legacy_for_user(db, user_id, problem_id):
    from app.services.solve_evidence import preserve_legacy
    score = preserve_legacy(db, user_id, problem_id)
    if score is None:
        raise HTTPException(409, '검수할 과거 점수 기록이 없습니다.')
    rows = db.query(m.SolveEvidence).filter_by(user_id=user_id, problem_id=problem_id,
        source_kind='legacy', active=True).all()
    if len(rows) != 1:
        raise HTTPException(409, '과거 해결 기록을 하나로 식별할 수 없습니다.')
    known = db.query(m.SolveEvidence.id).filter_by(user_id=user_id, problem_id=problem_id,
        active=True).filter(m.SolveEvidence.source_kind != 'legacy').first()
    if known:
        raise HTTPException(409, '이미 명시적인 해결 근거가 있어 별도 과거 기록 결정을 만들 수 없습니다.')
    return rows[0]


def append(db, contest_id, batch_id, data, actor):
    if actor.role != 'admin':
        raise HTTPException(403, '관리자 권한이 필요합니다.')
    execution_lock(db)
    from app.services import contest_rejudge
    batch = db.query(m.ContestRejudgeBatch).filter_by(id=batch_id, contest_id=contest_id).first()
    if batch is None:
        raise HTTPException(404, '재채점 기록을 찾을 수 없습니다.')
    request_hash = content_hash(dict(contestId=contest_id, batchId=batch_id,
        **data.model_dump(mode='json', by_alias=True)))
    old = db.query(m.LegacySolveResolution).filter_by(actor_id=actor.id,
        request_id=data.request_id).first()
    if old:
        if old.request_hash != request_hash:
            raise HTTPException(409, '같은 요청 ID를 다른 과거 기록 검수에 사용할 수 없습니다.')
        return read(db, contest_id, batch_id)
    if batch.request_hash != data.expected_request_hash:
        raise HTTPException(409, '재채점 후보 버전이 변경되었습니다.')
    _, problem, submissions, items, _ = contest_rejudge.ready_candidate(db, contest_id, batch)
    user_items = [item for item in items if next(row for row in submissions
        if row.id == item.submission_id).user_id == data.user_id]
    if not any(item.before_verdict == 'accepted' and item.after_verdict != 'accepted' for item in user_items):
        raise HTTPException(409, '이 참가자에게 차감 검수가 필요한 재채점 결과가 없습니다.')
    db.query(m.User).filter_by(id=data.user_id).update({'id': data.user_id}, synchronize_session=False)
    legacy = _legacy_for_user(db, data.user_id, problem.problem_id)
    if legacy_fingerprint(legacy) != data.expected_legacy_fingerprint:
        raise HTTPException(409, '과거 해결 기록이 변경되었습니다. 미리보기를 다시 확인하세요.')
    existing = db.query(m.LegacySolveResolution).filter_by(batch_id=batch.id,
        legacy_evidence_id=legacy.id).first()
    if existing:
        raise HTTPException(409, '이 과거 해결 기록은 이미 검수되었습니다.')
    source = None
    if data.decision == LINK:
        source = _source(db, data.source_kind, data.source_id, legacy)
    row = m.LegacySolveResolution(batch_id=batch.id, legacy_evidence_id=legacy.id,
        user_id=legacy.user_id, problem_id=legacy.problem_id,
        legacy_fingerprint=legacy_fingerprint(legacy), decision=data.decision,
        source_kind=data.source_kind, source_id=data.source_id,
        source_fingerprint=None if source is None else source.fingerprint,
        actor_id=actor.id, request_id=data.request_id, request_hash=request_hash, note=data.note)
    db.add(row)
    db.commit()
    return read(db, contest_id, batch_id)


def read(db, contest_id, batch_id):
    from app.services import contest_rejudge
    batch = db.query(m.ContestRejudgeBatch).filter_by(id=batch_id, contest_id=contest_id).first()
    if batch is None:
        raise HTTPException(404, '재채점 기록을 찾을 수 없습니다.')
    rows = db.query(m.LegacySolveResolution).filter_by(batch_id=batch.id).order_by(
        m.LegacySolveResolution.created_at, m.LegacySolveResolution.id).all()
    candidates = []
    if batch.status == 'ready':
        _, problem, submissions, items, _ = contest_rejudge.ready_candidate(db, contest_id, batch)
        by_submission = {row.id: row for row in submissions}
        users = sorted({by_submission[item.submission_id].user_id for item in items
            if item.before_verdict == 'accepted' and item.after_verdict != 'accepted'})
        names = {row.id: row.username for row in db.query(m.User).filter(m.User.id.in_(users))}
        for user_id in users:
            score = db.query(m.UserProblemScore).filter_by(user_id=user_id,
                challenge_id=problem.problem_id).first()
            if score is None:
                continue
            evidence = db.query(m.SolveEvidence).filter_by(user_id=user_id,
                problem_id=problem.problem_id, active=True).all()
            known = [item for item in evidence if item.source_kind != 'legacy']
            legacy = [item for item in evidence if item.source_kind == 'legacy']
            if known:
                continue
            if not legacy:
                legacy = [SimpleNamespace(id=None, user_id=user_id, problem_id=problem.problem_id,
                    source_id=score.id, points=score.points_awarded, solved_at=score.solved_at)]
            if len(legacy) != 1:
                raise HTTPException(409, '과거 해결 기록을 하나로 식별할 수 없습니다.')
            item = legacy[0]
            resolution = next((row for row in rows if row.legacy_evidence_id == item.id), None)
            candidates.append(dict(userId=user_id, username=names.get(user_id, user_id),
                points=item.points, solvedAt=iso(item.solved_at),
                legacyFingerprint=legacy_fingerprint(item),
                resolution=None if resolution is None else _event(resolution)))
    return dict(batchId=batch.id, requestHash=batch.request_hash,
        candidates=candidates, resolutions=[_event(row) for row in rows])
