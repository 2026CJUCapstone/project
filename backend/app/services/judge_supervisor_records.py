"""Versioned, source-pinned supervisor report parsers."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable

from app.services.judge_supervisor_record_v1 import decode_report_v1
from app.services.judge_supervisor_record_v2 import decode_report_v2


MAX_CONTRACT_SOURCE_BYTES=16384
V1_SOURCE=Path(__file__).with_name('judge_supervisor_record_v1.py')
V1_SHA256='sha256:fdd5f1506d994ea3fab5282d8f540324a19065837117969ca0e23fa2ce4500d9'
V2_SOURCE=Path(__file__).with_name('judge_supervisor_record_v2.py')
V2_SHA256='sha256:c3d6f5f9d6b10e6b007bf8e0f1293909bcf8bac6831af9286beb975fc3fe2d30'


@dataclass(frozen=True)
class ReportContract:
    name: str
    source_digest: str
    decode: Callable


def verified_contract(name):
    contracts = {
        'supervisor-record-v1': (V1_SOURCE, V1_SHA256, decode_report_v1),
        'supervisor-record-v2': (V2_SOURCE, V2_SHA256, decode_report_v2),
    }
    if name not in contracts:
        raise ValueError('Unknown trusted supervisor record contract')
    source, expected, decoder = contracts[name]
    if source.is_symlink() or not source.is_file() or source.stat().st_size>MAX_CONTRACT_SOURCE_BYTES:
        raise ValueError('Trusted supervisor record parser is unavailable')
    with source.open('rb') as stream:
        raw=stream.read(MAX_CONTRACT_SOURCE_BYTES+1)
    canonical=raw.replace(b'\r\n',b'\n')
    if not canonical or len(raw)>MAX_CONTRACT_SOURCE_BYTES or b'\r' in canonical:
        raise ValueError('Invalid trusted supervisor record parser')
    actual='sha256:'+hashlib.sha256(canonical).hexdigest()
    if actual!=expected:
        raise ValueError('Trusted supervisor record parser hash mismatch')
    return ReportContract(name,actual,decoder)
