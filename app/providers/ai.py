from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Citation:
    title: str | None = None
    url: str | None = None
    start_index: int | None = None
    end_index: int | None = None


@dataclass
class TextGeneration:
    text: str
    citations: list[Citation] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageGeneration:
    data: bytes
    mime_type: str
    prompt: str


@dataclass
class AudioGeneration:
    pcm_data: bytes
    sample_rate: int = 24000
    channels: int = 1
    sample_width: int = 2


@dataclass(frozen=True)
class SpeakerVoice:
    speaker: str
    voice_name: str
    style: str | None = None


class AIProvider(ABC):
    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: Any | None = None,
    ) -> TextGeneration:
        raise NotImplementedError

    @abstractmethod
    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        raise NotImplementedError

    @abstractmethod
    async def generate_tts(
        self,
        prompt: str,
        model: str,
        speakers: list[SpeakerVoice],
    ) -> AudioGeneration:
        raise NotImplementedError
