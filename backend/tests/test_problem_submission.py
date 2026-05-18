import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.main import app
from app.models.database import Problem, User
from app.services import compiler as compiler_service


def _create_problem_with_grading_case() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        user = User(username=f"problem_owner_{suffix}", hashed_password="")
        db.add(user)
        db.flush()

        problem = Problem(
            creator_id=user.id,
            title=f"채점 응답 검증 {suffix}",
            difficulty="iron5",
            tags=["io"],
            description="## 문제\n\n출력을 검증합니다.",
            test_cases={
                "sample": [{"input": "sample", "expected_output": "ok"}],
                "hidden": [{"input": "judge", "expected_output": "ok"}],
            },
        )
        db.add(problem)
        db.commit()
        return user.id, problem.id
    finally:
        db.close()


def _delete_problem_fixture(user_id: str, problem_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(Problem).filter(Problem.id == problem_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_problem_list_omits_grading_cases_for_public_users():
    user_id, problem_id = _create_problem_with_grading_case()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/problems/")

        assert response.status_code == 200
        problem = next(item for item in response.json() if item["id"] == problem_id)
        assert problem["testCases"] == [{"input": "sample", "expectedOutput": "ok"}]
        assert problem["hiddenTestCases"] == []
    finally:
        _delete_problem_fixture(user_id, problem_id)


@pytest.mark.asyncio
async def test_submission_response_does_not_reveal_grading_case_counts(monkeypatch: pytest.MonkeyPatch):
    user_id, problem_id = _create_problem_with_grading_case()

    async def fake_run(source_code: str, language: str, stdin: str = "", optimize: bool = False):
        return {"stdout": "ok\n", "stderr": "", "exit_code": 0, "execution_time": 1.0}

    monkeypatch.setattr(compiler_service.compiler_instance, "run", fake_run)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/problems/{problem_id}/submit",
                json={"code": "func main() -> u64 { return 0; }", "language": "bpp"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "Accepted"
        assert body["gradingCompleted"] is True
        assert body["gradingPassed"] is True
        assert body["sampleTotalCases"] == 1
        assert body["samplePassedCases"] == 1
        assert "hiddenTotalCases" not in body
        assert "hiddenPassedCases" not in body
        assert "hiddenCompleted" not in body
        assert body["details"] == [
            {
                "caseNumber": 1,
                "phase": "sample",
                "isVisible": True,
                "status": "Correct",
                "input": "sample",
                "expected": "ok",
                "actual": "ok",
            }
        ]
    finally:
        _delete_problem_fixture(user_id, problem_id)
