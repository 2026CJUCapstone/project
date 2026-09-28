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
    # Older/internal transition callers pass only the state fields. Missing
    # kind means the normal publication path, never the private authoring path.
    if getattr(job, 'kind', None) == 'authoring-validation-v1':
        return
    verdict = 'running' if job.status == 'running' else 'pending'
    db.query(m.ContestRejudgeItem).filter_by(execution_job_id=job.id).update(
        {'status':job.status}, synchronize_session=False)
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
    from app.services.judge_metrics import validate_report, public_usage
    from copy import deepcopy
    job = db.get(m.ExecutionJob, job_id)
    verdict = result.get('verdict', 'system_error')
    value = dict(result.get('value') or {})
    report = value.pop('_resource_report', None)
    if report is not None:
        if job is None or job.kind not in ('practice','contest','authoring-validation-v1'):
            raise ValueError('Resource report requires a judged submission')
        report_payload = job.payload
        if job.kind in ('practice','contest'):
            from app.services.legacy_execution_resolution import publication_payload
            report_payload = publication_payload(db, job)
        report = deepcopy(validate_report(report,report_payload))
        if (verdict == 'accepted'
                and (report['compile']['exitCode'] != 0
                    or report['compile']['failureReason'] is not None
                    or len(report['cases']) != len(report_payload.get('sample', [])) + len(report_payload.get('hidden', []))
                    or any(case['verdict'] != 'accepted' for case in report['cases']))):
            raise ValueError('Accepted verdict requires complete accepted resource evidence')
        value['resource_usage'] = public_usage(report)
    else:
        value.pop('resource_usage', None)  # Never trust an unbacked summary.
        if (job is not None and job.kind in ('practice','contest','authoring-validation-v1')
                and verdict != 'system_error'):
            raise ValueError('Graded completion requires a protected resource report')
    if 'value' in result: result['value'] = value
    if job is not None and job.kind == 'authoring-validation-v1':
        if verdict != 'system_error' and report is None:
            raise ValueError('Authoring validation requires a measured resource report')
        if verdict == 'accepted':
            payload = job.payload if isinstance(job.payload, dict) else {}
            contract = payload.get('judge_contract')
            contract = contract if isinstance(contract, dict) else {}
            fields = {
                'problem_id': payload.get('problem_id'),
                'contest_id': payload.get('contest_id'),
                'contest_problem_id': payload.get('contest_problem_id'),
                'problem_snapshot_hash': payload.get('problem_snapshot_hash'),
                'authoring_fingerprint': payload.get('authoring_fingerprint'),
                'language': payload.get('language'),
                'source_hash': payload.get('source_hash'),
                'reference_asset_digest': payload.get('reference_asset_digest'),
                'policy_hash': contract.get('policyHash'),
                'test_suite_hash': contract.get('testSuiteHash'),
            }
            if (
                payload.get('authoring_validation_version') != 1
                or contract.get('kind') != 'measured-v1'
                or any(not isinstance(value, str) or not value for value in fields.values())
                or fields['source_hash'] != fields['reference_asset_digest']
            ):
                raise ValueError('Invalid frozen authoring validation identity')
            previous = db.get(m.ProblemValidationAttestation, job.id)
            if previous is None:
                db.add(m.ProblemValidationAttestation(job_id=job.id, **fields))
            elif any(getattr(previous, key) != value for key, value in fields.items()):
                raise ValueError('Authoring validation attestation identity changed')
        # Replace every runner-supplied field with a private, bounded projection.
        # Source/test/policy identity comes only from the frozen queue payload.
        result['value'] = {
            'verdict': verdict,
            'resource_usage': public_usage(report) if report is not None else None,
            'source_hash': job.payload.get('source_hash'),
            'problem_snapshot_hash': job.payload.get('problem_snapshot_hash'),
        }
        return
    from app.services.contest_rejudge import publish_candidate
    if publish_candidate(db, job_id, verdict, report):
        return  # Staged results must never alter live contest facts or solves.
    record = db.get(m.CompileQueueRecord, job_id)
    if record:
        record.status, record.verdict = 'completed', verdict
        record.finished_at = now_utc()
        if record.started_at:
            record.run_ms = max(0, (utc_naive(record.finished_at)-utc_naive(record.started_at)).total_seconds()*1000)
    submission = db.query(m.Submission).filter_by(execution_job_id=job_id).first()
    if submission is not None:
        submission.resource_report = report
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
            if verdict == 'accepted':
                from app.services.solve_evidence import preserve_legacy, record as record_solve
                preserve_legacy(db, submission.user_id, submission.problem_id)
                record_solve(db, user_id=submission.user_id, problem_id=submission.problem_id,
                    source_kind='practice', source_id=submission.id, points=job.payload['practice_points'],
                    solved_at=job.received_at)
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
            from app.services.learning import record_attempt
            record_attempt(db, submission)
            _prune_old_submissions(db, submission.user_id)
    contest_submission = db.query(m.ContestSubmission).filter_by(execution_job_id=job_id).first()
    if contest_submission is not None:
        contest_submission.resource_report = report
        # Contest solutions never award practice points until contest finalization.
        changed = (contest_submission.status, contest_submission.verdict) != ('completed', verdict)
        contest_submission.status, contest_submission.verdict = 'completed', verdict
        contest_submission.finished_at = now_utc()
        contest_submission.lease_token = contest_submission.lease_until = None
        if changed:
            bump_scoreboard_revision(db, contest_submission.contest_id)
