from __future__ import annotations

import json
import math
import struct
from typing import Any

from app.providers.ai import (
    AIProvider,
    AudioGeneration,
    ImageGeneration,
    SpeakerVoice,
    TextGeneration,
)


class FakeAIProvider(AIProvider):
    """Deterministic local provider for tests and offline development."""

    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: object | None = None,
    ) -> TextGeneration:
        lower = prompt.lower()
        schema_name = getattr(response_schema, "__name__", "")
        if schema_name == "OrchestratedJobPayload" or "orchestration agent" in lower:
            orchestration_data: dict[str, Any] = {
                "topic": "AI Coding Agents in 2026",
                "category": "Tech",
                "audience": "curious tech listeners and software builders",
                "target_duration_seconds": 600,
                "language": "en",
                "tone": "clear, smart, conversational",
                "source_urls": [],
            }
            return TextGeneration(text=json.dumps(orchestration_data))
        if schema_name == "PodcastScript" or "podcast script agent" in lower:
            script_data: dict[str, Any] = {
                "title": "The AI Podcast Pipeline",
                "slug": "the-ai-podcast-pipeline",
                "summary": "A short conversation about building trustworthy AI-generated podcasts.",
                "description": "A practical look at research, verification, and audio generation.",
                "speakers": [
                    {"name": "Arman", "role": "Host", "voice_name": "Charon"},
                    {"name": "Maya", "role": "Analyst", "voice_name": "Puck"},
                ],
                "transcript": (
                    "TTS the following conversation between Arman and Maya:\n\n"
                    "Arman: Welcome back. Today we are looking at how an AI "
                    "podcast pipeline should work.\n"
                    "Maya: The key is simple: research first, verify every "
                    "important claim, then generate audio."
                ),
            }
            return TextGeneration(text=json.dumps(script_data))
        if schema_name == "VerificationReport" or "fact verification agent" in lower:
            verification_data: dict[str, Any] = {
                "verdict": "approved",
                "score": 0.92,
                "issues": [],
                "fixed_transcript": None,
                "line_checks": [],
            }
            return TextGeneration(text=json.dumps(verification_data))
        if schema_name == "ResearchDossier" or "research dossier" in lower:
            research_data: dict[str, Any] = {
                "summary": "This is a local fake research dossier for a technology podcast.",
                "key_points": [
                    "AI agents can automate research workflows.",
                    "Verification is required before publishing.",
                ],
                "sources": [
                    {
                        "url": "https://example.com/source",
                        "title": "Example Source",
                        "publisher": "Example",
                        "author": None,
                        "published_at": None,
                        "source_tier": "B",
                        "credibility_score": 0.65,
                        "notes": "Fake local source.",
                    }
                ],
                "claims": [
                    {
                        "claim_text": (
                            "AI podcast pipelines should verify factual claims "
                            "before audio generation."
                        ),
                        "source_urls": ["https://example.com/source"],
                        "verification_status": "supported",
                        "confidence": 0.8,
                        "notes": "Fake claim for local development.",
                    }
                ],
            }
            return TextGeneration(text=json.dumps(research_data))
        return TextGeneration(text=json.dumps({"result": "ok"}))

    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        # 1x1 transparent PNG.
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc``\x00"
            b"\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return ImageGeneration(data=png, mime_type="image/png", prompt=prompt)

    async def generate_tts(
        self,
        prompt: str,
        model: str,
        speakers: list[SpeakerVoice],
    ) -> AudioGeneration:
        sample_rate = 24000
        seconds = 1
        frames = []
        for n in range(sample_rate * seconds):
            value = int(16000 * math.sin(2 * math.pi * 440 * (n / sample_rate)))
            frames.append(struct.pack("<h", value))
        return AudioGeneration(pcm_data=b"".join(frames), sample_rate=sample_rate)
