from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "docker_down_webcompiler.sh"


def test_local_cleanup_accepts_only_explicitly_local_compose_projects():
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'webcompiler-local|webcompiler-e2e-*' in script
    assert "Refusing non-local compose project" in script
    assert "exit 2" in script


def test_local_cleanup_downs_only_the_selected_compose_project():
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-webcompiler-local}"' in script
    assert 'docker compose \\' in script
    assert '-p "$COMPOSE_PROJECT_NAME"' in script
    assert 'down --remove-orphans' in script


def test_local_cleanup_never_removes_production_resources_or_external_networks_directly():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "docker rm" not in script
    assert "docker network rm" not in script
    assert "webcompiler-blue" not in script
    assert "webcompiler-green" not in script
    assert "webcompiler-edge" not in script
    assert "External/shared networks and production edge/color stacks are not owned" in script
