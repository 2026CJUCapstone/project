"""Compile once, then fresh phase containers with immutable, per-job artifacts.

Reuses the durable runner's create/start/cleanup fencing. Runtime registrations
must be explicitly approved; an empty registry does not fall back to old limits.
"""
import asyncio
import contextlib
import hashlib
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from app.core.config import settings
from app.models.judge_policy import RuntimeLimits
from app.models.judge_test_manifest import test_data_buffer_bytes
from app.services.judge_policy import test_suite_hash
from app.services.judge_runtime_registry import (SOURCE_NAMES,RuntimeReplaySnapshot,
    TOOLCHAINS,launcher_source,runtime_key,trusted_adapter)
from app.services.judge_toolchain_catalog import ToolchainAdapter
from app.services.judge_artifact_contracts import ArtifactContract,verified_contract
from app.services.judge_container_contracts import (
    ContainerContract,verified_contract as verified_container_contract)
from app.services.judge_supervisor_record import decode_report


def phase_tmpfs(language, phase, limits, *, layout=None):
    adapter=trusted_adapter(language,TOOLCHAINS[language])
    if layout is None:
        layout=adapter.scratch_layout
    return verified_container_contract(adapter.container_contract).phase_tmpfs(
        language,phase,limits,layout=layout)


def artifact_archive_script(root='/work/artifact', *, contract='bounded-tar-v1'):
    return verified_contract(contract).archive_script(root)


async def finish_io(action, *args, on_cancel=None):
    """A cancelled coroutine must not leave a thread writing after cleanup.

    Repeated cancellation also waits for the in-flight Docker/filesystem call.
    Ownership of a newly acquired stream is discharged before propagating it.
    """
    task=asyncio.create_task(asyncio.to_thread(action,*args))
    cancelled=False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled=True
        except Exception:
            break
    if cancelled:
        if not task.cancelled() and task.exception() is None and on_cancel is not None:
            await finish_io(on_cancel,task.result())
        else:
            with contextlib.suppress(Exception,asyncio.CancelledError): task.result()
        raise asyncio.CancelledError
    return task.result()


def validate_receipt(payload):
    receipt=payload['judge_contract']
    keys={'kind','policyId','revision','policyHash','language','testSuiteHash','profile','jobDeadlineMs','reservationBytes'}
    buffers=test_data_buffer_bytes(payload.get('sample',[]),payload.get('hidden',[]))
    if buffers:
        keys.add('testDataBufferBytes')
        if (not isinstance(receipt,dict) or type(receipt.get('testDataBufferBytes')) is not int
                or receipt['testDataBufferBytes']!=buffers):
            raise ValueError('Receipt test data buffer mismatch')
    if not isinstance(receipt,dict) or set(receipt)!=keys or receipt['kind']!='measured-v1':
        raise ValueError('Invalid measured receipt')
    profile=RuntimeLimits.model_validate(receipt['profile'])
    if profile.launcher_digest is None:
        raise ValueError('Receipt must freeze the measured supervisor implementation')
    sample,hidden=payload.get('sample',[]),payload.get('hidden',[])
    if (not isinstance(receipt['policyId'],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,79}',receipt['policyId'])
            or payload['language'] not in SOURCE_NAMES
            or not 1<=len(sample)+len(hidden)<=200 or receipt['language']!=payload['language']
            or receipt['testSuiteHash']!=test_suite_hash(sample,hidden)
            or type(receipt['revision']) is not int or receipt['revision']<1
            or not isinstance(receipt['policyHash'],str) or not re.fullmatch('sha256:[a-f0-9]{64}',receipt['policyHash'])
            or type(receipt['reservationBytes']) is not int
            or receipt['reservationBytes']!=max(profile.compile.memory_bytes,profile.run.memory_bytes)+buffers):
        raise ValueError('Receipt identity/test suite/resource mismatch')
    base=profile.compile.wall_ms+(len(sample)+len(hidden))*profile.run.wall_ms
    # Publication/admission checked the service ceiling when this immutable
    # receipt was created. Reapplying a mutable setting here would invalidate
    # an already acknowledged job after a worker restart or config change.
    if type(receipt['jobDeadlineMs']) is not int or not base+1000<=receipt['jobDeadlineMs']<=base+120000:
        raise ValueError('Receipt job deadline is inconsistent with frozen phase limits')
    if min(profile.compile.pids,profile.run.pids)<2:
        raise ValueError('Measured supervisor needs a PID in addition to the child')
    if profile.compile.tmp_bytes==0:
        raise ValueError('Compilation requires temporary artifact space')
    return profile


