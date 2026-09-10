import copy
import importlib.util
from pathlib import Path

import pytest


def load_script():
    source = Path(__file__).resolve().parents[2] / 'scripts/e2e_stack_test.py'
    spec = importlib.util.spec_from_file_location('e2e_limits_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def model(script):
    rows = []
    for name, (memory, cpu, pids) in script.TEST_SERVICE_BUDGETS.items():
        host = {'Memory': memory * 1024**2, 'MemorySwap': memory * 1024**2,
                'NanoCpus': int(cpu * 1_000_000_000), 'PidsLimit': pids,
                'RestartPolicy': {'Name': 'no'}}
        if name in ('backend', 'frontend'):
            internal, published = (('8000/tcp', script.BACKEND_PORT) if name == 'backend'
                                   else ('8080/tcp', script.FRONTEND_PORT))
            host['PortBindings'] = {internal: [{'HostIp': '127.0.0.1', 'HostPort': str(published)}]}
        rows.append({'Config': {'Labels': {'com.docker.compose.service': name}},
                     'HostConfig': host,
                     'State': {'Running': name != 'initialize', 'ExitCode': 0, 'OOMKilled': False}})
    return {'container': rows}


def test_all_actual_limits_must_match_before_requests(monkeypatch):
    script = load_script()
    original = model(script)
    monkeypatch.setattr(script, 'owned_resources', lambda: original)
    script.verify_started_stack()
    for index in range(7):
        for key, value in [('Memory', 0), ('MemorySwap', -1), ('NanoCpus', 0),
                            ('PidsLimit', -1), ('RestartPolicy', {'Name': 'always'})]:
            changed = copy.deepcopy(original)
            changed['container'][index]['HostConfig'][key] = value
            monkeypatch.setattr(script, 'owned_resources', lambda: changed)
            with pytest.raises(RuntimeError, match='resource limits'):
                script.verify_started_stack()


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'oom', 'initializer', 'stopped', 'public_port'])
def test_missing_services_bad_state_or_wrong_listener_are_rejected(monkeypatch, fault):
    script = load_script()
    data = model(script)
    rows = data['container']
    services = {r['Config']['Labels']['com.docker.compose.service']: r for r in rows}
    if fault == 'missing': rows.pop()
    if fault == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    if fault == 'oom': rows[0]['State']['OOMKilled'] = True
    if fault == 'initializer': services['initialize']['State']['ExitCode'] = 1
    if fault == 'stopped': services['worker']['State']['Running'] = False
    if fault == 'public_port':
        services['frontend']['HostConfig']['PortBindings']['8080/tcp'][0]['HostIp'] = '0.0.0.0'
    monkeypatch.setattr(script, 'owned_resources', lambda: data)
    with pytest.raises(RuntimeError): script.verify_started_stack()
