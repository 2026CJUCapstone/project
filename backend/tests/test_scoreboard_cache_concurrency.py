"""Independent DB sessions: stale identity maps, rollback and changing revisions."""
import copy
from datetime import timedelta

import pytest

from app.models import database as m
from app.services import contests, scoreboard_cache
from tests.test_durable_queue import replicas
from tests.test_sandbox_operations import AT


@pytest.fixture
def seeded(replicas):
    with replicas[0]() as db:
        db.add(m.User(id='user', username='reader', hashed_password='fixture'))
        db.flush()
        db.add_all([
            m.Contest(id='contest', creator_id='user', title='fixture', description='',
                starts_at=AT, ends_at=AT + timedelta(hours=1), published=True),
            m.Problem(id='problem', creator_id='user', title='fixture', description='',
                difficulty='iron5', tags=[], points=100, test_cases={}),
        ])
        db.flush()
        db.add(m.ContestProblem(id='cp', contest_id='contest', problem_id='problem',
            position=0, points=100, is_new=False, snapshot={}))
        db.flush()
        db.add_all([
            m.ContestParticipant(contest_id='contest', user_id='user'),
            m.ContestSubmission(id='earlier', contest_id='contest', contest_problem_id='cp',
                user_id='user', request_id='earlier', language='python', code='private',
                received_at=AT + timedelta(seconds=10), status='queued', verdict='pending'),
            m.ContestSubmission(id='accepted', contest_id='contest', contest_problem_id='cp',
                user_id='user', request_id='accepted', language='python', code='private',
                received_at=AT + timedelta(seconds=20), status='completed', verdict='accepted'),
        ])
        db.commit()
    return replicas


@pytest.fixture
def cache(monkeypatch):
    entries = {}
    monkeypatch.setattr(scoreboard_cache, 'cache_get_json', lambda key: copy.deepcopy(entries.get(key)))
    monkeypatch.setattr(scoreboard_cache, 'cache_set_json',
        lambda key, value, **kwargs: entries.__setitem__(key, copy.deepcopy(value)))
    return entries


def wrong(db):
    db.query(m.ContestSubmission).filter_by(id='earlier').update(
        {'status': 'completed', 'verdict': 'wrong_answer'}, synchronize_session=False)
    scoreboard_cache.bump_scoreboard_revision(db, 'contest')


def board(db, contest):
    return contests.scoreboard(db, contest, public_cache=True, at=AT + timedelta(minutes=5))


def test_existing_orm_contest_does_not_keep_previous_revision_after_peer_commit(seeded, cache):
    with seeded[0]() as reader, seeded[1]() as writer:
        contest = reader.get(m.Contest, 'contest')
        assert board(reader, contest)['rows'][0]['penaltySeconds'] == 20
        assert contest.scoreboard_revision == 0
        wrong(writer)
        writer.commit()
        assert contest.scoreboard_revision == 0  # Deliberately stale identity map.
        assert board(reader, contest)['rows'][0]['penaltySeconds'] == 320
        assert scoreboard_cache.cache_key('contest', 1) in cache


def test_rolled_back_future_revision_cannot_poison_later_committed_revision(seeded, cache):
    with seeded[0]() as writer:
        contest = writer.get(m.Contest, 'contest')
        wrong(writer)
        assert board(writer, contest)['rows'][0]['penaltySeconds'] == 320
        assert cache == {}  # This transaction has not committed its facts.
        writer.rollback()
    with seeded[1]() as writer:
        writer.query(m.ContestSubmission).filter_by(id='earlier').update(
            {'status': 'completed', 'verdict': 'compile_error'}, synchronize_session=False)
        scoreboard_cache.bump_scoreboard_revision(writer, 'contest')
        writer.commit()
    with seeded[0]() as reader:
        result = board(reader, reader.get(m.Contest, 'contest'))
        assert result['rows'][0]['penaltySeconds'] == 20
        assert result['pendingCount'] == 0


def test_revision_change_during_projection_never_populates_old_cache_key(seeded, cache, monkeypatch):
    compute = contests._scoreboard_projection
    changed = []
    def raced(db, contest):
        if not changed:
            with seeded[1]() as writer:
                wrong(writer)
                writer.commit()
            changed.append(True)
        return compute(db, contest)
    monkeypatch.setattr(contests, '_scoreboard_projection', raced)
    with seeded[0]() as reader:
        result = board(reader, reader.get(m.Contest, 'contest'))
        assert result['rows'][0]['penaltySeconds'] == 320
        assert scoreboard_cache.cache_key('contest', 0) not in cache


def test_cache_is_reusable_in_new_transaction_after_successful_write(seeded, cache):
    with seeded[0]() as writer:
        wrong(writer)
        writer.commit()
        contest = writer.get(m.Contest, 'contest')
        assert board(writer, contest)['rows'][0]['penaltySeconds'] == 320
        assert scoreboard_cache.cache_key('contest', 1) in cache
