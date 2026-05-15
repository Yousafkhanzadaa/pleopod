from app.agents.audio_config import (
    GEMINI_TTS_SAFE_PROMPT_CHARS,
    GEMINI_TTS_SAFE_SOURCE_CHARS,
    build_tts_config,
    build_tts_prompt,
    normalize_tts_transcript,
    source_transcript_from_tts_prompt,
    tts_config_needs_rebuild,
)
from app.core.config import Settings


def test_normalize_tts_transcript_removes_generated_preamble() -> None:
    transcript = """
TTS the following conversation between Arman and Maya:

Arman: Welcome back.
Maya: Let's unpack the story.
""".strip()

    normalized = normalize_tts_transcript(transcript)

    assert normalized.startswith("Arman: Welcome back.")
    assert "TTS the following conversation" not in normalized


def test_build_tts_prompt_has_clear_transcript_boundary() -> None:
    prompt = build_tts_prompt(
        "Arman: Welcome back.\nMaya: Let's unpack the story.",
        [
            {"name": "Arman", "style": "clear and warm"},
            {"name": "Maya", "style": "curious and energetic"},
        ],
    )

    assert prompt.startswith("Make Arman sound clear and warm")
    assert "Keep each speaker's voice identity" in prompt
    assert "TTS the following conversation between Arman and Maya:" in prompt
    assert "### DIRECTOR'S NOTES" not in prompt
    assert "### TRANSCRIPT\nArman: Welcome back." in prompt
    assert source_transcript_from_tts_prompt(prompt).startswith("Arman: Welcome back.")


def test_tts_config_rebuild_detects_oversized_old_prompt() -> None:
    config = {
        "max_source_chunk_chars": 6500,
        "chunks": [
            {
                "index": 1,
                "transcript": "TTS the following conversation between Arman and Maya:\n\n"
                + ("Arman: hello\n" * 500),
                "prompt_char_count": GEMINI_TTS_SAFE_PROMPT_CHARS + 1,
            }
        ],
    }

    assert tts_config_needs_rebuild(config)


def test_build_tts_config_replaces_unsupported_voice_names() -> None:
    script = {
        "speakers": [
            {"name": "Arman", "voice_name": "en-US-Neural2-C"},
            {"name": "Maya", "voice_name": "en-US-Neural2-F"},
        ],
        "transcript": "Arman: Welcome back.\nMaya: Let's unpack the story.",
    }

    config = build_tts_config(
        script,
        Settings(_env_file=None, max_tts_chunk_chars=3000),  # type: ignore[call-arg]
    )

    assert config["generation_mode"] == "chunked"
    assert config["max_source_chunk_chars"] == GEMINI_TTS_SAFE_SOURCE_CHARS
    assert len(config["chunks"]) == 1
    assert config["chunks"][0]["source_transcript"].startswith("Arman: Welcome back.")
    assert config["speakers"][0]["voice_name"] == "Charon"
    assert config["speakers"][1]["voice_name"] == "Aoede"


def test_tts_config_rebuild_detects_unsupported_voice_names() -> None:
    config = {
        "generation_mode": "chunked",
        "max_source_chunk_chars": GEMINI_TTS_SAFE_SOURCE_CHARS,
        "speakers": [{"speaker": "Arman", "voice_name": "en-US-Neural2-C"}],
        "chunks": [{"index": 1, "transcript": "Arman: hello", "prompt_char_count": 12}],
    }

    assert tts_config_needs_rebuild(config)


def test_tts_config_rebuild_detects_generation_mode_mismatch() -> None:
    config = {
        "generation_mode": "single_request",
        "max_source_chunk_chars": 1200,
        "speakers": [{"speaker": "Arman", "voice_name": "Charon"}],
        "chunks": [{"index": 1, "transcript": "Arman: hello", "prompt_char_count": 12}],
    }

    assert tts_config_needs_rebuild(config, Settings(_env_file=None))  # type: ignore[call-arg]


def test_build_tts_config_uses_chunked_mode_by_default() -> None:
    script = {
        "speakers": [
            {"name": "Arman", "voice_name": "Charon"},
            {"name": "Maya", "voice_name": "Aoede"},
        ],
        "transcript": "\n".join(
            [
                "Arman: This is a longer host turn about the topic and why it matters.",
                "Maya: This analyst response adds context, caveats, and useful framing.",
                "Arman: Another host turn keeps the test comfortably above the chunk size.",
                "Maya: Another analyst turn gives the chunker enough work to split.",
            ]
        ),
    }

    config = build_tts_config(
        script,
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            max_tts_chunk_chars=120,
        ),
    )

    assert config["generation_mode"] == "chunked"
    assert config["max_source_chunk_chars"] == 120
    assert len(config["chunks"]) > 1


def test_build_tts_config_can_use_single_request_mode_when_explicit() -> None:
    script = {
        "speakers": [
            {"name": "Arman", "voice_name": "Charon"},
            {"name": "Maya", "voice_name": "Aoede"},
        ],
        "transcript": "Arman: Welcome back.\nMaya: Let's unpack the story.",
    }

    config = build_tts_config(
        script,
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            tts_generation_mode="single_request",
            max_tts_chunk_chars=120,
        ),
    )

    assert config["generation_mode"] == "single_request"
    assert config["max_source_chunk_chars"] == len(script["transcript"])
    assert len(config["chunks"]) == 1
