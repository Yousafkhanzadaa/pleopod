from __future__ import annotations

import base64
import logging
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.providers.ai import (
    AIProvider,
    AudioGeneration,
    Citation,
    ImageGeneration,
    SpeakerVoice,
    TextGeneration,
)

logger = logging.getLogger(__name__)


class GeminiAIProvider(AIProvider):
    def __init__(self, settings: Settings):
        settings.validate_ai()
        from google import genai

        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(3))
    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: Any | None = None,
    ) -> TextGeneration:
        from google.genai import types

        tools: list[Any] = []
        if urls:
            tools.append(types.Tool(url_context=types.UrlContext()))
        if use_google_search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))

        contents = prompt
        if urls:
            contents = f"{prompt}\n\nSpecific URLs to inspect:\n" + "\n".join(urls[:20])

        config_kwargs: dict[str, Any] = {}
        if tools:
            config_kwargs["tools"] = tools
        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_schema

        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        citations = self._extract_citations(response)
        return TextGeneration(text=response.text or "", citations=citations, raw={})

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(3))
    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        from google.genai import types

        response = self.client.models.generate_content(
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        parts = list(getattr(response, "parts", None) or [])
        if not parts:
            for candidate in response.candidates or []:
                parts.extend(getattr(candidate.content, "parts", None) or [])

        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data is not None and inline_data.data is not None:
                data = inline_data.data
                if isinstance(data, str):
                    data = base64.b64decode(data)
                if not isinstance(data, bytes):
                    continue
                return ImageGeneration(
                    data=data,
                    mime_type=getattr(inline_data, "mime_type", None) or "image/png",
                    prompt=prompt,
                )

            as_image = getattr(part, "as_image", None)
            if callable(as_image):
                image = as_image()
                if image is None:
                    continue
                import io

                buf = io.BytesIO()
                image.save(buf, format="PNG")
                return ImageGeneration(data=buf.getvalue(), mime_type="image/png", prompt=prompt)

        text = (getattr(response, "text", None) or "").strip()
        if text:
            raise RuntimeError(
                f"Gemini image generation returned text instead of image: {text[:300]}"
            )
        raise RuntimeError("Gemini image generation returned no image data")

    @retry(
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def generate_tts(
        self,
        prompt: str,
        model: str,
        speakers: list[SpeakerVoice],
    ) -> AudioGeneration:
        from google.genai import types

        if len(speakers) > 2:
            raise ValueError("Gemini multi-speaker TTS currently supports up to 2 speakers")
        if not prompt.strip():
            raise ValueError("Gemini TTS prompt cannot be empty")

        speaker_voice_configs = [
            types.SpeakerVoiceConfig(
                speaker=speaker.speaker,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=speaker.voice_name)
                ),
            )
            for speaker in speakers
        ]

        logger.info(
            "Generating Gemini TTS model=%s prompt_chars=%s speakers=%s",
            model,
            len(prompt),
            ",".join(speaker.speaker for speaker in speakers),
        )
        response = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                        speaker_voice_configs=speaker_voice_configs
                    )
                ),
            ),
        )
        candidates = response.candidates or []
        if not candidates:
            raise RuntimeError("Gemini TTS returned no candidates")
        parts = getattr(candidates[0].content, "parts", None) or []
        if not parts:
            raise RuntimeError("Gemini TTS returned no audio parts")
        inline_data = getattr(parts[0], "inline_data", None)
        if inline_data is None or inline_data.data is None:
            raise RuntimeError("Gemini TTS returned no inline audio data")

        data = inline_data.data
        if isinstance(data, str):
            data = base64.b64decode(data)
        if not isinstance(data, bytes):
            raise RuntimeError("Gemini TTS returned audio data in an unsupported format")
        return AudioGeneration(pcm_data=data, sample_rate=24000)

    def _extract_citations(self, response: Any) -> list[Citation]:
        try:
            metadata = response.candidates[0].grounding_metadata
            chunks = getattr(metadata, "grounding_chunks", []) or []
            supports = getattr(metadata, "grounding_supports", []) or []
        except Exception:
            return []

        citations: list[Citation] = []
        for support in supports:
            indices = getattr(support, "grounding_chunk_indices", []) or []
            segment = getattr(support, "segment", None)
            for index in indices:
                if index >= len(chunks):
                    continue
                web = getattr(chunks[index], "web", None)
                citations.append(
                    Citation(
                        title=getattr(web, "title", None),
                        url=getattr(web, "uri", None),
                        start_index=getattr(segment, "start_index", None),
                        end_index=getattr(segment, "end_index", None),
                    )
                )
        return citations
