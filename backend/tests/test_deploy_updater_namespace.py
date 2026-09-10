"""The optional sandbox updater is restricted to the canonical namespace."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(
    os.name != "posix" or BASH is None,
    reason="deploy shell contract requires a POSIX host with bash",
)


def checkout_fixture(tmp_path):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "deploy_server.sh", scripts / "deploy_server.sh")
    (scripts / "deploy_guard.sh").write_text(
        "printf '%s\\n' reached > \"$PROJECT_ROOT/guard-reached\"\nexit 77\n",
        encoding="utf-8",
    )
    return checkout, scripts / "deploy_server.sh"


def run_deploy_fixture(tmp_path, *, project_prefix=None, updater=None):
    checkout, script = checkout_fixture(tmp_path)
    environment = {"PATH": os.environ["PATH"]}
    if project_prefix is not None:
        environment["WEBCOMPILER_PROJECT_PREFIX"] = project_prefix
    if updater is not None:
        environment["WEBCOMPILER_ENABLE_SANDBOX_UPDATER"] = updater
    result = subprocess.run(
        [BASH, str(script)],
        cwd=checkout,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=5,
    )
    return result, checkout / "guard-reached"


@pytest.mark.parametrize(
    ("project_prefix", "updater", "returncode", "guard_reached"),
    [
        pytest.param("tenant", "1", 2, False, id="custom-enabled"),
        pytest.param("tenant", "invalid", 2, False, id="custom-invalid-enabled-value"),
        pytest.param("tenant", "0", 77, True, id="custom-disabled"),
        pytest.param("tenant", None, 77, True, id="custom-default-disabled"),
        pytest.param(None, "1", 77, True, id="canonical-enabled"),
    ],
)
def test_updater_namespace_guard_precedes_deploy_guard(
    tmp_path, project_prefix, updater, returncode, guard_reached
):
    result, marker = run_deploy_fixture(
        tmp_path,
        project_prefix=project_prefix,
        updater=updater,
    )

    assert result.returncode == returncode
    assert marker.exists() is guard_reached
