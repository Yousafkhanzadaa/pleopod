from app.agents.audio_config import build_tts_prompt, normalize_tts_transcript


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

    assert prompt.startswith("TTS the following conversation between Arman and Maya.")
    assert "### DIRECTOR'S NOTES" in prompt
    assert "### TRANSCRIPT\nArman: Welcome back." in prompt
