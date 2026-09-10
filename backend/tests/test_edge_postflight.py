import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TRANSACTION_SPEC = importlib.util.spec_from_file_location(
    'edge_transaction', ROOT / 'scripts' / 'edge_transaction.py'
)
edge_transaction = importlib.util.module_from_spec(TRANSACTION_SPEC)
# Dataclasses resolve the defining module through sys.modules while executing.
sys.modules[TRANSACTION_SPEC.name] = edge_transaction
TRANSACTION_SPEC.loader.exec_module(edge_transaction)

RUNTIME_SPEC = importlib.util.spec_from_file_location(
    'edge_runtime', ROOT / 'scripts' / 'edge_runtime.py'
)
edge_runtime = importlib.util.module_from_spec(RUNTIME_SPEC)
sys.modules[RUNTIME_SPEC.name] = edge_runtime
RUNTIME_SPEC.loader.exec_module(edge_runtime)

wait_postflight = edge_runtime.wait_postflight


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now = round(self.now + seconds, 6)


def test_wait_postflight_returns_true_after_literal_true_is_stable():
    clock = FakeClock()
    checks = []

    def check():
        checks.append(clock.now)
        return True

    assert wait_postflight(check, timeout=4, stable_seconds=1,
                           clock=clock, sleep=clock.sleep) is True
    assert checks[0] == 0
    assert checks[-1] >= 1
    assert clock.now < 4


def test_wait_postflight_restarts_stability_after_handoff_unhealthy():
    clock = FakeClock()
    outcomes = iter([True, False])
    checks = []

    def check():
        checks.append(clock.now)
        return next(outcomes, True)

    assert wait_postflight(check, timeout=5, stable_seconds=1,
                           clock=clock, sleep=clock.sleep) is True
    assert checks[:3] == [0, 0.2, 0.4]
    assert checks[-1] >= 1.4


@pytest.mark.parametrize('failure', [OSError, ValueError, edge_runtime.EdgeError])
def test_wait_postflight_restarts_stability_after_transient_error(failure):
    clock = FakeClock()
    outcomes = iter([True, failure])
    checks = []

    def check():
        checks.append(clock.now)
        outcome = next(outcomes, True)
        if isinstance(outcome, type):
            raise outcome('transient')
        return outcome

    assert wait_postflight(check, timeout=5, stable_seconds=1,
                           clock=clock, sleep=clock.sleep) is True
    assert checks[:3] == [0, 0.2, 0.4]
    assert checks[-1] >= 1.4


def test_wait_postflight_returns_false_when_health_never_stabilizes():
    clock = FakeClock()

    assert wait_postflight(lambda: False, timeout=3, stable_seconds=1,
                           clock=clock, sleep=clock.sleep) is False
    assert clock.now == 3


@pytest.mark.parametrize('kwargs', [
    {'stable_seconds': 0},
    {'stable_seconds': 11},
    {'timeout': 3},
    {'timeout': 61},
])
def test_wait_postflight_rejects_unbounded_or_inverted_windows(kwargs):
    with pytest.raises(ValueError):
        wait_postflight(lambda: True, **kwargs)
