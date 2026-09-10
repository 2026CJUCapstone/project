import pytest

from tests.proxy_helpers import final_upstream


@pytest.mark.parametrize(
    ('trace', 'expected'),
    [
        ('192.0.2.10:8000', '192.0.2.10:8000'),
        ('192.0.2.10:8000, 192.0.2.11:8000', '192.0.2.11:8000'),
        ('execution_api : 192.168.0.5:8000', '192.168.0.5:8000'),
        (
            'frontend : 192.0.2.10:8000, 192.0.2.11:8000'
            ' : execution_api : 192.0.2.12:8000, 192.0.2.13:8000',
            '192.0.2.13:8000',
        ),
        ('execution_api : [2001:db8::5]:8443', '[2001:db8::5]:8443'),
    ],
)
def test_final_upstream_returns_last_endpoint(trace, expected):
    assert final_upstream(trace) == expected


@pytest.mark.parametrize(
    'trace',
    [
        '',
        ' : 192.168.0.5:8000',
        'execution_api',
        'execution_api : ',
        'execution_api : unresolved',
        '192.168.0.5:8000, ',
        '192.168.0.5:8000 : execution_api',
        'execution_api : 192.168.0.5',
        'execution_api : 192.168.0.5:0',
        'execution_api : 192.168.0.5:65536',
        'execution_api : 999.168.0.5:8000',
    ],
)
def test_final_upstream_rejects_missing_or_malformed_final_entry(trace):
    with pytest.raises(ValueError):
        final_upstream(trace)
