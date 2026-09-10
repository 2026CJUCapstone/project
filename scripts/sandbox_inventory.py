"""Read-only sandbox ownership checks for a durably fenced runtime."""
import json
import re
import time

from edge_transaction import EdgeError
from runtime_binding import _runtime
from runtime_inventory import bounded_docker, exact_id


class SandboxInventory:
    def __init__(self,runtime,*,call=bounded_docker,clock=time.monotonic):
        self.runtime = _runtime(runtime)
        self.call,self.clock = call,clock

    def _read(self,args):
        if self.clock()>=self.deadline:
            raise EdgeError('Sandbox observation timed out')
        raw = self.call(args)
        if not isinstance(raw,str) or len(raw.encode())>262144 or self.clock()>=self.deadline:
            raise EdgeError('Sandbox observation exceeded bounded capacity')
        return raw

    def _observe(self):
        raw = self._read(['container','ls','--all','--no-trunc','--filter',
            'label=webcompiler.pool='+self.runtime['sandbox_pool_id'],'--format','{{.ID}}'])
        ids = raw.splitlines()
        if len(ids)>256 or len(set(ids))!=len(ids):
            raise EdgeError('Sandbox pool inventory exceeds bounded capacity')
        found = set()
        for identity in ids:
            exact_id(identity)
            data = json.loads(self._read(['container','inspect',identity]))
            if not isinstance(data,list) or len(data)!=1 or data[0]['Id']!=identity:
                raise EdgeError('Sandbox container identity mismatch')
            labels = data[0]['Config'].get('Labels') or {}
            # Legacy/unbound sandboxes cannot silently be attributed to a
            # different runtime, even if this runtime's DB has no active job.
            if (labels.get('webcompiler.pool')!=self.runtime['sandbox_pool_id']
                    or labels.get('webcompiler.runtime-version')!='1'):
                raise EdgeError('Unbound sandbox requires explicit reconciliation')
            runtime = _runtime({'id':labels.get('webcompiler.runtime'),
                'pool_id':labels.get('webcompiler.runtime-pool'),
                'deployment_sha':labels.get('webcompiler.release'),
                'sandbox_pool_id':labels.get('webcompiler.pool')})
            for key in ('webcompiler.worker','webcompiler.process','webcompiler.lease'):
                value = labels.get(key)
                if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value) or value=='0'*32:
                    raise EdgeError('Sandbox process/claim ownership is unproven')
            job = labels.get('webcompiler.job')
            if (not isinstance(job,str)
                    or not re.fullmatch('[a-f0-9]{32}|[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}',job)
                    or job.replace('-','')=='0'*32):
                raise EdgeError('Sandbox job ownership is unproven')
            if runtime['id']==self.runtime['id']:
                if runtime!=self.runtime:
                    raise EdgeError('Sandbox runtime metadata conflicts')
                found.add(identity)  # Exited leftovers also require cleanup.
        return found

    def empty(self):
        self.deadline = self.clock()+45
        try:
            first = self._observe()
            second = self._observe()
            if first or second:
                raise EdgeError('Runtime sandbox containers remain')
            return True
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError):
            raise EdgeError('Malformed sandbox ownership evidence') from None
