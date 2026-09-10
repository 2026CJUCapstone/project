from datetime import timedelta

import pytest

from app.models import database as m
from app.services.contest_access import now_utc
from app.services.durable_queue import DurableQueue
from app.services.execution_results import publish_result
from tests.test_durable_queue import replicas


def receipt(factory, queue, request='one'):
    with factory() as db:
        if db.get(m.User, 'solver') is None:
            db.add(m.User(id='solver', username='solver', hashed_password=''))
            db.flush()
            db.add(m.Problem(id='problem', creator_id='solver', title='test', difficulty='iron5', tags=[], description='',
                             test_cases={'sample':[{'input':'','expected_output':'42'}]}, points=100))
            db.flush()
        job = queue.enqueue_in_session(db, owner_key='solver', request_id=request, kind='practice',
            payload={'code':'print(42)','language':'python', 'practice_points':100})
        db.add(m.Submission(execution_job_id=job.id, user_id='solver', problem_id='problem', language='python',
            code='print(42)', status='queued', verdict='pending', sample_total_cases=1))
        job_id = job.id
        db.commit()
        return job_id


def accepted():
    return {'verdict':'accepted', 'value':{'status':'Accepted', 'sample_passed_cases':1,
            'grading_completed':True, 'grading_passed':True, 'details':[]}}


def test_two_durable_correct_submissions_award_only_once_and_preserve_receipt(replicas):
    queue = DurableQueue(replicas[0], on_terminal=publish_result)
    first = receipt(replicas[0], queue)
    second = receipt(replicas[0], queue, 'two')
    for _ in range(2):
        claim = queue.claim()
        assert queue.finish(claim.id, claim.token, accepted())
        assert not queue.finish(claim.id, claim.token, accepted())
    with replicas[1]() as db:
        assert db.get(m.User, 'solver').total_score == 100
        assert db.query(m.UserProblemScore).filter_by(user_id='solver').count() == 1
        rows = db.query(m.Submission).filter_by(user_id='solver').all()
        assert len(rows) == 2 and all(row.status == 'Accepted' for row in rows)
        assert sorted(row.awarded_points for row in rows) == [0,100]
    assert queue.read(first, owner_key='solver')['result']['value']['total_score'] == 100
    assert queue.read(second, owner_key='solver')['result']['value']['total_score'] == 100


def test_publication_failure_rolls_back_job_verdict_and_points(replicas):
    def interrupted(db, job_id, result):
        publish_result(db, job_id, result)
        db.flush()
        raise RuntimeError('crash before commit')
    queue = DurableQueue(replicas[0], on_terminal=interrupted)
    job_id = receipt(replicas[0], queue)
    claim = queue.claim()
    with pytest.raises(RuntimeError, match='crash before commit'):
        queue.finish(job_id, claim.token, accepted())
    with replicas[1]() as db:
        assert db.get(m.User, 'solver').total_score == 0
        assert db.query(m.UserProblemScore).count() == 0
        assert db.query(m.Submission).one().status == 'queued'
    assert queue.read(job_id, owner_key='solver')['status'] == 'running'
    queue.on_terminal = publish_result
    assert queue.finish(job_id, claim.token, accepted())


def test_retry_exhaustion_marks_bound_submission_terminal_without_award(replicas):
    queue = DurableQueue(replicas[0], on_terminal=publish_result, max_attempts=1, lease_seconds=1,
                         reap_expired=lambda *args:None)
    job_id = receipt(replicas[0], queue)
    at = now_utc()
    queue.claim(at=at)
    assert queue.claim(at=at+timedelta(seconds=1)) is None
    with replicas[1]() as db:
        submission = db.query(m.Submission).one()
        assert submission.status == 'Rejected' and submission.verdict == 'system_error'
        assert db.get(m.User, 'solver').total_score == 0
    assert queue.read(job_id, owner_key='solver')['status'] == 'failed'
