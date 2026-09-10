"""Read-only same-namespace observations; not a container retirement permit."""
import os
import socket

from app.models.database import ApiProcessRecord, ExecutionRuntimeRecord, WorkerProcessRecord
from app.services.runtime_identity import RuntimeIdentity, validate_runtime_id
from app.services.runtime_registry import check_identity
from app.services.worker_process import ProcessIdentity, configured_scope, local_namespace_token, process_start_token


def local_process_state(process):
    """Never turn permission/namespace/parse failures into evidence of absence."""
    if not isinstance(process, ProcessIdentity):
        raise ValueError('Exact process identity required')
    try:
        if (local_namespace_token() is None or process.hostname != socket.gethostname()
                or process.scope != configured_scope()):
            return 'unknown'
        try:
            token = process_start_token(process.pid)
        except FileNotFoundError as exc:
            # Missing boot/proc infrastructure is not an absent target. Also
            # check signal0 so a hidden proc entry is not classified as dead.
            if exc.filename != f'/proc/{process.pid}/stat':
                return 'unknown'
            try:
                os.kill(process.pid, 0)
            except ProcessLookupError:
                return 'absent'
            except OSError:
                return 'unknown'
            return 'unknown'
        except ProcessLookupError:
            return 'absent'  # Kernel observer also proves no surviving threads.
        return 'alive' if token == process.start_token else 'absent'
    except Exception:
        return 'unknown'


class ProcessObserver:
    def __init__(self, sessions, runtime):
        if not isinstance(runtime, RuntimeIdentity):
            raise ValueError('Exact runtime identity required')
        self.sessions, self.runtime = sessions, runtime

    def observe(self, role, epoch):
        if role not in ('api','worker'):
            raise ValueError('Invalid process role')
        validate_runtime_id(epoch)
        model = ApiProcessRecord if role == 'api' else WorkerProcessRecord
        with self.sessions() as db:
            runtime = db.get(ExecutionRuntimeRecord, self.runtime.id)
            check_identity(runtime, self.runtime)
            row = db.get(model, epoch)
            if runtime is None or row is None or row.runtime_id != self.runtime.id:
                raise ValueError('Exact registered process required')
            process = ProcessIdentity(row.id,row.pid,row.start_token,row.hostname,row.scope)
        return {'runtime_id':self.runtime.id,'role':role,'epoch':epoch,'state':local_process_state(process)}
