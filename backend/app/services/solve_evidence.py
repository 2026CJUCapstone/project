"""Unpruned solve provenance; callers hold the user row lock. Never commits."""
from fastapi import HTTPException
from app.models import database as m
from app.services.contest_access import utc_naive


def preserve_legacy(db, user_id, problem_id):
    score = db.query(m.UserProblemScore).filter_by(user_id=user_id, challenge_id=problem_id).first()
    if score and not db.query(m.SolveEvidence.id).filter_by(user_id=user_id, problem_id=problem_id).first():
        db.add(m.SolveEvidence(user_id=user_id, problem_id=problem_id, source_kind='legacy',
            source_id=score.id, points=score.points_awarded, solved_at=score.solved_at, active=True))
        db.flush()
    return score


def record(db, *, user_id, problem_id, source_kind, source_id, points, solved_at):
    if source_kind not in ('practice', 'contest', 'manual'):
        raise ValueError('Explicit solve source required')
    old = db.query(m.SolveEvidence).filter_by(source_kind=source_kind, source_id=source_id).first()
    if old:
        if (old.user_id, old.problem_id, old.points) != (user_id, problem_id, points):
            raise ValueError('Solve source identity changed')
        old.active = True
        return
    db.add(m.SolveEvidence(user_id=user_id, problem_id=problem_id, source_kind=source_kind,
        source_id=source_id, points=points, solved_at=solved_at, active=True))
    db.flush()


def award_plan(score, evidence, *, revoking=False, allow_legacy_only=False):
    """Pure decision shared by preview and transactional reconciliation."""
    # Staged claims do not have persisted row UUIDs yet. Use immutable source
    # identity for timestamp ties, so preview and insertion select the same award.
    evidence = sorted(evidence, key=lambda e: (utc_naive(e.solved_at), e.source_kind, e.source_id))
    known = [e for e in evidence if e.source_kind != 'legacy']
    if revoking and evidence and not known and not allow_legacy_only:
        raise HTTPException(409, '과거 해결 기록의 출처가 불명확해 자동 차감할 수 없습니다. 기록 검수가 필요합니다.')
    if score is None and evidence:
        selected = (known or evidence)[0]
        return 'add', selected.points, selected
    if score and not evidence:
        return 'remove', -score.points_awarded, None
    return 'keep', 0, None


def reconcile(db, user_id, problem_id, *, revoking=False, legacy_resolution_plans=()):
    """Exactly one award, preserving its amount while another solve exists."""
    score = db.query(m.UserProblemScore).filter_by(user_id=user_id, challenge_id=problem_id).first()
    evidence = db.query(m.SolveEvidence).filter_by(user_id=user_id, problem_id=problem_id, active=True).order_by(
        m.SolveEvidence.solved_at, m.SolveEvidence.id).all()
    allow_legacy_only = False
    if legacy_resolution_plans:
        from app.services.legacy_solve_resolution import apply_plans
        evidence, allow_legacy_only = apply_plans(evidence, legacy_resolution_plans)
    action, delta, selected = award_plan(score, evidence, revoking=revoking,
        allow_legacy_only=allow_legacy_only)
    changed = False
    if action == 'add':
        db.add(m.UserProblemScore(user_id=user_id, challenge_id=problem_id,
            points_awarded=delta, solved_at=selected.solved_at))
        changed = True
    elif action == 'remove':
        db.delete(score)
        changed = True
    if delta:
        db.query(m.User).filter_by(id=user_id).update({m.User.total_score:m.User.total_score + delta}, synchronize_session=False)
    if changed:
        db.info.setdefault('execution_awards', set()).add(user_id)
    db.flush()
    return delta
