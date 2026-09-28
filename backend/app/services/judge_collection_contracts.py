"""Versioned, source-pinned measured result collectors."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable

from app.services.judge_collection_contract_v1 import collect_phase_v1


MAX_CONTRACT_SOURCE_BYTES=16384
V1_SOURCE=Path(__file__).with_name('judge_collection_contract_v1.py')
V1_SHA256='sha256:3929e47342808b38aa9b73a8fae4af51a37cce2934ea97521b7deea923cdf87e'


@dataclass(frozen=True)
class CollectionContract:
    name: str
    source_digest: str
    collect: Callable


def verified_contract(name):
    if name!='measured-collection-v1':
        raise ValueError('Unknown trusted collection contract')
    if V1_SOURCE.is_symlink() or not V1_SOURCE.is_file() or V1_SOURCE.stat().st_size>MAX_CONTRACT_SOURCE_BYTES:
        raise ValueError('Trusted collection implementation is unavailable')
    with V1_SOURCE.open('rb') as stream:
        raw=stream.read(MAX_CONTRACT_SOURCE_BYTES+1)
    canonical=raw.replace(b'\r\n',b'\n')
    if not canonical or len(raw)>MAX_CONTRACT_SOURCE_BYTES or b'\r' in canonical:
        raise ValueError('Invalid trusted collection implementation')
    actual='sha256:'+hashlib.sha256(canonical).hexdigest()
    if actual!=V1_SHA256:
        raise ValueError('Trusted collection implementation hash mismatch')
    return CollectionContract(name,actual,collect_phase_v1)