def unpack_artifact(data,destination,language, *, contract='bounded-tar-v1'):
    return verified_contract(contract).unpack(data,destination,language)


class MeasuredSubmission:
    def __init__(self,runner,payload,registry,worker_class,*,snapshot=None):
        self.runner=runner
        self.payload=payload
        self.profile=validate_receipt(payload)
        if snapshot is None:
            self.entry=registry.resolve(payload['language'],self.profile,worker_class)
            self.launcher_script=launcher_source(self.entry.launcher_digest)
            self.toolchain=trusted_adapter(self.entry.language,self.entry.toolchain_profile)
            self.artifact_contract=verified_contract(self.toolchain.artifact_contract)
            self.container_contract=verified_container_contract(self.toolchain.container_contract)
        else:
            if (not isinstance(snapshot,RuntimeReplaySnapshot)
                    or runtime_key(payload['language'],self.profile,worker_class)!=runtime_key(
                        snapshot.registration.language,snapshot.registration,worker_class)
                    or snapshot.registration.worker_class!=worker_class
                    or not isinstance(snapshot.launcher_script,str)
                    or 'sha256:'+hashlib.sha256(snapshot.launcher_script.encode('utf-8')).hexdigest()!=self.profile.launcher_digest
                    or not isinstance(snapshot.toolchain,ToolchainAdapter)
                    or (snapshot.toolchain.language,snapshot.toolchain.profile)!=(
                        snapshot.registration.language,snapshot.registration.toolchain_profile)
                    or snapshot.toolchain.fingerprint()!=snapshot.toolchain_fingerprint
                    or not isinstance(snapshot.artifact,ArtifactContract)
                    or snapshot.artifact.name!=snapshot.toolchain.artifact_contract
                    or not isinstance(snapshot.container,ContainerContract)
                    or snapshot.container.name!=snapshot.toolchain.container_contract):
                raise ValueError('Preclaimed runtime snapshot does not match the frozen receipt')
            self.entry=snapshot.registration
            self.launcher_script=snapshot.launcher_script
            self.toolchain=snapshot.toolchain
            self.artifact_contract=snapshot.artifact
            self.container_contract=snapshot.container
        self.language=payload['language']
        self.directory=None
        self.client=None
        self.compiled=False
        self.attempted=False
        self.cleanup_unconfirmed=False

    async def __aenter__(self):
        root=Path(settings.SANDBOX_WORKDIR_ROOT);root.mkdir(parents=True,exist_ok=True)
        labels=self.runner.labels
        prefix='job-'+labels.get('webcompiler.job',uuid.uuid4().hex)+'-'+labels.get('webcompiler.lease',uuid.uuid4().hex)+'-'
        self.directory=Path(tempfile.mkdtemp(prefix=prefix,dir=root))
        try:
            self.directory.chmod(0o755)
            self.source=self.directory/'source';self.source.mkdir(mode=0o755)
            source=self.source/self.toolchain.source_name
            source.write_text(self.payload['code'],encoding='utf-8');source.chmod(0o444)
            self.artifact=self.directory/'artifact';self.artifact.mkdir(mode=0o755)
            # Docker discovery/ping may block; keep the worker heartbeat alive.
            self.client=await finish_io(self.runner._get_client,on_cancel=lambda client:getattr(client,'close',lambda:None)())
            image=await finish_io(self.client.images.get,self.entry.image_digest)
            if image.id!=self.entry.image_digest: raise RuntimeError('Exact registered image is unavailable')
            return self
        except BaseException:
            try: await self._remove_host_directory(self.directory)
            finally: await self._close_client()
            raise

    async def _close_client(self):
        if self.client is not None:
            client,self.client=self.client,None
            with contextlib.suppress(Exception):
                await finish_io(getattr(client,'close',lambda:None))

    async def __aexit__(self,*_):
        # Host read-only files must be made removable on Windows development
        # filesystems too. Never follow artifact links (they were rejected).
        try:
            if self.directory and not self.cleanup_unconfirmed:
                await self._remove_host_directory(self.directory)
        finally: await self._close_client()

    async def _remove_host_directory(self,directory):
        # Both chmod and removal must be inside the lease guard. A stale worker
        # must not even make a recovered lease's readonly files writable.
        if directory!=self.directory and directory.parent!=self.directory:
            raise ValueError('Cleanup target is outside this measured job')
        def remove():
            if not directory.exists(): return
            if directory.is_symlink(): raise ValueError('Symlink cleanup target')
            for path in directory.rglob('*'):
                if path.is_symlink(): raise ValueError('Unexpected host artifact link')
                path.chmod(0o700 if path.is_dir() else 0o600)
            directory.chmod(0o700)
            shutil.rmtree(directory)
        removed=await self.runner._cleanup(remove)
        if removed is False or directory.exists():
            raise RuntimeError('Measured directory cleanup did not complete')

    async def _execute(self,*,mode,source_code,language):
        if mode!='compile' or self.attempted or source_code!=self.payload['code'] or language!=self.language:
            raise ValueError('One exact compile per submission required')
        self.attempted=True
        result=await self._phase('compile',self.profile.compile,list(self.toolchain.compile_command),'')
        self.compiled=result['exit_code']==0 and not result['failure_reason']
        return result

    async def run(self,*,source_code,language,stdin):
        if not self.compiled or source_code!=self.payload['code'] or language!=self.language:
            raise ValueError('Run must use this submission compiled artifact')
        return await self._phase('run',self.profile.run,list(self.toolchain.run_command),stdin)

    def _read_record(self,stream,phase,limits):
        raw=bytearray()
        for out,err in stream:
            if err: raise RuntimeError('Unexpected supervisor diagnostic')
            raw.extend(out or b'')
            if len(raw)>4096: raise ValueError('Oversized supervisor record')
            if b'\n' in raw:
                return self.container_contract.decode_report(bytes(raw),phase,limits)
        raise RuntimeError('Supervisor stopped without a completion record')

    def _collect(self,container,record,phase,limits):
        return self.container_contract.collect(container,record,phase,limits,
            self.artifact_contract,self.artifact,self.language)

    async def _phase(self,phase,limits,argv,stdin):
        phase_id=uuid.uuid4().hex
        inputs=self.directory/('input-'+phase_id);inputs.mkdir(mode=0o755)
        input_file=inputs/'stdin';input_file.write_text(stdin,encoding='utf-8');input_file.chmod(0o444)
        empty=self.directory/('empty-'+phase_id);empty.mkdir(mode=0o555)
        options=self.container_contract.create_options(
            phase_id=phase_id,phase=phase,limits=limits,argv=argv,
            language=self.language,layout=self.toolchain.scratch_layout,
            inputs=inputs,source=self.source,artifact=self.artifact,empty=empty,
            image_digest=self.entry.image_digest,launcher_script=self.launcher_script,
            labels=self.runner.labels)
        container=stream=task=None
        try:
            container=await self.runner._allocate_container(
                self.client.containers.create,**options)
            stream=await finish_io(lambda:container.attach(stream=True,logs=False,demux=True),on_cancel=lambda value:value.close())
            task=asyncio.create_task(asyncio.to_thread(self._read_record,stream,phase,limits))
            await self.runner._start_container(container)
            record=await asyncio.wait_for(asyncio.shield(task),timeout=limits.wall_ms/1000+5)
            return await finish_io(self._collect,container,record,phase,limits)
        finally:
            # Settle all consumers before __aexit__ can remove the workdir.
            # Closing the stream is required even when container cleanup fails.
            async def cleanup():
                self.cleanup_unconfirmed=True
                try:
                    if container is not None:
                        # The legacy helper suppresses Docker failures. A
                        # measured phase must not delete mounted input or begin
                        # another phase after an ambiguous removal. Leave this
                        # lease's workdir for the fenced recovery/reaper path.
                        from docker.errors import NotFound
                        def remove():
                            try: container.remove(force=True)
                            except NotFound: pass  # Exact container already gone.
                        removed=await self.runner._cleanup(remove)
                        if removed is False:
                            raise RuntimeError('Measured phase cleanup ownership was lost')
                finally:
                    if stream is not None:
                        with contextlib.suppress(Exception): await finish_io(stream.close)
                    if task is not None:
                        with contextlib.suppress(Exception,asyncio.CancelledError): await task
                # Keep disk usage proportional to one case, not the whole
                # suite. Only remove these exact per-phase directories after
                # the mounted container is confirmed gone and readers settled.
                for directory in (inputs,empty):
                    await self._remove_host_directory(directory)
                self.cleanup_unconfirmed=False
            cleanup_task=asyncio.create_task(cleanup())
            cancelled=False
            while not cleanup_task.done():
                try: await asyncio.shield(cleanup_task)
                except asyncio.CancelledError: cancelled=True
            cleanup_task.result()
            if cancelled: raise asyncio.CancelledError
