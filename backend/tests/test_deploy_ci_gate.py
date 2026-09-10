import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_deploy_ci.py"
SHA = "a" * 40
REPOSITORY = "octo-org/octo-repo"
TOKEN = "test-token-must-never-appear-in-output"
RUN_ID = "123"


class FakeResponse:
    def __init__(self, payload=None, status=200, raw_body=None, headers=None):
        self._payload = payload
        self._status = status
        self._raw_body = raw_body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def getcode(self):
        return self._status

    def read(self, size=-1):
        body = self._raw_body
        if body is None:
            body = json.dumps(self._payload).encode("utf-8")
        return body if size < 0 else body[:size]


def load_script():
    spec = importlib.util.spec_from_file_location("verify_deploy_ci_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def valid_run():
    return {
        "id": int(RUN_ID),
        "status": "completed",
        "conclusion": "success",
        "head_sha": SHA,
        "head_branch": "main",
        "event": "push",
        "path": ".github/workflows/ci.yml@main",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    }


def set_deploy_environment(monkeypatch, *, run_id=RUN_ID):
    monkeypatch.setenv("DEPLOY_SHA", SHA)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    if run_id is None:
        monkeypatch.delenv("DEPLOY_CI_RUN_ID", raising=False)
    else:
        monkeypatch.setenv("DEPLOY_CI_RUN_ID", run_id)


def install_responses(monkeypatch, script, responses):
    calls = []
    response_iterator = iter(responses)

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        response = next(response_iterator)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, FakeResponse):
            return response
        return FakeResponse(response)

    monkeypatch.setattr(script, "urlopen", fake_urlopen)
    return calls


def test_run_id_success_validates_exact_ci_run(monkeypatch, capsys):
    script = load_script()
    set_deploy_environment(monkeypatch)
    calls = install_responses(monkeypatch, script, [valid_run()])

    assert script.main() == 0
    captured = capsys.readouterr()
    assert captured.out == f"{script.SUCCESS_MESSAGE}\n"
    assert captured.err == ""
    assert len(calls) == 1
    request, timeout = calls[0]
    assert timeout == 10
    assert request.full_url == f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert request.get_header("Accept") == "application/vnd.github+json"


def test_bare_workflow_path_from_actual_repository_run_is_accepted(monkeypatch):
    # Read-only GitHub API observation: run34338284742 returns ci.yml with no
    # @ suffix. That is valid, unlike another filename or an empty @ suffix.
    script = load_script()
    set_deploy_environment(monkeypatch)
    run = valid_run()
    run['path'] = '.github/workflows/ci.yml'
    install_responses(monkeypatch,script,[run])
    assert script.main() == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda run: run.update(conclusion="failure"),
        lambda run: run.update(head_sha="b" * 40),
        lambda run: run["head_repository"].update(full_name="fork-owner/octo-repo"),
        lambda run: run["repository"].update(full_name="other-owner/octo-repo"),
        lambda run: run.update(path=".github/workflows/release.yml@main"),
        lambda run: run.update(path=".github/workflows/ci.yml@"),
        lambda run: run.update(head_branch="release"),
        lambda run: run.update(event="pull_request"),
    ],
    ids=[
        "failed",
        "wrong_sha",
        "fork",
        "wrong_repository",
        "wrong_workflow",
        "empty_ref_workflow_path",
        "wrong_branch",
        "wrong_event",
    ],
)
def test_run_id_rejects_untrusted_ci_run(monkeypatch, capsys, mutate):
    script = load_script()
    set_deploy_environment(monkeypatch)
    run = valid_run()
    mutate(run)
    install_responses(monkeypatch, script, [run])

    assert script.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{script.FAILURE_MESSAGE}\n"
    assert TOKEN not in captured.err


def test_manual_deploy_finds_matching_ci_workflow_run(monkeypatch, capsys):
    script = load_script()
    set_deploy_environment(monkeypatch, run_id=None)
    calls = install_responses(monkeypatch, script, [{"workflow_runs": [valid_run()]}])

    assert script.main() == 0
    assert capsys.readouterr().err == ""
    assert len(calls) == 1
    request, timeout = calls[0]
    parsed = urlsplit(request.full_url)
    assert parsed.path == f"/repos/{REPOSITORY}/actions/workflows/ci.yml/runs"
    assert parse_qs(parsed.query) == {
        "branch": ["main"],
        "event": ["push"],
        "head_sha": [SHA],
        "status": ["success"],
        "per_page": ["100"],
        "page": ["1"],
    }
    assert timeout == 10


