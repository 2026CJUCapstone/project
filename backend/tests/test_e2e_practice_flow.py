"""The E2E practice flow distinguishes submission results from score history."""

import importlib.util
from pathlib import Path

import pytest

from app.models.schemas import SubmissionResponse


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "e2e_stack_test.py"
PROBLEM_ID = "practice-problem"
SOLVER_HEADERS = {"Authorization": "Bearer fixture-solver"}


def load_script():
    spec = importlib.util.spec_from_file_location("e2e_practice_flow_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def submission_wire(total_score: int) -> dict:
    return SubmissionResponse(
        status="completed",
        verdict="accepted",
        total_cases=1,
        passed_cases=1,
        sample_total_cases=1,
        sample_passed_cases=1,
        grading_completed=True,
        grading_passed=True,
        total_score=total_score,
        details=[],
        message="accepted",
    ).model_dump(by_alias=True)


def install_practice_api(
    monkeypatch,
    script,
    *,
    account=None,
    problem=None,
    history_mutator=None,
    duplicate_receipt_id=False,
    duplicate_execution_id=False,
):
    baseline = {"id": "solver-id", "totalScore": 10}
    account = account or {"id": "solver-id", "totalScore": 30}
    problem = problem or {"solved": True, "bestAwardedPoints": 20}
    history = {
        "filteredTotal": 2,
        "submissions": [
            {
                "id": "practice-receipt-1",
                "awardedPoints": 20,
                "userId": "solver-id",
                "problemId": PROBLEM_ID,
                "verdict": "accepted",
            },
            {
                "id": "practice-receipt-2",
                "awardedPoints": 0,
                "userId": "solver-id",
                "problemId": PROBLEM_ID,
                "verdict": "accepted",
            },
        ],
    }
    if history_mutator is not None:
        history_mutator(history)

    receipts = [
        {"id": "practice-receipt-1", "executionId": "execution-1"},
        {
            "id": "practice-receipt-1" if duplicate_receipt_id else "practice-receipt-2",
            "executionId": "execution-1" if duplicate_execution_id else "execution-2",
        },
    ]
    calls = {"post": [], "poll": [], "request": []}
    me_reads = 0
    expected_submit_url = (
        script.FRONTEND_BASE_URL + f"/api/v1/problems/{PROBLEM_ID}/submit"
    )
    expected_history_url = (
        script.FRONTEND_BASE_URL
        + f"/api/v1/problems/submissions?mine=true&problemId={PROBLEM_ID}"
    )
    expected_problem_url = script.FRONTEND_BASE_URL + f"/api/v1/problems/{PROBLEM_ID}"

    def post_json(url, payload, headers=None):
        assert url == expected_submit_url
        assert payload == {
            "code": script.LANGUAGE_SMOKE_CODES["bpp"],
            "language": "bpp",
        }
        assert headers is not None and headers["Authorization"] == SOLVER_HEADERS["Authorization"]
        calls["post"].append((url, payload, headers))
        return 202, receipts[len(calls["post"]) - 1]

    def poll_execution(execution_id, *, headers=None):
        calls["poll"].append((execution_id, headers))
        return {"ok": True, "value": submission_wire(30)}

    def request_json(url, *, headers=None, **kwargs):
        nonlocal me_reads
        calls["request"].append((url, headers, kwargs))
        if url.endswith("/api/v1/auth/me"):
            me_reads += 1
            return 200, baseline if me_reads == 1 else account
        if url == expected_history_url:
            return 200, history
        if url == expected_problem_url:
            return 200, problem
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(script, "post_json", post_json)
    monkeypatch.setattr(script, "poll_execution", poll_execution)
    monkeypatch.setattr(script, "request_json", request_json)
    return calls, history


def test_practice_uses_canonical_submission_response_and_checks_history(monkeypatch):
    script = load_script()
    wire = submission_wire(30)
    assert "totalScore" in wire
    assert "gradingPassed" in wire and "gradingCompleted" in wire
    assert "awardedPoints" not in wire
    assert "alreadySolved" not in wire
    calls, _ = install_practice_api(monkeypatch, script)

    result = script.exercise_practice(PROBLEM_ID, SOLVER_HEADERS)

    assert result == {"awardedPoints": 20, "duplicateAwardedPoints": 0}
    assert len(calls["post"]) == 2
    assert [call[2]["X-Request-ID"] for call in calls["post"]][0] != [
        call[2]["X-Request-ID"] for call in calls["post"]
    ][1]
    assert [execution_id for execution_id, _ in calls["poll"]] == [
        "execution-1", "execution-2"
    ]
    assert [url for url, _, _ in calls["request"]] == [
        script.FRONTEND_BASE_URL + "/api/v1/auth/me",
        script.FRONTEND_BASE_URL
        + f"/api/v1/problems/submissions?mine=true&problemId={PROBLEM_ID}",
        script.FRONTEND_BASE_URL + "/api/v1/auth/me",
        script.FRONTEND_BASE_URL + f"/api/v1/problems/{PROBLEM_ID}",
    ]


def test_practice_rejects_a_duplicate_award_in_history(monkeypatch):
    script = load_script()

    def duplicate_award(history):
        history["submissions"][1]["awardedPoints"] = 20

    install_practice_api(monkeypatch, script, history_mutator=duplicate_award)

    with pytest.raises(RuntimeError, match="score ledger did not award exactly once"):
        script.exercise_practice(PROBLEM_ID, SOLVER_HEADERS)


@pytest.mark.parametrize(
    "mutation",
    ["account", "problem"],
    ids=["account-total", "problem-progress"],
)
def test_practice_rejects_account_or_problem_progress_mismatch(monkeypatch, mutation):
    script = load_script()
    account = {"id": "solver-id", "totalScore": 29} if mutation == "account" else None
    problem = {"solved": False, "bestAwardedPoints": 0} if mutation == "problem" else None
    install_practice_api(monkeypatch, script, account=account, problem=problem)

    with pytest.raises(RuntimeError, match="account/progress disagrees"):
        script.exercise_practice(PROBLEM_ID, SOLVER_HEADERS)


@pytest.mark.parametrize(
    ("duplicate_receipt_id", "duplicate_execution_id"),
    [(True, False), (False, True)],
    ids=["receipt-id", "execution-id"],
)
def test_practice_rejects_receipt_reuse(monkeypatch, duplicate_receipt_id, duplicate_execution_id):
    script = load_script()
    calls, _ = install_practice_api(
        monkeypatch,
        script,
        duplicate_receipt_id=duplicate_receipt_id,
        duplicate_execution_id=duplicate_execution_id,
    )

    with pytest.raises(RuntimeError, match="reused a receipt"):
        script.exercise_practice(PROBLEM_ID, SOLVER_HEADERS)

    assert len(calls["post"]) == 2
    assert len(calls["poll"]) == 2
    assert not any("submissions?mine=true" in url for url, _, _ in calls["request"])
