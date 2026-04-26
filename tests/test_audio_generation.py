import pytest

from app.agents.audio_generation import AudioGenerationAgent
from app.agents.publisher import duration_seconds_from_artifact
from app.models.enums import ArtifactType


class _ArtifactRepo:
    async def get_latest_for_job(self, job_id: str, artifact_type: str) -> dict | None:
        if artifact_type == ArtifactType.FINAL_AUDIO:
            return {"id": "final-artifact-id", "r2_key": f"jobs/{job_id}/audio/final.mp3"}
        return None


class _Context:
    artifact_repo = _ArtifactRepo()

    async def latest_json(self, job_id: str, artifact_type: str) -> dict:
        raise AssertionError("latest_json should not be called when final audio already exists")


@pytest.mark.asyncio
async def test_audio_generation_skips_when_final_audio_exists() -> None:
    agent = AudioGenerationAgent()

    result = await agent.run({"id": "job-1"}, _Context(), {})

    assert result.output_artifact_id == "final-artifact-id"


def test_publisher_duration_seconds_uses_audio_artifact_metadata() -> None:
    assert duration_seconds_from_artifact({"metadata": {"duration_seconds": 64.4}}) == 64
    assert duration_seconds_from_artifact({"metadata": {"duration_seconds": 64.6}}) == 65
    assert duration_seconds_from_artifact({"metadata": {}}) is None
