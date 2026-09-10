"""Complete epoch coverage and stable two-system evidence, never zero-count stop."""
from copy import deepcopy
import json

import pytest

from tests.test_runtime_inventory import inventory
from tests.test_edge_deploy import edge
from runtime_binding import Binding, snapshot


@pytest.fixture
def binding(inventory):
    deploy, release, subject, containers, networks, calls = inventory
    for index, container in enumerate(containers.values()):
        container['Config']['Hostname'] = 'runtime-'+str(index)
    subject.capture()
    runtime = {'id': release.runtime_id, 'pool_id': subject.project,
        'deployment_sha': release.sha, 'sandbox_pool_id': subject.sandbox_pool}
    processes, lanes, reports = [], [], {}
    for index, container in enumerate(containers.values(), 1):
        role = container['Config']['Labels']['com.docker.compose.service']
        if role not in ('backend', 'worker'):
            continue
        role = 'api' if role == 'backend' else 'worker'
        epoch, scope = f'{index:032x}', f'{index:064x}'
        process = {'epoch': epoch, 'role': role, 'pid': 1, 'start_token': 'linux:fixture:42',
            'hostname': container['Config']['Hostname'], 'scope': scope, 'stopped': False}
        if role == 'api':
            process.update(active_http=0, active_websockets=1)
        else:
            process.update(active_claims=1, draining=True)
            lanes.append({'id': 'e'*32, 'epoch': epoch, 'draining': True, 'active_claims': 1})
        processes.append(process)
        reports[container['Id']] = {'version': 1, 'runtime': runtime, 'role': role,
            'hostname': process['hostname'], 'scope': scope,
            'processes': [{'epoch': epoch, 'state': 'alive'}]}
    db = {'version': 1, 'runtime': runtime, 'draining': True, 'processes': processes,
        'lanes': lanes, 'active_claims': 1, 'active_http': 0, 'active_websockets': 2}
    reads = []
    def read(identity, requested, role):
        assert requested == runtime
        reads.append((identity, role))
        if role is None:
            return json.dumps(db)
        expected_role = containers[identity]['Config']['Labels']['com.docker.compose.service']
        assert role == ('api' if expected_role == 'backend' else 'worker')
        return json.dumps(reports[identity])
    return Binding(subject, read=read), db, reports, containers, reads


def test_complete_match_preserves_unresolved_work_and_reports_alive_not_stop(binding):
    subject, db, reports, containers, reads = binding
    original = deepcopy(db)
    before = subject.inventory.path.read_bytes()
    result = subject.observe()
    assert result['snapshot'] == original and db == original
    assert {p['state'] for p in result['bindings'].values()} == {'alive'}
    assert len(result['bindings']) == 3
    assert len(reads) == 7 and reads[0][1] is None and reads[-1][1] is None
    for identity, report in reports.items():
        assert result['bindings'][report['processes'][0]['epoch']]['container_id'] == identity
    assert subject.inventory.path.read_bytes() == before
    assert not list((subject.inventory.store.path/'state'/'drains').iterdir())


@pytest.mark.parametrize('case', ['empty', 'unknown', 'foreign', 'duplicate', 'wrong-host',
    'wrong-scope', 'wrong-role', 'wrong-runtime', 'boolean-version'])
def test_refuses_local_evidence_without_complete_exact_identity(binding, case):
    subject, db, reports, containers, reads = binding
    report = next(iter(reports.values()))
    if case == 'empty': report['processes'] = []
    elif case == 'unknown': report['processes'][0]['state'] = 'unknown'
    elif case == 'foreign': report['processes'][0]['epoch'] = 'f'*32
    elif case == 'duplicate': report['processes'] *= 2
    elif case == 'wrong-host': report['hostname'] = 'foreign'
    elif case == 'wrong-scope': report['scope'] = 'f'*64
    elif case == 'wrong-role': report['role'] = 'worker'
    elif case == 'wrong-runtime': report['runtime'] = dict(report['runtime'], id='f'*32)
    elif case == 'boolean-version': report['version'] = True
    with pytest.raises(edge.EdgeError): subject.observe()


