"""Pure validation tests for the bounded BuildKit builder configuration."""

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_build_builder_under_test", ROOT / "scripts" / "verify_build_builder.py"
)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


CONTAINER_ID = "a" * 64


def config(**overrides):
    values = {"name": "builder-ci"}
    values.update(overrides)
    return builder.Config(**values)


def environment(**overrides):
    values = {"WEBCOMPILER_BUILD_BUILDER": "builder-ci"}
    values.update(overrides)
    return values


def test_config_accepts_defaults():
    result = config()

    assert result.name == "builder-ci"
    assert result.memory_mb == 2048
    assert result.cpu_millis == 1000
    assert result.pids == 512
    assert result.container_id == ""


def test_config_accepts_explicit_resource_budget_and_container_identity():
    result = config(memory_mb=256, cpu_millis=50, pids=64, container_id=CONTAINER_ID)

    assert (result.memory_mb, result.cpu_millis, result.pids, result.container_id) == (
        256,
        50,
        64,
        CONTAINER_ID,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("memory_mb", 256, id="memory-min"),
        pytest.param("memory_mb", 32768, id="memory-max"),
        pytest.param("cpu_millis", 50, id="cpu-min"),
        pytest.param("cpu_millis", 8000, id="cpu-max"),
        pytest.param("pids", 64, id="pids-min"),
        pytest.param("pids", 4096, id="pids-max"),
    ],
)
def test_config_accepts_resource_budget_boundaries(field, value):
    assert getattr(config(**{field: value}), field) == value


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("", id="empty"),
        pytest.param("default", id="default-builder"),
        pytest.param("Builder-ci", id="uppercase"),
        pytest.param("builder/ci", id="slash"),
        pytest.param("builder ci", id="spaces"),
        pytest.param("a" * 81, id="overlong"),
        pytest.param(None, id="none"),
        pytest.param(123, id="integer"),
    ],
)
def test_config_rejects_invalid_builder_names(name):
    with pytest.raises(builder.BuilderError):
        config(name=name)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("memory_mb", 255, id="memory-below-min"),
        pytest.param("memory_mb", 32769, id="memory-above-max"),
        pytest.param("cpu_millis", 49, id="cpu-below-min"),
        pytest.param("cpu_millis", 8001, id="cpu-above-max"),
        pytest.param("pids", 63, id="pids-below-min"),
        pytest.param("pids", 4097, id="pids-above-max"),
        pytest.param("memory_mb", True, id="memory-bool"),
        pytest.param("cpu_millis", False, id="cpu-bool"),
        pytest.param("pids", True, id="pids-bool"),
        pytest.param("memory_mb", 2048.0, id="memory-float"),
        pytest.param("cpu_millis", "1000", id="cpu-string"),
        pytest.param("pids", None, id="pids-none"),
    ],
)
def test_config_rejects_invalid_resource_budgets(field, value):
    with pytest.raises(builder.BuilderError):
        config(**{field: value})


@pytest.mark.parametrize(
    "container_id",
    [
        pytest.param("a" * 63, id="short"),
        pytest.param("a" * 65, id="long"),
        pytest.param("A" * 64, id="uppercase"),
        pytest.param("a" * 32 + "-" * 32, id="punctuation"),
        pytest.param(None, id="none"),
        pytest.param(True, id="bool"),
        pytest.param(b"a" * 64, id="bytes"),
    ],
)
def test_config_rejects_invalid_bound_container_identity(container_id):
    with pytest.raises(builder.BuilderError):
        config(container_id=container_id)


def test_from_environment_uses_defaults_when_only_builder_name_is_supplied():
    result = builder.Config.from_environment(environment())

    assert (result.name, result.memory_mb, result.cpu_millis, result.pids, result.container_id) == (
        "builder-ci",
        2048,
        1000,
        512,
        "",
    )


def test_from_environment_accepts_explicit_overrides():
    result = builder.Config.from_environment(
        environment(
            WEBCOMPILER_BUILD_BUILDER="builder-explicit",
            WEBCOMPILER_BUILD_MEMORY_MB="256",
            WEBCOMPILER_BUILD_CPU_MILLIS="50",
            WEBCOMPILER_BUILD_PIDS="64",
            WEBCOMPILER_BUILD_CONTAINER_ID=CONTAINER_ID,
        )
    )

    assert result == builder.Config("builder-explicit", 256, 50, 64, CONTAINER_ID)


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="missing-builder"),
        pytest.param({"WEBCOMPILER_BUILD_BUILDER": ""}, id="empty-builder"),
    ],
)
def test_from_environment_requires_a_builder_name(env):
    with pytest.raises(builder.BuilderError):
        builder.Config.from_environment(env)


@pytest.mark.parametrize(
    "key",
    [
        "WEBCOMPILER_BUILD_MEMORY_MB",
        "WEBCOMPILER_BUILD_CPU_MILLIS",
        "WEBCOMPILER_BUILD_PIDS",
    ],
)
def test_from_environment_rejects_invalid_integer_budget(key):
    with pytest.raises(builder.BuilderError):
        builder.Config.from_environment(environment(**{key: "not-an-integer"}))


def test_from_environment_rejects_invalid_container_identity():
    with pytest.raises(builder.BuilderError):
        builder.Config.from_environment(
            environment(WEBCOMPILER_BUILD_CONTAINER_ID="not-a-container-identity")
        )
