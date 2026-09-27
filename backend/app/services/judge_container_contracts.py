"""Package-owned, source-pinned container creation contracts."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable

from app.services.judge_container_contract_v1 import (
    phase_create_options_v1,phase_tmpfs_v1)
from app.services.judge_container_contract_v2 import (
    phase_create_options_v2,phase_tmpfs_v2)
from app.services.judge_collection_contracts import verified_contract as verified_collection_contract
from app.services.judge_supervisor_records import verified_contract as verified_report_contract


MAX_CONTRACT_SOURCE_BYTES=16384
V1_SOURCE=Path(__file__).with_name('judge_container_contract_v1.py')
V1_SHA256='sha256:c9031e0b100ddfdf9a2d839f268fa13ee1ffb2b90b67a313ea408ee259281f01'
V2_SOURCE=Path(__file__).with_name('judge_container_contract_v2.py')
V2_SHA256='sha256:0522bdf65dda2a007f86a49a49d823550da59a196960528e1ae002a58f2f5a61'


@dataclass(frozen=True)
class ContainerContract:
    name: str
    source_digest: str
    report_source_digest: str
    collection_source_digest: str
    create_options: Callable
    phase_tmpfs: Callable
    decode_report: Callable
    collect: Callable


def verified_contract(name):
    contracts = {
        'measured-container-v1': (V1_SOURCE, V1_SHA256, phase_create_options_v1,
                                  phase_tmpfs_v1, 'supervisor-record-v1'),
        'measured-container-v2': (V2_SOURCE, V2_SHA256, phase_create_options_v2,
                                  phase_tmpfs_v2, 'supervisor-record-v2'),
    }
    if name not in contracts:
        raise ValueError('Unknown trusted container contract')
    source, expected, create_options, phase_tmpfs, report_name = contracts[name]
    if source.is_symlink() or not source.is_file() or source.stat().st_size>MAX_CONTRACT_SOURCE_BYTES:
        raise ValueError('Trusted container implementation is unavailable')
    with source.open('rb') as stream:
        raw=stream.read(MAX_CONTRACT_SOURCE_BYTES+1)
    canonical=raw.replace(b'\r\n',b'\n')
    if not canonical or len(raw)>MAX_CONTRACT_SOURCE_BYTES or b'\r' in canonical:
        raise ValueError('Invalid trusted container implementation')
    actual='sha256:'+hashlib.sha256(canonical).hexdigest()
    if actual!=expected:
        raise ValueError('Trusted container implementation hash mismatch')
    report=verified_report_contract(report_name)
    collection=verified_collection_contract('measured-collection-v1')
    return ContainerContract(name,actual,report.source_digest,collection.source_digest,
        create_options,phase_tmpfs,report.decode,collection.collect)
