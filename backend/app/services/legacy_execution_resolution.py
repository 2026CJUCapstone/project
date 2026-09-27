"""Fail-closed replay bindings for unresolved historical graded jobs.

The resolver never derives a historical contract from current settings. An
administrator must provide a complete measured-v1 receipt whose test, language,
resource and runtime identities validate against the immutable old payload.
"""
from copy import deepcopy
from dataclasses import dataclass

from fastapi import HTTPException

from app.core.config import settings
from app.models import database as m
from app.services.contest_access import iso
from app.services.judge_policy import content_hash
from app.services.measured_judge import validate_receipt
from app.services.runtime_registry import execution_lock


SUPPORTED_VERDICT_SCHEMA = 'measured-v1'
GRADED_KINDS = frozenset(('practice', 'contest'))


@dataclass(frozen=True)
class LegacyReplayBinding:
    resolution_id: str
    execution_job_id: str
    payload_hash: str
    judge_contract: dict
    judge_contract_hash: str
    verdict_schema_version: str


@dataclass(frozen=True)
class PreparedLegacyReplay:
    resolution_id: str
    runtime_snapshot: object
    judge_contract: dict


def _projection(row):
    return dict(id=row.id, executionJobId=row.execution_job_id,
        payloadHash=row.payload_hash, judgeContractHash=row.judge_contract_hash,
        verdictSchemaVersion=row.verdict_schema_version, actorId=row.actor_id,
        requestId=row.request_id, note=row.note, createdAt=iso(row.created_at))


def _validate_job(job):
    if job is None:
        raise HTTPException(404, '실행 기록을 찾을 수 없습니다.')
    if job.kind not in GRADED_KINDS:
        raise HTTPException(409, '일반 문제 또는 대회 채점 기록만 복구할 수 있습니다.')
    if job.status != 'queued' or job.attempts != 0 or job.started_at is not None:
        raise HTTPException(409, '선점되지 않은 대기 중 기록만 복구할 수 있습니다.')
    if job.content_expired_at is not None or not isinstance(job.payload, dict):
        raise HTTPException(409, '복구할 실행 내용이 남아 있지 않습니다.')
    old_contract = job.payload.get('judge_contract')
    if old_contract is not None and (
            not isinstance(old_contract, dict) or old_contract.get('kind') != 'legacy-v1'):
        raise HTTPException(409, '이미 실행 계약이 있는 기록은 과거 계약 복구 대상이 아닙니다.')
    return job


def _validated_contract(job, contract, verdict_schema_version):
    if verdict_schema_version != SUPPORTED_VERDICT_SCHEMA:
        raise HTTPException(409, '지원하지 않는 과거 판정 스키마입니다.')
    payload = deepcopy(job.payload)
    payload['judge_contract'] = deepcopy(contract)
    try:
        profile = validate_receipt(payload)
        from app.services.judge_runtime_registry import RuntimeRegistry
        registry = RuntimeRegistry.load(settings.JUDGE_RUNTIME_REGISTRY)
        # Creation validates identity against the operator registry. The worker
        # independently requires archived launcher bytes and the exact image
        # before claim, so this is not a liveness assertion.
        registry.resolve(payload['language'], profile, profile.worker_class)
    except (KeyError, OSError, RuntimeError, ValueError, TypeError):
        raise HTTPException(409, '과거 실행 계약이 payload 또는 운영자 런타임 등록부와 일치하지 않습니다.') from None
    return payload['judge_contract']


