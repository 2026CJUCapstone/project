from __future__ import annotations

from enum import Enum


class RunnerState(str, Enum):
    CREATED = "created"
    VALIDATING = "validating"
    PREPARING = "preparing"
    RUNNING = "running"
    COLLECTING = "collecting"
    FINISHED = "finished"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[RunnerState, set[RunnerState]] = {
    RunnerState.CREATED: {RunnerState.VALIDATING},
    RunnerState.VALIDATING: {RunnerState.PREPARING, RunnerState.FAILED},
    RunnerState.PREPARING: {RunnerState.RUNNING, RunnerState.FAILED},
    RunnerState.RUNNING: {RunnerState.COLLECTING, RunnerState.FAILED},
    RunnerState.COLLECTING: {RunnerState.FINISHED, RunnerState.FAILED},
    RunnerState.FINISHED: set(),
    RunnerState.FAILED: set(),
}


def allowed_transitions(state: RunnerState) -> set[RunnerState]:
    return set(_ALLOWED_TRANSITIONS[state])


def can_transition(current: RunnerState, nxt: RunnerState) -> bool:
    return nxt in _ALLOWED_TRANSITIONS[current]
