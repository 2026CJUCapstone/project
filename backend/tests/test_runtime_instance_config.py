import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def isolate_runtime_instance_environment(monkeypatch):
    monkeypatch.delenv('RUNTIME_INSTANCE_ID', raising=False)


def test_runtime_instance_id_defaults_to_local_empty_value_without_external_environment():
    result = Settings(_env_file=None)

    assert result.RUNTIME_INSTANCE_ID == ''


@pytest.mark.parametrize('instance_id', ['', 'a' * 32, '0' * 31 + '1'])
def test_runtime_instance_id_accepts_empty_or_nonzero_lowercase_hex(monkeypatch, instance_id):
    monkeypatch.setenv('RUNTIME_INSTANCE_ID', instance_id)

    result = Settings(_env_file=None)

    assert result.RUNTIME_INSTANCE_ID == instance_id


@pytest.mark.parametrize('instance_id', [
    '0' * 32,
    'a' * 31,
    'a' * 33,
    'A' * 32,
    'g' * 32,
    'a' * 32 + '\n',
    'a' * 32 + '\r\n',
    123,
    b'a' * 32,
    None,
])
def test_runtime_instance_id_rejects_zero_malformed_or_non_string_values(monkeypatch, instance_id):
    if instance_id is None:
        monkeypatch.delenv('RUNTIME_INSTANCE_ID', raising=False)
        # Missing environment uses the valid empty default; None is not a
        # representable environment value and is covered by direct settings input.
        with pytest.raises(ValidationError):
            Settings(_env_file=None, RUNTIME_INSTANCE_ID=None)
        return
    if isinstance(instance_id, bytes):
        # Environment variables are strings; exercise the field's strict input
        # path directly so byte values cannot be silently coerced.
        with pytest.raises(ValidationError):
            Settings(_env_file=None, RUNTIME_INSTANCE_ID=instance_id)
        return
    if isinstance(instance_id, int):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, RUNTIME_INSTANCE_ID=instance_id)
        return

    monkeypatch.setenv('RUNTIME_INSTANCE_ID', instance_id)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
