from types import SimpleNamespace

import pytest

from app.agents.audio_generation import (
    AudioGenerationAgent,
    canonical_word_timings,
    line_timings_from_word_alignment,
    tts_config_fingerprint,
    tts_segment_fingerprint,
)
from app.agents.publisher import duration_seconds_from_artifact
from app.models.enums import ArtifactType
from app.providers.ai import AudioGeneration, WordAlignment, WordTiming


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
        self.settings = SimpleNamespace(
            tts_generation_mode=config.get("generation_mode") or "chunked",
            ai_provider="fake",
        )

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
    expected_segment_fingerprint = tts_segment_fingerprint(config, config["chunks"][0])
    assert context.segment_repo.reuse_attempts == [(1, expected_segment_fingerprint)]
    assert context.segment_repo.upserts[-1]["status"] == "completed"
    assert context.segment_repo.upserts[-1]["transcript"] == expected_segment_fingerprint
    assert context.artifact_service.final_metadata["segment_count"] == 1
    assert context.artifact_service.final_metadata[
        "tts_config_fingerprint"
    ] == tts_config_fingerprint(config)
    assert context.artifact_service.final_metadata["segment_timings"][0]["source_transcript"] == (
        "Arman: Current line."
    )


@pytest.mark.asyncio
async def test_audio_generation_stores_measured_word_and_line_timings() -> None:
    config = _config("Arman: Current line.")
    context = _AlignedGenerationContext(config)

    await AudioGenerationAgent().run(
        {"id": "job-1", "language": "en"},
        context,
        {},
    )

    metadata = context.artifact_service.final_metadata
    assert metadata["word_timings"] == [
        {"word": "Current", "start_seconds": 0.05, "end_seconds": 0.18},
        {"word": "line.", "start_seconds": 0.19, "end_seconds": 0.31},
    ]
    assert metadata["line_timings"][0]["start_seconds"] == 0.05
    assert metadata["line_timings"][0]["end_seconds"] == 0.31
    assert context.aligner.calls[0]["model"] == "whisper-1"


def test_publisher_duration_seconds_uses_audio_artifact_metadata() -> None:
    assert duration_seconds_from_artifact({"metadata": {"duration_seconds": 64.4}}) == 64
    assert duration_seconds_from_artifact({"metadata": {"duration_seconds": 64.6}}) == 65
    assert duration_seconds_from_artifact({"metadata": {}}) is None


def test_line_timings_from_word_alignment_maps_script_lines() -> None:
    words = [
        WordTiming("First", 0.1, 0.3),
        WordTiming("idea", 0.31, 0.55),
        WordTiming("Second", 0.8, 1.0),
        WordTiming("point", 1.01, 1.25),
    ]

    timings = line_timings_from_word_alignment(
        "Arman: First idea.\nArman: Second point.",
        words,
    )

    assert [(item["start_seconds"], item["end_seconds"]) for item in timings] == [
        (0.1, 0.55),
        (0.8, 1.25),
    ]


def test_line_timings_from_word_alignment_labels_unlabeled_lines() -> None:
    words = [
        WordTiming("First", 0.1, 0.3),
        WordTiming("idea", 0.31, 0.55),
        WordTiming("Wrapped", 0.8, 1.0),
        WordTiming("continuation", 1.01, 1.25),
        WordTiming("Final", 1.4, 1.6),
        WordTiming("point", 1.61, 1.9),
    ]

    timings = line_timings_from_word_alignment(
        "Arman: First idea.\nWrapped continuation.\nArman: Final point.",
        words,
    )

    assert [item["speaker"] for item in timings] == ["Arman", "Arman", "Arman"]
    assert timings[1]["text"] == "Wrapped continuation."


def test_canonical_word_timings_restores_verified_spelling_and_numbers() -> None:
    aligned = [
        WordTiming("by", 0.2, 0.4),
        WordTiming("Anthropx", 0.4, 0.8),
        WordTiming("2", 0.9, 1.05),
        WordTiming("8", 1.05, 1.2),
        WordTiming("model", 1.25, 1.6),
    ]

    words = canonical_word_timings(
        "Arman: driven by Anthropic's 2.8 model.",
        aligned,
    )

    assert [word.word for word in words] == [
        "driven",
        "by",
        "Anthropic's",
        "2.8",
        "model.",
    ]
    assert all(word.end_seconds > word.start_seconds for word in words)
    assert all(
        earlier.end_seconds <= later.start_seconds
        for earlier, later in zip(words, words[1:], strict=False)
    )


def _config(source_transcript: str) -> dict:
    return {
        "tts_model": "fake-tts",
        "export_format": "wav",
        "generation_mode": "single_request",
        "max_source_chunk_chars": 1200,
        "speakers": [{"speaker": "Arman", "voice_name": "Algenib", "style": "low-pitched"}],
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


class _AlignedGenerationContext(_GenerationContext):
    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.settings.enable_word_alignment = True
        self.settings.alignment_model = "whisper-1"
        self.aligner = _Aligner()
        self.word_aligner = self.aligner


class _AI:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate_tts(self, prompt: str, model: str, speakers: list) -> AudioGeneration:
        self.prompts.append(prompt)
        return AudioGeneration(pcm_data=b"\0" * 4800, sample_rate=24000, channels=1, sample_width=2)


class _Aligner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def align_words(
        self,
        audio_data: bytes,
        *,
        mime_type: str,
        model: str,
        language: str | None = None,
    ) -> WordAlignment:
        self.calls.append(
            {
                "audio_data": audio_data,
                "mime_type": mime_type,
                "model": model,
                "language": language,
            }
        )
        return WordAlignment(
            text="Current line.",
            words=[
                WordTiming("Current", 0.05, 0.18),
                WordTiming("line", 0.19, 0.31),
            ],
        )


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
