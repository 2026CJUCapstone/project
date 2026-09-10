import asyncio
from typing import Literal, TypeAlias

from sqlalchemy import func

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import database as db_models

QueueVerdict: TypeAlias = Literal[
    "pending", "running", "compile_success", "compile_error", "accepted",
    "wrong_answer", "finished", "runtime_error", "time_limit_exceeded",
    "memory_limit_exceeded", "system_error", "canceled",
]


class CompileQueue:
    """Read-only compatibility facade for durable execution observations."""

    def __init__(self, concurrency: int, history_limit: int):
        # Kept for compatibility; durable workers own execution concurrency.
        self._history_limit = max(50, history_limit)

    async def snapshot(
        self, *, limit: int = 100, offset: int = 0,
        status: str | None = None, verdict: str | None = None,
        kind: str | None = None, username: str | None = None,
        user_id: str | None = None, problem_id: str | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._snapshot_sync,
            limit=limit, offset=offset, status=status, verdict=verdict,
            kind=kind, username=username, user_id=user_id,
            problem_id=problem_id,
        )

    def _snapshot_sync(
        self, *, limit: int = 100, offset: int = 0,
        status: str | None = None, verdict: str | None = None,
        kind: str | None = None, username: str | None = None,
        user_id: str | None = None, problem_id: str | None = None,
    ) -> dict:
        normalized_username = username.lower().strip() if username else None
        normalized_status = status.lower().strip() if status else None
        normalized_verdict = verdict.lower().strip() if verdict else None
        normalized_kind = kind.lower().strip() if kind else None

        # Observation must never claim leases, repair Redis, or alter jobs.
        with SessionLocal() as db:
            base_query = db.query(db_models.CompileQueueRecord)
            pending_positions = {
                job_id: index
                for index, (job_id,) in enumerate(
                    db.query(db_models.CompileQueueRecord.id)
                    .filter(db_models.CompileQueueRecord.status == "queued")
                    .order_by(db_models.CompileQueueRecord.queued_at,
                              db_models.CompileQueueRecord.id)
                    .all(), start=1,
                )
            }
            filtered_query = base_query
            if normalized_status:
                filtered_query = filtered_query.filter(
                    db_models.CompileQueueRecord.status == normalized_status)
            if normalized_verdict:
                filtered_query = filtered_query.filter(
                    db_models.CompileQueueRecord.verdict == normalized_verdict)
            if normalized_kind:
                filtered_query = filtered_query.filter(
                    db_models.CompileQueueRecord.kind == normalized_kind)
            if normalized_username:
                filtered_query = filtered_query.filter(
                    func.lower(db_models.CompileQueueRecord.username)
                    == normalized_username)
            if user_id:
                filtered_query = filtered_query.filter(
                    db_models.CompileQueueRecord.user_id == user_id)
            if problem_id:
                filtered_query = filtered_query.filter(
                    db_models.CompileQueueRecord.problem_id == problem_id)

            page = (filtered_query
                    .order_by(db_models.CompileQueueRecord.queued_at.desc())
                    .offset(max(0, offset)).limit(limit).all())
            group_records = (filtered_query
                             .order_by(db_models.CompileQueueRecord.queued_at.desc())
                             .limit(self._history_limit).all())
            return {
                "jobs": [self._record_to_dict(record, pending_positions.get(record.id))
                         for record in page],
                "total": base_query.count(),
                "filtered_total": filtered_query.count(),
                "queued": base_query.filter(
                    db_models.CompileQueueRecord.status == "queued").count(),
                "running": base_query.filter(
                    db_models.CompileQueueRecord.status == "running").count(),
                "problem_groups": self._build_groups(group_records, "problem"),
                "user_groups": self._build_groups(group_records, "user"),
            }

    @staticmethod
    def _build_groups(jobs: list[db_models.CompileQueueRecord],
                      group_by: Literal["problem", "user"]) -> list[dict]:
        groups: dict[str, dict] = {}
        for job in jobs:
            if group_by == "problem":
                key = job.problem_id or "__main__"
                label = job.problem_title or job.problem_id or "일반 컴파일"
                identity = {"problem_id": job.problem_id,
                            "problem_title": job.problem_title,
                            "username": None, "user_id": None}
            else:
                key = job.user_id or job.username or "__anonymous__"
                label = job.username or "익명"
                identity = {"problem_id": None, "problem_title": None,
                            "username": job.username, "user_id": job.user_id}
            group = groups.setdefault(key, {
                "key": key, "label": label, **identity, "total": 0,
                "queued": 0, "running": 0, "completed": 0, "failed": 0,
                "canceled": 0, "verdicts": {},
                "last_queued_at": job.queued_at,
            })
            group["total"] += 1
            group[job.status] += 1
            group["verdicts"][job.verdict] = group["verdicts"].get(job.verdict, 0) + 1
            if job.queued_at > group["last_queued_at"]:
                group["last_queued_at"] = job.queued_at
        return sorted(groups.values(), key=lambda group: (
            -(group["queued"] + group["running"]), -group["total"], group["label"]))

    @staticmethod
    def _record_to_dict(record: db_models.CompileQueueRecord,
                        position: int | None = None) -> dict:
        return {
            "id": record.id, "kind": record.kind, "status": record.status,
            "verdict": record.verdict, "language": record.language,
            "username": record.username, "user_id": record.user_id,
            "problem_id": record.problem_id, "problem_title": record.problem_title,
            "target": record.target, "source_size_bytes": record.source_size_bytes,
            "queued_at": record.queued_at, "started_at": record.started_at,
            "finished_at": record.finished_at, "wait_ms": record.wait_ms,
            "run_ms": record.run_ms, "position": position, "error": record.error,
            "verdict_detail": record.verdict_detail,
        }


