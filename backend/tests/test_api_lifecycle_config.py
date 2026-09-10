"""Validation for the runtime-wide HTTP/WebSocket admission cap."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def isolate_api_lifecycle_environment(monkeypatch):
    monkeypatch.delenv("RUNTIME_MAX_ACTIVE_REQUESTS", raising=False)


def test_runtime_max_active_requests_defaults_to_512_without_external_environment():
    config = Settings(_env_file=None)

    assert config.RUNTIME_MAX_ACTIVE_REQUESTS == 512


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [("1", 1), ("512", 512), ("4096", 4096)],
)
def test_runtime_max_active_requests_accepts_integer_form_environment_values(
    monkeypatch,
    raw_value,
    expected,
):
    monkeypatch.setenv("RUNTIME_MAX_ACTIVE_REQUESTS", raw_value)

    config = Settings(_env_file=None)

    assert config.RUNTIME_MAX_ACTIVE_REQUESTS == expected


@pytest.mark.parametrize("value", [1, 4096])
def test_runtime_max_active_requests_accepts_integer_boundaries(value):
    config = Settings(_env_file=None, RUNTIME_MAX_ACTIVE_REQUESTS=value)

    assert config.RUNTIME_MAX_ACTIVE_REQUESTS == value


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        1.0,
        512.5,
        0,
        -1,
        4097,
        "",
        "1.0",
        "not-an-integer",
    ],
)
def test_runtime_max_active_requests_rejects_non_strict_or_out_of_range_values(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, RUNTIME_MAX_ACTIVE_REQUESTS=value)


@pytest.mark.parametrize("raw_value", ["0", "-1", "4097", "1.0", "not-an-integer"])
def test_runtime_max_active_requests_rejects_invalid_environment_values(
    monkeypatch,
    raw_value,
):
    monkeypatch.setenv("RUNTIME_MAX_ACTIVE_REQUESTS", raw_value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
