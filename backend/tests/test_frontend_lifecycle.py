"""Static lifecycle checks for the production Nginx frontend container."""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
NGINX = ROOT / "frontend" / "nginx.conf"


def frontend_service(compose: str) -> str:
    match = re.search(
        r"^  frontend:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "frontend service is missing"
    return match.group("body")


def test_frontend_is_restartable_and_healthchecks_its_nginx_health_route():
    frontend = frontend_service(COMPOSE.read_text(encoding="utf-8"))
    nginx = NGINX.read_text(encoding="utf-8")

    assert "restart: unless-stopped" in frontend
    assert 'test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/health"]' in frontend
    assert "interval: 15s" in frontend
    assert "timeout: 5s" in frontend
    assert "retries: 5" in frontend
    assert re.search(r"location\s*=\s*/health\s*\{\s*proxy_pass\s+http://backend_upstream/health;", nginx)


def test_frontend_has_bounded_resources_and_rotated_json_logs():
    frontend = frontend_service(COMPOSE.read_text(encoding="utf-8"))

    assert "mem_limit: 128m" in frontend
    assert "memswap_limit: 128m" in frontend
    assert "cpus: 0.25" in frontend
    assert "pids_limit: 64" in frontend
    assert "driver: json-file" in frontend
    assert 'options: { max-size: "10m", max-file: "3" }' in frontend
