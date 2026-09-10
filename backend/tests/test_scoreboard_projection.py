import os
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def scoreboard_env(monkeypatch):
    database_path = Path(tempfile.gettempdir()) / f"bpp-scoreboard-{uuid.uuid4().hex}.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")

    # Import service/model modules only after the isolated test environment is set.
    # app.main is intentionally not imported because it performs application DB setup.
    from app.core.database import Base
    from app.models import database as models
    from app.services import contests as service

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db, engine, models, service
    finally:
        db.close()
        engine.dispose()
        database_path.unlink(missing_ok=True)


def test_scoreboard_projects_submission_fields_without_code(scoreboard_env):
    db, engine, models, service = scoreboard_env
    start = datetime(2030, 1, 1)
    contest = models.Contest(
        id="contest",
        creator_id="admin",
        title="Projection test",
        description="",
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        published=True,
    )
    db.add_all([
        models.User(id="admin", username="admin", hashed_password="unused", role="admin"),
        models.User(id="alice", username="alice", nickname="Alice", hashed_password="unused"),
        models.User(id="bob", username="bob", hashed_password="unused"),
        contest,
        models.Problem(
            id="problem", creator_id="admin", title="P", description="", difficulty="iron5",
            tags=[], points=100, test_cases=[],
        ),
    ])
    db.flush()
    db.add(models.ContestProblem(
        id="contest-problem", contest_id=contest.id, problem_id="problem",
        position=0, points=500, is_new=False, snapshot={"practicePoints": 100},
    ))
    db.add_all([
        models.ContestParticipant(contest_id=contest.id, user_id="alice"),
        models.ContestParticipant(contest_id=contest.id, user_id="bob"),
    ])
    db.flush()

    def submission(identifier, user_id, minute, status, verdict, code):
        return models.ContestSubmission(
            id=identifier,
            contest_id=contest.id,
            contest_problem_id="contest-problem",
            user_id=user_id,
            request_id=identifier,
            language="python",
            code=code,
            received_at=start + timedelta(minutes=minute),
            status=status,
            verdict=verdict,
        )

    # Insert out of receipt order. Only completed penalty verdicts before the
    # first receipt-ordered AC count; later ACs and wrong answers must not.
    db.add_all([
        submission("alice-late-ac", "alice", 30, "completed", "accepted", "secret late source"),
        submission("alice-compile", "alice", 1, "completed", "compile_error", "secret compile source"),
        submission("alice-wrong", "alice", 5, "completed", "wrong_answer", "secret wrong source"),
        submission("alice-first-ac", "alice", 20, "completed", "accepted", "secret accepted source"),
        submission("alice-after", "alice", 25, "completed", "wrong_answer", "secret after source"),
        submission("bob-pending", "bob", 10, "queued", "pending", "secret pending source"),
        submission("bob-ac", "bob", 25, "completed", "accepted", "secret bob source"),
    ])
    db.commit()

    statements = []

    def capture_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_sql)
    try:
        board = service.scoreboard(db, contest)
    finally:
        event.remove(engine, "before_cursor_execute", capture_sql)

    rows = {row["userId"]: row for row in board["rows"]}
    assert rows["alice"]["totalPoints"] == 500
    assert rows["alice"]["penaltySeconds"] == 20 * 60 + 5 * 60
    assert rows["alice"]["problems"][0]["wrongAttempts"] == 1
    assert rows["alice"]["problems"][0]["acceptedAt"].startswith("2030-01-01T00:20:00")
    assert rows["bob"]["totalPoints"] == 500
    assert rows["bob"]["penaltySeconds"] == 25 * 60
    assert rows["alice"]["rank"] == rows["bob"]["rank"] == 1
    assert board["pendingCount"] == 1

    submission_selects = [
        statement.lower()
        for statement in statements
        if statement.lstrip().lower().startswith("select") and "contest_submissions" in statement.lower()
    ]
    assert len(submission_selects) == 1
    scoreboard_select = submission_selects[0]
    assert "contest_submissions.code" not in scoreboard_select
    for column in ("id", "contest_problem_id", "user_id", "received_at", "status", "verdict"):
        assert f"contest_submissions.{column}" in scoreboard_select
