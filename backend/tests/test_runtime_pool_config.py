import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def isolate_runtime_pool_environment(monkeypatch):
    monkeypatch.delenv('RUNTIME_POOL_ID', raising=False)


def test_runtime_pool_id_defaults_to_local_without_external_environment():
    result = Settings(_env_file=None)

    assert result.RUNTIME_POOL_ID == 'local'


@pytest.mark.parametrize('pool_id', [
    'local',
    'blue',
    'green',
    'webcompiler-blue',
    'webcompiler_green',
    '1pool',
    'a' * 80,
])
def test_runtime_pool_id_accepts_canonical_values(monkeypatch, pool_id):
    monkeypatch.setenv('RUNTIME_POOL_ID', pool_id)

    result = Settings(_env_file=None)

    assert result.RUNTIME_POOL_ID == pool_id


@pytest.mark.parametrize('pool_id', [
    '',
    'a' * 81,
    'Blue',
    'pool:id',
    'pool/path',
    'pool\nid',
    'pool\n',
    'pool\r\n',
    'pool id',
])
def test_runtime_pool_id_rejects_invalid_values(monkeypatch, pool_id):
    monkeypatch.setenv('RUNTIME_POOL_ID', pool_id)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
