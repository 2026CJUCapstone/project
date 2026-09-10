import copy
import importlib.util
from pathlib import Path
import socket

import pytest


def load_script():
    source = Path(__file__).resolve().parents[2] / 'scripts/e2e_stack_test.py'
    spec = importlib.util.spec_from_file_location('e2e_preflight_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('marker', ['.deploy', '.data', '.sandbox-work', '.env',
                                   'bpp_project.db', 'backend/bpp_project.db'])
def test_existing_workspace_state_is_rejected_without_changes(tmp_path, marker):
    script = load_script()
    target = tmp_path / marker
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'preserve this existing state')
    with pytest.raises(RuntimeError, match='fresh isolated checkout'):
        script.validate_test_workspace(tmp_path)
    assert target.read_bytes() == b'preserve this existing state'


def test_occupied_port_fails_without_touching_listener():
    script = load_script()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        address = listener.getsockname()
        with pytest.raises(RuntimeError, match='port is already in use'):
            script.check_test_ports((address[1], 0))
        assert listener.getsockname() == address


def test_preflight_failure_never_starts_or_stops_a_stack(monkeypatch):
    script = load_script()
    calls = []
    def fail(): raise RuntimeError('preflight refused')
    monkeypatch.setattr(script, 'preflight', fail)
    monkeypatch.setattr(script, 'run_command', lambda *args: calls.append(args))
    with pytest.raises(RuntimeError, match='preflight refused'):
        script.exercise_stack()
    assert calls == []


def test_all_services_require_finite_matching_resource_limits():
    script = load_script()
    model = {'name': script.E2E_NAMESPACE, 'services': {
        name: {'mem_limit': mem * 1024**2, 'memswap_limit': mem * 1024**2,
               'cpus': str(cpu), 'pids_limit': pids, 'restart': 'no'}
        for name, (mem, cpu, pids) in script.TEST_SERVICE_BUDGETS.items()
    }}
    script.validate_test_budget(model)
    # Actual Compose UnitBytes fields are strings; no unbounded/fuzzy parsing.
    strings = copy.deepcopy(model)
    for service in strings['services'].values():
        for field in ('mem_limit', 'memswap_limit'):
            service[field] = str(service[field])
    script.validate_test_budget(strings)
    for name in model['services']:
        for field, invalid in [('mem_limit', 0), ('mem_limit', True),
                               ('mem_limit', '256m'), ('mem_limit', '268435456.0'),
                               ('mem_limit', ' 268435456'), ('memswap_limit', -1),
                               ('cpus', 'nan'), ('cpus', '100'),
                               ('pids_limit', -1), ('restart', 'always')]:
            changed = copy.deepcopy(model)
            changed['services'][name][field] = invalid
            with pytest.raises(RuntimeError):
                script.validate_test_budget(changed)
    for changed in ({**model, 'name': 'production'},
                    {**model, 'services': {**model['services'], 'extra': {}}}):
        with pytest.raises(RuntimeError):
            script.validate_test_budget(changed)
