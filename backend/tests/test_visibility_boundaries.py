"""HTTP visibility contracts for private contest and archived problems.

These tests deliberately exercise the public practice/community/submission
surfaces separately from the contest snapshot surfaces.  A private contest
problem is allowed in the admin/editor view and, once the contest is running,
in the participant's contest view; it must not become an ordinary problem
until the contest has ended.  Hidden tests never become public.  Soft-deleted
problems retain minimal submission history metadata for the score ledger, but
not source, description, or test material.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import contests as contest_routes
from app.api.routes import problems as problem_routes
from app.core.database import Base, get_db
from app.main import app
from app.models import database as models
from app.services import contest_access, contests as contest_service
from app.services.auth import create_access_token


def _headers(user: models.User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': user.username})}"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'visibility-boundaries.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()

    admin = models.User(id="visibility-admin", username="visibility-admin", hashed_password="unused", role="admin")
    participant = models.User(id="visibility-participant", username="visibility-participant", hashed_password="unused")
    outsider = models.User(id="visibility-outsider", username="visibility-outsider", hashed_password="unused")
    db.add_all([admin, participant, outsider])
    db.commit()

    clock = [datetime(2040, 1, 1, 12, 0, 0)]
    # Contest and private-problem policy reads each module's imported clock.
    for module in (contest_access, contest_service, contest_routes, problem_routes):
        monkeypatch.setattr(module, "now_utc", lambda: clock[0])

    previous_overrides = dict(app.dependency_overrides)

    def session_override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = session_override

    result = SimpleNamespace(
        db=db,
        factory=factory,
        clock=clock,
        admin=admin,
        participant=participant,
        outsider=outsider,
        contests={},
        deleted=None,
    )
    _seed_fixtures(result)

    try:
        yield result
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        db.close()
        engine.dispose()


def _seed_fixtures(env: SimpleNamespace) -> None:
    """Create one upcoming, running, ended, and archived problem fixture."""

    def add_contest(name: str, start: timedelta, end: timedelta, *, finished: bool = False):
        now = env.clock[0]
        title = f"{name}-private-title"
        description = f"{name}-private-description"
        sample_input = f"{name}-visible-sample"
        hidden_input = f"{name}-hidden-input"
        sample = [{"input": sample_input, "expectedOutput": f"{name}-visible-output"}]
        hidden = [{"input": hidden_input, "expectedOutput": f"{name}-hidden-output"}]
        problem_id = f"{name}-problem"
        contest_id = f"{name}-contest"
        contest_problem_id = f"{name}-contest-problem"
        contest = models.Contest(
            id=contest_id,
            creator_id=env.admin.id,
            title=f"{name}-contest-title",
            description=f"{name}-contest-description",
            starts_at=now + start,
            ends_at=now + end,
            published=True,
            finalized_at=(now - timedelta(minutes=1)) if finished else None,
        )
        problem = models.Problem(
            id=problem_id,
            creator_id=env.admin.id,
            title=title,
            description=description,
            difficulty="iron5",
            tags=[f"{name}-private-tag"],
            points=123,
            test_cases={"sample": sample, "hidden": hidden},
        )
        contest_problem = models.ContestProblem(
            id=contest_problem_id,
            contest_id=contest_id,
            problem_id=problem_id,
            position=0,
            points=500,
            is_new=True,
            snapshot={
                "title": title,
                "description": description,
                "difficulty": "iron5",
                "tags": [f"{name}-private-tag"],
                "practicePoints": 123,
                "sample": sample,
                "hidden": hidden,
            },
        )
        db_objects = [contest, problem, contest_problem]
        db_objects.extend(
            [
                models.ContestParticipant(contest_id=contest_id, user_id=env.participant.id),
                models.Comment(problem_id=problem_id, user_id=env.outsider.id, content=f"{name}-community-secret"),
                models.Submission(
                    problem_id=problem_id,
                    user_id=env.outsider.id,
                    language="python",
                    code=f"{name}-submission-code",
                    status="completed",
                    verdict="accepted",
                    sample_total_cases=1,
                    sample_passed_cases=1,
                    grading_completed=True,
                    grading_passed=True,
                    awarded_points=123,
                    created_at=now,
                ),
            ]
        )
        env.db.add_all(db_objects)
        env.db.commit()
        env.contests[name] = SimpleNamespace(
            contest=contest,
            problem=problem,
            contest_problem=contest_problem,
            title=title,
            description=description,
            sample_input=sample_input,
            hidden_input=hidden_input,
            comment=f"{name}-community-secret",
        )

    add_contest("upcoming", timedelta(hours=1), timedelta(hours=2))
    add_contest("running", -timedelta(hours=1), timedelta(hours=1))
    add_contest("ended", -timedelta(hours=2), -timedelta(hours=1), finished=True)

    now = env.clock[0]
    deleted_problem = models.Problem(
        id="deleted-public-problem",
        creator_id=env.admin.id,
        title="deleted-public-title",
        description="deleted-public-description",
        difficulty="iron5",
        tags=["deleted"],
        points=90,
        test_cases={
            "sample": [{"input": "deleted-sample", "expectedOutput": "deleted-output"}],
            "hidden": [{"input": "deleted-hidden-input", "expectedOutput": "deleted-hidden-output"}],
        },
        deleted_at=now - timedelta(minutes=5),
    )
    env.db.add_all(
        [
            deleted_problem,
            models.Comment(problem_id=deleted_problem.id, user_id=env.outsider.id, content="deleted-community-secret"),
            models.Submission(
                problem_id=deleted_problem.id,
                user_id=env.outsider.id,
                language="python",
                code="deleted-submission-code",
                status="completed",
                verdict="accepted",
                sample_total_cases=1,
                sample_passed_cases=1,
                grading_completed=True,
                grading_passed=True,
                awarded_points=90,
                created_at=now,
            ),
        ]
    )
    env.db.commit()
    env.deleted = SimpleNamespace(
        problem=deleted_problem,
        title=deleted_problem.title,
        description=deleted_problem.description,
    )


def _public_id_set(response):
    return {problem["id"] for problem in response.json()}


@pytest.mark.asyncio
async def test_unfinished_private_problems_are_absent_from_ordinary_surfaces(env):
    """Upcoming/running private problems stay out of practice, posts, counts, and history."""

    identities = [("anonymous", None), ("outsider", env.outsider), ("participant", env.participant)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for name in ("upcoming", "running"):
            fixture = env.contests[name]
            private_id = fixture.problem.id
            secrets = (fixture.title, fixture.description, fixture.hidden_input, fixture.comment)

            for identity, user in identities:
                headers = _headers(user) if user else {}
                listing = await client.get("/api/v1/problems/", headers=headers)
                assert listing.status_code == 200
                assert private_id not in _public_id_set(listing)
                # The ended fixture is public at this clock value; the
                # unfinished private row must not increase this count.
                assert listing.headers["X-Total-Count"] == "1"
                assert all(secret not in listing.text for secret in secrets)

                detail = await client.get(f"/api/v1/problems/{private_id}", headers=headers)
                assert detail.status_code == 404, f"{name}/{identity} practice detail leaked"
                assert all(secret not in detail.text for secret in secrets)

                posts = await client.get("/api/v1/community/posts", params={"problemId": private_id}, headers=headers)
                assert posts.status_code == 404, f"{name}/{identity} community detail leaked"
                assert all(secret not in posts.text for secret in secrets)

                counts = await client.post("/api/v1/community/posts/counts", json={"problemIds": [private_id]})
                assert counts.status_code == 200
                assert counts.json() == {}
                assert all(secret not in counts.text for secret in secrets)

                history = await client.get(
                    "/api/v1/problems/submissions",
                    params={"problemId": private_id},
                    headers=headers,
                )
                assert history.status_code == 200
                assert history.json() == {"submissions": [], "total": 2, "filteredTotal": 0}
                assert all(secret not in history.text for secret in secrets)

            # Administrators may inspect private problem material through the
            # problem editor/community moderation surface.  This is distinct
            # from ordinary public submission history, which remains hidden.
            admin_headers = _headers(env.admin)
            admin_detail = await client.get(f"/api/v1/problems/{private_id}", headers=admin_headers)
            assert admin_detail.status_code == 200
            assert admin_detail.json()["title"] == fixture.title
            assert admin_detail.json()["description"] == fixture.description
            assert admin_detail.json()["hiddenTestCases"][0]["input"] == fixture.hidden_input

            admin_listing = await client.get("/api/v1/problems/", headers=admin_headers)
            assert private_id in _public_id_set(admin_listing)
            admin_problem = next(item for item in admin_listing.json() if item["id"] == private_id)
            assert admin_problem["hiddenTestCases"][0]["input"] == fixture.hidden_input

            admin_posts = await client.get(
                "/api/v1/community/posts", params={"problemId": private_id}, headers=admin_headers
            )
            assert admin_posts.status_code == 200
            assert fixture.comment in admin_posts.text

            admin_history = await client.get(
                "/api/v1/problems/submissions", params={"problemId": private_id}, headers=admin_headers
            )
            assert admin_history.json() == {"submissions": [], "total": 2, "filteredTotal": 0}


@pytest.mark.asyncio
async def test_contest_snapshot_boundary_distinguishes_participant_and_admin(env):
    """Only running participants see a contest problem; admin can manage it."""

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for name in ("upcoming", "running"):
            fixture = env.contests[name]
            root = f"/api/v1/contests/{fixture.contest.id}"
            detail_url = f"{root}/problems/{fixture.contest_problem.id}"

            anonymous_root = await client.get(root)
            outsider_root = await client.get(root, headers=_headers(env.outsider))
            participant_root = await client.get(root, headers=_headers(env.participant))
            admin_root = await client.get(root, headers=_headers(env.admin))
            assert anonymous_root.status_code == outsider_root.status_code == participant_root.status_code == 200
            assert anonymous_root.json()["problems"] == []
            assert outsider_root.json()["problems"] == []
            if name == "upcoming":
                assert participant_root.json()["problems"] == []
            else:
                assert participant_root.json()["problems"][0]["title"] == fixture.title
            assert admin_root.json()["problems"][0]["title"] == fixture.title

            anonymous_detail = await client.get(detail_url)
            outsider_detail = await client.get(detail_url, headers=_headers(env.outsider))
            participant_detail = await client.get(detail_url, headers=_headers(env.participant))
            admin_detail = await client.get(detail_url, headers=_headers(env.admin))
            assert anonymous_detail.status_code == outsider_detail.status_code == 403
            assert participant_detail.status_code == (403 if name == "upcoming" else 200)
            assert admin_detail.status_code == 200
            if name == "running":
                body = participant_detail.json()
                assert body["title"] == fixture.title
                assert body["description"] == fixture.description
                assert body["testCases"][0]["input"] == fixture.sample_input
                assert fixture.hidden_input not in participant_detail.text
                assert "hiddenTestCases" not in body
            assert fixture.hidden_input not in admin_detail.text

            manage = await client.get(f"{root}/manage", headers=_headers(env.admin))
            assert manage.status_code == 200
            assert fixture.hidden_input in manage.text


@pytest.mark.asyncio
async def test_ended_private_problem_enters_public_surfaces_without_hidden_tests(env):
    """After the deadline, the problem becomes practice-visible but hidden cases stay private."""

    fixture = env.contests["ended"]
    private_id = fixture.problem.id
    root = f"/api/v1/contests/{fixture.contest.id}"
    detail_url = f"{root}/problems/{fixture.contest_problem.id}"
    identities = [("anonymous", None), ("outsider", env.outsider), ("participant", env.participant)]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for identity, user in identities:
            headers = _headers(user) if user else {}
            detail = await client.get(f"/api/v1/problems/{private_id}", headers=headers)
            assert detail.status_code == 200, f"ended/{identity} practice detail did not open"
            assert detail.json()["title"] == fixture.title
            assert detail.json()["description"] == fixture.description
            assert detail.json()["hiddenTestCases"] == []
            assert fixture.hidden_input not in detail.text

            listing = await client.get("/api/v1/problems/", headers=headers)
            assert private_id in _public_id_set(listing)
            listed = next(item for item in listing.json() if item["id"] == private_id)
            assert listed["hiddenTestCases"] == []
            assert fixture.hidden_input not in listing.text

            posts = await client.get("/api/v1/community/posts", params={"problemId": private_id}, headers=headers)
            assert posts.status_code == 200
            assert fixture.comment in posts.text
            assert fixture.hidden_input not in posts.text

            counts = await client.post("/api/v1/community/posts/counts", json={"problemIds": [private_id]})
            assert counts.json() == {private_id: 1}

            history = await client.get("/api/v1/problems/submissions", params={"problemId": private_id}, headers=headers)
            assert history.status_code == 200
            assert history.json()["total"] == 2
            assert history.json()["filteredTotal"] == 1
            retained = history.json()["submissions"][0]
            assert retained["problemTitle"] == fixture.title
            assert "code" not in retained
            assert "description" not in retained
            assert "testCases" not in retained
            assert "hiddenTestCases" not in retained
            assert fixture.hidden_input not in history.text

            contest_detail = await client.get(detail_url, headers=headers)
            assert contest_detail.status_code == 200
            assert fixture.hidden_input not in contest_detail.text

        admin_detail = await client.get(f"/api/v1/problems/{private_id}", headers=_headers(env.admin))
        assert admin_detail.status_code == 200
        assert admin_detail.json()["hiddenTestCases"][0]["input"] == fixture.hidden_input


@pytest.mark.asyncio
async def test_deleted_problem_blocks_new_access_but_preserves_safe_history(env):
    """Soft deletion hides the problem while retaining minimal history metadata."""

    problem_id = env.deleted.problem.id
    identities = [("anonymous", None), ("outsider", env.outsider), ("admin", env.admin)]
    leaks = []

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for identity, user in identities:
            headers = _headers(user) if user else {}
            detail = await client.get(f"/api/v1/problems/{problem_id}", headers=headers)
            assert detail.status_code == 404

            listing = await client.get("/api/v1/problems/", headers=headers)
            assert listing.status_code == 200
            assert problem_id not in _public_id_set(listing)
            assert env.deleted.title not in listing.text
            assert env.deleted.description not in listing.text

            posts = await client.get("/api/v1/community/posts", params={"problemId": problem_id}, headers=headers)
            assert posts.status_code == 404
            counts = await client.post("/api/v1/community/posts/counts", json={"problemIds": [problem_id]})
            assert counts.status_code == 200
            assert counts.json() == {}

            new_submission = await client.post(
                f"/api/v1/problems/{problem_id}/submit",
                headers={**headers, "X-Request-ID": str(uuid4())},
                json={"code": "new-deleted-source", "language": "python"},
            )
            assert new_submission.status_code == 404

            history = await client.get(
                "/api/v1/problems/submissions", params={"problemId": problem_id}, headers=headers
            )
            body = history.json()
            assert body["total"] == 2
            assert body["filteredTotal"] == 1
            retained = body["submissions"]
            if len(retained) != 1:
                leaks.append((identity, body))
                continue
            item = retained[0]
            assert item["problemId"] == problem_id
            assert item["problemTitle"] == env.deleted.title
            assert item["verdict"] == "accepted"
            assert item["awardedPoints"] == 90
            assert all(
                field not in item for field in ("code", "description", "testCases", "hiddenTestCases")
            )
            assert all(
                secret not in history.text
                for secret in (
                    "deleted-submission-code",
                    env.deleted.description,
                    "deleted-sample",
                    "deleted-output",
                    "deleted-hidden-input",
                    "deleted-hidden-output",
                    "deleted-community-secret",
                )
            )

    assert not leaks, f"archived problem history was not preserved: {leaks}"
