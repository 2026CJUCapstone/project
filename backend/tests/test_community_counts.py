from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.community import get_post_counts
from app.core.database import Base
from app.models import database as models
from app.models import schemas


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'community-counts.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(models.User(id='author', username='author', hashed_password='unused'))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def add_problem(db, problem_id, *, archived=False):
    problem = models.Problem(
        id=problem_id,
        creator_id='author',
        title=problem_id,
        description='',
        difficulty='iron5',
        tags=[],
        points=100,
        test_cases=[],
        deleted_at=datetime.now(timezone.utc).replace(tzinfo=None) if archived else None,
    )
    db.add(problem)
    return problem


def add_comments(db, problem_id, count):
    db.add_all([
        models.Comment(problem_id=problem_id, user_id='author', content=f'comment {index}')
        for index in range(count)
    ])


def counts_for(db, problem_ids):
    return get_post_counts(schemas.CommunityPostCountsRequest(problemIds=problem_ids), db)


def test_post_counts_groups_many_comments_and_keeps_zero_counts(db):
    add_problem(db, 'busy')
    add_problem(db, 'quiet')
    add_comments(db, 'busy', 6)
    db.commit()

    assert counts_for(db, ['busy', 'quiet', 'missing']) == {
        'busy': 6,
        'quiet': 0,
        'missing': 0,
    }


def test_post_counts_returns_empty_response_for_an_empty_problem_list(db):
    assert counts_for(db, []) == {}


def test_post_counts_does_not_leak_private_or_archived_problem_counts(db):
    add_problem(db, 'public')
    add_problem(db, 'private')
    add_problem(db, 'archived', archived=True)
    db.add(models.Contest(
        id='draft-contest',
        creator_id='author',
        title='Draft',
        description='',
        starts_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ends_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None),
        published=False,
    ))
    db.add(models.ContestProblem(
        id='draft-problem',
        contest_id='draft-contest',
        problem_id='private',
        position=0,
        points=100,
        is_new=True,
        snapshot={},
    ))
    add_comments(db, 'public', 2)
    add_comments(db, 'private', 3)
    add_comments(db, 'archived', 4)
    db.commit()

    assert counts_for(db, ['public', 'private', 'archived']) == {'public': 2}
