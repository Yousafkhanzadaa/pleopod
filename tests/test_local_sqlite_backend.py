from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.queue import QueueRepository
from app.db.repositories import ArtifactRepository, JobRepository, TTSSegmentRepository
from app.db.session import dispose_engine, get_sessionmaker, initialize_database
from app.models.enums import ArtifactType, JobStatus


@pytest.mark.asyncio
async def test_sqlite_backend_stores_jobs_artifacts_segments_and_queue_messages(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'pleopod.db'}",
        database_backend="sqlite",
        queue_backend="sqlite",
    )
    await dispose_engine()
    await initialize_database(settings)

    try:
        sessionmaker = get_sessionmaker(settings)
        async with sessionmaker() as session:
            jobs = JobRepository(session)
            artifacts = ArtifactRepository(session)
            segments = TTSSegmentRepository(session)
            queue = QueueRepository(session)

            job = await jobs.create_job(
                {
                    "topic": "Local-first pipeline",
                    "category": "Tech",
                    "audience": "builders",
                    "target_duration_seconds": 120,
                    "language": "en",
                    "tone": "clear",
                    "source_urls": [],
                    "auto_publish": False,
                    "metadata": {"mode": "local"},
                },
                created_by="test",
            )

            assert job["metadata"] == {"mode": "local"}
            assert job["auto_publish"] is False

            updated = await jobs.update_job(job["id"], status=JobStatus.RUNNING)
            assert updated is not None
            assert updated["status"] == "running"

            artifact = await artifacts.create_artifact(
                artifact_type=ArtifactType.SCRIPT_JSON,
                r2_key=f"jobs/{job['id']}/scripts/script_v1.json",
                mime_type="application/json",
                job_id=job["id"],
                metadata={"fixture": True},
            )
            latest = await artifacts.get_latest_for_job(job["id"], ArtifactType.SCRIPT_JSON)
            assert latest is not None
            assert latest["id"] == artifact["id"]
            assert latest["metadata"] == {"fixture": True}

            await segments.upsert_segment(job["id"], 1, "Arman: Hello", "completed", "seg.wav")
            assert await segments.get_completed_segment_key(job["id"], 1) == "seg.wav"

            msg_id = await queue.send(
                "script_queue", {"job_id": job["id"], "step": "script"}, delay_seconds=0
            )
            messages = await queue.read(
                "script_queue",
                visibility_timeout_seconds=30,
                qty=1,
                max_poll_seconds=0,
            )
            assert messages == [
                type(messages[0])(
                    msg_id=msg_id,
                    read_ct=1,
                    message={"job_id": job["id"], "step": "script"},
                )
            ]
            assert await queue.delete("script_queue", msg_id)
    finally:
        await dispose_engine()
