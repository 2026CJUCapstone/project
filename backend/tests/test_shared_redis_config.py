import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ensure_shared_redis.py"


def load_script():
    spec = importlib.util.spec_from_file_location("ensure_shared_redis_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses inspects sys.modules while processing the class annotations.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ensure_shared_redis = load_script()


def deployment_root(tmp_path):
    return str(tmp_path / "deployment")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "redis/name"),
        ("volume", "redis volume"),
        ("network", "-redis-network"),
        ("name", "r" * 101),
    ],
)
def test_config_rejects_invalid_docker_resource_names(tmp_path, field, value):
    with pytest.raises(ValueError, match="Invalid Docker resource name"):
        ensure_shared_redis.Config(root=deployment_root(tmp_path), **{field: value})


@pytest.mark.parametrize("image", ["", "-redis:7-alpine", "redis 7-alpine"])
def test_config_rejects_invalid_preinstalled_image_options(tmp_path, image):
    with pytest.raises(ValueError, match="Invalid preinstalled Redis image"):
        ensure_shared_redis.Config(root=deployment_root(tmp_path), image=image)


@pytest.mark.parametrize(
    "root",
    [
        "relative/deployment",
        Path.home(),
        Path(Path.home().anchor),
    ],
)
def test_config_requires_an_explicit_deployment_root(root):
    with pytest.raises(ValueError, match="An explicit deployment directory is required"):
        ensure_shared_redis.Config(root=root)


@pytest.mark.parametrize(
    "options",
    [
        {"memory_mb": 63},
        {"memory_mb": 2049},
        {"maxmemory_mb": 15},
        {"memory_mb": 256, "maxmemory_mb": 256},
        {"memory_mb": 320, "maxmemory_mb": 320},
    ],
)
def test_config_rejects_invalid_redis_memory_budgets(tmp_path, options):
    with pytest.raises(ValueError, match="Invalid Redis memory budget"):
        ensure_shared_redis.Config(root=deployment_root(tmp_path), **options)


@pytest.mark.parametrize("cpu_millis", [49, 2001])
def test_config_rejects_invalid_redis_cpu_budgets(tmp_path, cpu_millis):
    with pytest.raises(ValueError, match="Invalid Redis CPU budget"):
        ensure_shared_redis.Config(root=deployment_root(tmp_path), cpu_millis=cpu_millis)


def test_labels_are_independent_of_deploy_color(tmp_path):
    root = deployment_root(tmp_path)
    first_color = ensure_shared_redis.Config(
        root=root,
        name="webcompiler-redis-blue",
        volume="webcompiler-redis-blue-data",
    )
    second_color = ensure_shared_redis.Config(
        root=root,
        name="webcompiler-redis-green",
        volume="webcompiler-redis-green-data",
    )

    expected_owner = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()
    assert first_color.labels == second_color.labels == {
        "io.webcompiler.shared.role": "redis",
        "io.webcompiler.owner": expected_owner,
    }


def test_command_enables_persistence_noeviction_and_private_network_binding(tmp_path):
    config = ensure_shared_redis.Config(root=deployment_root(tmp_path))

    assert config.command == [
        "redis-server",
        "--bind",
        "0.0.0.0",
        "--protected-mode",
        "no",
        "--appendonly",
        "yes",
        "--appendfsync",
        "everysec",
        "--save",
        "60",
        "1000",
        "--maxmemory",
        "256mb",
        "--maxmemory-policy",
        "noeviction",
    ]


@pytest.mark.parametrize("failure_source", ["config", "ensure"])
def test_main_reports_generic_failures_without_sensitive_exception_text(
    monkeypatch, capsys, tmp_path, failure_source
):
    secret = "private docker stderr: redis-password=do-not-print"
    monkeypatch.setenv("PROJECT_ROOT", deployment_root(tmp_path))

    if failure_source == "config":
        def raising_config(*args, **kwargs):
            raise ValueError(secret)

        monkeypatch.setattr(ensure_shared_redis, "Config", raising_config)
    else:
        def raising_ensure(*args, **kwargs):
            raise ensure_shared_redis.SharedRedisError(secret)

        monkeypatch.setattr(ensure_shared_redis, "ensure", raising_ensure)

    assert ensure_shared_redis.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Shared Redis configuration/readiness check failed; "
        "existing data was not reset\n"
    )
    assert secret not in captured.err
