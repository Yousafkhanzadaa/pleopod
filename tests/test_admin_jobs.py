from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.api.deps import admin_dep, db_session_dep, settings_dep
from app.core.config import Settings
from app.db.queue import QueueRepository
from app.db.repositories import ArtifactRepository, JobRepository
from app.main import app


async def _db_override() -> AsyncIterator[object]:
    yield object()


def test_create_generation_job_orchestrates_title_and_queues_research(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _create_job(self, payload: dict, created_by: str | None = None) -> dict:
        captured["payload"] = payload
        captured["created_by"] = created_by
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            **payload,
            "status": "queued",
            "current_step": None,
            "error": None,
            "created_at": "2026-04-23T00:00:00+00:00",
            "updated_at": "2026-04-23T00:00:00+00:00",
        }

    async def _send(self, queue_name: str, message: dict, delay_seconds: int = 0) -> int:
        captured["queue_name"] = queue_name
        captured["message"] = message
        return 1

    monkeypatch.setattr(JobRepository, "create_job", _create_job)
    monkeypatch.setattr(QueueRepository, "send", _send)

    app.dependency_overrides[admin_dep] = lambda: {"auth_type": "test"}
    app.dependency_overrides[db_session_dep] = _db_override
    app.dependency_overrides[settings_dep] = lambda: Settings(_env_file=None, ai_provider="fake")

    try:
        response = TestClient(app).post(
            "/admin/generation-jobs",
            json={"title": "AI Coding Agents in 2026"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert captured["payload"]["topic"] == "AI Coding Agents in 2026"
    assert captured["created_by"] == "test"
    assert captured["queue_name"] == "research_queue"
    assert captured["message"]["step"] == "research"


def test_publish_generation_job_rejects_missing_artifacts(monkeypatch) -> None:
    async def _get_job(self, job_id: str) -> dict:
        return {
            "id": str(job_id),
            "topic": "AI",
            "category": "Tech",
            "audience": "developers",
            "target_duration_seconds": 600,
            "language": "en",
            "tone": "clear",
            "status": "queued",
            "current_step": "audio_generation",
            "auto_publish": False,
            "error": None,
            "metadata": {},
            "created_at": "2026-04-23T00:00:00+00:00",
            "updated_at": "2026-04-23T00:00:00+00:00",
        }

    async def _get_latest_for_job(self, job_id: str, artifact_type: str) -> None:
        return None

    async def _send(self, queue_name: str, message: dict, delay_seconds: int = 0) -> int:
        raise AssertionError("publish should not queue when required artifacts are missing")

    monkeypatch.setattr(JobRepository, "get_job", _get_job)
    monkeypatch.setattr(ArtifactRepository, "get_latest_for_job", _get_latest_for_job)
    monkeypatch.setattr(QueueRepository, "send", _send)

    app.dependency_overrides[admin_dep] = lambda: {"auth_type": "test"}
    app.dependency_overrides[db_session_dep] = _db_override

    try:
        response = TestClient(app).post(
            "/admin/generation-jobs/11111111-1111-1111-1111-111111111111/publish"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "missing required artifacts" in response.json()["detail"]


def test_approve_script_requires_awaiting_approval_status(monkeypatch) -> None:
    async def _get_job(self, job_id: str) -> dict:
        return {
            "id": str(job_id),
            "topic": "AI",
            "category": "Tech",
            "audience": "developers",
            "target_duration_seconds": 600,
            "language": "en",
            "tone": "clear",
            "status": "queued",
            "current_step": "fact_check",
            "auto_publish": False,
            "error": None,
            "metadata": {},
            "created_at": "2026-04-23T00:00:00+00:00",
            "updated_at": "2026-04-23T00:00:00+00:00",
        }

    monkeypatch.setattr(JobRepository, "get_job", _get_job)

    app.dependency_overrides[admin_dep] = lambda: {"auth_type": "test"}
    app.dependency_overrides[db_session_dep] = _db_override

    try:
        response = TestClient(app).post(
            "/admin/generation-jobs/11111111-1111-1111-1111-111111111111/approve-script",
            json={"note": "looks good"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "Job is not awaiting script approval"