def _stderr_text(result: dict) -> str:
    return str(result.get("stderr") or "").lower()


def _exit_code(result: dict) -> int:
    try:
        return int(result.get("exit_code", 0))
    except (TypeError, ValueError):
        return 1


def _classify_nonzero_execution(result: dict) -> QueueVerdict:
    # Only the worker's deadline/Docker state establishes a resource failure.
    # User programs can print these words or exit with 124/137 themselves.
    reason = result.get('failure_reason')
    if reason in {'time_limit_exceeded', 'memory_limit_exceeded'}:
        return reason
    if reason == 'output_limit_exceeded':
        return 'runtime_error'
    if result.get('execution_phase') == 'compile':
        return 'compile_error'
    if result.get('execution_phase') == 'run':
        return 'runtime_error'
    # Compatibility for persisted results/old sandbox images without a phase
    # handshake. New sandbox results must not use stderr as an authority.
    exit_code, stderr = _exit_code(result), _stderr_text(result)
    if exit_code == 124 or "timeout" in stderr or "시간이 초과" in stderr:
        return "time_limit_exceeded"
    if (exit_code in {137, 143} or "out of memory" in stderr
            or "oom" in stderr or "memory" in stderr):
        return "memory_limit_exceeded"
    if ("compiler pipeline" in stderr or "compilation" in stderr
            or "compile" in stderr):
        return "compile_error"
    return "runtime_error"


def classify_compile_result(result: dict) -> QueueVerdict:
    return "compile_success" if result.get("success") else "compile_error"


def classify_run_result(result: dict) -> QueueVerdict:
    return "finished" if _exit_code(result) == 0 else _classify_nonzero_execution(result)


def classify_grading_result(result: dict, expected_output: str) -> QueueVerdict:
    if _exit_code(result) != 0:
        return _classify_nonzero_execution(result)
    return ("accepted" if str(result.get("stdout") or "").strip()
            == expected_output.strip() else "wrong_answer")


compile_queue = CompileQueue(settings.COMPILER_QUEUE_CONCURRENCY,
                             settings.COMPILER_QUEUE_HISTORY_LIMIT)
