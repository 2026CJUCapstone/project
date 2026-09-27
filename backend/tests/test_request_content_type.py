"""Dependency-free request Content-Type boundary checks."""

import pytest

from app.services.request_content_type import is_utf8_json_content_type


@pytest.mark.parametrize('values', [
    ['application/json'],
    [' Application/JSON '],
    ['application/json; charset=utf-8'],
    ['application/json;charset="UTF8"'],
    ['application/json; profile=private-v1; charset=utf-8'],
])
def test_accepts_one_utf8_json_content_type(values):
    assert is_utf8_json_content_type(values) is True


@pytest.mark.parametrize('values', [
    [],
    ['application/json', 'application/json'],
    ['text/plain'],
    ['application/problem+json'],
    ['application/json; charset=utf-16'],
    ['application/json; charset='],
    ['application/json; broken'],
    ['application/json; charset=utf-8;'],
])
def test_rejects_missing_duplicate_non_json_or_malformed_content_type(values):
    assert is_utf8_json_content_type(values) is False
