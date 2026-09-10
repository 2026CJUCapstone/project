"""Credential validation fails before the deployment adapter can mutate state."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(
    os.name != "posix" or BASH is None,
    reason="deployment credential preflight requires a POSIX host with bash",
)

VALID_POSTGRES_PASSWORD = "postgres-valid-credential-123456"


def checkout_fixture(tmp_path, *, secret_contents=None):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    deploy = checkout / ".deploy"
    scripts.mkdir(parents=True)
    deploy.mkdir()
    shutil.copy2(ROOT / "scripts" / "deploy_server.sh", scripts / "deploy_server.sh")
    shutil.copy2(ROOT / "scripts" / "runtime_secrets.py", scripts / "runtime_secrets.py")
    (scripts / "deploy_guard.sh").write_text(":\n", encoding="utf-8")
    (scripts / "validate_ingress.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    (scripts / "verify_build_builder.py").write_text("print('a'*64)\n",encoding="utf-8")
    (scripts / "edge_deploy.py").write_text(
        "from pathlib import Path\n"
        "import os\n"
        "Path(os.environ['PROJECT_ROOT'], 'edge-called').write_text('called')\n"
        "raise SystemExit(66)\n",
        encoding="utf-8",
    )
    secret_file = deploy / "runtime-secrets.env"
    if secret_contents is not None:
        secret_file.write_bytes(secret_contents)
        secret_file.chmod(0o600)
    return checkout, scripts / "deploy_server.sh", secret_file


def run_deploy(tmp_path, *, credentials, secret_contents=None):
    checkout, script, secret_file = checkout_fixture(
        tmp_path, secret_contents=secret_contents
    )
    environment = {"PATH": os.environ["PATH"]}
    environment.update(credentials)
    result = subprocess.run(
        [BASH, str(script)],
        cwd=checkout,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        check=False,
    )
    return result, checkout, secret_file


@pytest.mark.parametrize(
    "postgres_password",
    [pytest.param(None, id="missing"), pytest.param("", id="empty"), pytest.param("short", id="short")],
)
def test_invalid_postgres_credential_stops_before_edge_and_does_not_create_file(
    tmp_path, postgres_password
):
    credentials = {}
    if postgres_password is not None:
        credentials["WEBCOMPILER_POSTGRES_PASSWORD"] = postgres_password

    result, checkout, secret_file = run_deploy(tmp_path, credentials=credentials)

    assert result.returncode != 0
    assert not (checkout / "edge-called").exists()
    assert not secret_file.exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param("WEBCOMPILER_SECRET_KEY", "short", id="short-secret-key"),
        pytest.param("WEBCOMPILER_ADMIN_PASSWORD", "short", id="short-admin-password"),
        pytest.param("SECRET_KEY", "short", id="short-raw-secret-key"),
        pytest.param("ADMIN_PASSWORD", "short", id="short-raw-admin-password"),
    ],
)
def test_weak_application_credential_stops_before_edge_and_file_creation(
    tmp_path, key, value
):
    credentials = {
        "WEBCOMPILER_POSTGRES_PASSWORD": VALID_POSTGRES_PASSWORD,
        key: value,
    }

    result, checkout, secret_file = run_deploy(tmp_path, credentials=credentials)

    assert result.returncode != 0
    assert not (checkout / "edge-called").exists()
    assert not secret_file.exists()


def test_empty_file_postgres_value_overrides_valid_environment_without_mutation(tmp_path):
    original = b"# operator-managed fixture\nWEBCOMPILER_POSTGRES_PASSWORD=\n"
    result, checkout, secret_file = run_deploy(
        tmp_path,
        credentials={"WEBCOMPILER_POSTGRES_PASSWORD": VALID_POSTGRES_PASSWORD},
        secret_contents=original,
    )

    assert result.returncode != 0
    assert not (checkout / "edge-called").exists()
    assert secret_file.read_bytes() == original


def test_valid_postgres_credential_reaches_edge_without_creating_secrets_file(tmp_path):
    result, checkout, secret_file = run_deploy(
        tmp_path,
        credentials={"WEBCOMPILER_POSTGRES_PASSWORD": VALID_POSTGRES_PASSWORD},
    )

    assert result.returncode == 66
    assert (checkout / "edge-called").read_text(encoding="utf-8") == "called"
    assert not secret_file.exists()
