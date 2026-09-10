"""Expired execution receipts remain isolated by anonymous owner session."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.database import ExecutionJob
from app.services.execution_retention import expire_execution_content
from tests.test_execution_api import runtime


AT = datetime(2030, 1, 20)


@pytest.mark.asyncio
async def test_expired_receipt_request_id_is_scoped_to_each_anonymous_session(runtime):
    queue, factory = runtime
    request_id = str(uuid4())
    original = {"language": "python", "code": "print(42)"}
    headers = {"X-Request-ID": request_id}

    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as first,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as second,
    ):
        accepted = await first.post("/api/v1/executions", headers=headers, json=original)
        assert accepted.status_code == 202
        original_job_id = accepted.json()["id"]
        claim = queue.claim()
        assert claim is not None and claim.id == original_job_id
        assert queue.finish(
            original_job_id,
            claim.token,
            {
                "verdict": "finished",
                "value": {"stdout": "42", "stderr": "", "exit_code": 0, "execution_time": 0},
            },
        )

        with factory() as db:
            job = db.get(ExecutionJob, original_job_id)
            job.finished_at = AT - timedelta(days=8)
            db.commit()
        with factory() as db:
            assert expire_execution_content(db, at=AT, retention_days=7) == 1
            db.commit()

        assert (await first.get(f"/api/v1/executions/{original_job_id}")).status_code == 410
        assert (await second.get(f"/api/v1/executions/{original_job_id}")).status_code == 404

        replacement = await second.post("/api/v1/executions", headers=headers, json=original)
        assert replacement.status_code == 202
        replacement_job_id = replacement.json()["id"]
        assert replacement_job_id != original_job_id

        assert (await first.get(f"/api/v1/executions/{original_job_id}")).status_code == 410
        assert (await second.get(f"/api/v1/executions/{original_job_id}")).status_code == 404
        assert (await first.post("/api/v1/executions", headers=headers, json=original)).status_code == 410
        assert (
            await first.post(
                "/api/v1/executions",
                headers=headers,
                json={**original, "code": "print('changed')"},
            )
        ).status_code == 410
        assert (await second.get(f"/api/v1/executions/{replacement_job_id}")).status_code == 200

        with factory() as db:
            assert db.query(ExecutionJob).count() == 2
            expired = db.get(ExecutionJob, original_job_id)
            replacement_job = db.get(ExecutionJob, replacement_job_id)
            assert expired.payload == {}
            assert expired.result is None
            assert expired.content_expired_at == AT
            assert replacement_job.payload["code"] == original["code"]