def test_unmatched_historical_epoch_is_not_erased_by_zero_totals(binding):
    subject, db, reports, containers, reads = binding
    extra = dict(db['processes'][0], epoch='f'*32, hostname='previous-container',
        active_websockets=0, stopped=True)
    db['processes'].append(extra)
    with pytest.raises(edge.EdgeError, match='Unmatched'): subject.observe()
    assert extra in db['processes']


def test_absence_does_not_close_claims_or_requests(binding):
    subject, db, reports, containers, reads = binding
    for report in reports.values(): report['processes'][0]['state'] = 'absent'
    result = subject.observe()
    assert all(item['state'] == 'absent' for item in result['bindings'].values())
    assert result['snapshot']['active_claims'] == 1
    assert result['snapshot']['active_websockets'] == 2
    assert not any(p['stopped'] for p in db['processes'])


@pytest.mark.parametrize('change', ['db', 'container', 'deadline'])
def test_cross_system_change_refuses_even_when_each_individual_read_succeeds(binding, change):
    subject, db, reports, containers, reads = binding
    read = subject.read
    clock = [0]
    subject.clock = lambda: clock[0]
    def changing(identity, requested, role):
        value = read(identity, requested, role)
        if role == 'worker':
            if change == 'db':
                db['active_websockets'] -= 1
                db['processes'][0]['active_websockets'] -= 1
            elif change == 'container': containers[identity]['RestartCount'] += 1
            else: clock[0] = 61
        return value
    subject.read = changing
    with pytest.raises(edge.EdgeError): subject.observe()


@pytest.mark.parametrize('change', ['duplicate-epoch', 'duplicate-lane', 'foreign-lane',
    'lane-total', 'runtime-total', 'boolean-count', 'negative-count', 'unfenced'])
def test_snapshot_ownership_and_aggregate_integrity(binding, change):
    subject, db, reports, containers, reads = binding
    if change == 'duplicate-epoch': db['processes'].append(db['processes'][0])
    elif change == 'duplicate-lane': db['lanes'] *= 2
    elif change == 'foreign-lane': db['lanes'][0]['epoch'] = 'f'*32
    elif change == 'lane-total': db['lanes'][0]['active_claims'] = 0
    elif change == 'runtime-total': db['active_claims'] = 0
    elif change == 'boolean-count': db['active_claims'] = True
    elif change == 'negative-count': db['processes'][0]['active_http'] = -1
    else: db['draining'] = False
    with pytest.raises(edge.EdgeError): snapshot(json.dumps(db), subject.runtime)


def test_duplicate_json_fields_are_not_silently_overwritten(binding):
    subject, db, reports, containers, reads = binding
    raw = json.dumps(db).replace('"version": 1', '"version": 2, "version": 1')
    with pytest.raises(edge.EdgeError, match='Malformed'): snapshot(raw, subject.runtime)


def test_worker_cannot_supply_matching_epoch_but_different_db_work(binding):
    subject, db, reports, containers, reads = binding
    read = subject.read
    worker = next(identity for identity, report in reports.items() if report['role'] == 'worker')
    def different_database(identity, requested, role):
        raw = read(identity, requested, role)
        if identity == worker and role is None:
            value = json.loads(raw)
            value['active_websockets'] -= 1
            value['processes'][0]['active_websockets'] -= 1
            return json.dumps(value)
        return raw
    subject.read = different_database
    with pytest.raises(edge.EdgeError, match='disagree'): subject.observe()


def test_false_inventory_verification_does_not_start_process_queries(binding, monkeypatch):
    subject, db, reports, containers, reads = binding
    monkeypatch.setattr(subject.inventory, 'verify', lambda: False)
    with pytest.raises(edge.EdgeError, match='Verified container inventory'): subject.observe()
    assert not reads
