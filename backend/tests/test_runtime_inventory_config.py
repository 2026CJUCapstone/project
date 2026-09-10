"""Sandbox-pool configuration for the runtime inventory adapter."""

import os
from pathlib import Path

import pytest

from tests.test_edge_deploy import adapter, edge


@pytest.fixture(autouse=True)
def clean_edge_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("WEBCOMPILER_") or name in {
            "PROJECT_ROOT",
            "SANDBOX_POOL_ID",
        }:
            monkeypatch.delenv(name, raising=False)


def make_config(root, **overrides):
    values = {
        "root": root,
        "layout": edge.Layout(18000, 15173),
        "blue": (18001, 15174),
        "green": (18002, 15175),
    }
    values.update(overrides)
    return adapter.Config(**values)


def test_config_defaults_sandbox_pool_to_webcompiler(tmp_path):
    config = make_config(tmp_path)

    assert config.sandbox_pool == "webcompiler"


def test_from_environment_propagates_exact_sandbox_pool_id(monkeypatch, tmp_path):
    expected = "shared_sandbox-pool-7"
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("SANDBOX_POOL_ID", expected)

    config = adapter.Config.from_environment()

    assert config.root == Path(tmp_path)
    assert config.sandbox_pool == expected


@pytest.mark.parametrize(
    "sandbox_pool",
    ["a", "sandbox_pool", "sandbox-pool", "1pool", "a" * 80],
)
def test_config_accepts_supported_sandbox_pool_names(tmp_path, sandbox_pool):
    config = make_config(tmp_path, sandbox_pool=sandbox_pool)

    assert config.sandbox_pool == sandbox_pool


@pytest.mark.parametrize(
    "sandbox_pool",
    ["", "sandbox pool", "Sandbox", None, 123, b"sandbox", "a" * 81],
)
def test_config_rejects_malformed_sandbox_pool_names(tmp_path, sandbox_pool):
    with pytest.raises((TypeError, ValueError)):
        make_config(tmp_path, sandbox_pool=sandbox_pool)
