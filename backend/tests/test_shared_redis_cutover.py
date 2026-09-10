import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SCRIPT = SCRIPTS / "verify_shared_redis_cutover.py"


def load_script():
    # The cutover guard imports ensure_shared_redis from its sibling script.
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "verify_shared_redis_cutover_under_test", SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


cutover = load_script()


ENDPOINT = "redis://webcompiler-redis:6379/0"
PREFIX = "webcompiler-shared"


def runtime_container(project, service, endpoint=ENDPOINT, prefix=PREFIX):
    return {
        "Id": f"{project}-{service}-id",
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
            },
            "Env": [f"REDIS_URL={endpoint}", f"REDIS_KEY_PREFIX={prefix}"],
        },
    }


class ReadOnlyDocker:
    """Fake only the inspect/list calls allowed by the cutover guard."""

    def __init__(self, projects):
        self.projects = projects
        self.calls = []

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        assert args[0] == "container"
        if args[1] == "ls":
            label = next(
                argument
                for argument in args
                if argument.startswith("label=com.docker.compose.project=")
            )
            project = label.split("=", 2)[-1]
            return " ".join(container["Id"] for container in self.projects.get(project, []))
        if args[1] == "inspect":
            by_id = {
                container["Id"]: container
                for containers in self.projects.values()
                for container in containers
            }
            return json.dumps([by_id[container_id] for container_id in args[2:]])
        raise AssertionError(f"unexpected fake Docker command: {args!r}")


def assert_read_only(fake):
    assert fake.calls
    assert all(
        args[:2] in (["container", "ls"], ["container", "inspect"])
        for args in fake.calls
    )


def all_runtime_projects(endpoint=ENDPOINT, prefix=PREFIX):
    return {
        project: [
            runtime_container(project, "backend", endpoint, prefix),
            runtime_container(project, "worker", endpoint, prefix),
        ]
        for project in ("webcompiler", "webcompiler-blue", "webcompiler-green")
    }


@pytest.mark.parametrize("active_color", ["blue", "green"])
def test_blue_green_and_legacy_runtimes_share_endpoint_and_prefix(active_color):
    fake = ReadOnlyDocker(all_runtime_projects())

    assert (
        cutover.verify(
            active_color,
            "webcompiler",
            ENDPOINT,
            PREFIX,
            call=fake,
        )
        is None
    )

    assert_read_only(fake)
    inspected_projects = {
        next(
            argument.split("=", 2)[-1]
            for argument in args
            if argument.startswith("label=com.docker.compose.project=")
        )
        for args in fake.calls
        if args[1] == "ls"
    }
    assert inspected_projects == {
        "webcompiler",
        "webcompiler-blue",
        "webcompiler-green",
    }


@pytest.mark.parametrize('endpoint,prefix', [
    ('redis://wrong-host:6379/0', PREFIX), (ENDPOINT, 'wrong-namespace'), ('', PREFIX),
])
def test_inactive_color_endpoint_mismatch_is_refused_read_only(endpoint, prefix):
    projects = all_runtime_projects()
    projects["webcompiler-green"][1]["Config"]["Env"] = [
        f"REDIS_URL={endpoint}",
        f"REDIS_KEY_PREFIX={prefix}",
    ]
    fake = ReadOnlyDocker(projects)

    with pytest.raises(
        cutover.SharedRedisError,
        match="different Redis endpoint or namespace",
    ):
        cutover.verify("blue", "webcompiler", ENDPOINT, PREFIX, call=fake)

    assert_read_only(fake)


def test_empty_initial_deployment_is_allowed_but_active_marker_requires_runtime():
    empty = ReadOnlyDocker({})
    assert cutover.verify("", "webcompiler", ENDPOINT, PREFIX, call=empty) is None
    assert_read_only(empty)
    assert not any(args[1] == "inspect" for args in empty.calls)

    marked_active = ReadOnlyDocker({})
    with pytest.raises(
        cutover.SharedRedisError,
        match="Active color runtime could not be verified",
    ):
        cutover.verify("blue", "webcompiler", ENDPOINT, PREFIX, call=marked_active)
    assert_read_only(marked_active)
    assert not any(args[1] == "inspect" for args in marked_active.calls)


@pytest.mark.parametrize(
    ("active_color", "legacy_project"),
    [
        ("purple", "webcompiler"),
        ("BLUE", "webcompiler"),
        ("blue", "webcompiler/project"),
        ("blue", "webcompiler.project"),
    ],
)
def test_invalid_active_color_or_legacy_project_is_rejected(active_color, legacy_project):
    with pytest.raises(ValueError, match="Invalid (active color|legacy project)"):
        cutover.verify(active_color, legacy_project, ENDPOINT, PREFIX, call=ReadOnlyDocker({}))


@pytest.mark.parametrize("endpoint,prefix", [("", PREFIX), (ENDPOINT, "")])
def test_missing_shared_redis_setting_is_rejected(endpoint, prefix):
    with pytest.raises(ValueError, match="Shared Redis settings are required"):
        cutover.verify("", "webcompiler", endpoint, prefix, call=ReadOnlyDocker({}))


@pytest.mark.parametrize("failure", ["shared-error", "timeout"])
def test_main_redacts_shared_redis_failures_and_docker_timeout(monkeypatch, capsys, failure):
    secret = "sensitive-docker-output=redis-password-do-not-print"
    monkeypatch.setenv("WEBCOMPILER_DEPLOY_ACTIVE_COLOR", "blue")
    monkeypatch.setenv("WEBCOMPILER_LEGACY_PROJECT_NAME", "webcompiler")
    monkeypatch.setenv("WEBCOMPILER_REDIS_URL", ENDPOINT)
    monkeypatch.setenv("WEBCOMPILER_REDIS_KEY_PREFIX", PREFIX)

    if failure == "shared-error":
        def fail(*args, **kwargs):
            raise cutover.SharedRedisError(secret)
    else:
        def fail(*args, **kwargs):
            raise subprocess.TimeoutExpired(["docker", secret], timeout=20)

    monkeypatch.setattr(cutover, "verify", fail)

    assert cutover.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Shared Redis cutover refused; verify the current runtime and complete "
        "an offline transition before deployment\n"
    )
    assert secret not in captured.err
