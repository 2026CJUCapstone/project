"""Public contest scoreboard caching stays reproducible and secret-free."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from app.api.routes import contests as contest_routes
from app.core import database as database_core
from app.core.database import Base
from app.models import database as m
from app.services import contests, scoreboard_cache
from app.services.execution_results import publish_result, publish_transition


class _MemoryCache:
    def __init__(self):
        self.values = {}
        self.writes = []

    def get(self, key):
        return copy.deepcopy(self.values.get(key))

    def set(self, key, value, *, ttl_seconds=None):
        self.writes.append((key, copy.deepcopy(value), ttl_seconds))
        self.values[key] = copy.deepcopy(value)


@pytest.fixture
def scoreboard_env(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'scoreboard-cache.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    now = datetime(2030, 1, 1, 12, 0, 0)
    db.add_all([
        m.User(id="admin", username="admin", hashed_password="unused", role="admin"),
        m.User(id="alice", username="alice", nickname="Alice", hashed_password="unused"),
        m.User(id="bob", username="bob", hashed_password="unused"),
    ])
    db.commit()
    contest = m.Contest(
        id="contest", creator_id="admin", title="Private contest title", description="private rules",
        starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(minutes=55), published=True,
    )
    db.add_all([
        contest,
        m.Problem(
            id="problem", creator_id="admin", title="secret problem title", description="secret description",
            difficulty="iron5", tags=["secret-tag"], points=100,
            test_cases={"sample": [{"input": "sample", "expectedOutput": "42"}],
                        "hidden": [{"input": "hidden-input", "expectedOutput": "hidden-output"}]},
        ),
    ])
    db.flush()
    problem = m.ContestProblem(
        id="contest-problem", contest_id=contest.id, problem_id="problem", position=0, points=500,
        is_new=True,
        snapshot={
            "title": "secret snapshot title", "description": "secret snapshot description",
            "difficulty": "iron5", "tags": ["secret-tag"], "practicePoints": 100,
            "sample": [{"input": "sample", "expectedOutput": "42"}],
            "hidden": [{"input": "hidden-input", "expectedOutput": "hidden-output"}],
        },
    )
    db.add_all([
        problem,
        m.ContestParticipant(contest_id=contest.id, user_id="alice"),
        m.ContestParticipant(contest_id=contest.id, user_id="bob"),
        # Inserted deliberately out of receipt order.  The pending earlier
        # receipt becomes a late completed wrong answer in a later test.
        m.ContestSubmission(
            id="alice-earlier", contest_id=contest.id, contest_problem_id=problem.id, user_id="alice",
            request_id="alice-earlier", language="python", code="very secret earlier source",
            received_at=now + timedelta(minutes=2), status="queued", verdict="pending",
        ),
        m.ContestSubmission(
            id="alice-accepted", contest_id=contest.id, contest_problem_id=problem.id, user_id="alice",
            request_id="alice-accepted", language="python", code="very secret accepted source",
            received_at=now + timedelta(minutes=20), status="completed", verdict="accepted",
        ),
        m.ContestSubmission(
            id="bob-pending", contest_id=contest.id, contest_problem_id=problem.id, user_id="bob",
            request_id="bob-pending", language="python", code="very secret bob source",
            received_at=now + timedelta(minutes=10), status="queued", verdict="pending",
        ),
    ])
    db.commit()
    try:
        yield SimpleNamespace(db=db, engine=engine, factory=factory, now=now, contest=contest, problem=problem)
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def memory_cache(monkeypatch):
    cache = _MemoryCache()
    monkeypatch.setattr(scoreboard_cache, "cache_get_json", cache.get)
    monkeypatch.setattr(scoreboard_cache, "cache_set_json", cache.set)
    return cache


def _row(board, user_id="alice"):
    return next(row for row in board["rows"] if row["userId"] == user_id)


def _revision(db, contest_id="contest"):
    return db.query(m.Contest.scoreboard_revision).filter_by(id=contest_id).scalar()


def test_public_cache_is_secret_free_and_hit_avoids_submission_scan(scoreboard_env, memory_cache):
    env = scoreboard_env
    miss_statements = []

    def capture_miss(_connection, _cursor, statement, _parameters, _context, _executemany):
        miss_statements.append(statement.lower())

    event.listen(env.engine, "before_cursor_execute", capture_miss)
    try:
        first = contests.scoreboard(env.db, env.contest, public_cache=True, at=env.now)
    finally:
        event.remove(env.engine, "before_cursor_execute", capture_miss)
    assert first["state"] == "running"
    assert _row(first)["username"] == "Alice"
    assert len(memory_cache.writes) == 1
    key, cached, ttl = memory_cache.writes[0]
    assert key == scoreboard_cache.cache_key("contest", 0)
    assert ttl == scoreboard_cache.SCOREBOARD_CACHE_TTL_SECONDS == 15
    serialized = repr(cached)
    for secret in ("Private contest title", "secret snapshot", "hidden-input", "hidden-output", "very secret"):
        assert secret not in serialized
    assert "username" not in serialized
    assert set(cached) == {"rows", "pendingCount", "problems"}
    problem_queries = [statement for statement in miss_statements if "from contest_problems" in statement]
    assert len(problem_queries) == 1
    assert "contest_problems.snapshot" not in problem_queries[0]

    # A user rename must be reflected even while the score facts are cached.
    env.db.get(m.User, "alice").nickname = "Renamed Alice"
    env.db.commit()
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(env.engine, "before_cursor_execute", capture)
    try:
        hit = contests.scoreboard(env.db, env.contest, public_cache=True, at=env.now + timedelta(seconds=1))
    finally:
        event.remove(env.engine, "before_cursor_execute", capture)
    assert _row(hit)["username"] == "Renamed Alice"
    assert hit["serverTime"] != first["serverTime"]
    assert len(memory_cache.writes) == 1
    assert not any("contest_submissions" in statement for statement in statements)
    assert not any("contest_problems" in statement for statement in statements)
    # The only dynamic scoreboard identity read is the narrow name projection.
    user_queries = [statement for statement in statements if "from users" in statement]
    assert len(user_queries) == 1
    assert "users.nickname" in user_queries[0] and "users.username" in user_queries[0]


def test_missing_or_corrupt_public_cache_falls_back_to_receipt_order_recalculation(scoreboard_env, memory_cache):
    env = scoreboard_env
    key = scoreboard_cache.cache_key(env.contest.id, 0)
    memory_cache.values[key] = {"rows": [{"code": "attacker-controlled secret"}]}
    rebuilt = contests.scoreboard(env.db, env.contest, public_cache=True, at=env.now)
    assert _row(rebuilt)["problems"][0]["wrongAttempts"] == 0
    assert "code" not in repr(memory_cache.values[key])

    # A delayed completion for an earlier receipt must invalidate the old
    # generation and count before the already-known acceptance.
    earlier = env.db.get(m.ContestSubmission, "alice-earlier")
    earlier.status, earlier.verdict = "completed", "wrong_answer"
    scoreboard_cache.bump_scoreboard_revision(env.db, env.contest.id)
    env.db.commit()
    env.db.expire_all()
    contest = env.db.get(m.Contest, env.contest.id)
    recalculated = contests.scoreboard(env.db, contest, public_cache=True, at=env.now)
    alice = _row(recalculated)
    assert contest.scoreboard_revision == 1
    assert alice["problems"][0]["wrongAttempts"] == 1
    assert alice["penaltySeconds"] == 25 * 60 + 300
    assert scoreboard_cache.cache_key(contest.id, 0) != scoreboard_cache.cache_key(contest.id, 1)


def test_revision_bumps_share_write_transactions_and_result_publication(scoreboard_env):
    env = scoreboard_env
    assert _revision(env.db) == 0
    scoreboard_cache.bump_scoreboard_revision(env.db, env.contest.id)
    env.db.rollback()
    env.db.expire_all()
    assert _revision(env.db) == 0

    job = m.ExecutionJob(
        id="job", owner_key="account:alice", quota_key="account:alice", request_id="contest-job",
        payload_hash="a" * 64, kind="contest", payload={}, status="queued", received_at=env.now,
    )
    env.db.add(job)
    env.db.flush()
    receipt = env.db.get(m.ContestSubmission, "alice-earlier")
    receipt.execution_job_id = job.id
    env.db.commit()

    publish_transition(env.db, SimpleNamespace(id=job.id, status="running", started_at=env.now))
    env.db.commit()
    assert _revision(env.db) == 1
    assert env.db.get(m.ContestSubmission, receipt.id).status == "running"

    publish_result(env.db, job.id, {"verdict": "wrong_answer", "value": {}})
    env.db.commit()
    assert _revision(env.db) == 2
    assert env.db.get(m.ContestSubmission, receipt.id).status == "completed"
    # Replaying an already-published terminal result changes no scoreboard fact.
    publish_result(env.db, job.id, {"verdict": "wrong_answer", "value": {}})
    env.db.commit()
    assert _revision(env.db) == 2


def test_finalization_and_admin_or_prestart_views_do_not_reuse_public_cache(scoreboard_env, memory_cache, monkeypatch):
    env = scoreboard_env
    monkeypatch.setattr(contest_routes, "now_utc", lambda: env.now)
    alice = env.db.get(m.User, "alice")
    admin = env.db.get(m.User, "admin")
    public = contest_routes.read_scoreboard(env.contest.id, env.db, alice)
    assert public["state"] == "running"
    assert len(memory_cache.writes) == 1
    # An administrator gets a fresh DB calculation, never the shared public
    # object, even though the response shape currently matches.
    contest_routes.read_scoreboard(env.contest.id, env.db, admin)
    assert len(memory_cache.writes) == 1

    env.contest.published = False
    env.db.commit()
    contest_routes.read_scoreboard(env.contest.id, env.db, admin)
    assert len(memory_cache.writes) == 1
    with pytest.raises(HTTPException):
        contest_routes.read_scoreboard(env.contest.id, env.db, alice)

    # A completed contest changes its state only once finalization commits.
    env.contest.published = True
    env.contest.ends_at = env.now - timedelta(seconds=1)
    for receipt in env.db.query(m.ContestSubmission).all():
        receipt.status, receipt.verdict = "completed", "wrong_answer"
    env.db.commit()
    before = _revision(env.db)
    monkeypatch.setattr(contests, "SessionLocal", env.factory)
    monkeypatch.setattr(contests, "now_utc", lambda: env.now)
    monkeypatch.setattr(contests, "invalidate_rating_cache", lambda *_args: None)
    contests.finalize_contests()
    with env.factory() as fresh:
        assert _revision(fresh) == before + 1
        assert fresh.get(m.Contest, env.contest.id).finalized_at == env.now
    contests.finalize_contests()
    with env.factory() as fresh:
        assert _revision(fresh) == before + 1


def test_scoreboard_revision_migration_is_additive_and_repeatable(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-contests.db').as_posix()}")
    try:
        # The historical migration routine also maintains older application
        # tables.  Keep their current harmless shapes so this isolates the
        # legacy contest column without weakening those preconditions.
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE contests"))
            connection.execute(text(
                "CREATE TABLE contests (id VARCHAR PRIMARY KEY, creator_id VARCHAR NOT NULL, title VARCHAR NOT NULL, "
                "description TEXT NOT NULL, starts_at TIMESTAMP NOT NULL, ends_at TIMESTAMP NOT NULL, "
                "published BOOLEAN NOT NULL, finalized_at TIMESTAMP, created_at TIMESTAMP NOT NULL)"
            ))
            connection.execute(text(
                "INSERT INTO contests (id, creator_id, title, description, starts_at, ends_at, published, created_at) "
                "VALUES ('legacy', 'admin', 'legacy title', 'legacy description', :starts, :ends, 1, :created)"
            ), {"starts": "2030-01-01 00:00:00", "ends": "2030-01-02 00:00:00", "created": "2030-01-01 00:00:00"})
        database_core.migrate_schema(engine)
        columns = {column["name"]: column for column in inspect(engine).get_columns("contests")}
        assert columns["scoreboard_revision"]["nullable"] is False
        with engine.connect() as connection:
            assert connection.execute(text("SELECT scoreboard_revision FROM contests WHERE id = 'legacy'")).scalar_one() == 0
        database_core.migrate_schema(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT scoreboard_revision FROM contests WHERE id = 'legacy'")).scalar_one() == 0
    finally:
        engine.dispose()
