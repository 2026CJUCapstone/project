"""Operator-owned immutable runtime allowlist, separate from problem JSON.

No administrator-supplied shell commands, tags, flags or inferred versions.
Registry creation/approval is an operator action, never an API side effect.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from app.models.judge_policy import RuntimeLimits
from app.services.judge_artifact_contracts import ArtifactContract,verified_contract
from app.services.judge_container_contracts import (
    ContainerContract,verified_contract as verified_container_contract)
from app.services.judge_toolchain_catalog import (ADAPTERS, CURRENT_TOOLCHAINS, SOURCE_NAMES,
    ToolchainAdapter, trusted_adapter)


LAUNCHER_PATH = Path(__file__).with_name('linux_phase_launcher.py')
LAUNCHER_ARCHIVE_DIR = Path(__file__).with_name('launcher_archive')
MAX_LAUNCHER_BYTES = 65536
TOOLCHAINS = CURRENT_TOOLCHAINS


def launcher_digest():
    return 'sha256:'+hashlib.sha256(_launcher_bytes(LAUNCHER_PATH)).hexdigest()


def _launcher_bytes(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_LAUNCHER_BYTES:
        raise ValueError('Trusted measured launcher is unavailable')
    with path.open('rb') as stream:
        data=stream.read(MAX_LAUNCHER_BYTES+1)
    if not data or len(data)>MAX_LAUNCHER_BYTES:
        raise ValueError('Trusted measured launcher has invalid size')
    return data


def launcher_source(digest):
    """Read only trusted, content-addressed bytes; never substitute a new launcher.

    Archived files are packaged with the worker release before the active
    launcher changes. A missing archive makes the old receipt unavailable.
    """
    if not isinstance(digest,str) or not re.fullmatch('sha256:[a-f0-9]{64}',digest):
        raise ValueError('Invalid measured launcher digest')
    active=_launcher_bytes(LAUNCHER_PATH)
    if 'sha256:'+hashlib.sha256(active).hexdigest()==digest:
        return active.decode('utf-8')
    if LAUNCHER_ARCHIVE_DIR.is_symlink():
        raise ValueError('Symlinked measured launcher archive')
    archived=LAUNCHER_ARCHIVE_DIR/('sha256-'+digest[7:]+'.py')
    data=_launcher_bytes(archived)
    if 'sha256:'+hashlib.sha256(data).hexdigest()!=digest:
        raise ValueError('Archived measured launcher hash mismatch')
    return data.decode('utf-8')


def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value: raise ValueError('Duplicate runtime registry key')
        value[key]=item
    return value


@dataclass(frozen=True)
class RuntimeRegistration:
    language: str
    runtime_id: str
    runtime_version: str
    image_digest: str
    worker_class: str
    toolchain_profile: str
    launcher_digest: str
    admit_new: bool = True


@dataclass(frozen=True)
class RuntimeReplaySnapshot:
    registration: RuntimeRegistration
    launcher_script: str
    toolchain: ToolchainAdapter
    toolchain_fingerprint: str
    artifact: ArtifactContract
    container: ContainerContract


def runtime_key(language, profile, worker_class):
    return (language,profile.runtime_id,profile.runtime_version,profile.image_digest,
        worker_class,profile.toolchain_profile,profile.launcher_digest)


class RuntimeRegistry:
    def __init__(self, raw):
        if (not isinstance(raw,dict) or set(raw)!={'version','runtimes'}
                or type(raw['version']) is not int or raw['version'] not in (1,2)
                or not isinstance(raw['runtimes'],list) or not 1<=len(raw['runtimes'])<=100):
            raise ValueError('Invalid trusted runtime registry')
        self.version=raw['version']
        entries={}
        for item in raw['runtimes']:
            required={'language','runtimeId','runtimeVersion','imageDigest',
                    'workerClass','toolchainProfile','launcherDigest'}
            if not isinstance(item,dict) or set(item)!=(required | ({'admitNew'} if self.version==2 else set())):
                raise ValueError('Invalid runtime registration')
            if (not isinstance(item['language'],str) or item['language'] not in TOOLCHAINS
                    or not isinstance(item['toolchainProfile'],str)
                    or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,79}',item['toolchainProfile'])
                    or ((item['language'],item['toolchainProfile']) not in ADAPTERS
                        and (self.version==1 or item['admitNew']))
                    or any(not isinstance(item[k],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,79}',item[k]) for k in ('runtimeId','workerClass'))
                    or not isinstance(item['runtimeVersion'],str) or not 1<=len(item['runtimeVersion'])<=160
                    or any(not isinstance(item[k],str) or not re.fullmatch('sha256:[a-f0-9]{64}',item[k]) for k in ('imageDigest','launcherDigest'))
                    or (self.version==2 and type(item['admitNew']) is not bool)):
                raise ValueError('Untrusted runtime/toolchain identity')
            entry=RuntimeRegistration(item['language'],item['runtimeId'],item['runtimeVersion'],item['imageDigest'],
                item['workerClass'],item['toolchainProfile'],item['launcherDigest'],
                item['admitNew'] if self.version==2 else True)
            key=(entry.language,entry.runtime_id,entry.runtime_version,entry.image_digest,
                entry.worker_class,entry.toolchain_profile,entry.launcher_digest)
            if key in entries: raise ValueError('Duplicate runtime registration')
            entries[key]=entry
        self._entries=entries

    @classmethod
    def load(cls,path):
        if not path: raise RuntimeError('Measured runtime registry is not configured')
        file=Path(path)
        if not file.is_absolute(): raise ValueError('Absolute operator registry path required')
        with file.open('rb') as stream: raw=stream.read(65537)
        if len(raw)>65536: raise ValueError('Oversized runtime registry')
        return cls(json.loads(raw,object_pairs_hook=_unique))

    def resolve(self,language,profile:RuntimeLimits,worker_class,*,for_admission=False):
        key=runtime_key(language,profile,worker_class)
        entry=self._entries.get(key)
        if (entry is None or profile.worker_class!=worker_class
                or (for_admission and (not entry.admit_new
                    or entry.toolchain_profile!=TOOLCHAINS[language]
                    # New receipts must bind the launcher shipped by this
                    # release.  Archived bytes exist only to replay an exact
                    # historical receipt; marking an archived launcher
                    # `admitNew` must not pair the current container/toolchain
                    # protocol with an older supervisor protocol.
                    or entry.launcher_digest!=launcher_digest()))):
            raise ValueError('Runtime profile does not match the approved worker/toolchain/launcher')
        adapter=trusted_adapter(language,entry.toolchain_profile)
        verified_contract(adapter.artifact_contract)
        verified_container_contract(adapter.container_contract)
        if adapter.scratch_layout == 'bpp-split-v1' and (profile.compile.tmp_bytes < 8192 or profile.compile.tmp_bytes % 4096):
            raise ValueError('B++ compiler scratch budget requires at least two aligned 4 KiB pages')
        launcher_source(entry.launcher_digest)
        return entry

    def replay_snapshots(self, worker_class):
        """Preload trusted scripts before queue locking; unavailable entries stay queued."""
        result={}
        for key,entry in self._entries.items():
            if entry.worker_class!=worker_class:
                continue
            try:
                source=launcher_source(entry.launcher_digest)
                adapter=trusted_adapter(entry.language,entry.toolchain_profile)
                artifact=verified_contract(adapter.artifact_contract)
                container=verified_container_contract(adapter.container_contract)
            except (OSError,ValueError,UnicodeError):
                continue
            result[key]=RuntimeReplaySnapshot(entry,source,adapter,adapter.fingerprint(),artifact,container)
        return result


def require_registered_policy(policy,settings):
    """API admission validates operator approval without contacting Docker.

    The registry must also be mounted in API processes. Matching registrations
    are not a liveness claim; workers still check their class/image at execution.
    """
    try:
        registry=RuntimeRegistry.load(settings.JUDGE_RUNTIME_REGISTRY)
        for language,profile in policy.profiles.items():
            registry.resolve(language,profile,profile.worker_class,for_admission=True)
    except (OSError,ValueError,RuntimeError,AttributeError):
        raise ValueError('문제의 실행 환경이 운영자 등록부와 일치하지 않습니다. 런타임·워커·실행기 버전을 확인하세요.') from None


def compile_argv(language):
    """Static source and output paths; no shell expansion or user flags."""
    return list(trusted_adapter(language,TOOLCHAINS[language]).compile_command)


def run_argv(language):
    return list(trusted_adapter(language,TOOLCHAINS[language]).run_command)
