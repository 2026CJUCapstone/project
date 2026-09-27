"""Versioned, package-owned artifact implementations for measured receipts."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable

from app.services.judge_artifact_contract_v1 import artifact_archive_script_v1,unpack_artifact_v1


MAX_CONTRACT_SOURCE_BYTES=32768
V1_SOURCE=Path(__file__).with_name('judge_artifact_contract_v1.py')
# SHA-256 of canonical LF bytes. CRLF checkout differences do not create a
# different implementation, but bare CR and all semantic edits fail closed.
V1_SHA256='sha256:10ffee31249f320ec10e0391cd91963324f42a004b07cc2c40e04d28e9d1dc4a'


@dataclass(frozen=True)
class ArtifactContract:
    name: str
    source_digest: str
    archive_script: Callable
    unpack: Callable


def verified_contract(name):
    if name!='bounded-tar-v1':
        raise ValueError('Unknown trusted artifact contract')
    if V1_SOURCE.is_symlink() or not V1_SOURCE.is_file() or V1_SOURCE.stat().st_size>MAX_CONTRACT_SOURCE_BYTES:
        raise ValueError('Trusted artifact implementation is unavailable')
    with V1_SOURCE.open('rb') as stream:
        raw=stream.read(MAX_CONTRACT_SOURCE_BYTES+1)
    canonical=raw.replace(b'\r\n',b'\n')
    if not canonical or len(raw)>MAX_CONTRACT_SOURCE_BYTES or b'\r' in canonical:
        raise ValueError('Invalid trusted artifact implementation')
    actual='sha256:'+hashlib.sha256(canonical).hexdigest()
    if actual!=V1_SHA256:
        raise ValueError('Trusted artifact implementation hash mismatch')
    return ArtifactContract(name,actual,artifact_archive_script_v1,unpack_artifact_v1)
