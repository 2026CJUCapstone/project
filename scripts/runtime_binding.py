"""Bind fenced DB process epochs to exact, unchanged Docker incarnations.

Read-only diagnostic evidence, not retirement authorization. Sandboxes and
physical shutdown still require separate reconciliation and verification.
"""
import json
import re
import subprocess
import threading
import time

from edge_transaction import EdgeError
from runtime_inventory import MAX_RECORD_BYTES, exact_id

MAX_OUTPUT_BYTES = 262144


def _match(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _runtime(value):
    if (not isinstance(value, dict) or set(value) != {
            'id', 'pool_id', 'deployment_sha', 'sandbox_pool_id'}
            or not _match(value['id'], '[a-f0-9]{32}') or value['id'] == '0'*32
            or not _match(value['deployment_sha'], '[a-f0-9]{40}')
            or any(not _match(value[k], '[a-z0-9][a-z0-9_-]{0,79}')
                   for k in ('pool_id', 'sandbox_pool_id'))):
        raise EdgeError('Exact runtime evidence identity required')
    return value


def read_evidence(container_id, runtime, role=None, *, timeout=15):
    """Fixed private read-only command; bound bytes before decoding/parsing."""
    exact_id(container_id)
    _runtime(runtime)
    if role not in (None, 'api', 'worker'):
        raise EdgeError('Exact evidence role required')
    if type(timeout) not in (int, float) or not .1 <= timeout <= 15:
        raise EdgeError('Bounded evidence timeout required')
    args = ['docker', 'exec', container_id, 'python', '-m', 'app.runtime_inspect',
            '--runtime', runtime['id'], '--pool', runtime['pool_id'],
            '--release', runtime['deployment_sha'], '--sandbox-pool', runtime['sandbox_pool_id']]
    if role is not None:
        args += ['--local-role', role]
    try:
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        raise EdgeError('Runtime evidence command unavailable') from None
    output = []
    def read():
        try:
            output.append(child.stdout.read(MAX_OUTPUT_BYTES+1))
        except (OSError, ValueError):
            pass
    reader = threading.Thread(target=read, daemon=True)
    deadline = time.monotonic()+timeout
    try:
        reader.start()
        reader.join(max(0, deadline-time.monotonic()))
        if reader.is_alive() or not output or len(output[0]) > MAX_OUTPUT_BYTES:
            raise EdgeError('Runtime evidence exceeded time or size limit')
        if child.wait(timeout=max(.001, deadline-time.monotonic())):
            raise EdgeError('Runtime evidence command failed')
        return output[0].decode('utf-8')
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise EdgeError('Runtime evidence command unavailable') from None
    finally:
        if child.poll() is None:
            child.kill()  # This owned Docker client only, never the runtime.
        child.wait(timeout=5)
        reader.join(5)
        child.stdout.close()


def _object(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('Duplicate field')
            value[key] = item
        return value
    try:
        if not isinstance(raw, str) or len(raw.encode()) > MAX_OUTPUT_BYTES:
            raise ValueError('Oversized evidence')
        value = json.loads(raw, object_pairs_hook=pairs)
        if not isinstance(value, dict):
            raise ValueError('Object required')
        return value
    except (ValueError, TypeError, RecursionError):
        raise EdgeError('Malformed runtime evidence') from None


def _count(value):
    if type(value) is not int or not 0 <= value <= 2**63-1:
        raise EdgeError('Invalid active work count')
    return value


def snapshot(raw, runtime):
    value = _object(raw)
    if (set(value) != {'version', 'runtime', 'draining', 'processes', 'lanes',
                       'active_claims', 'active_http', 'active_websockets'}
            or type(value['version']) is not int or value['version'] != 1
            or value['runtime'] != runtime or value['draining'] is not True
            or not isinstance(value['processes'], list) or not 1 <= len(value['processes']) <= 256
            or not isinstance(value['lanes'], list) or len(value['lanes']) > 1024):
        raise EdgeError('Complete fenced runtime evidence required')
    epochs = {}
    for process in value['processes']:
        if not isinstance(process, dict):
            raise EdgeError('Invalid process evidence')
        role = process.get('role')
        extra = {'active_http', 'active_websockets'} if role == 'api' else {'active_claims', 'draining'}
        if (role not in ('api', 'worker') or set(process) != {
                'role', 'epoch', 'pid', 'start_token', 'hostname', 'scope', 'stopped'} | extra
                or not _match(process['epoch'], '[a-f0-9]{32}') or process['epoch'] == '0'*32
                or process['epoch'] in epochs or type(process['pid']) is not int or process['pid'] < 1
                or not _match(process['start_token'], '[a-z0-9:-]{1,160}')
                or not _match(process['hostname'], '[a-zA-Z0-9][a-zA-Z0-9_.-]{0,252}')
                or not _match(process['scope'], '[a-f0-9]{64}')
                or type(process['stopped']) is not bool
                or (role == 'worker' and type(process['draining']) is not bool)):
            raise EdgeError('Ambiguous process ownership evidence')
        for key in extra-{'draining'}:
            _count(process[key])
        epochs[process['epoch']] = process
    lanes = set()
    claims = {epoch: 0 for epoch, p in epochs.items() if p['role'] == 'worker'}
    for lane in value['lanes']:
        if (not isinstance(lane, dict) or set(lane) != {'id', 'epoch', 'draining', 'active_claims'}
                or not _match(lane['id'], '[a-f0-9]{32}') or lane['id'] == '0'*32
                or lane['id'] in lanes or not isinstance(lane['epoch'], str) or lane['epoch'] not in claims
                or type(lane['draining']) is not bool):
            raise EdgeError('Unbound or ambiguous worker lane evidence')
        lanes.add(lane['id'])
        claims[lane['epoch']] += _count(lane['active_claims'])
    if any(epochs[epoch]['active_claims'] != total for epoch, total in claims.items()):
        raise EdgeError('Worker claim totals differ from lane evidence')
    for key in ('active_claims', 'active_http', 'active_websockets'):
        if _count(value[key]) != sum(p.get(key, 0) for p in epochs.values()):
            raise EdgeError('Runtime work totals differ from process evidence')
    return value


class Binding:
    def __init__(self, inventory, *, read=read_evidence, clock=time.monotonic):
        self.inventory, self.read, self.clock = inventory, read, clock
        self.runtime = _runtime({'id': inventory.release.runtime_id, 'pool_id': inventory.project,
            'deployment_sha': inventory.release.sha, 'sandbox_pool_id': inventory.sandbox_pool})

    def observe(self):
        """Only a complete stable DB + Docker + local kernel match succeeds."""
        try:
            return self._observe()
        except (ValueError, TypeError, KeyError, AttributeError, StopIteration, RecursionError):
            raise EdgeError('Malformed runtime binding evidence') from None

    def _observe(self):
        deadline = self.clock()+60
        def checked_read(identity, role=None):
            if self.clock() >= deadline:
                raise EdgeError('Runtime binding observation timed out')
            result = self.read(identity, self.runtime, role)
            if self.clock() >= deadline:
                raise EdgeError('Runtime binding observation timed out')
            return result
        if self.inventory.verify() is not True:
            raise EdgeError('Verified container inventory required')
        owned = self.inventory.store.read_json(self.inventory.path, max_bytes=MAX_RECORD_BYTES)
        containers = [c for c in owned['containers'] if c['role'] in ('backend', 'worker')]
        if (not containers or any(not _match(c.get('hostname'), '[a-zA-Z0-9][a-zA-Z0-9_.-]{0,252}')
                for c in containers) or len({c['hostname'] for c in containers}) != len(containers)):
            raise EdgeError('Distinct immutable container hostnames required')
        source = next(c['id'] for c in containers if c['role'] == 'backend')
        before = snapshot(checked_read(source), self.runtime)
        bound = {}
        for container in containers:
            # Every process container must see the same complete DB evidence,
            # not merely a copied local epoch in a differently scoped database.
            if container['id'] != source and snapshot(checked_read(container['id']), self.runtime) != before:
                raise EdgeError('Process containers disagree on runtime DB evidence')
            role = 'api' if container['role'] == 'backend' else 'worker'
            report = _object(checked_read(container['id'], role))
            if (set(report) != {'version', 'runtime', 'role', 'hostname', 'scope', 'processes'}
                    or type(report['version']) is not int or report['version'] != 1
                    or report['runtime'] != self.runtime or report['role'] != role
                    or report['hostname'] != container['hostname']
                    or not _match(report['scope'], '[a-f0-9]{64}')
                    or not isinstance(report['processes'], list) or not 1 <= len(report['processes']) <= 256):
                raise EdgeError('Local container evidence identity mismatch')
            expected = {p['epoch'] for p in before['processes'] if (p['role'], p['hostname'], p['scope']) ==
                        (role, report['hostname'], report['scope'])}
            found = set()
            for process in report['processes']:
                if (not isinstance(process, dict) or set(process) != {'epoch', 'state'}
                        or not isinstance(process['epoch'], str) or process['epoch'] not in expected
                        or process['epoch'] in found or process['epoch'] in bound
                        or process['state'] not in ('alive', 'absent')):
                    raise EdgeError('Missing, unknown or ambiguous local process evidence')
                found.add(process['epoch'])
                bound[process['epoch']] = {'container_id': container['id'], 'state': process['state']}
            if found != expected:
                raise EdgeError('Local process evidence is incomplete')
        if set(bound) != {p['epoch'] for p in before['processes']}:
            raise EdgeError('Unmatched registered process requires explicit reconciliation')
        after = snapshot(checked_read(source), self.runtime)
        if self.inventory.verify() is not True:
            raise EdgeError('Verified container inventory required')
        if before != after:
            raise EdgeError('DB evidence changed during observation; retry required')
        if self.clock() >= deadline:
            raise EdgeError('Runtime binding observation timed out')
        return {'version': 1, 'runtime': self.runtime, 'snapshot': before, 'bindings': bound}
