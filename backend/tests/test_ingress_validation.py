"""The deployment ingress gate requires two explicit, narrow peer networks."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_ingress.py"
EDGE_KEY = "WEBCOMPILER_EDGE_TRUSTED_INGRESS_CIDRS"
PROXY_KEY = "WEBCOMPILER_PROXY_TRUSTED_INGRESS_CIDRS"
KEYS = (EDGE_KEY, PROXY_KEY)


def load_script():
    spec = importlib.util.spec_from_file_location("validate_ingress_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def valid_environment():
    return {
        EDGE_KEY: "192.0.2.0/24",
        PROXY_KEY: "198.51.100.0/24",
    }


def test_validate_accepts_two_explicit_test_only_networks():
    assert load_script().validate(valid_environment()) is None


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("value", [None, ""])
def test_validate_requires_each_ingress_environment_value(key, value):
    environ = valid_environment()
    if value is None:
        environ.pop(key)
    else:
        environ[key] = value

    with pytest.raises(ValueError, match=key):
        load_script().validate(environ)


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize(
    "value",
    [
        "0.0.0.0/0",
        "10.0.0.0/8",
        "not-a-cidr",
        "192.0.2.1/24",
        "192.0.2.0/24; return 200;",
        "192.0.2.0/24\n198.51.100.0/24",
    ],
)
def test_validate_rejects_broad_malformed_and_injected_networks(key, value):
    environ = valid_environment()
    environ[key] = value

    with pytest.raises((ValueError, TypeError)):
        load_script().validate(environ)


def test_cli_failure_is_exit2_and_creates_no_side_effects(tmp_path):
    environ = os.environ.copy()
    environ[EDGE_KEY] = ""
    environ[PROXY_KEY] = "198.51.100.0/24"

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        env=environ,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert EDGE_KEY in result.stderr
    assert list(tmp_path.iterdir()) == []