def append(db, job_id, data, actor):
    if actor.role != 'admin':
        raise HTTPException(403, '관리자 권한이 필요합니다.')
    execution_lock(db)
    old_request = db.query(m.LegacyExecutionResolution).filter_by(
        actor_id=actor.id, request_id=data.request_id).first()
    request_hash = content_hash(dict(executionJobId=job_id,
        **data.model_dump(mode='json', by_alias=True)))
    if old_request:
        if old_request.request_hash != request_hash:
            raise HTTPException(409, '같은 요청 ID를 다른 과거 실행 복구에 사용할 수 없습니다.')
        return _projection(old_request)
    job = _validate_job(db.get(m.ExecutionJob, job_id))
    if job.payload_hash != data.expected_payload_hash:
        raise HTTPException(409, '실행 payload가 변경되었습니다.')
    existing = db.query(m.LegacyExecutionResolution).filter_by(execution_job_id=job.id).first()
    if existing:
        raise HTTPException(409, '이 실행 기록에는 이미 복구 계약이 연결되어 있습니다.')
    contract = _validated_contract(job, data.judge_contract, data.verdict_schema_version)
    row = m.LegacyExecutionResolution(execution_job_id=job.id,
        payload_hash=job.payload_hash, judge_contract=deepcopy(contract),
        judge_contract_hash=content_hash(contract),
        verdict_schema_version=data.verdict_schema_version,
        actor_id=actor.id, request_id=data.request_id,
        request_hash=request_hash, note=data.note.strip())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _projection(row)


def read(db, job_id):
    row = db.query(m.LegacyExecutionResolution).filter_by(execution_job_id=job_id).first()
    if row is None:
        raise HTTPException(404, '과거 실행 복구 기록을 찾을 수 없습니다.')
    return _projection(row)


def load_bindings(db):
    """Load immutable, non-source replay facts before the queue claim lock."""
    rows = (db.query(m.LegacyExecutionResolution)
        .join(m.ExecutionJob, m.ExecutionJob.id == m.LegacyExecutionResolution.execution_job_id)
        .filter(m.ExecutionJob.status == 'queued').all())
    return {row.execution_job_id: LegacyReplayBinding(row.id, row.execution_job_id,
        row.payload_hash, deepcopy(row.judge_contract), row.judge_contract_hash,
        row.verdict_schema_version) for row in rows}


def prepare_binding(binding, *, job_id, kind, payload, snapshots, worker_class):
    """Validate an immutable resolution against the exact queued payload."""
    from app.services.durable_queue import execution_payload_hash
    if (binding is None or binding.execution_job_id != job_id
            or binding.verdict_schema_version != SUPPORTED_VERDICT_SCHEMA):
        return None
    digest, _ = execution_payload_hash(kind,payload)
    if (digest != binding.payload_hash
            or content_hash(binding.judge_contract) != binding.judge_contract_hash):
        return None
    candidate = deepcopy(payload)
    candidate['judge_contract'] = deepcopy(binding.judge_contract)
    try:
        profile = validate_receipt(candidate)
        from app.services.judge_runtime_registry import runtime_key
        snapshot = snapshots.get(runtime_key(candidate['language'],profile,worker_class))
    except (KeyError, TypeError, ValueError):
        return None
    if snapshot is None:
        return None
    return PreparedLegacyReplay(binding.resolution_id,snapshot,deepcopy(binding.judge_contract))


def publication_payload(db, job):
    """Rebind an exact resolution while publishing a protected result.

    The queue payload remains immutable. Result validation independently checks
    the same job, payload and contract hashes used before claim so a database
    mutation between execution and publication cannot authorize a report.
    """
    if job is None or job.kind not in GRADED_KINDS or not isinstance(job.payload, dict):
        raise ValueError('Invalid legacy result publication target')
    contract = job.payload.get('judge_contract')
    if contract is not None and (
            not isinstance(contract, dict) or contract.get('kind') != 'legacy-v1'):
        return job.payload
    row = db.query(m.LegacyExecutionResolution).filter_by(execution_job_id=job.id).first()
    if row is None or row.verdict_schema_version != SUPPORTED_VERDICT_SCHEMA:
        raise ValueError('Unresolved legacy result cannot be published')
    from app.services.durable_queue import execution_payload_hash
    digest, _ = execution_payload_hash(job.kind, job.payload)
    if (digest != job.payload_hash or digest != row.payload_hash
            or content_hash(row.judge_contract) != row.judge_contract_hash):
        raise ValueError('Legacy result binding changed before publication')
    payload = {**job.payload, 'judge_contract': deepcopy(row.judge_contract)}
    try:
        validate_receipt(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Legacy result contract is invalid') from exc
    return payload
