"""Static contract for the unprivileged, read-only frontend runtime."""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
DOCKERFILE = ROOT / "frontend" / "Dockerfile"
NGINX = ROOT / "frontend" / "nginx.conf"


def frontend_service(compose: str) -> str:
    match = re.search(
        r"^  frontend:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "frontend service is missing"
    return match.group("body")


def test_frontend_container_is_nonroot_readonly_and_has_only_bounded_tmpfs_writes():
    frontend = frontend_service(COMPOSE.read_text(encoding="utf-8"))

    assert 'user: "10001:10001"' in frontend
    assert "read_only: true" in frontend
    assert "cap_drop: [ALL]" in frontend
    assert "security_opt: [no-new-privileges:true]" in frontend
    assert 'tmpfs: ["/tmp:size=32m,mode=1777,noexec,nosuid"]' in frontend
    assert 'ports: ["${WEBCOMPILER_FRONTEND_PORT_MAPPING:-5173:8080}"]' in frontend
    assert 'http://127.0.0.1:8080/health' in frontend


def test_frontend_nginx_uses_the_nonprivileged_port_and_tmpfs_only_runtime_paths():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    nginx = NGINX.read_text(encoding="utf-8")

    assert "EXPOSE 8080" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'ENTRYPOINT ["nginx"]' in dockerfile
    assert 'CMD ["-g", "daemon off;"]' in dockerfile
    assert "pid        /tmp/nginx.pid;" in dockerfile
    assert "error_log  /dev/stderr warn;" in dockerfile
    assert re.search(r"^\s*listen\s+8080;", nginx, flags=re.MULTILINE)
    assert "access_log /dev/stdout;" in nginx
    for directive in (
        "client_body_temp_path /tmp/client_temp;",
        "proxy_temp_path /tmp/proxy_temp;",
        "fastcgi_temp_path /tmp/fastcgi_temp;",
        "uwsgi_temp_path /tmp/uwsgi_temp;",
        "scgi_temp_path /tmp/scgi_temp;",
    ):
        assert directive in nginx
