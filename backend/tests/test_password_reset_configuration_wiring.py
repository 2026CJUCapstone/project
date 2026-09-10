"""Static and local-only regression checks for password-reset delivery wiring.

These tests deliberately stop at configuration and a fake SMTP transport. They
do not read deployment secrets, contact an SMTP server, or start Compose.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]

RESET_AND_SMTP_KEYS = (
    "PASSWORD_RESET_BASE_URL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "SMTP_STARTTLS",
)


def _service_block(source: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        source,
    )
    assert match, f"service {service!r} is missing"
    return match.group(1)


def _load_runtime_secrets_module():
    path = ROOT / "scripts" / "runtime_secrets.py"
    spec = importlib.util.spec_from_file_location("password_reset_runtime_secrets", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_declare_every_reset_and_smtp_runtime_field():
    source = (ROOT / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    for key in RESET_AND_SMTP_KEYS:
        assert re.search(rf"(?m)^    {re.escape(key)}:", source), key


def test_fake_smtp_receives_reset_url_tls_auth_and_message(monkeypatch):
    from app.services import email as email_service

    class FakeSMTP:
        instances = []

        def __init__(self, host, port, *, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.starttls_calls = 0
            self.login_calls = []
            self.messages = []
            self.closed = False
            self.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            self.closed = True

        def starttls(self, *, context):
            assert context.check_hostname
            self.starttls_calls += 1

        def login(self, username, password):
            self.login_calls.append((username, password))

        def send_message(self, message):
            self.messages.append(message)

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(
        email_service,
        "settings",
        SimpleNamespace(
            SMTP_HOST="smtp.fixture.invalid",
            SMTP_PORT=2525,
            SMTP_USERNAME="fixture-user",
            SMTP_PASSWORD="fixture-password",
            SMTP_FROM="no-reply@fixture.invalid",
            SMTP_STARTTLS=True,
            PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30,
            PASSWORD_RESET_BASE_URL="https://frontend.fixture.invalid/webcompiler/",
        ),
    )

    email_service.send_password_reset_email("recipient@fixture.invalid", "token+/fixture")

    smtp = FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.fixture.invalid", 2525, 10)
    assert smtp.starttls_calls == 1
    assert smtp.login_calls == [("fixture-user", "fixture-password")]
    assert smtp.closed is True
    assert len(smtp.messages) == 1
    message = smtp.messages[0]
    assert message["From"] == "no-reply@fixture.invalid"
    assert message["To"] == "recipient@fixture.invalid"
    body = message.get_content()
    assert "https://frontend.fixture.invalid/webcompiler/?resetToken=token%2B/fixture" in body
    assert "fixture-password" not in body


def test_runtime_secrets_exports_reset_and_smtp_values_as_literal_assignments():
    runtime_secrets = _load_runtime_secrets_module()
    values = {key: f"fixture-{key.lower()}" for key in RESET_AND_SMTP_KEYS}
    rendered = runtime_secrets.exports(values)
    for key, value in values.items():
        assert f"export {key}=" in rendered
        assert value in rendered


def test_deploy_aliases_are_loaded_before_candidate_stack_is_started():
    source = (ROOT / "scripts" / "deploy_server.sh").read_text(encoding="utf-8")
    ensure = source.index('runtime_secret_exports="$(python3')
    evaluation = source.index('eval "$runtime_secret_exports"')
    stack_start = source.index('compose_for_color "$target_color" up --no-build -d')

    aliases = {
        "PASSWORD_RESET_BASE_URL": "WEBCOMPILER_PASSWORD_RESET_BASE_URL",
        "SMTP_HOST": "WEBCOMPILER_SMTP_HOST",
        "SMTP_PORT": "WEBCOMPILER_SMTP_PORT",
        "SMTP_USERNAME": "WEBCOMPILER_SMTP_USERNAME",
        "SMTP_PASSWORD": "WEBCOMPILER_SMTP_PASSWORD",
        "SMTP_FROM": "WEBCOMPILER_SMTP_FROM",
        "SMTP_STARTTLS": "WEBCOMPILER_SMTP_STARTTLS",
    }
    for key, alias in aliases.items():
        line_start = 'export ' + key + '="${' + key + ':-${' + alias + ':-'
        line = next(line for line in source.splitlines() if line.startswith(line_start))
        assert ensure < source.index(line) < stack_start
    assert ensure < evaluation < stack_start


def test_base_compose_passes_reset_and_smtp_fields_to_all_backend_runtime_services():
    source = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    anchor = source.split("x-backend-environment: &backend-environment\n", 1)[1].split(
        "\nx-backend-image:", 1
    )[0]
    for key in RESET_AND_SMTP_KEYS:
        assert re.search(rf"(?m)^  {re.escape(key)}:", anchor), key

    for service in ("initialize", "backend"):
        assert "<<: *backend-environment" in _service_block(source, service)
    assert "environment: *backend-environment" in _service_block(source, "worker")


def test_production_overlays_do_not_reset_the_inherited_backend_environment():
    for name in (
        "docker-compose.deploy.yml",
        "docker-compose.shared-runtime.yml",
        "docker-compose.ready-lb.yml",
    ):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "environment: !reset" not in source, name
