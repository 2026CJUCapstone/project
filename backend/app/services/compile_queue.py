import asyncio
import contextlib
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal, TypeVar

from app.core.config import settings

QueueKind = Literal["compile", "run", "grading"]
QueueStatus = Literal["queued", "running", "completed", "failed", "canceled"]
T = TypeVar("T")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class CompileQueueJob:
    id: str
    kind: QueueKind
    status: QueueStatus
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

    def to_dict(self, position: int | None = None) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
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
        task: Callable[[], Awaitable[T]],
    ) -> T:
        job = CompileQueueJob(
            id=uuid.uuid4().hex,
            kind=kind,
            status="queued",
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
            self._prune_locked()
            self._condition.notify_all()

            try:
                while self._pending[0] != job.id or self._active_count >= self._concurrency:
                    await self._condition.wait()

                self._pending.popleft()
                self._active_count += 1
                job.status = "running"
                job.started_at = utc_now()
                job.wait_ms = round((job.started_at - job.queued_at).total_seconds() * 1000, 2)
                self._condition.notify_all()
            except asyncio.CancelledError:
                self._cancel_queued_locked(job)
                self._condition.notify_all()
                raise

        started_monotonic = time.monotonic()
        try:
            result = await task()
        except asyncio.CancelledError:
            await self._finish(job, "canceled", started_monotonic)
            raise
        except Exception as exc:
            await self._finish(job, "failed", started_monotonic, str(exc))
            raise

        await self._finish(job, "completed", started_monotonic)
        return result

    async def snapshot(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        kind: str | None = None,
        username: str | None = None,
        user_id: str | None = None,
        problem_id: str | None = None,
    ) -> dict:
        normalized_username = username.lower().strip() if username else None
        normalized_status = status.lower().strip() if status else None
        normalized_kind = kind.lower().strip() if kind else None

        async with self._condition:
            pending_positions = {job_id: index for index, job_id in enumerate(self._pending, start=1)}
            jobs = list(reversed(self._jobs.values()))
            queued_count = sum(1 for job in self._jobs.values() if job.status == "queued")
            running_count = sum(1 for job in self._jobs.values() if job.status == "running")

            filtered = []
            for job in jobs:
                if normalized_status and job.status != normalized_status:
                    continue
                if normalized_kind and job.kind != normalized_kind:
                    continue
                if normalized_username and (job.username or "").lower() != normalized_username:
                    continue
                if user_id and job.user_id != user_id:
                    continue
                if problem_id and job.problem_id != problem_id:
                    continue
                filtered.append(job.to_dict(pending_positions.get(job.id)))
                if len(filtered) >= limit:
                    break

            return {
                "jobs": filtered,
                "total": len(self._jobs),
                "queued": queued_count,
                "running": running_count,
            }

    async def _finish(
        self,
        job: CompileQueueJob,
        status: QueueStatus,
        started_monotonic: float,
        error: str | None = None,
    ) -> None:
        async with self._condition:
            job.status = status
            job.finished_at = utc_now()
            job.run_ms = round((time.monotonic() - started_monotonic) * 1000, 2)
            if error:
                job.error = error[:300]
            if self._active_count > 0:
                self._active_count -= 1
            self._prune_locked()
            self._condition.notify_all()

    def _cancel_queued_locked(self, job: CompileQueueJob) -> None:
        with contextlib.suppress(ValueError):
            self._pending.remove(job.id)
        job.status = "canceled"
        job.finished_at = utc_now()
        job.wait_ms = round((job.finished_at - job.queued_at).total_seconds() * 1000, 2)

    def _prune_locked(self) -> None:
        while len(self._jobs) > self._history_limit:
            job_id, job = next(iter(self._jobs.items()))
            if job.status in {"queued", "running"}:
                break
            self._jobs.pop(job_id, None)


compile_queue = CompileQueue(
    concurrency=settings.COMPILER_QUEUE_CONCURRENCY,
    history_limit=settings.COMPILER_QUEUE_HISTORY_LIMIT,
)
