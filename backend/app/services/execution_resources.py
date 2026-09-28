"""Server-owned peak reservations; tmpfs is already within cgroup memory.

CPU is concurrent CPU allocation, not a submission's accumulated CPU deadline.
Reservations remain charged while status is running, including ambiguous Docker
operations and expired leases. They are not reconstructed from heartbeat age.
"""
from dataclasses import dataclass
import math

from app.models.judge_policy import RuntimeLimits
from app.models.judge_test_manifest import test_data_buffer_bytes,has_stored_cases


@dataclass(frozen=True)
class ResourceBudget:
    memory_bytes: int
    cpu_millis: int
    legacy_memory_bytes: int
    legacy_cpu_millis: int
    overhead_bytes: int = 0
    worker_class: str = 'legacy'

    def __post_init__(self):
        for value in (self.memory_bytes, self.cpu_millis, self.legacy_memory_bytes, self.legacy_cpu_millis):
            if type(value) is not int or value <= 0:
                raise ValueError('Positive integer resource budgets required')
        if type(self.overhead_bytes) is not int or self.overhead_bytes < 0:
            raise ValueError('Nonnegative outside-cgroup overhead required')
        if self.legacy_memory_bytes + self.overhead_bytes > self.memory_bytes or self.legacy_cpu_millis > self.cpu_millis:
            raise ValueError('Legacy execution cannot fit the configured worker host budget')
        if not isinstance(self.worker_class, str) or not self.worker_class:
            raise ValueError('Worker resource class required')

    def reservation(self, payload, scope):
        contract = payload.get('judge_contract')
        if has_stored_cases(payload.get('sample',[]),payload.get('hidden',[])) and (
                not isinstance(contract,dict) or contract.get('kind')!='measured-v1'):
            raise ValueError('Stored test reservations require measured execution')
        memory, cpu, worker_class = self.legacy_memory_bytes, self.legacy_cpu_millis, None
        if contract is not None:
            if not isinstance(contract, dict):
                raise ValueError('Invalid receipt resource contract')
            if contract.get('kind') == 'measured-v1':
                profile = RuntimeLimits.model_validate(contract.get('profile'))
                memory = max(profile.compile.memory_bytes, profile.run.memory_bytes)
                buffers=test_data_buffer_bytes(payload.get('sample',[]),payload.get('hidden',[]))
                if buffers and (type(contract.get('testDataBufferBytes')) is not int
                                or contract['testDataBufferBytes']!=buffers):
                    raise ValueError('Receipt test data reservation mismatch')
                if not buffers and 'testDataBufferBytes' in contract:
                    raise ValueError('Unexpected test data reservation')
                memory+=buffers
                # One CPU allocation per measured execution lane. Aggregate
                # cpuMs is independently enforced by the measured supervisor.
                cpu, worker_class = 1000, profile.worker_class
                if type(contract.get('reservationBytes')) is not int or contract['reservationBytes'] != memory:
                    raise ValueError('Receipt reservation does not match stage limits')
            elif contract.get('kind') == 'legacy-v1':
                memory = contract.get('memoryBytes')
                quota = contract.get('cpuQuota')
                if (type(memory) is not int or memory <= 0 or type(quota) not in (int, float)
                        or not math.isfinite(quota) or quota <= 0):
                    raise ValueError('Invalid legacy receipt resource limits')
                cpu = math.ceil(quota * 1000)
            else:
                raise ValueError('Unknown resource contract')
        return {'version': 1, 'scope': scope, 'memoryBytes': memory + self.overhead_bytes,
                'cpuMillis': cpu, 'workerClass': worker_class}

    def fits(self, reservation, used_memory=0, used_cpu=0):
        return (used_memory + reservation['memoryBytes'] <= self.memory_bytes
                and used_cpu + reservation['cpuMillis'] <= self.cpu_millis)
