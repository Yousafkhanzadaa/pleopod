import pytest

from app.agents.audio_generation import AudioGenerationAgent, tts_config_fingerprint
from app.agents.publisher import duration_seconds_from_artifact
from app.models.enums import ArtifactType
from app.providers.ai import AudioGeneration


class _ArtifactRepo:
    def __init__(self, final_audio: dict | None = None) -> None:
        self.final_audio = final_audio

    async def get_latest_for_job(self, job_id: str, artifact_type: str) -> dict | None:
        if artifact_type == ArtifactType.FINAL_AUDIO:
            return self.final_audio
        return None


class _Context:
    def __init__(self, config: dict, final_audio: dict | None) -> None:
        self.config = config
        self.artifact_repo = _ArtifactRepo(final_audio)

    async def latest_json(self, job_id: str, artifact_type: str) -> dict:
        assert artifact_type == ArtifactType.TTS_CONFIG_JSON
        return self.config


@pytest.mark.asyncio
async def test_audio_generation_skips_when_final_audio_exists() -> None:
    config = _config("Arman: Current line.")
    final_audio = {
        "id": "final-artifact-id",
        "r2_key": "jobs/job-1/audio/final.wav",
        "metadata": {"tts_config_fingerprint": tts_config_fingerprint(config)},
    }
    agent = AudioGenerationAgent()

    result = await agent.run({"id": "job-1"}, _Context(config, final_audio), {})

    assert result.output_artifact_id == "final-artifact-id"


@pytest.mark.asyncio
async def test_audio_generation_regenerates_stale_final_and_changed_segment() -> None:
    config = _config("Arman: Current line.")
    context = _GenerationContext(config)
    agent = AudioGenerationAgent()

    result = await agent.run({"id": "job-1"}, context, {})

    assert result.output_artifact_id == "final-audio-id"
    assert context.ai.prompts == ["Arman: Current line."]
    assert context.segment_repo.reuse_attempts == [(1, "Arman: Current line.")]
    assert context.segment_repo.upserts[-1]["status"] == "completed"
    assert context.artifact_service.final_metadata["segment_count"] == 1
    assert context.artifact_service.final_metadata[
        "tts_config_fingerprint"
    ] == tts_config_fingerprint(config)
    assert context.artifact_service.final_metadata["segment_timings"][0]["source_transcript"] == (
        "Arman: Current line."
    )


def test_publisher_duration_seconds_uses_audio_artifact_metadata() -> None:
    assert duration_seconds_from_artifact({"metadata": {"duration_seconds": 64.4}}) == 64
    assert duration_seconds_from_artifact({"metadata": {"duration_seconds": 64.6}}) == 65
    assert duration_seconds_from_artifact({"metadata": {}}) is None


def _config(source_transcript: str) -> dict:
    return {
        "tts_model": "fake-tts",
        "export_format": "wav",
        "max_source_chunk_chars": 1200,
        "speakers": [{"speaker": "Arman", "voice_name": "Charon", "style": "warm"}],
        "chunks": [
            {
                "index": 1,
                "transcript": source_transcript,
                "source_transcript": source_transcript,
                "source_char_count": len(source_transcript),
                "prompt_char_count": len(source_transcript),
            }
        ],
    }


class _GenerationContext(_Context):
    def __init__(self, config: dict) -> None:
        super().__init__(
            config,
            {
                "id": "stale-final-id",
                "r2_key": "jobs/job-1/audio/final.wav",
                "metadata": {"tts_config_fingerprint": "old"},
            },
        )
        self.ai = _AI()
        self.storage = _Storage()
        self.segment_repo = _SegmentRepo()
        self.tts_segment_repo = self.segment_repo
        self.artifact_service = _ArtifactService()


class _AI:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate_tts(self, prompt: str, model: str, speakers: list) -> AudioGeneration:
        self.prompts.append(prompt)
        return AudioGeneration(pcm_data=b"\0" * 4800, sample_rate=24000, channels=1, sample_width=2)


class _Storage:
    async def get_bytes(self, key: str) -> bytes:
        raise AssertionError("stale segment should not be reused")


class _SegmentRepo:
    def __init__(self) -> None:
        self.reuse_attempts: list[tuple[int, str]] = []
        self.upserts: list[dict] = []

    async def get_completed_segment_key(
        self, job_id: str, index: int, transcript: str | None = None
    ) -> str | None:
        self.reuse_attempts.append((index, transcript or ""))
        return None

    async def upsert_segment(
        self,
        job_id: str,
        index: int,
        transcript: str,
        status: str,
        r2_key: str | None = None,
    ) -> None:
        self.upserts.append(
            {
                "job_id": job_id,
                "index": index,
                "transcript": transcript,
                "status": status,
                "r2_key": r2_key,
            }
        )


class _ArtifactService:
    def __init__(self) -> None:
        self.final_metadata: dict = {}

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        artifact_type: ArtifactType,
        mime_type: str,
        job_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        if artifact_type == ArtifactType.FINAL_AUDIO:
            self.final_metadata = metadata or {}
            return {"id": "final-audio-id", "r2_key": key, "metadata": self.final_metadata}
        return {"id": "segment-id", "r2_key": key, "metadata": metadata or {}}
