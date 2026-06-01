import asyncio
import contextlib
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal, TypeAlias, TypeVar

from sqlalchemy import func

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import database as db_models

QueueKind = Literal["compile", "run", "grading"]
QueueStatus = Literal["queued", "running", "completed", "failed", "canceled"]
QueueVerdict: TypeAlias = Literal[
    "pending",
    "running",
    "compile_success",
    "compile_error",
    "accepted",
    "wrong_answer",
    "finished",
    "runtime_error",
    "time_limit_exceeded",
    "memory_limit_exceeded",
    "system_error",
    "canceled",
]
T = TypeVar("T")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class CompileQueueJob:
    id: str
    kind: QueueKind
    status: QueueStatus
    verdict: QueueVerdict
    language: str
    source_size_bytes: int
    queued_at: datetime
    username: str | None = None
    user_id: str | None = None
    problem_id: str | None = None
    problem_title: str | None = None
    target: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    wait_ms: float | None = None
    run_ms: float | None = None
    error: str | None = None
    verdict_detail: str | None = None

    def to_dict(self, position: int | None = None) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "verdict": self.verdict,
            "language": self.language,
            "username": self.username,
            "user_id": self.user_id,
            "problem_id": self.problem_id,
            "problem_title": self.problem_title,
            "target": self.target,
            "source_size_bytes": self.source_size_bytes,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "wait_ms": self.wait_ms,
            "run_ms": self.run_ms,
            "position": position,
            "error": self.error,
            "verdict_detail": self.verdict_detail,
        }