def test_manual_deploy_uses_bounded_pagination(monkeypatch, capsys):
    script = load_script()
    set_deploy_environment(monkeypatch, run_id=None)
    rejected_run = valid_run()
    rejected_run["head_branch"] = "not-main"
    full_page = [rejected_run] * script.PER_PAGE
    config = script.load_config()
    responses = []
    for page in range(1, script.MAX_PAGES + 1):
        headers = {}
        if page < script.MAX_PAGES:
            next_url = script.workflow_runs_api_url(config, page + 1)
            headers = {"Link": f"<{next_url}>; rel=\"next\""}
        responses.append(FakeResponse({"workflow_runs": full_page}, headers=headers))
    calls = install_responses(
        monkeypatch,
        script,
        responses,
    )

    assert script.main() == 1
    assert capsys.readouterr().err == f"{script.FAILURE_MESSAGE}\n"
    assert len(calls) == script.MAX_PAGES
    assert [parse_qs(urlsplit(request.full_url).query)["page"] for request, _ in calls] == [
        [str(page)] for page in range(1, script.MAX_PAGES + 1)
    ]


def test_manual_deploy_follows_github_next_link_even_after_a_short_page(monkeypatch, capsys):
    script = load_script()
    set_deploy_environment(monkeypatch, run_id=None)
    rejected_run = valid_run()
    rejected_run["head_branch"] = "not-main"
    next_url = script.workflow_runs_api_url(script.load_config(), 2)
    calls = install_responses(
        monkeypatch,
        script,
        [
            FakeResponse({"workflow_runs": [rejected_run]}, headers={"Link": f"<{next_url}>; rel=\"next\""}),
            FakeResponse({"workflow_runs": [valid_run()]}),
        ],
    )

    assert script.main() == 0
    assert capsys.readouterr().err == ""
    assert len(calls) == 2


def test_manual_deploy_rejects_malformed_run_id(monkeypatch, capsys):
    script = load_script()
    set_deploy_environment(monkeypatch, run_id=None)
    malformed_run = valid_run()
    malformed_run["id"] = True
    install_responses(monkeypatch, script, [{"workflow_runs": [malformed_run]}])

    assert script.main() == 1
    assert capsys.readouterr().err == f"{script.FAILURE_MESSAGE}\n"


def test_manual_deploy_rejects_cross_origin_pagination_link(monkeypatch, capsys):
    script = load_script()
    set_deploy_environment(monkeypatch, run_id=None)
    rejected_run = valid_run()
    rejected_run["head_branch"] = "not-main"
    response = FakeResponse(
        {"workflow_runs": [rejected_run]},
        headers={"Link": "<https://example.invalid/next>; rel=\"next\""},
    )
    calls = install_responses(monkeypatch, script, [response])

    assert script.main() == 1
    assert capsys.readouterr().err == f"{script.FAILURE_MESSAGE}\n"
    assert len(calls) == 1


def test_api_error_is_generic_and_never_leaks_token_or_response_body(monkeypatch, capsys):
    script = load_script()
    set_deploy_environment(monkeypatch)
    api_body = b'{"message":"private API error detail"}'
    error = HTTPError("https://api.github.com/example", 403, "Forbidden", {}, io.BytesIO(api_body))
    install_responses(monkeypatch, script, [error])

    assert script.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{script.FAILURE_MESSAGE}\n"
    assert TOKEN not in captured.err
    assert "private API error detail" not in captured.err


def test_oversized_api_response_fails_closed(monkeypatch, capsys):
    script = load_script()
    set_deploy_environment(monkeypatch)
    oversized_response = FakeResponse(raw_body=b"x" * (script.MAX_RESPONSE_BYTES + 1))
    install_responses(monkeypatch, script, [oversized_response])

    assert script.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{script.FAILURE_MESSAGE}\n"


def test_redirect_handler_rejects_cross_origin_redirect_before_forwarding_token():
    script = load_script()
    request = script.Request(
        "https://api.github.com/repos/octo-org/octo-repo/actions/runs/123",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    with pytest.raises(script.VerificationError):
        script.ApiOnlyRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://example.invalid/redirect-target",
        )


@pytest.mark.parametrize("missing_name", ["DEPLOY_SHA", "GITHUB_REPOSITORY", "GITHUB_TOKEN"])
def test_missing_required_configuration_fails_before_network(monkeypatch, capsys, missing_name):
    script = load_script()
    set_deploy_environment(monkeypatch)
    monkeypatch.delenv(missing_name)

    def network_must_not_run(*_args, **_kwargs):
        raise AssertionError("network must not run for invalid configuration")

    monkeypatch.setattr(script, "urlopen", network_must_not_run)

    assert script.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{script.FAILURE_MESSAGE}\n"
