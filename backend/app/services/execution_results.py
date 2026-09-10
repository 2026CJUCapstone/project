"""Publish grading state and its score ledger in the fenced job transaction."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import database as m
from app.services.contest_access import now_utc, utc_naive
from app.services.scoreboard_cache import bump_scoreboard_revision


@event.listens_for(Session, 'after_commit')
def invalidate_committed_awards(db):
    if db.in_nested_transaction():
        return
    from app.services.rating import invalidate_rating_cache
    for user_id in db.info.pop('execution_awards', set()):
        invalidate_rating_cache(user_id)


def publish_transition(db, job):
    verdict = 'running' if job.status == 'running' else 'pending'
    db.query(m.Submission).filter_by(execution_job_id=job.id).update(
        {'status':job.status, 'verdict':verdict}, synchronize_session=False)
    contest_submission = db.query(
        m.ContestSubmission.contest_id,
        m.ContestSubmission.status,
        m.ContestSubmission.verdict,
    ).filter_by(execution_job_id=job.id).first()
    if contest_submission is not None:
        db.query(m.ContestSubmission).filter_by(execution_job_id=job.id).update(
            {'status':job.status, 'verdict':verdict}, synchronize_session=False)
        if (contest_submission.status, contest_submission.verdict) != (job.status, verdict):
            bump_scoreboard_revision(db, contest_submission.contest_id)
    record = db.get(m.CompileQueueRecord, job.id)
    if record:
        record.status, record.verdict = job.status, verdict
        record.started_at = job.started_at
        if job.started_at:
            record.wait_ms = max(0, (utc_naive(job.started_at)-utc_naive(job.received_at)).total_seconds()*1000)


def publish_result(db, job_id, result):
    verdict = result.get('verdict', 'system_error')
    record = db.get(m.CompileQueueRecord, job_id)
    if record:
        record.status, record.verdict = 'completed', verdict
        record.finished_at = now_utc()
        if record.started_at:
            record.run_ms = max(0, (utc_naive(record.finished_at)-utc_naive(record.started_at)).total_seconds()*1000)
    submission = db.query(m.Submission).filter_by(execution_job_id=job_id).first()
    if submission is not None:
        job = db.get(m.ExecutionJob, job_id)
        value = dict(result.get('value') or {})
        submission.status = value.get('status', 'Rejected')
        submission.verdict = verdict
        submission.sample_passed_cases = value.get('sample_passed_cases', 0)
        submission.grading_completed = value.get('grading_completed', False)
        submission.grading_passed = verdict == 'accepted'
        if verdict == 'accepted':
            submission.status = 'Accepted'
        total_score = 0
        if submission.user_id:
            # Same user-then-unique-solve order as contest finalization.
            db.query(m.User).filter_by(id=submission.user_id).update({'id':submission.user_id}, synchronize_session=False)
            if verdict == 'accepted' and not db.query(m.UserProblemScore.id).filter_by(
                    user_id=submission.user_id, challenge_id=submission.problem_id).first():
                points = job.payload['practice_points']
                try:
                    with db.begin_nested():
                        db.add(m.UserProblemScore(user_id=submission.user_id, challenge_id=submission.problem_id,
                            points_awarded=points, solved_at=job.received_at))
                        db.flush()
                except IntegrityError:
                    pass
                else:
                    db.query(m.User).filter_by(id=submission.user_id).update(
                        {m.User.total_score:m.User.total_score + points}, synchronize_session=False)
                    submission.awarded_points = points
                    db.info.setdefault('execution_awards', set()).add(submission.user_id)
            total_score = db.query(m.User.total_score).filter_by(id=submission.user_id).scalar()
        result['value'] = {**value, 'status':submission.status, 'verdict':verdict,
            'total_cases':submission.sample_total_cases, 'passed_cases':submission.sample_passed_cases,
            'sample_total_cases':submission.sample_total_cases, 'sample_passed_cases':submission.sample_passed_cases,
            'grading_completed':submission.grading_completed, 'grading_passed':submission.grading_passed,
            'total_score':total_score, 'details':value.get('details', []),
            'message':'모든 테스트를 통과했습니다.' if verdict == 'accepted' else '채점 결과를 확인하세요.'}
        if submission.user_id:
            from app.api.routes.problems import _prune_old_submissions
            _prune_old_submissions(db, submission.user_id)
    contest_submission = db.query(m.ContestSubmission).filter_by(execution_job_id=job_id).first()
    if contest_submission is not None:
        # Contest solutions never award practice points until contest finalization.
        changed = (contest_submission.status, contest_submission.verdict) != ('completed', verdict)
        contest_submission.status, contest_submission.verdict = 'completed', verdict
        contest_submission.finished_at = now_utc()
        contest_submission.lease_token = contest_submission.lease_until = None
        if changed:
            bump_scoreboard_revision(db, contest_submission.contest_id)
