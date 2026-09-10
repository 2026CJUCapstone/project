"""Bounded, consistent DB evidence for a fenced runtime; never a stop permit.

No payloads, results, request URLs or credentials are selected. A caller must
still bind every process to exact Docker/kernel evidence and account for
separate sandbox containers before authorizing retirement.
"""
from dataclasses import asdict
import json
import socket

from sqlalchemy import func, or_, text

from app.models.database import (
    ActiveApiRequest, ApiProcessRecord, ExecutionJob, ExecutionRuntimeRecord,
    ExecutionWorkerRecord, WorkerProcessRecord,
)
from app.services.process_observation import local_process_state
from app.services.runtime_identity import RuntimeIdentity, validate_runtime_id
from app.services.runtime_registry import check_identity
from app.services.worker_process import ProcessIdentity, configured_scope, local_namespace_token


class RuntimeEvidence:
    def __init__(self,sessions,runtime,*,max_processes=256,max_lanes=1024):
        if not isinstance(runtime,RuntimeIdentity):
            raise ValueError('Exact runtime identity required')
        if (type(max_processes) is not int or not 1<=max_processes<=1024
                or type(max_lanes) is not int or not 1<=max_lanes<=4096):
            raise ValueError('Bounded runtime evidence capacity required')
        self.sessions,self.runtime = sessions,runtime
        self.max_processes,self.max_lanes = max_processes,max_lanes

    def snapshot(self):
        with self.sessions() as db:
            dialect = db.get_bind().dialect.name
            if dialect=='postgresql':
                # One MVCC snapshot across processes, lanes and active counts.
                db.connection(execution_options={'isolation_level':'REPEATABLE READ'})
                db.execute(text('SET TRANSACTION READ ONLY'))
                db.execute(text("SET LOCAL statement_timeout = '5s'"))
            elif dialect=='sqlite':
                # The legacy sqlite driver does not BEGIN for SELECT alone.
                db.execute(text('BEGIN'))
            else:
                raise ValueError('Consistent runtime evidence is unsupported on this database')
            runtime = db.get(ExecutionRuntimeRecord,self.runtime.id)
            check_identity(runtime,self.runtime)
            if runtime is None or runtime.draining_at is None:
                raise ValueError('Registered durable runtime fence required')
            processes = []
            for role,model in (('api',ApiProcessRecord),('worker',WorkerProcessRecord)):
                rows = db.query(model).filter_by(runtime_id=self.runtime.id).order_by(model.id).limit(
                    self.max_processes-len(processes)+1).all()
                if len(processes)+len(rows)>self.max_processes:
                    raise ValueError('Runtime process evidence exceeds capacity')
                for row in rows:
                    identity = ProcessIdentity(row.id,row.pid,row.start_token,row.hostname,row.scope)
                    processes.append({'role':role,**asdict(identity),'stopped':row.stopped_at is not None,
                        **({'draining':row.draining_at is not None} if role=='worker' else {})})
            api_ids = [p['epoch'] for p in processes if p['role']=='api']
            worker_ids = [p['epoch'] for p in processes if p['role']=='worker']
            # Include lanes pointing into this runtime's processes even if
            # their runtime metadata was corrupted; never hide them via join.
            rows = db.query(ExecutionWorkerRecord).filter(or_(
                ExecutionWorkerRecord.runtime_id==self.runtime.id,
                ExecutionWorkerRecord.process_id.in_(worker_ids))).order_by(
                ExecutionWorkerRecord.id).limit(self.max_lanes+1).all()
            if len(rows)>self.max_lanes:
                raise ValueError('Runtime lane evidence exceeds capacity')
            lanes = []
            for row in rows:
                validate_runtime_id(row.id)
                if (row.runtime_id!=self.runtime.id or row.process_id not in worker_ids
                        or (row.pool_id,row.deployment_sha,row.sandbox_pool_id)!=(
                            self.runtime.pool_id,self.runtime.deployment_sha,self.runtime.sandbox_pool_id)):
                    raise ValueError('Unbound or conflicting runtime lane; explicit reconciliation required')
                lanes.append({'id':row.id,'epoch':row.process_id,'draining':row.draining_at is not None})
            if db.query(ActiveApiRequest.id).filter(ActiveApiRequest.process_id.in_(api_ids),
                    ActiveApiRequest.kind.notin_(('http','websocket'))).limit(1).first() is not None:
                raise ValueError('Unknown active request kind; closure is unproven')
            requests = db.query(ActiveApiRequest.process_id,ActiveApiRequest.kind,func.count()).filter(
                ActiveApiRequest.process_id.in_(api_ids),ActiveApiRequest.kind.in_(('http','websocket'))).group_by(
                ActiveApiRequest.process_id,ActiveApiRequest.kind).limit(2*len(api_ids)+1).all()
            if len(requests)>2*len(api_ids):
                raise ValueError('Active request evidence exceeds capacity')
            counts = {(epoch,kind):count for epoch,kind,count in requests}
            claims = dict(db.query(ExecutionJob.worker_id,func.count()).filter(
                ExecutionJob.worker_id.in_([lane['id'] for lane in lanes]),
                ExecutionJob.status=='running').group_by(ExecutionJob.worker_id).all())
            for lane in lanes:
                # Expired leases still represent unresolved work.
                lane['active_claims'] = claims.get(lane['id'],0)
            for process in processes:
                if process['role']=='api':
                    process['active_http'] = counts.get((process['epoch'],'http'),0)
                    process['active_websockets'] = counts.get((process['epoch'],'websocket'),0)
                else:
                    process['active_claims'] = sum(lane['active_claims'] for lane in lanes
                        if lane['epoch']==process['epoch'])
            result = {'version':1,'runtime':asdict(self.runtime),'draining':True,
                'processes':processes,'lanes':lanes,
                'active_claims':sum(claims.values()),
                'active_http':sum(count for (_,kind),count in counts.items() if kind=='http'),
                'active_websockets':sum(count for (_,kind),count in counts.items() if kind=='websocket')}
            if len(json.dumps(result).encode())>262144:
                raise ValueError('Runtime evidence exceeds serialized capacity')
            return result

    def local(self,role):
        if role not in ('api','worker'):
            raise ValueError('Exact process role required')
        if local_namespace_token() is None:
            raise ValueError('Kernel namespace observation unavailable')
        hostname,scope = socket.gethostname(),configured_scope()
        report = self.snapshot()
        processes = []
        for process in report['processes']:
            if process['role']!=role or (process['hostname'],process['scope'])!=(hostname,scope):
                continue
            identity = ProcessIdentity(**{key:process[key] for key in
                ('epoch','pid','start_token','hostname','scope')})
            processes.append({'epoch':identity.epoch,'state':local_process_state(identity)})
        # Empty/unknown is reported honestly, never converted to absence.
        return {'version':1,'runtime':report['runtime'],'role':role,
            'hostname':hostname,'scope':scope,'processes':processes}
