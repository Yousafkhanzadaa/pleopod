from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.providers.ai import (
    AIProvider,
    AudioGeneration,
    ImageGeneration,
    SpeakerVoice,
    TextGeneration,
)

_MIME_BY_FORMAT = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


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

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(3))
    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        response = await asyncio.to_thread(self._generate_image_sync, prompt, model)

        data = response.get("data") or []
        if not data:
            raise RuntimeError("OpenAI image generation returned no image data")

        image_base64 = data[0].get("b64_json")
        if not image_base64:
            raise RuntimeError("OpenAI image generation returned no base64 image")

        return ImageGeneration(
            data=base64.b64decode(image_base64),
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
            timeout=120,
        )
        response.raise_for_status()
        return response.json()

    async def generate_tts(
        self,
        prompt: str,
        model: str,
        speakers: list[SpeakerVoice],
    ) -> AudioGeneration:
        raise NotImplementedError("OpenAIImageProvider only supports image generation")