class CompileQueue:
    def __init__(self, concurrency: int, history_limit: int):
        self._concurrency = max(1, concurrency)
        self._history_limit = max(50, history_limit)
        self._jobs: OrderedDict[str, CompileQueueJob] = OrderedDict()
        self._pending: deque[str] = deque()
        self._active_count = 0
        self._condition = asyncio.Condition()

    async def run(
        self,
        *,
        kind: QueueKind,
        language: str,
        source_code: str,
        target: str | None = None,
        user_id: str | None = None,
        username: str | None = None,
        problem_id: str | None = None,
        problem_title: str | None = None,
        result_classifier: Callable[[T], QueueVerdict | tuple[QueueVerdict, str | None]] | None = None,
        task: Callable[[], Awaitable[T]],
    ) -> T:
        job = CompileQueueJob(
            id=uuid.uuid4().hex,
            kind=kind,
            status="queued",
            verdict="pending",
            language=language,
            source_size_bytes=len(source_code.encode("utf-8")),
            queued_at=utc_now(),
            username=username,
            user_id=user_id,
            problem_id=problem_id,
            problem_title=problem_title,
            target=target,
        )

        async with self._condition:
            self._jobs[job.id] = job
            self._pending.append(job.id)
            self._persist_job(job)
            self._prune_locked()
            self._condition.notify_all()

            try:
                while self._pending[0] != job.id or self._active_count >= self._concurrency:
                    await self._condition.wait()

                self._pending.popleft()
                self._active_count += 1
                job.status = "running"
                job.verdict = "running"
                job.started_at = utc_now()
                job.wait_ms = round((job.started_at - job.queued_at).total_seconds() * 1000, 2)
                self._persist_job(job)
                self._condition.notify_all()
            except asyncio.CancelledError:
                self._cancel_queued_locked(job)
                self._condition.notify_all()
                raise

        started_monotonic = time.monotonic()
        try:
            result = await task()
            verdict, verdict_detail = self._classify_result(result, result_classifier)
        except asyncio.CancelledError:
            await self._finish(job, "canceled", started_monotonic, verdict="canceled")
            raise
        except Exception as exc:
            await self._finish(
                job,
                "failed",
                started_monotonic,
                str(exc),
                verdict="system_error",
                verdict_detail=str(exc),
            )
            raise

        await self._finish(
            job,
            "completed",
            started_monotonic,
            verdict=verdict,
            verdict_detail=verdict_detail,
        )
        return result

    async def snapshot(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        verdict: str | None = None,
        kind: str | None = None,
        username: str | None = None,
        user_id: str | None = None,
        problem_id: str | None = None,
    ) -> dict:
        normalized_username = username.lower().strip() if username else None
        normalized_status = status.lower().strip() if status else None
        normalized_verdict = verdict.lower().strip() if verdict else None
        normalized_kind = kind.lower().strip() if kind else None
        normalized_offset = max(0, offset)

        async with self._condition:
            pending_positions = {job_id: index for index, job_id in enumerate(self._pending, start=1)}
            active_ids = set(self._jobs.keys())

        self._recover_stale_active_records(active_ids)

        with SessionLocal() as db:
            base_query = db.query(db_models.CompileQueueRecord)
            filtered_query = base_query
            if normalized_status:
                filtered_query = filtered_query.filter(db_models.CompileQueueRecord.status == normalized_status)
            if normalized_verdict:
                filtered_query = filtered_query.filter(db_models.CompileQueueRecord.verdict == normalized_verdict)
            if normalized_kind:
                filtered_query = filtered_query.filter(db_models.CompileQueueRecord.kind == normalized_kind)
            if normalized_username:
                filtered_query = filtered_query.filter(func.lower(db_models.CompileQueueRecord.username) == normalized_username)
            if user_id:
                filtered_query = filtered_query.filter(db_models.CompileQueueRecord.user_id == user_id)
            if problem_id:
                filtered_query = filtered_query.filter(db_models.CompileQueueRecord.problem_id == problem_id)

            total = base_query.count()
            filtered_total = filtered_query.count()
            queued_count = base_query.filter(db_models.CompileQueueRecord.status == "queued").count()
            running_count = base_query.filter(db_models.CompileQueueRecord.status == "running").count()
            page = (
                filtered_query.order_by(db_models.CompileQueueRecord.queued_at.desc())
                .offset(normalized_offset)
                .limit(limit)
                .all()
            )
            group_records = (
                filtered_query.order_by(db_models.CompileQueueRecord.queued_at.desc())
                .limit(self._history_limit)
                .all()
            )

            return {
                "jobs": [self._record_to_dict(record, pending_positions.get(record.id)) for record in page],
                "total": total,
                "filtered_total": filtered_total,
                "queued": queued_count,
                "running": running_count,
                "problem_groups": self._build_groups(group_records, "problem"),
                "user_groups": self._build_groups(group_records, "user"),
            }

    async def _finish(
        self,
        job: CompileQueueJob,
        status: QueueStatus,
        started_monotonic: float,
        error: str | None = None,
        verdict: QueueVerdict | None = None,
        verdict_detail: str | None = None,
    ) -> None:
        async with self._condition:
            job.status = status
            if verdict is not None:
                job.verdict = verdict
            job.finished_at = utc_now()
            job.run_ms = round((time.monotonic() - started_monotonic) * 1000, 2)
            if error:
                job.error = error[:300]
            if verdict_detail:
                job.verdict_detail = verdict_detail[:300]
            if self._active_count > 0:
                self._active_count -= 1
            self._persist_job(job)
            self._prune_locked()
            self._condition.notify_all()

    def _cancel_queued_locked(self, job: CompileQueueJob) -> None:
        with contextlib.suppress(ValueError):
            self._pending.remove(job.id)
        job.status = "canceled"
        job.verdict = "canceled"
        job.finished_at = utc_now()
        job.wait_ms = round((job.finished_at - job.queued_at).total_seconds() * 1000, 2)
        self._persist_job(job)

    def _prune_locked(self) -> None:
        while len(self._jobs) > self._history_limit:
            job_id, job = next(iter(self._jobs.items()))
            if job.status in {"queued", "running"}:
                break
            self._jobs.pop(job_id, None)
        self._prune_records()

    def _classify_result(
        self,
        result: T,
        result_classifier: Callable[[T], QueueVerdict | tuple[QueueVerdict, str | None]] | None,
    ) -> tuple[QueueVerdict, str | None]:
        if result_classifier is None:
            return "finished", None

        classified = result_classifier(result)
        if isinstance(classified, tuple):
            return classified
        return classified, None

    def _build_groups(self, jobs: list[CompileQueueJob] | list[db_models.CompileQueueRecord], group_by: Literal["problem", "user"]) -> list[dict]:
        groups: dict[str, dict] = {}
        for job in jobs:
            if group_by == "problem":
                key = job.problem_id or "__main__"
                default_label = job.problem_title or job.problem_id or "일반 컴파일"
                identity = {
                    "problem_id": job.problem_id,
                    "problem_title": job.problem_title,
                    "username": None,
                    "user_id": None,
                }
            else:
                key = job.user_id or job.username or "__anonymous__"
                default_label = job.username or "익명"
                identity = {
                    "problem_id": None,
                    "problem_title": None,
                    "username": job.username,
                    "user_id": job.user_id,
                }

            group = groups.setdefault(
                key,
                {
                    "key": key,
                    "label": default_label,
                    **identity,
                    "total": 0,
                    "queued": 0,
                    "running": 0,
                    "completed": 0,
                    "failed": 0,
                    "canceled": 0,
                    "verdicts": {},
                    "last_queued_at": job.queued_at,
                },
            )
            group["total"] += 1
            group[job.status] += 1
            group["verdicts"][job.verdict] = group["verdicts"].get(job.verdict, 0) + 1
            if job.queued_at > group["last_queued_at"]:
                group["last_queued_at"] = job.queued_at

        return sorted(
            groups.values(),
            key=lambda group: (
                -(group["queued"] + group["running"]),
                -group["total"],
                group["label"],
            ),
        )

    def _persist_job(self, job: CompileQueueJob) -> None:
        try:
            with SessionLocal() as db:
                record = db.get(db_models.CompileQueueRecord, job.id)
                if record is None:
                    record = db_models.CompileQueueRecord(id=job.id)
                    db.add(record)
                record.kind = job.kind
                record.status = job.status
                record.verdict = job.verdict
                record.language = job.language
                record.username = job.username
                record.user_id = job.user_id
                record.problem_id = job.problem_id
                record.problem_title = job.problem_title
                record.target = job.target
                record.source_size_bytes = job.source_size_bytes
                record.queued_at = job.queued_at
                record.started_at = job.started_at
                record.finished_at = job.finished_at
                record.wait_ms = job.wait_ms
                record.run_ms = job.run_ms
                record.error = job.error
                record.verdict_detail = job.verdict_detail
                db.commit()
        except Exception:
            return

    def _prune_records(self) -> None:
        try:
            with SessionLocal() as db:
                stale_ids = [
                    job_id
                    for (job_id,) in (
                        db.query(db_models.CompileQueueRecord.id)
                        .filter(~db_models.CompileQueueRecord.status.in_(["queued", "running"]))
                        .order_by(db_models.CompileQueueRecord.queued_at.desc())
                        .offset(self._history_limit)
                        .all()
                    )
                ]
                if stale_ids:
                    db.query(db_models.CompileQueueRecord).filter(
                        db_models.CompileQueueRecord.id.in_(stale_ids)
                    ).delete(synchronize_session=False)
                    db.commit()
        except Exception:
            return

    def _recover_stale_active_records(self, active_ids: set[str]) -> None:
        try:
            with SessionLocal() as db:
                query = db.query(db_models.CompileQueueRecord).filter(
                    db_models.CompileQueueRecord.status.in_(["queued", "running"])
                )
                if active_ids:
                    query = query.filter(~db_models.CompileQueueRecord.id.in_(active_ids))
                stale_records = query.all()
                if not stale_records:
                    return
                now = utc_now()
                for record in stale_records:
                    record.status = "failed"
                    record.verdict = "system_error"
                    record.finished_at = record.finished_at or now
                    record.verdict_detail = "서버 재시작으로 중단된 작업입니다."
                db.commit()
        except Exception:
            return

    def _record_to_dict(self, record: db_models.CompileQueueRecord, position: int | None = None) -> dict:
        return {
            "id": record.id,
            "kind": record.kind,
            "status": record.status,
            "verdict": record.verdict,
            "language": record.language,
            "username": record.username,
            "user_id": record.user_id,
            "problem_id": record.problem_id,
            "problem_title": record.problem_title,
            "target": record.target,
            "source_size_bytes": record.source_size_bytes,
            "queued_at": record.queued_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "wait_ms": record.wait_ms,
            "run_ms": record.run_ms,
            "position": position,
            "error": record.error,
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
    exit_code = _exit_code(result)
    stderr = _stderr_text(result)

    if exit_code == 124 or "timeout" in stderr or "시간이 초과" in stderr:
        return "time_limit_exceeded"
    if exit_code in {137, 143} or "out of memory" in stderr or "oom" in stderr or "memory" in stderr:
        return "memory_limit_exceeded"
    if "compiler pipeline" in stderr or "compilation" in stderr or "compile" in stderr:
        return "compile_error"
    return "runtime_error"


def classify_compile_result(result: dict) -> QueueVerdict:
    return "compile_success" if result.get("success") else "compile_error"


def classify_run_result(result: dict) -> QueueVerdict:
    return "finished" if _exit_code(result) == 0 else _classify_nonzero_execution(result)


def classify_grading_result(result: dict, expected_output: str) -> QueueVerdict:
    if _exit_code(result) != 0:
        return _classify_nonzero_execution(result)
    actual_output = str(result.get("stdout") or "").strip()
    return "accepted" if actual_output == expected_output.strip() else "wrong_answer"


compile_queue = CompileQueue(
    concurrency=settings.COMPILER_QUEUE_CONCURRENCY,
    history_limit=settings.COMPILER_QUEUE_HISTORY_LIMIT,
)
