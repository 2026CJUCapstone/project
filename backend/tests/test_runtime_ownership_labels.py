"""Static contract for managed color-container ownership labels."""
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OVERLAY = PROJECT_ROOT / "docker-compose.ready-lb.yml"

ROLES = (
    "backend",
    "worker",
    "frontend",
    "pgbouncer",
    "initialize",
    "api-proxy",
    "proxy-controller",
    "proxy-control-init",
)

SHARED_LABELS = {
    "io.webcompiler.runtime.version": "'1'",
    "io.webcompiler.runtime.id": "${WEBCOMPILER_RUNTIME_INSTANCE_ID:?Set the reserved runtime instance}",
    "io.webcompiler.runtime.pool": "${COMPOSE_PROJECT_NAME:?Set the color project}",
    "io.webcompiler.runtime.release": "${DEPLOY_SHA:?Set the exact verified release}",
    "io.webcompiler.runtime.sandbox-pool": "${SANDBOX_POOL_ID:-webcompiler}",
}


def service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"managed service {service!r} is missing"
    return match.group("body")


def test_managed_color_services_share_exact_runtime_ownership_labels():
    compose = OVERLAY.read_text(encoding="utf-8")
    anchor = re.search(
        r"^x-runtime-ownership-labels: &runtime-ownership-labels\n"
        r"(?P<body>.*?)(?=^services:\n)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert anchor, "managed runtime ownership-label anchor is missing"
    for key, value in SHARED_LABELS.items():
        assert f"  {key}: {value}" in anchor.group("body")

    for role in ROLES:
        labels = re.search(
            rf"^    labels:\n"
            rf"      <<: \*runtime-ownership-labels\n"
            rf"      io\.webcompiler\.runtime\.role: {re.escape(role)}$",
            service_block(compose, role),
            flags=re.MULTILINE,
        )
        assert labels, f"{role} must merge the exact managed ownership labels"
