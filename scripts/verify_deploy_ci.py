#!/usr/bin/env python3
"""Fail closed unless the deployment commit passed this repository's CI."""

from __future__ import annotations

import hmac
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"
API_HOST = "api.github.com"
CI_WORKFLOW_FILE = "ci.yml"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
MAIN_BRANCH = "main"
REQUEST_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
PER_PAGE = 100
MAX_PAGES = 10
FAILURE_MESSAGE = "Deployment CI verification failed."
SUCCESS_MESSAGE = "Deployment CI verification passed."

SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
RUN_ID_PATTERN = re.compile(r"^[1-9][0-9]*$")
LINK_URL_PATTERN = re.compile(r"^\s*<([^>]+)>\s*(.*)$")
LINK_REL_PATTERN = re.compile(r'(?:^|;)\s*rel\s*=\s*(?:"([^"]+)"|([^;\s,]+))', re.IGNORECASE)


class VerificationError(Exception):
    """Raised for any condition that must block deployment."""


class DeployConfig:
    def __init__(self, deploy_sha: str, repository: str, token: str, run_id: str | None) -> None:
        self.deploy_sha = deploy_sha
        self.repository = repository
        self.token = token
        self.run_id = run_id


def _is_api_origin(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == API_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


class ApiOnlyRedirectHandler(HTTPRedirectHandler):
    """Prevent a redirect from forwarding the bearer token off api.github.com."""

    def redirect_request(self, request, file_pointer, status_code, message, headers, new_url):
        redirected_url = urljoin(request.full_url, new_url)
        if not _is_api_origin(redirected_url):
            raise VerificationError
        return super().redirect_request(
            request,
            file_pointer,
            status_code,
            message,
            headers,
            redirected_url,
        )


API_OPENER = build_opener(ApiOnlyRedirectHandler())


def urlopen(request: Request, timeout: float):
    """Open GitHub API requests through the redirect-restricted urllib opener."""
    return API_OPENER.open(request, timeout=timeout)


def load_config(environ: Mapping[str, str] | None = None) -> DeployConfig:
    """Load the small, intentionally fixed set of deployment-gate inputs."""
    env = os.environ if environ is None else environ
    deploy_sha = env.get("DEPLOY_SHA")
    repository = env.get("GITHUB_REPOSITORY")
    token = env.get("GITHUB_TOKEN")
    run_id = env.get("DEPLOY_CI_RUN_ID")

    if not isinstance(deploy_sha, str) or SHA_PATTERN.fullmatch(deploy_sha) is None:
        raise VerificationError
    if not isinstance(repository, str) or REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise VerificationError
    if not isinstance(token, str) or not token.strip():
        raise VerificationError

    if run_id is None or run_id == "":
        verified_run_id = None
    elif isinstance(run_id, str) and RUN_ID_PATTERN.fullmatch(run_id) is not None:
        verified_run_id = run_id
    else:
        raise VerificationError

    return DeployConfig(deploy_sha.lower(), repository, token, verified_run_id)


def repository_api_url(repository: str) -> str:
    owner, name = repository.split("/", 1)
    return f"{API_ROOT}/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def run_api_url(config: DeployConfig) -> str:
    if config.run_id is None:
        raise VerificationError
    return f"{repository_api_url(config.repository)}/actions/runs/{config.run_id}"


def workflow_runs_api_url(config: DeployConfig, page: int) -> str:
    if not 1 <= page <= MAX_PAGES:
        raise VerificationError
    parameters = (
        ("branch", MAIN_BRANCH),
        ("event", "push"),
        ("head_sha", config.deploy_sha),
        ("status", "success"),
        ("per_page", str(PER_PAGE)),
        ("page", str(page)),
    )
    query = urlencode(parameters)
    workflow = quote(CI_WORKFLOW_FILE, safe="")
    return f"{repository_api_url(config.repository)}/actions/workflows/{workflow}/runs?{query}"


def github_get_json(url: str, token: str) -> tuple[dict[str, Any], str | None]:
    """Make a read-only GitHub API request without exposing transport details."""
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "deploy-ci-verifier",
            "X-GitHub-Api-Version": API_VERSION,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.getcode() != 200:
                raise VerificationError
            raw_body = response.read(MAX_RESPONSE_BYTES + 1)
            response_headers = getattr(response, "headers", None)
    except (HTTPError, URLError, OSError, TimeoutError):
        raise VerificationError from None

    if not isinstance(raw_body, bytes) or len(raw_body) > MAX_RESPONSE_BYTES:
        raise VerificationError
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise VerificationError from None
    if not isinstance(payload, dict):
        raise VerificationError
    if response_headers is None:
        return payload, None
    get_header = getattr(response_headers, "get", None)
    if not callable(get_header):
        raise VerificationError
    link_header = get_header("Link")
    if link_header is not None and not isinstance(link_header, str):
        raise VerificationError
    return payload, link_header


def _matches_expected_repository(value: object, expected_repository: str) -> bool:
    return isinstance(value, str) and value.casefold() == expected_repository.casefold()


def _matches_ci_workflow_path(value: object) -> bool:
    if not isinstance(value, str):
        return False
    # This repository's real run API returns the bare path; GitHub's examples
    # also use ref-qualified paths. Accept only these two exact-path forms.
    return value == CI_WORKFLOW_PATH or (
        value.startswith(f"{CI_WORKFLOW_PATH}@") and len(value) > len(CI_WORKFLOW_PATH) + 1
    )


def _repository_full_name(run: Mapping[str, Any], field: str) -> object:
    repository = run.get(field)
    if not isinstance(repository, dict):
        return None
    return repository.get("full_name")


def trusted_ci_run(run: object, config: DeployConfig, expected_run_id: str | None = None) -> bool:
    """Return whether one workflow-run object is a deployable CI result."""
    if not isinstance(run, dict):
        return False

    received_run_id = run.get("id")
    if (
        isinstance(received_run_id, bool)
        or not isinstance(received_run_id, int)
        or received_run_id < 1
    ):
        return False
    if expected_run_id is not None:
        if str(received_run_id) != expected_run_id:
            return False

    head_sha = run.get("head_sha")
    if not isinstance(head_sha, str) or SHA_PATTERN.fullmatch(head_sha) is None:
        return False

    return (
        run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and hmac.compare_digest(head_sha.lower(), config.deploy_sha)
        and run.get("head_branch") == MAIN_BRANCH
        # ci.yml currently only runs on push; manual deploys must find that CI result.
        and run.get("event") == "push"
        and _matches_ci_workflow_path(run.get("path"))
        and _matches_expected_repository(_repository_full_name(run, "repository"), config.repository)
        and _matches_expected_repository(_repository_full_name(run, "head_repository"), config.repository)
    )


def next_workflow_runs_url(
    link_header: str | None,
    config: DeployConfig,
    current_url: str,
    current_page: int,
) -> str | None:
    """Extract and strictly validate GitHub's rel=next pagination URL."""
    if link_header is None:
        return None

    next_targets = []
    for link in link_header.split(","):
        url_match = LINK_URL_PATTERN.match(link)
        if url_match is None:
            raise VerificationError
        rel_match = LINK_REL_PATTERN.search(url_match.group(2))
        if rel_match is None:
            continue
        rel_values = rel_match.group(1) or rel_match.group(2)
        if "next" in rel_values.casefold().split():
            next_targets.append(url_match.group(1))

    if not next_targets:
        return None
    if len(next_targets) != 1:
        raise VerificationError

    next_url = urljoin(current_url, next_targets[0])
    if not _is_api_origin(next_url):
        raise VerificationError

    parsed_next = urlsplit(next_url)
    expected_path = urlsplit(workflow_runs_api_url(config, 1)).path
    expected_query = {
        "branch": [MAIN_BRANCH],
        "event": ["push"],
        "head_sha": [config.deploy_sha],
        "status": ["success"],
        "per_page": [str(PER_PAGE)],
    }
    query = parse_qs(parsed_next.query, keep_blank_values=True)
    page_values = query.pop("page", None)
    if parsed_next.fragment or parsed_next.path != expected_path or query != expected_query:
        raise VerificationError
    if page_values is None or len(page_values) != 1 or RUN_ID_PATTERN.fullmatch(page_values[0]) is None:
        raise VerificationError
    next_page = int(page_values[0])
    if next_page != current_page + 1 or next_page > MAX_PAGES:
        raise VerificationError
    return next_url


def verify(config: DeployConfig) -> None:
    """Verify a supplied CI run or locate a matching CI run for manual deployment."""
    if config.run_id is not None:
        run, _ = github_get_json(run_api_url(config), config.token)
        if not trusted_ci_run(run, config, expected_run_id=config.run_id):
            raise VerificationError
        return

    page = 1
    page_url = workflow_runs_api_url(config, page)
    for _ in range(MAX_PAGES):
        response, link_header = github_get_json(page_url, config.token)
        runs = response.get("workflow_runs")
        if not isinstance(runs, list) or len(runs) > PER_PAGE:
            raise VerificationError
        if any(not isinstance(run, dict) for run in runs):
            raise VerificationError
        if any(trusted_ci_run(run, config) for run in runs):
            return
        next_url = next_workflow_runs_url(link_header, config, page_url, page)
        if next_url is None:
            break
        page += 1
        page_url = next_url

    raise VerificationError


def main() -> int:
    try:
        verify(load_config())
    except Exception:  # Fail closed and do not print token-bearing request or response details.
        print(FAILURE_MESSAGE, file=sys.stderr)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
