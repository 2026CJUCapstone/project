"""Read-only impact calculation. No simulated writes, commits or cache updates."""
from types import SimpleNamespace
from fastapi import HTTPException
from app.models import database as m
from app.services import contests, solve_evidence, contest_rejudge_review, legacy_solve_resolution
from app.services.contest_access import iso
from app.services.judge_policy import content_hash


def compute_preview(db, contest, batch, problem, submissions, items):
    users = sorted({s.user_id for s in submissions})
    by_submission = {s.id:s for s in submissions}
    evidence_query = db.query(m.SolveEvidence).filter(m.SolveEvidence.user_id.in_(users),
        m.SolveEvidence.problem_id == problem.problem_id)
    if evidence_query.count() > 20_000:
        raise HTTPException(413, '해결 근거 검토 한도를 초과했습니다. 분할 검수가 필요합니다.')
    evidence = evidence_query.order_by(m.SolveEvidence.solved_at, m.SolveEvidence.id).all()
    scores = {s.user_id:s for s in db.query(m.UserProblemScore).filter(
        m.UserProblemScore.user_id.in_(users), m.UserProblemScore.challenge_id == problem.problem_id)}
    overrides = {i.submission_id:i.after_verdict for i in items}
    outcomes, basis, resolution_plans = {}, [], {}
    for user_id in users:
        score = scores.get(user_id)
        all_evidence = [e for e in evidence if e.user_id == user_id]
        active = [e for e in all_evidence if e.active and not (e.source_kind == 'contest' and e.source_id in overrides)]
        if score and not all_evidence:
            active.append(SimpleNamespace(id='legacy:'+score.id, source_kind='legacy', source_id=score.id,
                points=score.points_awarded, solved_at=score.solved_at))
        user_items = [i for i in items if by_submission[i.submission_id].user_id == user_id]
        for item in user_items:
            if item.after_verdict == 'accepted':
                active.append(SimpleNamespace(id='candidate:'+item.id, source_kind='contest', source_id=item.submission_id,
                    points=problem.snapshot['practicePoints'], solved_at=by_submission[item.submission_id].received_at))
        revoking = any(i.before_verdict == 'accepted' and i.after_verdict != 'accepted' for i in user_items)
        active, allow_legacy_only, plans = legacy_solve_resolution.plans_for_user(
            db, batch, user_id, problem.problem_id, active, overrides)
        resolution_plans[user_id] = plans
        try:
            _, delta, _ = solve_evidence.award_plan(score, active, revoking=revoking,
                allow_legacy_only=allow_legacy_only)
            outcomes[user_id] = dict(practicePointDelta=delta, blocker=None)
        except HTTPException as exc:
            outcomes[user_id] = dict(practicePointDelta=None, blocker=str(exc.detail))
        basis.append(dict(userId=user_id,
            score=None if score is None else dict(id=score.id, points=score.points_awarded, solvedAt=iso(score.solved_at)),
            evidence=[dict(id=e.id, source=e.source_kind, sourceId=e.source_id, active=e.active,
                points=e.points, solvedAt=iso(e.solved_at)) for e in all_evidence],
            legacyResolutions=plans))
    before = contests._scoreboard_projection(db, contest)
    after = contests._scoreboard_projection(db, contest, verdict_overrides=overrides)
    after_by_user = {r['userId']:r for r in after['rows']}
    names = contests._scoreboard_names(db, before['rows'])
    rows = []
    for old in before['rows']:
        new = after_by_user[old['userId']]
        rows.append(dict(userId=old['userId'], username=names.get(old['userId'],old['userId']),
            beforeRank=old['rank'], afterRank=new['rank'], beforePoints=old['totalPoints'], afterPoints=new['totalPoints'],
            beforePenaltySeconds=old['penaltySeconds'], afterPenaltySeconds=new['penaltySeconds'],
            **outcomes.get(old['userId'], dict(practicePointDelta=0, blocker=None))))
    review_state = contest_rejudge_review.state(db, batch)
    fingerprint = content_hash(dict(requestHash=batch.request_hash, before=before, after=after, review=review_state,
        basis=basis, outcomes=outcomes, candidate=[dict(id=i.id, verdict=i.after_verdict, finishedAt=iso(i.finished_at),
            reportHash=content_hash(i.resource_report)) for i in sorted(items,key=lambda i:i.id)]))
    return dict(hash=fingerprint, rows=rows, blockedCount=sum(o['blocker'] is not None for o in outcomes.values()),
        reviewBlocked=not review_state['ready'], resolutionPlans=resolution_plans,
        resolutionProvenance=[plan for user_plans in resolution_plans.values() for plan in user_plans])
