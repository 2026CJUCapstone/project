"""The E2E cleanup drain proves producer and journal quiescence first."""

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "e2e_stack_test.py"


def load_script():
    spec = importlib.util.spec_from_file_location("e2e_quiescence_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


IDS = {
    "frontend": "a" * 64,
    "backend": "b" * 64,
    "worker": "c" * 64,
    "postgres": "d" * 64,
}


def container(service: str) -> dict:
    return {
        "Id": IDS[service],
        "Config": {"Labels": {"com.docker.compose.service": service}},
    }


def resource_fixture() -> dict:
    # Deliberately do not return producers in the desired stop order. The
    # drain must impose frontend -> backend -> worker itself.
    return {
        "container": [
            container("worker"),
            container("postgres"),
            container("backend"),
            container("frontend"),
        ],
        "sandbox": [],
        "volume": [],
        "network": [],
    }


def install_checkpoint_fakes(monkeypatch, script, state, events):
    def checkpoint_exists(name):
        events.append(("checkpoint", name))
        return name in state

    def record_checkpoint(name):
        events.append(("record", name))
        state.add(name)

    monkeypatch.setattr(script, "checkpoint_exists", checkpoint_exists)
    monkeypatch.setattr(script, "record_checkpoint", record_checkpoint)


def test_missing_setup_ack_refuses_to_touch_docker(monkeypatch):
    script = load_script()
    events = []
    install_checkpoint_fakes(monkeypatch, script, set(), events)
    monkeypatch.setattr(script, "owned_resources", lambda: pytest.fail("Docker discovery must not run"))
    monkeypatch.setattr(script, "docker", lambda *args: pytest.fail("Docker must not run"))

    with pytest.raises(RuntimeError, match="no durable completion acknowledgment"):
        script.settle_producers()

    assert [event for event in events if event[0] == "record"] == []
    assert {event[1] for event in events if event[0] == "checkpoint"} == {
        "producers-settled",
        "setup-complete",
    }


def test_already_settled_is_a_docker_free_noop(monkeypatch):
    script = load_script()
    events = []
    install_checkpoint_fakes(monkeypatch, script, {"producers-settled"}, events)
    monkeypatch.setattr(script, "owned_resources", lambda: pytest.fail("Already settled must be a no-op"))
    monkeypatch.setattr(script, "docker", lambda *args: pytest.fail("Docker must not run"))
    monkeypatch.setattr(script, "record_checkpoint", lambda *args: pytest.fail("Must not re-record"))

    script.settle_producers()

    assert events == [("checkpoint", "producers-settled")]


def test_clean_producers_are_stopped_in_order_and_readonly_journal_is_zero(monkeypatch):
    script = load_script()
    events = []
    install_checkpoint_fakes(monkeypatch, script, {"setup-complete"}, events)
    monkeypatch.setattr(script, "owned_resources", lambda: (events.append(("owned",)) or resource_fixture()))

    query = (
        "BEGIN READ ONLY; SET LOCAL statement_timeout='5s'; "
        "SELECT (SELECT count(*) FROM execution_jobs WHERE "
        "status NOT IN ('completed','failed') OR sandbox_operation IS NOT NULL "
        "OR lease_token IS NOT NULL OR lease_until IS NOT NULL OR finished_at IS NULL) + "
        "(SELECT count(*) FROM execution_workers WHERE draining_at IS NULL) + "
        "(SELECT CASE WHEN count(*) = 0 THEN 1 ELSE 0 END FROM execution_workers); COMMIT;"
    )

    def docker(*args):
        events.append(("docker", args))
        if args[:3] == ("container", "stop", "--time"):
            assert args[3] == "150"
            return ""
        if args[:2] == ("container", "inspect"):
            identifier = args[-1]
            return json.dumps([{
                "Id": identifier,
                "State": {"Running": False, "OOMKilled": False, "ExitCode": 0},
            }])
        if args[0] == "exec":
            return "0"
        raise AssertionError(args)

    monkeypatch.setattr(script, "docker", docker)
    script.settle_producers()

    stop_calls = [event[1] for event in events
                  if event[0] == "docker" and event[1][:2] == ("container", "stop")]
    assert stop_calls == [
        ("container", "stop", "--time", "150", IDS["frontend"]),
        ("container", "stop", "--time", "150", IDS["backend"]),
        ("container", "stop", "--time", "150", IDS["worker"]),
    ]
    inspect_calls = [event[1] for event in events
                     if event[0] == "docker" and event[1][:2] == ("container", "inspect")]
    assert [args[-1] for args in inspect_calls] == [
        IDS["frontend"], IDS["backend"], IDS["worker"]
    ]

    exec_calls = [event[1] for event in events
                  if event[0] == "docker" and event[1][0] == "exec"]
    assert len(exec_calls) == 1
    assert exec_calls[0][:-1] == (
        "exec", IDS["postgres"], "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
        "-U", script.POSTGRES_USER, "-d", script.POSTGRES_DB, "-Atc",
    )
    assert exec_calls[0][-1] == query
    assert "BEGIN READ ONLY;" in query
    assert not any(word in query.upper() for word in ("DELETE ", "UPDATE ", "INSERT ", "TRUNCATE "))

    exec_index = next(index for index, event in enumerate(events)
                      if event[0] == "docker" and event[1][0] == "exec")
    record_index = next(index for index, event in enumerate(events)
                        if event == ("record", "producers-settled"))
    assert all(index < exec_index for index, event in enumerate(events)
               if event[0] == "docker" and event[1][:2] == ("container", "inspect"))
    assert exec_index < record_index


@pytest.mark.parametrize("failure", ["inspect-exit-137", "stop-exit-137"])
def test_failed_or_forced_stop_blocks_journal_query_and_checkpoint(monkeypatch, failure):
    script = load_script()
    events = []
    install_checkpoint_fakes(monkeypatch, script, {"setup-complete"}, events)
    monkeypatch.setattr(script, "owned_resources", lambda: resource_fixture())

    def docker(*args):
        events.append(("docker", args))
        if args[:3] == ("container", "stop", "--time"):
            if failure == "stop-exit-137":
                raise subprocess.CalledProcessError(137, args)
            return ""
        if args[:2] == ("container", "inspect"):
            exit_code = 137 if failure == "inspect-exit-137" else 0
            return json.dumps([{
                "Id": args[-1],
                "State": {"Running": False, "OOMKilled": False, "ExitCode": exit_code},
            }])
        if args[0] == "exec":
            pytest.fail("Journal query must not run after a failed stop")
        raise AssertionError(args)

    monkeypatch.setattr(script, "docker", docker)

    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        script.settle_producers()

    assert not any(event[0] == "record" for event in events)
    assert not any(event[0] == "docker" and event[1][0] == "exec" for event in events)


def test_nonzero_unresolved_journal_count_blocks_checkpoint(monkeypatch):
    script = load_script()
    events = []
    install_checkpoint_fakes(monkeypatch, script, {"setup-complete"}, events)
    monkeypatch.setattr(script, "owned_resources", lambda: resource_fixture())

    def docker(*args):
        events.append(("docker", args))
        if args[:3] == ("container", "stop", "--time"):
            return ""
        if args[:2] == ("container", "inspect"):
            return json.dumps([{
                "Id": args[-1],
                "State": {"Running": False, "OOMKilled": False, "ExitCode": 0},
            }])
        if args[0] == "exec":
            return "2\n"
        raise AssertionError(args)

    monkeypatch.setattr(script, "docker", docker)

    with pytest.raises(RuntimeError, match="unresolved jobs"):
        script.settle_producers()

    assert not any(event[0] == "record" for event in events)
    assert sum(event[0] == "docker" and event[1][0] == "exec" for event in events) == 1


@pytest.mark.parametrize('signal_role,accepted', [('backend', True), ('worker', False)])
def test_uvicorn_sigterm_exit_is_not_generalized_to_worker(monkeypatch, signal_role, accepted):
    script = load_script()
    events = []
    install_checkpoint_fakes(monkeypatch, script, {'setup-complete'}, events)
    monkeypatch.setattr(script, 'owned_resources', resource_fixture)
    def docker(*args):
        if args[:2] == ('container', 'stop'):
            return ''
        if args[:2] == ('container', 'inspect'):
            return json.dumps([{'Id': args[-1], 'State': {
                'Running': False, 'OOMKilled': False,
                'ExitCode': 143 if args[-1] == IDS[signal_role] else 0}}])
        assert args[0] == 'exec'
        assert accepted, 'Unclean worker must not reach the journal check'
        return '0'
    monkeypatch.setattr(script, 'docker', docker)
    if accepted:
        script.settle_producers()
        assert ('record', 'producers-settled') in events
    else:
        with pytest.raises(RuntimeError, match='did not exit cleanly'):
            script.settle_producers()
        assert not any(event[0] == 'record' for event in events)
