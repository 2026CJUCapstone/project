import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.core.config import settings
from app.main import app
from app.models.database import Problem, User, UserProblemScore
from app.services import auth
from app.services.rating import calculate_rating_stats, difficulty_value, solved_count_bonus


def _admin_headers() -> dict[str, str]:
    token = auth.create_access_token({"sub": settings.ADMIN_USERNAME})
    return {"Authorization": f"Bearer {token}"}


def _auth_headers(username: str) -> dict[str, str]:
    token = auth.create_access_token({"sub": username})
    return {"Authorization": f"Bearer {token}"}


def test_rating_difficulty_values_follow_problem_difficulty_order():
    assert difficulty_value("iron5") == 1
    assert difficulty_value("diamond1") == 30
    assert difficulty_value("unknown") == 0


def test_rating_uses_top_100_difficulty_values_and_solved_count_bonus():
    stats = calculate_rating_stats(["diamond1"] * 101 + ["iron5"])

    assert stats.solved_count == 102
    assert stats.difficulty_score == 30 * 100
    assert stats.solved_bonus == solved_count_bonus(102)
    assert stats.rating == stats.difficulty_score + stats.solved_bonus


@pytest.mark.asyncio
async def test_leaderboard_score_submission_accumulates_and_ranks_users():
    suffix = uuid.uuid4().hex[:10]
    high_user = f"leader_high_{suffix}"
    low_user = f"leader_low_{suffix}"
    usernames = [high_user, low_user]
    high_first_challenge = f"problem_high_first_{suffix}"
    high_second_challenge = f"problem_high_second_{suffix}"
    low_challenge = f"problem_low_{suffix}"
    challenge_ids = [high_first_challenge, high_second_challenge, low_challenge]

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first_response = await client.post(
                "/api/v1/problems/leaderboard/score",
                headers=_admin_headers(),
                json={
                    "username": high_user,
                    "points": 40,
                    "challengeId": high_first_challenge,
                    "avatarUrl": "https://example.com/high.svg",
                },
            )
            second_response = await client.post(
                "/api/v1/problems/leaderboard/score",
                headers=_admin_headers(),
                json={
                    "username": high_user,
                    "points": 15,
                    "challengeId": high_first_challenge,
                    "avatarUrl": "https://example.com/high-new.svg",
                },
            )
            third_response = await client.post(
                "/api/v1/problems/leaderboard/score",
                headers=_admin_headers(),
                json={
                    "username": high_user,
                    "points": 15,
                    "challengeId": high_second_challenge,
                },
            )
            await client.post(
                "/api/v1/problems/leaderboard/score",
                headers=_admin_headers(),
                json={"username": low_user, "points": 10, "challengeId": low_challenge},
            )
            leaderboard_response = await client.get("/api/v1/problems/leaderboard?limit=100")

        assert first_response.status_code == 200
        assert first_response.json()["totalScore"] == 40
        assert first_response.json()["awardedPoints"] == 40
        assert first_response.json()["alreadySolved"] is False

        assert second_response.status_code == 200
        assert second_response.json()["totalScore"] == 40
        assert second_response.json()["awardedPoints"] == 0
        assert second_response.json()["alreadySolved"] is True
        assert second_response.json()["avatarUrl"] == "https://example.com/high-new.svg"

        assert third_response.status_code == 200
        assert third_response.json()["totalScore"] == 55
        assert third_response.json()["awardedPoints"] == 15

        assert leaderboard_response.status_code == 200
        rows = {row["username"]: row for row in leaderboard_response.json()}
        assert rows[high_user]["totalScore"] == 55
        assert rows[high_user]["rating"] == 0
        assert rows[high_user]["tier"] == "Unrated"
        assert rows[high_user]["solvedCount"] == 0
        assert rows[low_user]["totalScore"] == 10
        assert rows[high_user]["rank"] < rows[low_user]["rank"]
    finally:
        db = SessionLocal()
        try:
            db.query(UserProblemScore).filter(
                UserProblemScore.challenge_id.in_(challenge_ids)
            ).delete(synchronize_session=False)
            db.query(User).filter(User.username.in_(usernames)).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


@pytest.mark.asyncio
async def test_leaderboard_excludes_admin_users():
    suffix = uuid.uuid4().hex[:10]
    admin_user = f"leader_admin_{suffix}"
    normal_user = f"leader_user_{suffix}"

    db = SessionLocal()
    try:
        db.add(
            User(
                username=admin_user,
                hashed_password=auth.get_password_hash("password123"),
                total_score=9999,
                role="admin",
            )
        )
        db.add(
            User(
                username=normal_user,
                hashed_password=auth.get_password_hash("password123"),
                total_score=10,
                role="user",
            )
        )
        db.commit()
    finally:
        db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/problems/leaderboard?limit=100")

        assert response.status_code == 200
        rows = {row["username"]: row for row in response.json()}
        assert admin_user not in rows
        assert rows[normal_user]["rank"] >= 1
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username.in_([admin_user, normal_user])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


