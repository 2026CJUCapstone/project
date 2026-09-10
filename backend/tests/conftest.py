import pytest


@pytest.fixture(autouse=True)
def isolate_process_local_rate_budgets():
    """Each test models its own clock/traffic, never a previous test's requests."""
    from app.core import rate_limit
    with rate_limit._lock:
        rate_limit._attempts.clear()
        rate_limit._expirations.clear()
        rate_limit._next_cleanup = 0
    yield
