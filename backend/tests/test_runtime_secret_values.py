"""Positive parsing contract for the deployment runtime-secrets file."""

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "runtime_secrets_under_test", ROOT / "scripts" / "runtime_secrets.py"
)
assert SPEC and SPEC.loader
runtime_secrets = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime_secrets
SPEC.loader.exec_module(runtime_secrets)


def write_secret_file(tmp_path, contents):
    path = tmp_path / "runtime-secrets.env"
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_load_parses_all_supported_secret_values_without_shell_expansion(tmp_path):
    path = write_secret_file(
        tmp_path,
        """
# deployment secrets are literal KEY=value records

WEBCOMPILER_SECRET_KEY='literal-$HOME-$(not-expanded)'
export WEBCOMPILER_ADMIN_PASSWORD="admin password"
WEBCOMPILER_POSTGRES_PASSWORD=postgres-password

SMTP_HOST=smtp.example.test
export SMTP_PORT='587'
SMTP_USERNAME="smtp-user"
SMTP_PASSWORD='smtp password'
SMTP_FROM=no-reply@example.test
SMTP_STARTTLS=true

WEBCOMPILER_SMTP_HOST='prefixed.smtp.example.test'
WEBCOMPILER_SMTP_PORT="2525"
WEBCOMPILER_SMTP_USERNAME=
export WEBCOMPILER_SMTP_PASSWORD=""
WEBCOMPILER_SMTP_FROM='prefixed-no-reply@example.test'
WEBCOMPILER_SMTP_STARTTLS="false"

PASSWORD_RESET_BASE_URL=https://example.test/reset/
WEBCOMPILER_PASSWORD_RESET_BASE_URL='https://prefixed.example.test/reset/'
""",
    )

    assert runtime_secrets.load(path) == {
        "WEBCOMPILER_SECRET_KEY": "literal-$HOME-$(not-expanded)",
        "WEBCOMPILER_ADMIN_PASSWORD": "admin password",
        "WEBCOMPILER_POSTGRES_PASSWORD": "postgres-password",
        "SMTP_HOST": "smtp.example.test",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "smtp-user",
        "SMTP_PASSWORD": "smtp password",
        "SMTP_FROM": "no-reply@example.test",
        "SMTP_STARTTLS": "true",
        "WEBCOMPILER_SMTP_HOST": "prefixed.smtp.example.test",
        "WEBCOMPILER_SMTP_PORT": "2525",
        "WEBCOMPILER_SMTP_USERNAME": "",
        "WEBCOMPILER_SMTP_PASSWORD": "",
        "WEBCOMPILER_SMTP_FROM": "prefixed-no-reply@example.test",
        "WEBCOMPILER_SMTP_STARTTLS": "false",
        "PASSWORD_RESET_BASE_URL": "https://example.test/reset/",
        "WEBCOMPILER_PASSWORD_RESET_BASE_URL": "https://prefixed.example.test/reset/",
    }
