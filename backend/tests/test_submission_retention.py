from datetime import timedelta
import uuid

from app.api.routes.problems import _prune_old_submissions
from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models import database as m
from app.services.contest_access import now_utc
from app.services.housekeeping import purge_expired_anonymous_submissions


def test_explicit_zero_preserves_legacy_anonymous_submission(monkeypatch):
    monkeypatch.setattr(settings, 'ANONYMOUS_SUBMISSION_RETENTION_DAYS', 0)
    with SessionLocal() as db:
        try:
            user = m.User(username=f'preserve_{uuid.uuid4().hex}', hashed_password='')
            db.add(user)
            db.flush()
            problem = m.Problem(creator_id=user.id, title='preserve', difficulty='iron5', tags=[], description='', test_cases=[])
            db.add(problem)
            db.flush()
            row = m.Submission(problem_id=problem.id, language='python', code='legacy record', status='Accepted',
                               created_at=now_utc()-timedelta(days=365))
            db.add(row)
            db.flush()
            identifier = row.id
            assert purge_expired_anonymous_submissions(db) == 0
            assert db.get(m.Submission, identifier).code == 'legacy record'
        finally:
            db.rollback()


def test_retention_flushes_current_submission_and_preserves_active(monkeypatch):
    monkeypatch.setattr(settings, 'SUBMISSION_RETENTION_PER_USER', 2)
    with SessionLocal() as db:
        user = m.User(username=f'retention_{uuid.uuid4().hex}', hashed_password='')
        db.add(user)
        db.flush()
        problem = m.Problem(creator_id=user.id, title='retention', difficulty='iron5', tags=[], description='', test_cases=[])
        db.add(problem)
        db.flush()
        try:
            for index, status in enumerate(['queued', 'running', 'Accepted', 'Rejected', 'Accepted']):
                db.add(m.Submission(user_id=user.id, problem_id=problem.id, language='python', code='',
                                    status=status, created_at=now_utc()+timedelta(seconds=index)))
                _prune_old_submissions(db, user.id)
            rows = db.query(m.Submission).filter_by(user_id=user.id).all()
            assert len(rows) == 4
            assert sorted(s.status for s in rows) == ['Accepted', 'Rejected', 'queued', 'running']
        finally:
            db.rollback()


def test_anonymous_ttl_is_bounded_and_idempotent_and_keeps_active_registered_contests(monkeypatch):
    monkeypatch.setattr(settings, 'ANONYMOUS_SUBMISSION_RETENTION_DAYS', 7)
    now = now_utc()
    with SessionLocal() as db:
        user = m.User(username=f'ttl_{uuid.uuid4().hex}', hashed_password='')
        db.add(user)
        db.flush()
        problem = m.Problem(creator_id=user.id, title='ttl', difficulty='iron5', tags=[], description='', test_cases=[])
        db.add(problem)
        db.flush()
        try:
            for status, user_id, days in [('Accepted',None,8), ('Rejected',None,8), ('queued',None,8),
                                          ('running',None,8), ('Accepted',user.id,8), ('Accepted',None,7)]:
                db.add(m.Submission(problem_id=problem.id, user_id=user_id, code='', language='python',
                                    status=status, created_at=now-timedelta(days=days)))
            contest = m.Contest(creator_id=user.id, title='ttl', starts_at=now-timedelta(days=10), ends_at=now-timedelta(days=9))
            db.add(contest)
            db.flush()
            cp = m.ContestProblem(contest_id=contest.id, problem_id=problem.id, position=0, points=100, snapshot={})
            db.add(cp)
            db.flush()
            db.add(m.ContestSubmission(contest_id=contest.id, contest_problem_id=cp.id, user_id=user.id,
                                       code='keep forever', language='python', request_id=uuid.uuid4().hex,
                                       received_at=now-timedelta(days=10), status='completed', verdict='accepted'))
            db.flush()
            assert purge_expired_anonymous_submissions(db, at=now, batch_size=1) == 1
            assert purge_expired_anonymous_submissions(db, at=now, batch_size=1) == 1
            assert purge_expired_anonymous_submissions(db, at=now) == 0
            assert db.query(m.Submission).filter_by(problem_id=problem.id).count() == 4
            assert db.query(m.ContestSubmission).filter_by(contest_id=contest.id).one().code == 'keep forever'
        finally:
            db.rollback()
