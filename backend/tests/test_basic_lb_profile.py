"""Static contracts for the small single-host basic-LB Compose profile."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "scripts" / "basic-lb.compose.yml"


def compose_profile() -> dict:
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))


def test_runtime_identity_is_required_on_initializer_backend_and_worker():
    services = compose_profile()["services"]
    expected = {
        "RUNTIME_POOL_ID": "${COMPOSE_PROJECT_NAME:?}",
        "RUNTIME_INSTANCE_ID": "${BASIC_LB_RUNTIME_ID:?}",
    }

    for name in ("initialize", "backend", "worker"):
        environment = services[name]["environment"]
        for key, value in expected.items():
            assert environment.get(key) == value


def test_basic_lb_uses_shared_external_network_and_frontend_subpath_proxy():
    profile = compose_profile()
    network = profile["networks"]["default"]
    assert network == {
        "external": True,
        "name": "${BASIC_LB_NETWORK:?}",
    }

    frontend_args = profile["services"]["frontend"]["build"]["args"]
    assert frontend_args == {
        "FRONTEND_API_UPSTREAM": "api-proxy:8080",
        "VITE_API_URL": "/webcompiler",
        "VITE_APP_BASE_PATH": "/webcompiler/",
    }


def test_every_basic_lb_service_has_finite_matching_memory_and_swap_caps():
    services = compose_profile()["services"]
    assert set(services) == {
        "initialize", "backend", "worker", "frontend",
        "postgres", "pgbouncer", "redis",
    }

    for name, service in services.items():
        memory = service.get("mem_limit")
        swap = service.get("memswap_limit")
        assert isinstance(memory, str) and re.fullmatch(r"[1-9][0-9]*[kKmMgG]", memory), name
        assert swap == memory, name
