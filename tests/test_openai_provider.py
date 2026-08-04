import base64

import httpx
import pytest

from app.providers.ai import AudioGeneration, SpeakerVoice
from app.providers.openai import (
    OpenAIAudioProvider,
    OpenAIImageGenerationError,
    OpenAIImageProvider,
    _is_retryable_openai_image_error,
)
from app.services.audio import wav_bytes


@pytest.mark.asyncio
async def test_generate_image_decodes_openai_image_response(monkeypatch) -> None:
    provider = OpenAIImageProvider.__new__(OpenAIImageProvider)
    provider.settings = type("Settings", (), {"openai_image_output_format": "png"})()

    captured: dict[str, str] = {}

    def fake_generate(prompt: str, model: str):
        captured["prompt"] = prompt
        captured["model"] = model
        return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode("ascii")}]}

    monkeypatch.setattr(provider, "_generate_image_sync", fake_generate)

    image = await provider.generate_image("make a thumbnail", "gpt-image-2")

    assert image.data == b"image-bytes"
    assert image.mime_type == "image/png"
    assert image.prompt == "make a thumbnail"
    assert captured == {"prompt": "make a thumbnail", "model": "gpt-image-2"}


def test_generate_image_sync_posts_openai_image_options(monkeypatch) -> None:
    provider = OpenAIImageProvider.__new__(OpenAIImageProvider)
    provider.settings = type(
        "Settings",
        (),
        {
            "openai_api_key": "openai-key",
            "openai_image_size": "1280x720",
            "openai_image_quality": "medium",
            "openai_image_output_format": "png",
            "openai_image_timeout_seconds": 300,
        },
    )()

    captured: dict[str, object] = {}

    class _Response:
        is_error = False

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"data": [{"b64_json": "abc"}]}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.providers.openai.httpx.post", fake_post)

    response = provider._generate_image_sync("make a thumbnail", "gpt-image-2")

    assert response == {"data": [{"b64_json": "abc"}]}
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert captured["headers"] == {
        "Authorization": "Bearer openai-key",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "prompt": "make a thumbnail",
        "model": "gpt-image-2",
        "n": 1,
        "size": "1280x720",
        "quality": "medium",
        "output_format": "png",
    }
    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 10
    assert timeout.read == 300


def test_generate_image_sync_preserves_openai_error_details(monkeypatch) -> None:
    provider = OpenAIImageProvider.__new__(OpenAIImageProvider)
    provider.settings = type(
        "Settings",
        (),
        {
            "openai_api_key": "openai-key",
            "openai_image_size": "1280x720",
            "openai_image_quality": "high",
            "openai_image_output_format": "png",
            "openai_image_timeout_seconds": 300,
        },
    )()
    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    response = httpx.Response(
        400,
        request=request,
        headers={"x-request-id": "req_thumbnail_123"},
        json={
            "error": {
                "message": "The requested image size is invalid.",
                "type": "image_generation_user_error",
                "code": "invalid_size",
            }
        },
    )
    monkeypatch.setattr("app.providers.openai.httpx.post", lambda *_args, **_kwargs: response)

    with pytest.raises(OpenAIImageGenerationError) as caught:
        provider._generate_image_sync("make a thumbnail", "gpt-image-2")

    assert caught.value.status_code == 400
    assert caught.value.code == "invalid_size"
    assert caught.value.request_id == "req_thumbnail_123"
    assert "The requested image size is invalid." in str(caught.value)
    assert _is_retryable_openai_image_error(caught.value) is False


@pytest.mark.parametrize("status_code", [408, 409, 429, 500, 503])
def test_transient_openai_image_errors_are_retryable(status_code: int) -> None:
    error = OpenAIImageGenerationError("temporary failure", status_code=status_code)

    assert _is_retryable_openai_image_error(error) is True


@pytest.mark.asyncio
async def test_generate_image_does_not_retry_permanent_openai_error(monkeypatch) -> None:
    provider = OpenAIImageProvider.__new__(OpenAIImageProvider)
    provider.settings = type("Settings", (), {"openai_image_output_format": "png"})()
    calls = 0

    def fail_permanently(_prompt: str, _model: str) -> dict:
        nonlocal calls
        calls += 1
        raise OpenAIImageGenerationError(
            "blocked by moderation",
            status_code=400,
            code="moderation_blocked",
        )

    monkeypatch.setattr(provider, "_generate_image_sync", fail_permanently)

    with pytest.raises(OpenAIImageGenerationError, match="moderation_blocked"):
        await provider.generate_image("make a thumbnail", "gpt-image-2")

    assert calls == 1


def test_generate_tts_sync_posts_directed_openai_speech_options(monkeypatch) -> None:
    provider = OpenAIAudioProvider.__new__(OpenAIAudioProvider)
    provider.settings = type(
        "Settings",
        (),
        {
            "openai_api_key": "openai-key",
            "openai_tts_instructions": "Measured documentary delivery.",
            "openai_tts_speed": 0.95,
        },
    )()
    captured: dict[str, object] = {}

    class _Response:
        content = b"wav"

        def raise_for_status(self) -> None:
            pass

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.providers.openai.httpx.post", fake_post)

    assert provider._generate_tts_sync("Narration text.", "gpt-4o-mini-tts", "onyx") == b"wav"
    assert captured["url"] == "https://api.openai.com/v1/audio/speech"
    assert captured["json"] == {
        "model": "gpt-4o-mini-tts",
        "input": "Narration text.",
        "voice": "onyx",
        "instructions": "Measured documentary delivery.",
        "response_format": "wav",
        "speed": 0.95,
    }


@pytest.mark.asyncio
async def test_generate_tts_decodes_wav_response(monkeypatch) -> None:
    provider = OpenAIAudioProvider.__new__(OpenAIAudioProvider)
    provider.settings = object()
    wav_data = wav_bytes(AudioGeneration(pcm_data=b"\0" * 4800))
    monkeypatch.setattr(provider, "_generate_tts_sync", lambda *_args: wav_data)

    audio = await provider.generate_tts(
        "Narration text.",
        "gpt-4o-mini-tts",
        [SpeakerVoice("Arman", "onyx")],
    )

    assert audio.pcm_data == b"\0" * 4800
    assert audio.sample_rate == 24000


@pytest.mark.asyncio
async def test_align_words_normalizes_openai_timestamps(monkeypatch) -> None:
    provider = OpenAIAudioProvider.__new__(OpenAIAudioProvider)
    provider.settings = object()
    monkeypatch.setattr(
        provider,
        "_align_words_sync",
        lambda *_args: {
            "text": "Hello world.",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.25},
                {"word": "world", "start": 0.26, "end": 0.6},
            ],
        },
    )

    alignment = await provider.align_words(
        b"audio",
        mime_type="audio/wav",
        model="whisper-1",
        language="en",
    )

    assert alignment.text == "Hello world."
    assert [(word.word, word.start_seconds, word.end_seconds) for word in alignment.words] == [
        ("Hello", 0.0, 0.25),
        ("world", 0.26, 0.6),
    ]
