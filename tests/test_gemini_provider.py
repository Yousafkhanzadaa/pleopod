from types import SimpleNamespace
from typing import Any

import pytest

from app.providers.ai import SpeakerVoice, TextGeneration
from app.providers.gemini import GeminiAIProvider, _is_retryable_gemini_error


class _Models:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_images(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            generated_images=[
                SimpleNamespace(
                    image=SimpleNamespace(image_bytes=b"image-bytes", mime_type="image/png")
                )
            ]
        )


class _GeminiError(RuntimeError):
    def __init__(self, code: int):
        super().__init__(f"Gemini error {code}")
        self.code = code


def test_retryable_gemini_error_only_accepts_transient_statuses() -> None:
    assert _is_retryable_gemini_error(_GeminiError(408))
    assert _is_retryable_gemini_error(_GeminiError(429))
    assert _is_retryable_gemini_error(_GeminiError(503))
    assert not _is_retryable_gemini_error(_GeminiError(400))
    assert not _is_retryable_gemini_error(_GeminiError(403))


@pytest.mark.asyncio
async def test_generate_text_uses_fallback_after_transient_primary_failure() -> None:
    provider = GeminiAIProvider.__new__(GeminiAIProvider)
    provider.settings = SimpleNamespace(gemini_text_fallback_model="gemini-2.5-flash-lite")
    calls: list[tuple[str, Any]] = []

    def generate_content(*, model, contents, config):
        calls.append((model, config))
        if model == "gemini-3.1-flash-lite":
            raise _GeminiError(503)
        return SimpleNamespace(
            text="fallback response",
            candidates=[],
            parts=[],
        )

    provider.client = SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    )

    result = await provider.generate_text(
        "research this topic",
        "gemini-3.1-flash-lite",
        use_google_search=True,
        response_schema={"type": "object"},
    )

    assert isinstance(result, TextGeneration)
    assert result.text == "fallback response"
    assert result.raw["requested_model"] == "gemini-3.1-flash-lite"
    assert result.raw["resolved_model"] == "gemini-2.5-flash-lite"
    assert [model for model, _ in calls] == [
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-lite",
    ]
    assert calls[0][1].response_mime_type == "application/json"
    assert calls[1][1].response_mime_type is None
    assert calls[1][1].tools


@pytest.mark.asyncio
async def test_generate_text_does_not_fallback_after_permanent_failure() -> None:
    provider = GeminiAIProvider.__new__(GeminiAIProvider)
    provider.settings = SimpleNamespace(gemini_text_fallback_model="gemini-2.5-flash-lite")
    calls: list[str] = []

    def generate_content(*, model, contents, config):
        calls.append(model)
        raise _GeminiError(400)

    provider.client = SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    )

    with pytest.raises(_GeminiError, match="400"):
        await provider.generate_text(
            "research this topic",
            "gemini-3.1-flash-lite",
        )

    assert calls == ["gemini-3.1-flash-lite"]


@pytest.mark.asyncio
async def test_generate_image_uses_imagen_api_for_imagen_models() -> None:
    provider = GeminiAIProvider.__new__(GeminiAIProvider)
    models = _Models()
    provider.client = SimpleNamespace(models=models)

    image = await provider.generate_image("make a thumbnail", "imagen-4.0-fast-generate-001")

    assert image.data == b"image-bytes"
    assert image.mime_type == "image/png"
    assert image.prompt == "make a thumbnail"
    assert models.calls[0]["model"] == "imagen-4.0-fast-generate-001"
    assert models.calls[0]["prompt"] == "make a thumbnail"


def test_extract_response_text_reads_candidate_parts_when_response_text_is_empty() -> None:
    provider = GeminiAIProvider.__new__(GeminiAIProvider)
    response = SimpleNamespace(
        text="",
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text='{"topic":"A sourced topic"}'),
                    ]
                )
            )
        ],
    )

    assert provider._extract_response_text(response) == '{"topic":"A sourced topic"}'


class _FakeTypes:
    class PrebuiltVoiceConfig(SimpleNamespace):
        pass

    class VoiceConfig(SimpleNamespace):
        pass

    class SpeakerVoiceConfig(SimpleNamespace):
        pass

    class MultiSpeakerVoiceConfig(SimpleNamespace):
        pass

    class SpeechConfig(SimpleNamespace):
        pass


def test_tts_speech_config_uses_single_voice_config_for_one_speaker() -> None:
    provider = GeminiAIProvider.__new__(GeminiAIProvider)

    config = provider._tts_speech_config(
        _FakeTypes,
        [SpeakerVoice("Arman", "Algenib")],
    )

    assert config.voice_config.prebuilt_voice_config.voice_name == "Algenib"
    assert not hasattr(config, "multi_speaker_voice_config")


def test_tts_speech_config_uses_multi_speaker_config_for_two_speakers() -> None:
    provider = GeminiAIProvider.__new__(GeminiAIProvider)

    config = provider._tts_speech_config(
        _FakeTypes,
        [SpeakerVoice("Arman", "Algenib"), SpeakerVoice("Maya", "Aoede")],
    )

    voice_configs = config.multi_speaker_voice_config.speaker_voice_configs
    assert [item.speaker for item in voice_configs] == ["Arman", "Maya"]
    assert [item.voice_config.prebuilt_voice_config.voice_name for item in voice_configs] == [
        "Algenib",
        "Aoede",
    ]
    assert not hasattr(config, "voice_config")