@pytest.mark.asyncio
async def test_leaderboard_orders_by_rating_before_xp():
    suffix = uuid.uuid4().hex[:10]
    owner_name = f"rating_owner_{suffix}"
    rated_name = f"rating_solver_{suffix}"
    xp_name = f"xp_solver_{suffix}"
    problem_id = f"rating_problem_{suffix}"

    db = SessionLocal()
    try:
        owner = User(username=owner_name, hashed_password=auth.get_password_hash("password123"), role="admin")
        rated_user = User(username=rated_name, hashed_password=auth.get_password_hash("password123"), total_score=10)
        xp_user = User(username=xp_name, hashed_password=auth.get_password_hash("password123"), total_score=999)
        db.add_all([owner, rated_user, xp_user])
        db.flush()
        db.add(
            Problem(
                id=problem_id,
                creator_id=owner.id,
                title="Rating sort problem",
                difficulty="diamond1",
                tags=["io"],
                description="rating",
                points=1,
                test_cases={"sample": [], "hidden": []},
            )
        )
        db.add(
            UserProblemScore(
                user_id=rated_user.id,
                challenge_id=problem_id,
                points_awarded=1,
            )
        )
        db.commit()
    finally:
        db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/problems/leaderboard?limit=100")

        assert response.status_code == 200
        rows = {row["username"]: row for row in response.json()}
        assert rows[rated_name]["rating"] > rows[xp_name]["rating"]
        assert rows[rated_name]["rank"] < rows[xp_name]["rank"]
        assert rows[rated_name]["solvedCount"] == 1
        assert rows[xp_name]["totalScore"] == 999
    finally:
        db = SessionLocal()
        try:
            db.query(UserProblemScore).filter(UserProblemScore.challenge_id == problem_id).delete(synchronize_session=False)
            db.query(Problem).filter(Problem.id == problem_id).delete(synchronize_session=False)
            db.query(User).filter(User.username.in_([owner_name, rated_name, xp_name])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


@pytest.mark.asyncio
async def test_me_returns_current_rating_stats():
    suffix = uuid.uuid4().hex[:10]
    owner_name = f"me_rating_owner_{suffix}"
    solver_name = f"me_rating_solver_{suffix}"
    problem_id = f"me_rating_problem_{suffix}"
    second_problem_id = f"me_rating_problem_second_{suffix}"

    db = SessionLocal()
    try:
        owner = User(username=owner_name, hashed_password=auth.get_password_hash("password123"), role="admin")
        solver = User(username=solver_name, hashed_password=auth.get_password_hash("password123"), total_score=55)
        db.add_all([owner, solver])
        db.flush()
        db.add_all([
            Problem(
                id=problem_id,
                creator_id=owner.id,
                title="Rating profile problem",
                difficulty="gold1",
                tags=["io", "math"],
                description="rating",
                points=25,
                test_cases={"sample": [], "hidden": []},
            ),
            Problem(
                id=second_problem_id,
                creator_id=owner.id,
                title="Rating profile second problem",
                difficulty="silver1",
                tags=["math", "array"],
                description="rating",
                points=30,
                test_cases={"sample": [], "hidden": []},
            ),
        ])
        db.add_all([
            UserProblemScore(
                user_id=solver.id,
                challenge_id=problem_id,
                points_awarded=25,
            ),
            UserProblemScore(
                user_id=solver.id,
                challenge_id=second_problem_id,
                points_awarded=30,
            ),
        ])
        db.commit()
    finally:
        db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/auth/me", headers=_auth_headers(solver_name))

        assert response.status_code == 200
        body = response.json()
        assert body["username"] == solver_name
        assert body["totalScore"] == 55
        assert body["rating"] == difficulty_value("gold1") + difficulty_value("silver1") + solved_count_bonus(2)
        assert body["solvedCount"] == 2
        assert body["tier"] in {"Unrated", "Iron V"}
        tags = {item["tag"]: item for item in body["tagProficiencies"]}
        assert tags["math"]["solvedCount"] == 2
        assert tags["math"]["difficultyScore"] == difficulty_value("gold1") + difficulty_value("silver1")
        assert tags["math"]["proficiency"] == 100
        assert tags["io"]["solvedCount"] == 1
        assert tags["io"]["maxDifficulty"] == "gold1"
        assert tags["array"]["maxDifficulty"] == "silver1"
    finally:
        db = SessionLocal()
        try:
            db.query(UserProblemScore).filter(
                UserProblemScore.challenge_id.in_([problem_id, second_problem_id])
            ).delete(synchronize_session=False)
            db.query(Problem).filter(Problem.id.in_([problem_id, second_problem_id])).delete(synchronize_session=False)
            db.query(User).filter(User.username.in_([owner_name, solver_name])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
