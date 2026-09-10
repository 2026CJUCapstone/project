"""Durable execution worker primitives; API acceptance is wired separately.

A pool currently represents one Docker host. All replicas for that pool must
share its Docker daemon; independent worker hosts need explicit placement.
"""
import asyncio
import contextlib
import logging
import re
import shutil
from threading import Event
from uuid import uuid4
from pathlib import Path

from docker.errors import NotFound

from app.core.config import settings
from app.services.compiler import DockerCompilerRunner
from app.services.compile_queue import classify_compile_result, classify_run_result
from app.services.judging import judge_code
from app.services.terminal_broker import TerminalClosed, TerminalLimit
from app.services.durable_queue import WorkerIdentity
from app.services.sandbox_identity import sandbox_labels

logger = logging.getLogger(__name__)


class SandboxPool:
    def __init__(self, client_factory=None, *, pool_id=None):
        self.client_factory = client_factory or DockerCompilerRunner()._get_client
        self.pool_id = settings.SANDBOX_POOL_ID if pool_id is None else pool_id
        if not isinstance(self.pool_id,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',self.pool_id):
            raise ValueError('Exact sandbox pool required')

    def labels(self, job_id, token):
        if not re.fullmatch(r'[a-f0-9-]{32,36}', job_id) or not re.fullmatch(r'[a-f0-9]{32}', token):
            raise ValueError('Invalid sandbox ownership')
        return {'webcompiler.pool': self.pool_id, 'webcompiler.job': job_id, 'webcompiler.lease': token}

    def reap(self, job_id, token):
        labels = self.labels(job_id, token)
        self.reap_claim(labels)

    def reap_claim(self, expected, *, daemon_id=None):
        """Sweep only the original claim's fully validated provenance."""
        job_id, token = expected['webcompiler.job'], expected['webcompiler.lease']
        labels = self.labels(job_id, token)
        if any(expected.get(key) != value for key, value in labels.items()):
            raise RuntimeError('Sandbox cleanup pool mismatch')
        client = self.client_factory()
        if daemon_id is not None and self._daemon_identity(client) != daemon_id:
            raise RuntimeError('Sandbox cleanup daemon mismatch')
        containers = client.containers.list(all=True, filters={'label': [f'{key}={value}' for key, value in labels.items()]})
        for container in containers:
            # Do not rely on the API filter alone for a destructive action.
            if any(container.labels.get(key) != value for key, value in expected.items()):
                raise RuntimeError('Sandbox ownership mismatch')
        for container in containers:
            try:
                container.remove(force=True)
            except NotFound:
                pass
        if daemon_id is not None:
            remaining = client.containers.list(all=True, filters={
                'label': [f'{key}={value}' for key, value in labels.items()]})
            if remaining or self._daemon_identity(client) != daemon_id:
                raise RuntimeError('Sandbox cleanup absence is not confirmed')
        # On Docker errors propagate: unconfirmed termination retains capacity.
        root = Path(settings.SANDBOX_WORKDIR_ROOT).resolve()
        for candidate in root.glob(f'job-{job_id}-{token}-*'):
            # Only this claim's generated immediate child dirs, never a broad
            # workspace/root or a symlink leading outside the sandbox directory.
            if candidate.is_symlink() or candidate.resolve().parent != root:
                raise RuntimeError('Unsafe sandbox work directory')
            if candidate.is_dir():
                shutil.rmtree(candidate)

    def _operation_target(self, operation, labels):
        """Validate private journal provenance before touching Docker."""
        if (operation.get('version') != 1 or operation.get('kind') not in ('create', 'start')
                or operation.get('lease_token') != labels.get('webcompiler.lease')
                or labels.get('webcompiler.pool') != self.pool_id
                or not isinstance(operation.get('id'), str)
                or not re.fullmatch('[a-f0-9]{32}', operation['id'])):
            raise RuntimeError('Invalid sandbox operation journal')
        expected = dict(labels)
        if operation['kind'] == 'create':
            name = 'compiler-' + operation['lease_token'] + '-' + operation['id']
            if operation.get('name') != name or operation.get('container_id') is not None:
                raise RuntimeError('Invalid sandbox create identity')
            expected['webcompiler.operation'] = operation['id']
            target = name
        else:
            target = operation.get('container_id')
            if not isinstance(target, str) or not re.fullmatch('[a-f0-9]{64}', target):
                raise RuntimeError('Invalid sandbox start identity')
        return target, expected

    @staticmethod
    def _check_operation_container(container, expected, *, identity=None, name=None):
        if (not isinstance(container.id, str) or not re.fullmatch('[a-f0-9]{64}', container.id)
                or (identity is not None and container.id != identity)
                or (name is not None and container.name != name)
                or any(container.labels.get(key) != value for key, value in expected.items())):
            raise RuntimeError('Sandbox operation ownership mismatch')

    def observe_operation(self, operation, labels):
        target, expected = self._operation_target(operation, labels)
        client = self.client_factory()
        daemon_id = self._daemon_identity(client)
        try:
            container = client.containers.get(target)
        except NotFound:
            # No positive engine binding yet: this could be the wrong daemon.
            return None
        self._check_operation_container(container, expected,
            identity=target if operation['kind'] == 'start' else None,
            name=target if operation['kind'] == 'create' else None)
        if self._daemon_identity(client) != daemon_id:
            raise RuntimeError('Sandbox daemon changed during observation')
        return {'container_id': container.id, 'daemon_id': daemon_id}

    @staticmethod
    def _daemon_identity(client):
        identity = client.info().get('ID')
        if (not isinstance(identity, str)
                or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}', identity)):
            raise RuntimeError('Exact Docker daemon identity required')
        return identity

    def _bound_operation_client(self, operation):
        client = self.client_factory()
        if self._daemon_identity(client) != operation.get('resolved_daemon_id'):
            raise RuntimeError('Sandbox reconciliation daemon mismatch')
        return client

    def confirm_operation_absent(self, operation, labels):
        self._operation_target(operation, labels)
        self.confirm_claim_absent(labels, operation.get('resolved_daemon_id'))

    def confirm_claim_absent(self, labels, daemon_id):
        client = self.client_factory()
        if self._daemon_identity(client) != daemon_id:
            raise RuntimeError('Sandbox reconciliation daemon mismatch')
        owned = client.containers.list(all=True, filters={'label': [
            f'{key}={labels[key]}' for key in ('webcompiler.pool', 'webcompiler.job', 'webcompiler.lease')]})
        if owned:
            raise RuntimeError('Claim sandbox remains after reconciliation')
        if self._daemon_identity(client) != daemon_id:
            raise RuntimeError('Sandbox daemon changed during absence confirmation')

    def daemon_identity(self):
        return self._daemon_identity(self.client_factory())

    def remove_operation(self, operation, labels):
        target, expected = self._operation_target(operation, labels)
        identity = operation.get('resolved_container_id')
        if (operation.get('phase') != 'removing' or not isinstance(identity, str)
                or not re.fullmatch('[a-f0-9]{64}', identity)
                or (operation['kind'] == 'start' and identity != target)):
            raise RuntimeError('Durable removal identity required')
        client = self._bound_operation_client(operation)
        try:
            container = client.containers.get(identity)
        except NotFound:
            if self._daemon_identity(client) != operation['resolved_daemon_id']:
                raise RuntimeError('Sandbox daemon changed during removal')
            return  # Resume only an already persisted exact-ID/daemon removal.
        self._check_operation_container(container, expected, identity=identity,
            name=target if operation['kind'] == 'create' else None)
        container.remove(force=True)
        try:
            client.containers.get(identity)
        except NotFound:
            if self._daemon_identity(client) != operation['resolved_daemon_id']:
                raise RuntimeError('Sandbox daemon changed during removal')
            return
        raise RuntimeError('Sandbox removal is not yet confirmed')


class ExecutionWorker:
    def __init__(self, queue, *, pool=None, runner_factory=DockerCompilerRunner, identity=None):
        self.queue = queue
        self.identity = identity or WorkerIdentity(uuid4().hex,settings.RUNTIME_POOL_ID,
            settings.DEPLOYMENT_SHA,settings.SANDBOX_POOL_ID,settings.RUNTIME_INSTANCE_ID)
        self._stop = Event()
        self.pool = pool or SandboxPool(pool_id=self.identity.sandbox_pool_id)
        self.runner_factory = runner_factory
        self.queue.reap_expired = None if isinstance(self.pool, SandboxPool) else self.pool.reap

    async def _execute(self, claim):
        def cleanup_guard(action):
            def checked():
                if isinstance(self.pool, SandboxPool) and self.pool.daemon_identity() != claim.daemon_id:
                    raise RuntimeError('Sandbox cleanup daemon mismatch')
                action()
                if isinstance(self.pool, SandboxPool) and self.pool.daemon_identity() != claim.daemon_id:
                    raise RuntimeError('Sandbox daemon changed during cleanup')
            return self.queue.cleanup_lease(claim.id, claim.token, checked)
        def operation_guard(kind, action, **metadata):
            if not isinstance(self.pool, SandboxPool):
                return self.queue.sandbox_operation(claim.id, claim.token, kind, action, **metadata)
            daemon_id = self.pool.daemon_identity()
            def bounded_action(operation):
                if self.pool.daemon_identity() != daemon_id:
                    raise RuntimeError('Sandbox daemon changed before execution')
                value = action(operation)
                if self.pool.daemon_identity() != daemon_id:
                    raise RuntimeError('Sandbox daemon changed during execution')
                return value
            return self.queue.sandbox_operation(claim.id, claim.token, kind, bounded_action,
                daemon_id=daemon_id, **metadata)
        runner = self.runner_factory(
            labels=sandbox_labels(claim.id, claim.token, self.identity),
            start_guard=lambda action: self.queue.start(claim.id, claim.token, action),
            operation_guard=operation_guard,
            cleanup_guard=cleanup_guard,
            client_factory=self.pool.client_factory if isinstance(self.pool, SandboxPool) else None,
        )
        payload = claim.payload
        if claim.kind == 'compile':
            value = await runner.compile(source_code=payload['code'], language=payload['language'],
                                         optimize=payload.get('optimize', False), target=payload.get('target', 'all'))
            verdict = classify_compile_result(value)
        elif claim.kind == 'run':
            value = await runner.run(source_code=payload['code'], language=payload['language'],
                                     stdin=payload.get('stdin', ''), optimize=payload.get('optimize', False))
            verdict = classify_run_result(value)
        elif claim.kind in ('practice', 'contest'):
            value = await judge_code(runner, payload, contest=claim.kind == 'contest')
            verdict = value['verdict']
        elif claim.kind == 'terminal':
            from app.services.terminal_broker import TerminalBroker
            from app.services.terminal_runner import run_terminal
            value = await run_terminal(runner, TerminalBroker(), payload)
            verdict = classify_run_result(value)
        else:
            raise ValueError('Unsupported durable execution kind')
        return {'value': value, 'verdict': verdict}

    def begin_drain(self):
        self._stop.set()
        self.queue.begin_worker_drain(self.identity)

    async def run_once(self, *, stop=None):
        daemon_id = None
        if isinstance(self.pool, SandboxPool):
            if not await asyncio.to_thread(self.queue.register_worker, self.identity,
                    stop_requested=lambda:self._stop.is_set() or (stop is not None and stop.is_set())):
                return False
            await asyncio.to_thread(self.queue.recover_expired, self.pool)
            daemon_id = await asyncio.to_thread(self.pool.daemon_identity)
        claim = await asyncio.to_thread(self.queue.claim,worker=self.identity,
            daemon_id=daemon_id,
            stop_requested=lambda:self._stop.is_set() or (stop is not None and stop.is_set()))
        if claim is None:
            return False

        async def heartbeat():
            while True:
                await asyncio.sleep(max(0.05, self.queue.lease_seconds / 3))
                if not await asyncio.to_thread(self.queue.renew, claim.id, claim.token):
                    return

        execution = asyncio.create_task(asyncio.wait_for(self._execute(claim), timeout=settings.EXECUTION_JOB_TIMEOUT_SECONDS))
        pulse = asyncio.create_task(heartbeat())
        try:
            done, _ = await asyncio.wait({execution, pulse}, return_when=asyncio.FIRST_COMPLETED)
            if pulse in done:
                # A failed renewal means stop immediately; never publish a result.
                with contextlib.suppress(Exception):
                    pulse.result()
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
                await asyncio.to_thread(self.queue.cleanup_lease,claim.id,claim.token,
                    lambda:self._reap_claim(claim, daemon_id))
                return True
            try:
                result = execution.result()
            except TimeoutError:
                result = {'verdict':'time_limit_exceeded', 'message':'전체 실행 시간이 초과되었습니다.'}
            except TerminalClosed:
                result = {'verdict':'canceled', 'message':'터미널 연결이 중단되었습니다. 자동으로 다시 실행하지 않습니다.'}
            except TerminalLimit as exc:
                result = {'verdict':'runtime_error', 'message':str(exc)}
            except Exception:
                # Raw exceptions may contain source paths, code, or hidden input.
                logger.warning('Execution failed for job %s', claim.id)
                result = {'verdict': 'system_error', 'message': '실행 서비스를 사용할 수 없습니다.'}
            # Even an apparently completed runner must confirm no old sandbox
            # remains before the global capacity can be released by finish().
            cleaned = await asyncio.to_thread(self.queue.cleanup_lease,claim.id,claim.token,
                lambda:self._reap_claim(claim, daemon_id))
            if not cleaned:
                return True
            await asyncio.to_thread(self.queue.finish, claim.id, claim.token, result)
            return True
        finally:
            execution.cancel()
            pulse.cancel()
            await asyncio.gather(execution, pulse, return_exceptions=True)

    def _reap_claim(self, claim, daemon_id):
        if isinstance(self.pool, SandboxPool):
            labels = sandbox_labels(claim.id, claim.token, self.identity)
            self.pool.reap_claim(labels, daemon_id=daemon_id)
            self.pool.confirm_claim_absent(labels, daemon_id)
        else:
            self.pool.reap(claim.id, claim.token)

    async def run(self, stop=None):
        try:
            while not self._stop.is_set() and (stop is None or not stop.is_set()):
                try:
                    if not await self.run_once(stop=stop):
                        await asyncio.sleep(0.25)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning('Worker iteration failed; retaining lease until recovery')
                    await asyncio.sleep(1)
        finally:
            # Cancellation cannot cancel a running to_thread claim. Publish
            # local stop first, then serialize a durable fence with that claim.
            await asyncio.to_thread(self.begin_drain)
