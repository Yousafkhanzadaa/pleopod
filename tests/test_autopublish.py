import json
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.db.repositories import AutomationLockRepository, JobRepository
from app.db.session import dispose_engine, get_sessionmaker, initialize_database
from app.models.enums import JobStatus
from app.providers.ai import AudioGeneration, ImageGeneration, TextGeneration
from app.worker.autopublish import AutopublishRunner


@pytest.mark.asyncio
async def test_automation_lock_allows_only_one_owner(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    await dispose_engine()
    await initialize_database(settings)

    try:
        sessionmaker = get_sessionmaker(settings)
        async with sessionmaker() as session:
            lock_repo = AutomationLockRepository(session)
            assert await lock_repo.acquire("autopublish", "owner-1", ttl_seconds=60)
            assert not await lock_repo.acquire("autopublish", "owner-2", ttl_seconds=60)
            await lock_repo.release("autopublish", "owner-1")
            assert await lock_repo.acquire("autopublish", "owner-2", ttl_seconds=60)
    finally:
        await dispose_engine()


@pytest.mark.asyncio
async def test_autopublish_runner_creates_and_completes_fake_pipeline(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    await dispose_engine()

    try:
        result = await AutopublishRunner(settings).run_once()

        assert result["status"] == JobStatus.COMPLETED
        assert result["completedSteps"] == [
            "research",
            "script",
            "fact_check",
            "thumbnail",
            "audio_config",
            "audio_generation",
            "publish",
        ]

        sessionmaker = get_sessionmaker(settings)
        async with sessionmaker() as session:
            job = await JobRepository(session).get_job(result["jobId"])

        assert job is not None
        assert job["status"] == JobStatus.COMPLETED
        assert job["auto_publish"] is True
        assert job["created_by"] == "autopublish"
        assert job["metadata"]["autopublish"] is True
        assert job["metadata"]["episode_id"]
    finally:
        await dispose_engine()


@pytest.mark.asyncio
async def test_autopublish_scout_only_does_not_create_job(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    await dispose_engine()

    try:
        result = await AutopublishRunner(settings).scout_only()

        assert result["status"] == "scouted"
        assert result["payload"]["topic"] == "AI Coding Agents in 2026"
        assert result["payload"]["auto_publish"] is True

        sessionmaker = get_sessionmaker(settings)
        async with sessionmaker() as session:
            jobs = await JobRepository(session).list_jobs()

        assert jobs == []
    finally:
        await dispose_engine()


@pytest.mark.asyncio
async def test_autopublish_scout_only_reports_insufficient_sources(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        autopublish_min_source_urls=3,
        autopublish_trusted_source_domains="openai.com,theverge.com",
    )
    await dispose_engine()

    try:
        runner = AutopublishRunner(settings)
        runner.ai = InsufficientSourceProvider()

        result = await runner.scout_only()

        assert result["status"] == "needs_sources"
        assert result["reason"] == "insufficient_topic_sources"
        assert result["requiredSourceUrls"] == 3
        assert result["foundSourceUrls"] == 1

        sessionmaker = get_sessionmaker(settings)
        async with sessionmaker() as session:
            jobs = await JobRepository(session).list_jobs()

        assert jobs == []
    finally:
        await dispose_engine()


@pytest.mark.asyncio
async def test_autopublish_run_skips_insufficient_sources(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        autopublish_min_source_urls=3,
        autopublish_trusted_source_domains="openai.com,theverge.com",
    )
    await dispose_engine()

    try:
        runner = AutopublishRunner(settings)
        runner.ai = InsufficientSourceProvider()

        result = await runner.run_once()

        assert result["status"] == "skipped"
        assert result["reason"] == "insufficient_topic_sources"
        assert result["requiredSourceUrls"] == 3
        assert result["foundSourceUrls"] == 1

        sessionmaker = get_sessionmaker(settings)
        async with sessionmaker() as session:
            jobs = await JobRepository(session).list_jobs()

        assert jobs == []
    finally:
        await dispose_engine()


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'pleopod.db'}",
        "database_backend": "sqlite",
        "queue_backend": "sqlite",
        "storage_backend": "local",
        "local_storage_path": tmp_path / "artifacts",
        "ai_provider": "fake",
        "audio_export_format": "wav",
        "enable_video_rendering": False,
        "enable_youtube_uploading": False,
        "autopublish_min_source_urls": 1,
        "autopublish_recent_job_limit": 10,
        "autopublish_lock_ttl_seconds": 60,
        "autopublish_max_runtime_seconds": 60,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


class InsufficientSourceProvider:
    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: object | None = None,
    ) -> TextGeneration:
        return TextGeneration(
            text=json.dumps(
                {
                    "topic": "A timely AI topic",
                    "title": "A timely AI topic",
                    "source_urls": [
                        "https://openai.com/blog/source",
                        "https://example.com/scraped-summary",
                    ],
                    "source_quality": {
                        "primary_sources": ["https://openai.com/blog/source"],
                        "reputable_coverage": ["https://example.com/scraped-summary"],
                    },
                    "candidates": [],
                }
            )
        )

    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        raise NotImplementedError

    async def generate_tts(self, prompt: str, model: str, speakers: list[Any]) -> AudioGeneration:
        raise NotImplementedError
