"""Project-prefix configuration and shared-Redis cutover scope."""

import os

import pytest

from tests.test_edge_deploy_config import Config
from tests.test_shared_redis_cutover import (
    ENDPOINT,
    PREFIX,
    ReadOnlyDocker,
    cutover,
    runtime_container,
)


@pytest.fixture(autouse=True)
def clean_deployment_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("WEBCOMPILER_") or name in {"PROJECT_ROOT", "SANDBOX_POOL_ID"}:
            monkeypatch.delenv(name, raising=False)


def deployment_root(tmp_path):
    root = tmp_path / "project"
    (root / ".deploy").mkdir(parents=True)
    return root


def test_from_environment_defaults_project_prefix_to_webcompiler(tmp_path, monkeypatch):
    root = deployment_root(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(root))

    config = Config.from_environment()

    assert config.project_prefix == "webcompiler"


def test_from_environment_propagates_custom_project_prefix(tmp_path, monkeypatch):
    root = deployment_root(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    monkeypatch.setenv("WEBCOMPILER_PROJECT_PREFIX", "tenant_stack")
    for index,name in enumerate(('EDGE_BACKEND_PORT','EDGE_FRONTEND_PORT','BLUE_BACKEND_PORT',
            'BLUE_FRONTEND_PORT','GREEN_BACKEND_PORT','GREEN_FRONTEND_PORT'),31000):
        monkeypatch.setenv('WEBCOMPILER_'+name,str(index))

    config = Config.from_environment()

    assert config.project_prefix == "tenant_stack"
    assert config.edge_name=='tenant_stack-edge-v2'
    assert config.shared_network=='tenant_stack-shared'
    assert config.sandbox_pool=='tenant_stack'
    assert all(name.startswith('tenant_stack-') for name in config.legacy_names)


def test_custom_prefix_cannot_fall_back_to_production_ports(tmp_path,monkeypatch):
    monkeypatch.setenv('PROJECT_ROOT',str(deployment_root(tmp_path)))
    monkeypatch.setenv('WEBCOMPILER_PROJECT_PREFIX','audit-isolated')
    with pytest.raises(ValueError,match='six explicit'): Config.from_environment()


@pytest.mark.parametrize(
    "project_prefix",
    [
        pytest.param("tenant stack", id="spaces"),
        pytest.param("tenant/stack", id="slash"),
        pytest.param("Tenant-stack", id="uppercase"),
        pytest.param("a" * 81, id="overlong"),
    ],
)
def test_from_environment_rejects_unsafe_project_prefix(tmp_path, monkeypatch, project_prefix):
    root = deployment_root(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    monkeypatch.setenv("WEBCOMPILER_PROJECT_PREFIX", project_prefix)

    with pytest.raises(ValueError, match="resource names"):
        Config.from_environment()


def runtime_projects(*projects):
    return {
        project: [
            runtime_container(project, "backend"),
            runtime_container(project, "worker"),
        ]
        for project in projects
    }


def queried_projects(fake):
    return {
        next(
            argument.split("=", 2)[-1]
            for argument in args
            if argument.startswith("label=com.docker.compose.project=")
        )
        for args in fake.calls
        if args[1] == "ls"
    }


def test_cutover_queries_custom_color_projects_and_explicit_legacy_only():
    projects = runtime_projects(
        "tenant-blue",
        "tenant-green",
        "legacy-stack",
        "webcompiler-blue",
        "webcompiler-green",
    )
    for project in ("webcompiler-blue", "webcompiler-green"):
        for container in projects[project]:
            container["Config"]["Env"] = [
                "REDIS_URL=redis://wrong-default:6379/0",
                f"REDIS_KEY_PREFIX={PREFIX}",
            ]
    fake = ReadOnlyDocker(projects)

    assert (
        cutover.verify(
            "green",
            "legacy-stack",
            ENDPOINT,
            PREFIX,
            project_prefix="tenant",
            call=fake,
        )
        is None
    )

    assert queried_projects(fake) == {"tenant-blue", "tenant-green", "legacy-stack"}


def test_cutover_requires_custom_active_color_runtime():
    fake = ReadOnlyDocker(runtime_projects("tenant-blue", "legacy-stack"))

    with pytest.raises(cutover.SharedRedisError, match="Active color runtime"):
        cutover.verify(
            "green",
            "legacy-stack",
            ENDPOINT,
            PREFIX,
            project_prefix="tenant",
            call=fake,
        )


def test_cutover_rejects_other_endpoint_in_custom_color_scope():
    projects = runtime_projects("tenant-blue", "tenant-green", "legacy-stack")
    projects["tenant-green"][1]["Config"]["Env"] = [
        "REDIS_URL=redis://wrong-runtime:6379/0",
        f"REDIS_KEY_PREFIX={PREFIX}",
    ]
    fake = ReadOnlyDocker(projects)

    with pytest.raises(cutover.SharedRedisError, match="different Redis endpoint or namespace"):
        cutover.verify(
            "blue",
            "legacy-stack",
            ENDPOINT,
            PREFIX,
            project_prefix="tenant",
            call=fake,
        )
