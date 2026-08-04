from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.providers.ai import (
    AIProvider,
    AudioGeneration,
    ImageGeneration,
    SpeakerVoice,
    TextGeneration,
    WordAlignment,
    WordAlignmentProvider,
    WordTiming,
)
from app.services.audio import audio_from_wav_bytes

_MIME_BY_FORMAT = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


class OpenAIImageGenerationError(RuntimeError):
    """A safe, actionable error returned by the OpenAI Images API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        details = f"status={status_code}"
        if code:
            details += f" code={code}"
        if request_id:
            details += f" request_id={request_id}"
        super().__init__(f"OpenAI image generation failed ({details}): {message}")
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


def _is_retryable_openai_image_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if not isinstance(exc, OpenAIImageGenerationError):
        return False
    return exc.status_code in {408, 409, 429} or exc.status_code >= 500


def _openai_image_generation_error(response: httpx.Response) -> OpenAIImageGenerationError:
    request_id = response.headers.get("x-request-id")
    try:
        payload = response.json()
    except ValueError:
        payload = None

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or "The Images API rejected the request")
        raw_code = error.get("code") or error.get("type")
        code = str(raw_code) if raw_code else None
    else:
        message = response.text.strip()[:500] or "The Images API rejected the request"
        code = None

    return OpenAIImageGenerationError(
        message,
        status_code=response.status_code,
        code=code,
        request_id=request_id,
    )


class OpenAIImageProvider(AIProvider):
    def __init__(self, settings: Settings):
        settings.validate_thumbnail_image()

        self.settings = settings

    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: Any | None = None,
    ) -> TextGeneration:
        raise NotImplementedError("OpenAIImageProvider only supports image generation")

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_exception(_is_retryable_openai_image_error),
        reraise=True,
    )
    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        response = await asyncio.to_thread(self._generate_image_sync, prompt, model)

        data = response.get("data") or []
        if not data:
            raise RuntimeError("OpenAI image generation returned no image data")

        image_base64 = data[0].get("b64_json")
        if not image_base64:
            raise RuntimeError("OpenAI image generation returned no base64 image")

        try:
            image_data = base64.b64decode(image_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError(
                "OpenAI image generation returned invalid base64 image data"
            ) from exc

        return ImageGeneration(
            data=image_data,
            mime_type=_MIME_BY_FORMAT[self.settings.openai_image_output_format],
            prompt=prompt,
        )

    def _generate_image_sync(self, prompt: str, model: str) -> dict[str, Any]:
        response = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": self.settings.openai_image_size,
                "quality": self.settings.openai_image_quality,
                "output_format": self.settings.openai_image_output_format,
            },
            timeout=httpx.Timeout(
                self.settings.openai_image_timeout_seconds,
                connect=10.0,
            ),
        )
        if response.is_error:
            raise _openai_image_generation_error(response)

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("OpenAI image generation returned an invalid JSON response")
        return payload

    async def generate_tts(
        self,
        prompt: str,
        model: str,
        speakers: list[SpeakerVoice],
    ) -> AudioGeneration:
        raise NotImplementedError("OpenAIImageProvider only supports image generation")


class OpenAIAudioProvider(AIProvider, WordAlignmentProvider):
    """Directed OpenAI narration plus measured word-level timestamps."""

    def __init__(self, settings: Settings):
        settings.validate_voice()
        self.settings = settings

    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: Any | None = None,
    ) -> TextGeneration:
        raise NotImplementedError("OpenAIAudioProvider only supports audio")

    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        raise NotImplementedError("OpenAIAudioProvider only supports audio")

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(3))
    async def generate_tts(
        self,
        prompt: str,
        model: str,
        speakers: list[SpeakerVoice],
    ) -> AudioGeneration:
        if len(speakers) != 1:
            raise ValueError("OpenAI narration requires exactly one speaker")
        text = prompt.strip()
        if not text:
            raise ValueError("OpenAI narration input cannot be empty")
        if len(text) > 4096:
            raise ValueError("OpenAI narration input exceeds the 4096-character API limit")

        wav_data = await asyncio.to_thread(
            self._generate_tts_sync,
            text,
            model,
            speakers[0].voice_name,
        )
        return audio_from_wav_bytes(wav_data)

    def _generate_tts_sync(self, text: str, model: str, voice: str) -> bytes:
        response = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": text,
                "voice": voice,
                "instructions": self.settings.openai_tts_instructions,
                "response_format": "wav",
                "speed": self.settings.openai_tts_speed,
            },
            timeout=180,
        )
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("OpenAI speech generation returned empty audio")
        return response.content

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(3))
    async def align_words(
        self,
        audio_data: bytes,
        *,
        mime_type: str,
        model: str,
        language: str | None = None,
    ) -> WordAlignment:
        response = await asyncio.to_thread(
            self._align_words_sync,
            audio_data,
            mime_type,
            model,
            language,
        )
        words: list[WordTiming] = []
        for item in response.get("words") or []:
            if not isinstance(item, dict):
                continue
            word = str(item.get("word") or "").strip()
            try:
                start = float(item["start"])
                end = float(item["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not word or start < 0 or end <= start:
                continue
            words.append(
                WordTiming(
                    word=word,
                    start_seconds=round(start, 3),
                    end_seconds=round(end, 3),
                )
            )
        if not words:
            raise RuntimeError("OpenAI transcription returned no word timestamps")
        return WordAlignment(
            text=str(response.get("text") or "").strip(),
            words=words,
            raw=response,
        )

    def _align_words_sync(
        self,
        audio_data: bytes,
        mime_type: str,
        model: str,
        language: str | None,
    ) -> dict[str, Any]:
        extension = "mp3" if mime_type in {"audio/mpeg", "audio/mp3"} else "wav"
        form_data = {
            "model": model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        if language:
            form_data["language"] = language
        response = httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            data=form_data,
            files={"file": (f"narration.{extension}", audio_data, mime_type)},
            timeout=300,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("OpenAI transcription returned an invalid response")
        return payload
