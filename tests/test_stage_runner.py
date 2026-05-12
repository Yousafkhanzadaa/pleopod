from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.queue import QueueRepository
from app.db.repositories import ArtifactRepository, JobRepository
from app.db.session import dispose_engine, get_sessionmaker, initialize_database
from app.models.enums import ArtifactType, PipelineStep
from app.worker.stage_runner import build_message, list_stages, parse_args, run_stage


def test_stage_runner_lists_contracts() -> None:
    contracts = list_stages()

    assert contracts[0]["step"] == "research"
    assert "script" in [contract["step"] for contract in contracts]
    assert contracts[1]["consumes"] == ["memory_md", "claim_bank_json"]


def test_stage_runner_builds_force_message() -> None:
    args = parse_args(["run", "audio_generation", "job-1", "--force"])

    assert build_message(args) == {
        "job_id": "job-1",
        "step": "audio_generation",
        "force": True,
    }


@pytest.mark.asyncio
async def test_stage_runner_runs_one_stage_without_enqueueing_next(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'pleopod.db'}",
        database_backend="sqlite",
        queue_backend="sqlite",
        storage_backend="local",
        local_storage_path=tmp_path / "artifacts",
        ai_provider="fake",
    )
    await dispose_engine()
    await initialize_database(settings)

    try:
        sessionmaker = get_sessionmaker(settings)
        async with sessionmaker() as session:
            job = await JobRepository(session).create_job(
                {
                    "topic": "Local stage runner",
                    "category": "Tech",
                    "audience": "builders",
                    "target_duration_seconds": 120,
                    "language": "en",
                    "tone": "clear",
                    "source_urls": [],
                    "auto_publish": False,
                    "metadata": {},
                },
                created_by="test",
            )
            job_id = str(job["id"])

        result = await run_stage(PipelineStep.RESEARCH, job_id, settings=settings)

        assert result["step"] == "research"
        assert result["nextSteps"] == ["script"]
        assert result["enqueuedNextSteps"] == []

        async with sessionmaker() as session:
            artifact_repo = ArtifactRepository(session)
            queue_repo = QueueRepository(session)
            assert await artifact_repo.get_latest_for_job(job_id, ArtifactType.MEMORY_MD)
            assert await artifact_repo.get_latest_for_job(job_id, ArtifactType.CLAIM_BANK_JSON)
            assert (
                await queue_repo.read(
                    "script_queue",
                    visibility_timeout_seconds=30,
                    max_poll_seconds=0,
                )
                == []
            )
    finally:
        await dispose_engine()
