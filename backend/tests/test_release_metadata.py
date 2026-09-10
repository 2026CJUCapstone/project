"""Deployment identity is public provenance, never runtime configuration."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.main import health_check


@pytest.mark.parametrize('sha', ['', '0123456789abcdef0123456789abcdef01234567'])
def test_exact_or_unversioned_release_setting(sha):
    assert Settings(_env_file=None, DEPLOYMENT_SHA=sha).DEPLOYMENT_SHA == sha


@pytest.mark.parametrize('sha', ['main', 'a'*39, 'a'*41, 'A'*40, 'a'*40+'\n'])
def test_invalid_release_setting_fails_startup(sha):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DEPLOYMENT_SHA=sha)


@pytest.mark.parametrize('sha', ['', 'a'*40])
def test_health_reports_only_explicit_release_identity(monkeypatch, sha):
    monkeypatch.setattr(settings, 'DEPLOYMENT_SHA', sha)
    response = health_check()
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert json.loads(response.body) == {
        'status': 'ok', 'version': settings.VERSION, 'deploymentSha': sha or None,
        'runtimeInstanceId': settings.RUNTIME_INSTANCE_ID or None,
    }


def test_all_compose_app_processes_receive_verified_sha():
    compose = (Path(__file__).resolve().parents[2]/'docker-compose.yml').read_text()
    assert 'DEPLOYMENT_SHA: ${DEPLOY_SHA:-}' in compose.split('services:', 1)[0]


def test_deployment_initializes_shared_database_and_gates_switch_on_readiness():
    root = Path(__file__).resolve().parents[2]
    overlay = (root/'docker-compose.deploy.yml').read_text()
    initializer = overlay.split('  initialize:', 1)[1].split('  pgbouncer:', 1)[0]
    assert '@${WEBCOMPILER_POSTGRES_HOST:-postgres}' in initializer
    assert 'WEBCOMPILER_MIGRATION_DATABASE_URL' in initializer
    deploy = (root/'scripts/deploy_server.sh').read_text()
    assert 'export WEBCOMPILER_POSTGRES_HOST="${WEBCOMPILER_POSTGRES_HOST:-$SHARED_POSTGRES_NAME}"' in deploy
    assert '--connect-timeout 2 --max-time 5' in deploy
    target_backend_check = 'wait_for_url "http://127.0.0.1:${target_backend_port}/ready"'
    target_frontend_check = 'wait_for_url "http://127.0.0.1:${target_frontend_port}/health"'
    switch = 'actual_active_color="$(python3 "$SOURCE_ROOT/scripts/edge_deploy.py" switch --color "$target_color")"'
    assert deploy.index('wait_for_color_pool "$target_color"') < deploy.index(target_backend_check)
    assert deploy.index(target_backend_check) < deploy.index(target_frontend_check) < deploy.index(switch)
    assert 'log "switching edge proxies' not in deploy

    edge_deploy = (root/'scripts/edge_deploy.py').read_text()
    switch_adapter = edge_deploy[edge_deploy.index('    def switch(self,color,sha):'):]
    assert 'return self.gate(target) and self.verify(target)' in switch_adapter
    assert 'return self.verify(target,edge=True) and self.gate(target)' in switch_adapter
    assert 'self.transaction.switch(release,preflight=before,postflight=after)' in switch_adapter
    assert 'api_ports=(self.config.layout.api_port,self.config.layout.frontend_port) if edge' in edge_deploy
    assert "self.probe(port,'/ready')" in edge_deploy
