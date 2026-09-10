"""Contract tests for the isolated stack's real-contest HTTP sequence.

No Docker service is started here.  The fake speaks only the public contest
API shapes so the E2E harness cannot accidentally regress its time, identity,
or privacy assertions while its full-stack validation is opt-in.
"""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from urllib.error import HTTPError
from uuid import UUID

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "e2e_stack_test.py"
REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")


def load_script():
    spec = importlib.util.spec_from_file_location("e2e_contest_flow_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeContestApi:
    """A minimal public HTTP contract, including the publication ID change."""

    contest_id = "contest-id"
    source_id = "underlying-private-problem"
    draft_problem_id = "draft-contest-problem"
    published_problem_id = "published-contest-problem"
    running_problem_id = "running-contest-problem"
    receipt_id = "contest-receipt"

    def __init__(self, script):
        self.script = script
        self.base = script.FRONTEND_BASE_URL
        self.path = "/api/v1/contests/" + self.contest_id
        self.admin_headers = {"Authorization": "Bearer admin"}
        self.solver_headers = {"Authorization": "Bearer solver"}
        self.manage_time = "2032-05-06T07:08:09Z"
        self.create_payload = None
        self.publish_payload = None
        self.submit_payloads = []
        self.submit_urls = []
        self.source_reads = 0
        self.contest_waits = 0
        self.duplicate_receipt_id = self.receipt_id
        self.leak_prestart_problem = False
        self.public = {
            "id": self.source_id,
            "solved": True,
            "bestAwardedPoints": 17,
            "hiddenTestCases": [],
        }
        self.account = {"id": "solver-id", "totalScore": 37}
        self.manage = {
            "id": self.contest_id,
            "title": "E2E contest fixture",
            "description": "isolated contract fixture",
            "serverTime": self.manage_time,
            "problems": [{
                "problemId": self.source_id,
                "points": 500,
                "newProblem": {
                    "title": "E2E private problem",
                    "description": "Print 42",
                    "difficulty": "iron5",
                    "tags": ["e2e"],
                    "points": 17,
                    "testCases": [{"input": "", "expectedOutput": "42"}],
                    "hiddenTestCases": [{"input": "", "expectedOutput": "42"}],
                },
            }],
        }

    def post_json(self, url, payload, headers=None):
        if url == self.base + "/api/v1/contests":
            assert headers == self.admin_headers
            self.create_payload = payload
            return 201, {
                "id": self.contest_id,
                "serverTime": "2032-05-06T07:00:00Z",
                "problems": [{"id": self.draft_problem_id, "problemId": self.source_id}],
            }
        if url == self.base + self.path + "/join":
            assert headers == self.solver_headers and payload == {}
            return 200, {"joined": True, "problems": []}
        expected_submit = self.base + self.path + "/problems/" + self.running_problem_id + "/submit"
        if url == expected_submit:
            assert headers == self.solver_headers
            self.submit_urls.append(url)
            self.submit_payloads.append(payload)
            receipt_id = self.receipt_id if len(self.submit_payloads) == 1 else self.duplicate_receipt_id
            return 202, {"id": receipt_id, "status": "queued", "verdict": None}
        raise AssertionError(f"unexpected POST {url}")

    def request_json(self, url, *, method="GET", payload=None, headers=None, timeout=20.0):
        if url == self.base + "/api/v1/auth/me":
            assert method == "GET" and headers == self.solver_headers
            return 200, {"id": "solver-id", "totalScore": 20} if self.source_reads == 0 else self.account
        if url == self.base + self.path + "/manage":
            assert method == "GET" and headers == self.admin_headers
            return 200, self.manage
        if url == self.base + self.path:
            assert method == "PUT" and headers == self.admin_headers
            self.publish_payload = payload
            return 200, {
                "id": self.contest_id,
                "state": "upcoming",
                "problems": [{"id": self.published_problem_id, "problemId": self.source_id}],
            }
        if url == self.base + "/api/v1/problems/" + self.source_id:
            assert method == "GET" and headers == self.solver_headers
            self.source_reads += 1
            if self.source_reads == 1:
                if self.leak_prestart_problem:
                    return 200, {"id": self.source_id}
                error = HTTPError(url, 404, "not found", hdrs=None, fp=None)
                raise RuntimeError("expected pre-start private-problem refusal") from error
            return 200, self.public
        raise AssertionError(f"unexpected {method} {url}")

    def wait_for_condition(self, path, predicate, *, headers, timeout=180):
        assert headers == self.solver_headers
        if path == self.path:
            self.contest_waits += 1
            value = ({
                "state": "running",
                "problems": [{"id": self.running_problem_id, "problemId": self.source_id}],
            } if self.contest_waits == 1 else {"state": "finished", "problems": []})
        elif path == self.path + "/submissions/" + self.receipt_id:
            value = {"id": self.receipt_id, "status": "completed", "verdict": "accepted"}
        elif path == self.path + "/scoreboard":
            value = {
                "pendingCount": 0,
                "rows": [{
                    "userId": "solver-id", "totalPoints": 500, "rank": 1,
                    "problems": [{"contestProblemId": self.running_problem_id, "verdict": "accepted"}],
                }],
            }
        else:
            raise AssertionError(f"unexpected wait path {path}")
        assert predicate(value), f"harness predicate rejected {value}"
        return value


def install_fake(script, fake, monkeypatch):
    monkeypatch.setattr(script, "request_json", fake.request_json)
    monkeypatch.setattr(script, "post_json", fake.post_json)
    monkeypatch.setattr(script, "wait_for_condition", fake.wait_for_condition)
    monkeypatch.setattr(script, "uuid4", lambda: REQUEST_ID)


def test_exercise_contest_publishes_from_manage_and_uses_current_problem_id(monkeypatch):
    script = load_script()
    fake = FakeContestApi(script)
    install_fake(script, fake, monkeypatch)

    result = script.exercise_contest(fake.admin_headers, fake.solver_headers, "nonce")

    assert fake.create_payload["published"] is False
    assert fake.create_payload["problems"][0]["newProblem"]["hiddenTestCases"]
    expected_start = datetime.fromisoformat(fake.manage_time.replace("Z", "+00:00")) + timedelta(seconds=10)
    assert fake.publish_payload == {
        "title": fake.manage["title"],
        "description": fake.manage["description"],
        "problems": fake.manage["problems"],
        "published": True,
        "startsAt": expected_start.isoformat(),
        "endsAt": (expected_start + timedelta(seconds=60)).isoformat(),
    }
    assert fake.publish_payload["problems"] is fake.manage["problems"]
    assert fake.draft_problem_id != fake.published_problem_id != fake.running_problem_id
    assert fake.submit_urls == [
        fake.base + fake.path + "/problems/" + fake.running_problem_id + "/submit",
        fake.base + fake.path + "/problems/" + fake.running_problem_id + "/submit",
    ]
    assert fake.submit_payloads[0] == fake.submit_payloads[1]
    assert fake.submit_payloads[0]["requestId"] == str(REQUEST_ID)
    assert fake.source_reads == 2  # pre-start refusal, then post-finalization public read
    assert result == {
        "points": 500,
        "generalScoreDelta": 17,
        "state": "finished",
        "sameReceiptOnRetry": True,
        "hiddenTestsPrivate": True,
    }


def test_exercise_contest_rejects_a_duplicate_request_with_another_receipt(monkeypatch):
    script = load_script()
    fake = FakeContestApi(script)
    fake.duplicate_receipt_id = "different-receipt"
    install_fake(script, fake, monkeypatch)

    with pytest.raises(RuntimeError, match="idempotent submission"):
        script.exercise_contest(fake.admin_headers, fake.solver_headers, "nonce")

    assert len(fake.submit_payloads) == 2
    assert fake.submit_payloads[0]["requestId"] == fake.submit_payloads[1]["requestId"]


def test_exercise_contest_rejects_pre_start_private_problem_leak(monkeypatch):
    script = load_script()
    fake = FakeContestApi(script)
    fake.leak_prestart_problem = True
    install_fake(script, fake, monkeypatch)

    with pytest.raises(RuntimeError, match="Private contest problem leaked before start"):
        script.exercise_contest(fake.admin_headers, fake.solver_headers, "nonce")

    assert not fake.submit_payloads


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda fake: fake.public.update(hiddenTestCases=[{"input": "secret", "expectedOutput": "42"}]),
         "Contest finalization/publication/general score failed"),
        (lambda fake: fake.account.update(totalScore=36),
         "Contest finalization/publication/general score failed"),
    ],
    ids=["hidden-tests-never-public", "general-score-must-increase-by-17"],
)
def test_exercise_contest_rejects_bad_final_publication_or_score(monkeypatch, mutate, message):
    script = load_script()
    fake = FakeContestApi(script)
    mutate(fake)
    install_fake(script, fake, monkeypatch)

    with pytest.raises(RuntimeError, match=message):
        script.exercise_contest(fake.admin_headers, fake.solver_headers, "nonce")
