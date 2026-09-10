"""Verified retirement primitives; no force-kill fallback or implicit adoption."""
from dataclasses import asdict
import json
import re
import subprocess

from edge_transaction import EdgeError, Release, fsync_directory
from runtime_inventory import exact_id, digest, MAX_RECORD_BYTES, INITIALIZERS
from runtime_binding import Binding, snapshot
from sandbox_inventory import SandboxInventory


def request_stop(container_id, *, signal='SIGTERM', timeout=10):
    """Request graceful stop of a previously verified exact container.

False means the owned CLI observation timed out, NOT that Docker canceled the
request or the process exited. Daemon timeout -1 forbids timed SIGKILL fallback.
The caller must durably record intent before calling and verify Docker lifetime
afterward. This function alone is not authorization to retire any container.
"""
    exact_id(container_id)
    if signal not in ('SIGTERM', 'SIGQUIT'):
        raise EdgeError('Explicit graceful stop signal required')
    if type(timeout) not in (int, float) or not .1 <= timeout <= 10:
        raise EdgeError('Bounded stop observation timeout required')
    try:
        result = subprocess.run(['docker', 'container', 'stop', '--signal', signal,
            '--timeout', '-1', container_id], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        # subprocess.run reaps its own client; no container kill/remove request.
        return False
    except (OSError, subprocess.SubprocessError):
        raise EdgeError('Graceful stop request unavailable; state unproven') from None
    if result.returncode:
        raise EdgeError('Graceful stop request failed; state unproven')
    return True


def begin_fence(container_id,runtime):
    """Exact configured-runtime CLI; retry is a monotonic idempotent fence."""
    from runtime_binding import _runtime
    exact_id(container_id)
    _runtime(runtime)
    try:
        result = subprocess.run(['docker','exec',container_id,'python','-m','app.runtime_drain',
            '--runtime',runtime['id'],'--pool',runtime['pool_id'],
            '--release',runtime['deployment_sha'],'--sandbox-pool',runtime['sandbox_pool_id'],'--begin'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,check=False)
    except (OSError,subprocess.SubprocessError):
        raise EdgeError('Runtime fence acknowledgment unavailable; intent retained') from None
    if result.returncode:
        raise EdgeError('Runtime fence failed; intent retained')
    # Binding subsequently reads the actual durable fence, never trusts exit0.


class Retirement:
    """One bounded, resumable step under the caller's deployment+state locks.

Preserves both promotion inventory and DB rows. Removes only a consumed local
drain marker after a durable retirement certificate and physical stop proof.
"""
    def __init__(self,deployment,release,*,binding=None,sandboxes=None,stop=request_stop,fence=begin_fence):
        self.deployment,self.release = deployment,release
        self.inventory = deployment.inventory(release)
        self.binding = binding or Binding(self.inventory)
        self.sandboxes = sandboxes or SandboxInventory(self.binding.runtime)
        self.stop,self.fence = stop,fence
        self.store = deployment.store
        self.path = self.store.path/'state'/('retirement-'+release.runtime_id+'.json')

    def _targets(self,retained):
        if self.store.pending() is not None or (retained is not None and retained.runtime_id==self.release.runtime_id):
            raise EdgeError('Only a non-active committed drain target may retire')
        paths = list((self.store.path/'state'/'drains').iterdir())
        if len(paths)>64:
            raise EdgeError('Drain registry exceeds capacity')
        matches = []
        for path in paths:
            if not re.fullmatch(r'[a-f0-9]{32}\.json',path.name):
                raise EdgeError('Unknown drain registry entry')
            value = self.store.read_json(path)
            if (not isinstance(value,dict) or type(value.get('version')) is not int or value['version']!=1
                    or value.get('operationId')!=path.stem or value.get('retained')!=self.store.expected(retained)
                    or not isinstance(value.get('retire'),list) or not 1<=len(value['retire'])<=2):
                raise EdgeError('Drain registry identity differs from retained routing')
            seen = set()
            for target in value['retire']:
                candidate = Release(**target['release'])
                if candidate.runtime_id in seen:
                    raise EdgeError('Duplicate runtime in drain registry')
                seen.add(candidate.runtime_id)
                if candidate.runtime_id==self.release.runtime_id:
                    if (candidate!=self.release or set(target)!={'generation','release','layout','templateSha256'}
                            or target['generation']!=candidate.generation or target['layout']!=asdict(self.store.layout)
                            or not isinstance(target['templateSha256'],str)
                            or not re.fullmatch('[a-f0-9]{64}',target['templateSha256'])):
                        raise EdgeError('Drain target metadata differs')
                    matches.append((path,value))
        if not matches:
            raise EdgeError('Explicit committed drain target required')
        return matches

    def _write(self,state):
        self.store.write(self.path,state)

    def _finish_markers(self,matches):
        # A failed first candidate is still reserved, but its fenced runtime
        # must never be reused by candidate(). Certificate precedes this unlink;
        # remove the exact reservation before markers so interruption is safe.
        if self.deployment.reserved()==self.release:
            (self.store.path/'state'/'candidate.json').unlink()
            fsync_directory(self.store.path/'state')
        for path,value in matches:
            remaining = [item for item in value['retire'] if item['release']['runtime_id']!=self.release.runtime_id]
            if remaining:
                self.store.write(path,{**value,'retire':remaining})
            else:
                path.unlink()
                fsync_directory(path.parent)

    def step(self):
        try:
            return self._step()
        except (ValueError,TypeError,KeyError,AttributeError,StopIteration,RecursionError):
            raise EdgeError('Invalid retirement state; evidence retained') from None

    def _step(self):
        retained = self.store.committed()
        original = self.store.read_json(self.inventory.path,max_bytes=MAX_RECORD_BYTES)
        containers = {c['id']:c for c in original['containers']}
        stopping = {identity for identity,c in containers.items() if c['role'] not in INITIALIZERS}
        try:
            state = self.store.read_json(self.path,max_bytes=MAX_RECORD_BYTES)
        except FileNotFoundError:
            state = None
        if state is not None:
            if (not isinstance(state,dict) or set(state)!={'version','release','retained','inventory','phase','requested','proof'}
                    or type(state['version']) is not int or state['version']!=1
                    or state['release']!=asdict(self.release) or state['inventory']!=digest(original)
                    or state['phase'] not in ('fencing','draining','stopping','retired')
                    or not isinstance(state['requested'],list) or any(not isinstance(i,str) for i in state['requested'])
                    or len(set(state['requested']))!=len(state['requested']) or not set(state['requested'])<=stopping):
                raise EdgeError('Retirement journal identity mismatch')
        # A completed certificate is historical, not authority to stop a new
        # incarnation. Retry only consumes residual matching markers below.
        matches = self._targets(retained)
        if retained is None:
            # HTTP 503 alone could come from an unrelated/failed application.
            # Prove the owned running edge adopted the precise closed template
            # and that durable config cannot reopen the failed candidate.
            container = self.deployment.runtime.preflight()
            if (container is None or not container['State']['Running']
                    or self.deployment.runtime.observe()!=self.store.expected(None)
                    or (self.store.path/'config'/'nginx.conf').read_text()!=self.store.configuration(None)):
                raise EdgeError('Closed edge configuration is unproven; retirement paused')
        if self.deployment.verify(retained,edge=True) is not True:
            raise EdgeError('Retained routing is not healthy; retirement paused')
        retained_identity = asdict(retained) if retained is not None else None
        if state is None:
            if self.inventory.verify() is not True:
                raise EdgeError('Exact retirement inventory required')
            state = {'version':1,'release':asdict(self.release),'retained':retained_identity,
                'inventory':digest(original),'phase':'fencing','requested':[],'proof':None}
            self._write(state)  # Durable intent precedes every external effect.
        if state['retained']!=retained_identity:
            raise EdgeError('Retained release changed during retirement')
        if state['phase']=='fencing':
            if state['requested'] or state['proof'] is not None or self.inventory.verify() is not True:
                raise EdgeError('Invalid pre-fence retirement state')
            source = next(c['id'] for c in containers.values() if c['role']=='backend')
            self.fence(source,self.binding.runtime)
            state['phase']='draining'
            self._write(state)
        if state['phase']=='draining':
            if state['requested'] or state['proof'] is not None:
                raise EdgeError('Invalid pre-stop retirement state')
            proof = self.binding.observe()
            report = proof['snapshot']
            if any(report[key] for key in ('active_http','active_websockets','active_claims')):
                return {'phase':'draining','runtime':self.release.runtime_id}
            if self.sandboxes.empty() is not True:
                raise EdgeError('Confirmed sandbox absence required')
            state.update(phase='stopping',proof=proof)
            self._write(state)
        # Validate persisted zero-work evidence on every partial/restarted step.
        proof = state['proof']
        report = snapshot(json.dumps(proof['snapshot']),self.binding.runtime)
        if (proof['runtime']!=self.binding.runtime or set(proof['bindings'])!={p['epoch'] for p in report['processes']}
                or any(report[k] for k in ('active_http','active_websockets','active_claims'))
                or any(item['container_id'] not in stopping or item['state'] not in ('alive','absent')
                       for item in proof['bindings'].values())):
            raise EdgeError('Complete quiescent process proof required')
        stopped = self.inventory.verify_retiring(set(state['requested']))
        if state['phase']=='retired' and stopped!=stopping:
            raise EdgeError('Retired certificate conflicts with physical state')
        if self.sandboxes.empty() is not True:
            raise EdgeError('Runtime sandbox absence no longer confirmed')
        if stopped==stopping:
            state['phase']='retired'
            self._write(state)  # Certificate before consuming the drain marker.
            self._finish_markers(matches)
            return {'phase':'retired','runtime':self.release.runtime_id}
        order = ('frontend','proxy-controller','api-proxy','backend','worker','pgbouncer')
        identity = next(c['id'] for role in order for c in containers.values()
                        if c['role']==role and c['id'] not in stopped)
        if identity not in state['requested']:
            state['requested'].append(identity)
            self._write(state)
        role = containers[identity]['role']
        self.stop(identity,signal='SIGQUIT' if role in ('frontend','api-proxy') else 'SIGTERM')
        # Even successful Docker CLI exit is not physical evidence. The next
        # step independently verifies stopped lifetimes and sandbox absence.
        return {'phase':'stopping','runtime':self.release.runtime_id}
