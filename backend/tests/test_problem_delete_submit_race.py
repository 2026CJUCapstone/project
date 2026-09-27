"""PostgreSQL proof that practice acceptance and archival have one serial order."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import sleep
from uuid import uuid4

from fastapi import HTTPException, Response
import pytest
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.api.routes import problems as problem_routes
from app.core.database import Base
from app.models import database as m, schemas
from app.services import submission_acceptance
from tests.test_judge_policy import policy_fixture


def _request(request_id: str) -> Request:
    return Request({
        'type': 'http',
        'method': 'POST',
        'path': '/api/v1/problems/race/submit',
        'headers': [(b'x-request-id', request_id.encode())],
        'client': ('198.51.100.77', 41234),
        'server': ('isolated.test', 80),
        'scheme': 'http',
        'query_string': b'',
    })


def _seed(factory, suffix: str) -> tuple[str, str, str]:
    sample = [{'input': '1\n', 'expected_output': '2\n'}]
    hidden = [{'input': '2\n', 'expected_output': '3\n'}]
    with factory() as db:
        admin = m.User(username=f'archive-admin-{suffix}', role='admin', hashed_password='')
        participant = m.User(username=f'archive-user-{suffix}', role='user', hashed_password='')
        db.add_all([admin, participant])
        db.flush()
        problem = m.Problem(
            creator_id=admin.id,
            title=f'archive race {suffix}',
            difficulty='iron5',
            tags=['race'],
            description='serial order proof',
            points=100,
            test_cases={'sample': sample, 'hidden': hidden},
            judge_policy=policy_fixture(sample, hidden, ('python',)),
        )
        db.add(problem)
        db.commit()
        return admin.id, participant.id, problem.id


@pytest.mark.parametrize('contest_engine', ['postgres'], indirect=True)
def test_delete_and_submit_have_one_serial_order(contest_engine, monkeypatch):
    Base.metadata.create_all(contest_engine)
    factory = sessionmaker(bind=contest_engine, autoflush=False)
    monkeypatch.setattr(problem_routes, 'invalidate_rating_cache', lambda: None)

    # Deletion owns the problem row first. A submission that observed the old
    # public snapshot must wait, reread the archived row and fail without a
    # durable receipt.
    admin_id, participant_id, problem_id = _seed(factory, uuid4().hex)
    delete_entered, release_delete = Event(), Event()
    real_now = problem_routes.now_utc

    def paused_delete_time():
        delete_entered.set()
        assert release_delete.wait(10)
        return real_now()

    monkeypatch.setattr(problem_routes, 'now_utc', paused_delete_time)

    def delete_first():
        with factory() as db:
            return problem_routes.delete_problem(problem_id, db, db.get(m.User, admin_id))

    def submit_after_delete():
        with factory() as db:
            return submission_acceptance.accept_practice(
                problem_id,
                schemas.SubmissionRequest(code='print(2)', language='python'),
                _request(str(uuid4())),
                Response(),
                db,
                db.get(m.User, participant_id),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        deleting = pool.submit(delete_first)
        assert delete_entered.wait(10)
        submitting = pool.submit(submit_after_delete)
        sleep(.2)
        assert not submitting.done()
        release_delete.set()
        assert deleting.result(timeout=10) == {'message': 'Successfully deleted'}
        with pytest.raises(HTTPException) as rejected:
            submitting.result(timeout=10)
    assert rejected.value.status_code == 404
    with factory() as db:
        assert db.get(m.Problem, problem_id).deleted_at is not None
        assert db.query(m.ExecutionJob).count() == 0
        assert db.query(m.Submission).filter_by(problem_id=problem_id).count() == 0

    # Submission owns the row first. Deletion waits for its commit, then
    # archives the problem while retaining the acknowledged receipt/history.
    monkeypatch.setattr(problem_routes, 'now_utc', real_now)
    admin_id, participant_id, problem_id = _seed(factory, uuid4().hex)
    submit_entered, release_submit = Event(), Event()

    def frozen_contract(*_args, **_kwargs):
        submit_entered.set()
        assert release_submit.wait(10)
        return {'version': 1, 'testSuiteHash': 'sha256:' + 'a' * 64}

    monkeypatch.setattr(submission_acceptance, 'freeze_stored_submission', frozen_contract)

    def submit_first():
        with factory() as db:
            return submission_acceptance.accept_practice(
                problem_id,
                schemas.SubmissionRequest(code='print(2)', language='python'),
                _request(str(uuid4())),
                Response(),
                db,
                db.get(m.User, participant_id),
            )

    def delete_after_submit():
        with factory() as db:
            return problem_routes.delete_problem(problem_id, db, db.get(m.User, admin_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        submitting = pool.submit(submit_first)
        assert submit_entered.wait(10)
        deleting = pool.submit(delete_after_submit)
        sleep(.2)
        assert not deleting.done()
        release_submit.set()
        receipt = submitting.result(timeout=10)
        assert receipt['status'] == 'queued'
        assert deleting.result(timeout=10) == {'message': 'Successfully deleted'}

    with factory() as db:
        problem = db.get(m.Problem, problem_id)
        submission = db.query(m.Submission).filter_by(problem_id=problem_id).one()
        job = db.get(m.ExecutionJob, receipt['executionId'])
        assert problem.deleted_at is not None
        assert submission.id == receipt['id']
        assert job.status == 'queued'
        assert job.payload['problem_id'] == problem_id
