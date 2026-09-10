"""Source-level contract checks for the baked frontend release marker."""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "frontend" / "Dockerfile"
NGINX = ROOT / "frontend" / "nginx.conf"
COMPOSE = ROOT / "docker-compose.yml"
MARKER_PATH = "/.well-known/webcompiler-release.json"


def frontend_service(compose: str) -> str:
    match = re.search(
        r"^  frontend:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "frontend service is missing"
    return match.group("body")


def exact_location_block(config: str, path: str) -> str:
    match = re.search(
        rf"^\s*location\s+=\s+{re.escape(path)}\s*\{{(?P<body>.*?)^\s*\}}",
        config,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"missing exact marker location for {path}"
    return match.group("body")


def test_frontend_build_passes_the_release_inputs_only_to_its_build_context():
    frontend = frontend_service(COMPOSE.read_text(encoding="utf-8"))

    assert "DEPLOY_SHA: ${DEPLOY_SHA:-}" in frontend
    assert "ENVIRONMENT: ${ENVIRONMENT:-development}" in frontend


def test_final_image_bakes_a_validated_nonsecret_marker():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    final_image = dockerfile.split("\nFROM nginx:", maxsplit=1)[1]

    assert "ARG DEPLOY_SHA=" in final_image
    assert "ARG ENVIRONMENT=development" in final_image
    assert "LC_ALL=C; export LC_ALL;" in final_image
    assert 'case "$ENVIRONMENT" in' in final_image
    assert "production)" in final_image
    assert "''|*[!0-9a-f]*)" in final_image
    assert '[ "${#DEPLOY_SHA}" -eq 40 ]' in final_image
    assert "development|test)" in final_image
    assert "Frontend ENVIRONMENT must be production, development, or test" in final_image
    assert "grep -E" not in final_image
    assert 'release_sha="non-release"' in final_image
    assert "mkdir -p /usr/share/nginx/html/.well-known" in final_image
    assert 'printf \'{"deployment_sha":"%s"}\\n\' "$release_sha"' in final_image
    assert final_image.index("COPY --from=build /app/dist /usr/share/nginx/html") < final_image.index(
        "mkdir -p /usr/share/nginx/html/.well-known"
    )


def test_marker_is_exact_json_static_content_with_no_spa_fallback_or_cache_storage():
    config = NGINX.read_text(encoding="utf-8")

    for path in (MARKER_PATH, "/webcompiler" + MARKER_PATH):
        marker = exact_location_block(config, path)
        assert "alias /usr/share/nginx/html/.well-known/webcompiler-release.json;" in marker
        assert "default_type application/json;" in marker
        assert 'add_header Cache-Control "no-store" always;' in marker
        assert 'add_header X-Frame-Options "DENY" always;' in marker
        assert 'add_header X-Content-Type-Options "nosniff" always;' in marker
        assert 'add_header Referrer-Policy "strict-origin-when-cross-origin" always;' in marker
        assert 'add_header Permissions-Policy "camera=(), geolocation=(), microphone=(), payment=(), usb=()" always;' in marker
        assert "try_files" not in marker
        assert "proxy_pass" not in marker
