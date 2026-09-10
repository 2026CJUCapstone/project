"""Import-time E2E listener ports are explicit, bounded, and loopback-only."""

import importlib.util
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "e2e_stack_test.py"
DEFAULT_BACKEND = 18010
DEFAULT_FRONTEND = 15180


@pytest.fixture(autouse=True)
def clear_test_port_environment(monkeypatch):
    monkeypatch.delenv("E2E_BACKEND_PORT", raising=False)
    monkeypatch.delenv("E2E_FRONTEND_PORT", raising=False)


def load_script():
    spec = importlib.util.spec_from_file_location("e2e_stack_test_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_ports_are_loopback_only_in_urls_and_compose_mappings():
    script = load_script()

    assert script.BACKEND_PORT == DEFAULT_BACKEND
    assert script.FRONTEND_PORT == DEFAULT_FRONTEND
    assert script.BACKEND_BASE_URL == f"http://127.0.0.1:{DEFAULT_BACKEND}"
    assert script.FRONTEND_BASE_URL == f"http://127.0.0.1:{DEFAULT_FRONTEND}"
    assert script.ENV["WEBCOMPILER_BACKEND_PORT_MAPPING"] == (
        f"127.0.0.1:{DEFAULT_BACKEND}:8000"
    )
    assert script.ENV["WEBCOMPILER_FRONTEND_PORT_MAPPING"] == (
        f"127.0.0.1:{DEFAULT_FRONTEND}:8080"
    )


def test_custom_ports_are_used_only_as_loopback_host_ports(monkeypatch):
    monkeypatch.setenv("E2E_BACKEND_PORT", "28010")
    monkeypatch.setenv("E2E_FRONTEND_PORT", "28180")

    script = load_script()

    assert script.BACKEND_BASE_URL == "http://127.0.0.1:28010"
    assert script.FRONTEND_BASE_URL == "http://127.0.0.1:28180"
    assert script.ENV["WEBCOMPILER_BACKEND_PORT_MAPPING"] == "127.0.0.1:28010:8000"
    assert script.ENV["WEBCOMPILER_FRONTEND_PORT_MAPPING"] == "127.0.0.1:28180:8080"
    assert all(
        mapping.startswith("127.0.0.1:")
        for mapping in (
            script.ENV["WEBCOMPILER_BACKEND_PORT_MAPPING"],
            script.ENV["WEBCOMPILER_FRONTEND_PORT_MAPPING"],
        )
    )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("12 34", id="space"),
        pytest.param("+18010", id="plus"),
        pytest.param("-18010", id="minus"),
        pytest.param("18010.0", id="float"),
        pytest.param("0", id="zero"),
        pytest.param("1023", id="below-minimum"),
        pytest.param("65536", id="above-maximum"),
        pytest.param("１８０１０", id="non-ascii-decimal"),
    ],
)
@pytest.mark.parametrize("key", ["E2E_BACKEND_PORT", "E2E_FRONTEND_PORT"])
def test_non_ascii_or_out_of_range_port_values_are_rejected(monkeypatch, key, value):
    monkeypatch.setenv(key, value)

    with pytest.raises(ValueError):
        load_script()


def test_backend_and_frontend_ports_must_be_distinct(monkeypatch):
    monkeypatch.setenv("E2E_BACKEND_PORT", "28080")
    monkeypatch.setenv("E2E_FRONTEND_PORT", "28080")

    with pytest.raises(ValueError):
        load_script()
