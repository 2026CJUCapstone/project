import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.main import app
from app.models.database import User, UserProblemScore


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
                json={
                    "username": high_user,
                    "points": 40,
                    "challengeId": high_first_challenge,
                    "avatarUrl": "https://example.com/high.svg",
                },
            )
            second_response = await client.post(
                "/api/v1/problems/leaderboard/score",
                json={
                    "username": high_user,
                    "points": 15,
                    "challengeId": high_first_challenge,
                    "avatarUrl": "https://example.com/high-new.svg",
                },
            )
            third_response = await client.post(
                "/api/v1/problems/leaderboard/score",
                json={
                    "username": high_user,
                    "points": 15,
                    "challengeId": high_second_challenge,
                },
            )
            await client.post(
                "/api/v1/problems/leaderboard/score",
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
