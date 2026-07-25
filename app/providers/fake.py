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
                "target_duration_seconds": 90,
                "language": "en",
                "tone": "clear, smart, conversational",
                "source_urls": [],
            }
            return TextGeneration(text=json.dumps(orchestration_data))
        if schema_name == "TopicScoutDecision" or "topic scout agent" in lower:
            topic_data: dict[str, Any] = {
                "topic": "OpenAI launches new Codex team controls",
                "title": "OpenAI Launches New Codex Team Controls",
                "rationale": "Fake local current-event topic for scheduled publishing tests.",
                "source_urls": [
                    "https://openai.com/blog/example-codex-team-controls",
                    "https://github.blog/example-codex-team-controls",
                    "https://arstechnica.com/example-codex-team-controls",
                ],
                "candidates": [
                    {
                        "topic": "OpenAI launches new Codex team controls",
                        "title": "OpenAI Launches New Codex Team Controls",
                        "rationale": (
                            "Fake local current-event topic for scheduled publishing tests."
                        ),
                        "source_urls": [
                            "https://openai.com/blog/example-codex-team-controls",
                            "https://github.blog/example-codex-team-controls",
                            "https://arstechnica.com/example-codex-team-controls",
                        ],
                        "score": 0.9,
                    },
                    {
                        "topic": "New AI Developer Tools Launch",
                        "title": "A New Wave of AI Developer Tools",
                        "rationale": "Alternative fake local topic.",
                        "source_urls": [
                            "https://blog.google/example-ai-developer-tools",
                            "https://theverge.com/example-ai-developer-tools",
                            "https://techcrunch.com/example-ai-developer-tools",
                        ],
                        "score": 0.7,
                    },
                ],
                "rejected_topics": [],
            }
            return TextGeneration(text=json.dumps(topic_data))
        if (
            schema_name == "PodcastScript"
            or "podcast script agent" in lower
            or "short video script agent" in lower
        ):
            script_data: dict[str, Any] = {
                "title": "The AI Media Pipeline",
                "slug": "the-ai-media-pipeline",
                "summary": "A short talk about building trustworthy AI-generated media.",
                "description": "A practical look at research, verification, and audio generation.",
                "speakers": [
                    {
                        "name": "Arman",
                        "role": "Presenter",
                        "voice_name": "Algenib",
                        "style": "low-pitched, grounded, authoritative, attention-grabbing",
                    },
                ],
                "transcript": (
                    "TTS the following talk by Arman:\n\n"
                    "Arman: Welcome back. Today we are looking at how an AI media pipeline "
                    "should work without turning into a long show.\n"
                    "Arman: The key is simple: research first, verify every important claim, "
                    "then generate audio and video only after the facts are stable.\n"
                    "Arman: That gives the workflow a real spine instead of a pile of prompts. "
                    "Each stage leaves an artifact, so builders can inspect what happened.\n"
                    "Arman: Once the pieces are solid, the worker connects them into a short, "
                    "dependable publishing flow. That is the whole point: tighter output, "
                    "better control, and no wasted runtime."
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
                "summary": "This is a local fake research dossier for a technology video.",
                "key_points": [
                    "AI agents can automate research workflows.",
                    "Verification is required before publishing.",
                ],
                "sources": [
                    {
                        "url": f"https://example.com/source-{index}",
                        "title": f"Example Source {index}",
                        "publisher": "Example",
                        "author": None,
                        "published_at": None,
                        "source_tier": "B",
                        "credibility_score": 0.65,
                        "notes": "Fake local source.",
                    }
                    for index in range(1, 6)
                ],
                "claims": [
                    {
                        "claim_text": f"Fake supported research claim {index}.",
                        "source_urls": [f"https://example.com/source-{((index - 1) % 5) + 1}"],
                        "verification_status": "supported",
                        "confidence": 0.8,
                        "notes": "Fake claim for local development.",
                    }
                    for index in range(1, 9)
                ],
            }
            return TextGeneration(text=json.dumps(research_data))
        if schema_name == "ScenePlan" or "scene director agent" in lower:
            scene_plan_data: dict[str, Any] = {
                "version": 1,
                "director_model": "fake",
                "duration_seconds": 90,
                "line_timings": [],
                "scenes": [
                    {
                        "id": "scene_title",
                        "start_seconds": 0,
                        "end_seconds": 6,
                        "layout": "title",
                        "headline": "The AI Media Pipeline",
                        "subheadline": "Research, verify, then generate",
                        "emphasis": "curious",
                    },
                    {
                        "id": "scene_statement",
                        "start_seconds": 6,
                        "end_seconds": 34,
                        "layout": "statement",
                        "headline": "Research first, verify every claim",
                        "emphasis": "technical",
                    },
                    {
                        "id": "scene_bullets",
                        "start_seconds": 34,
                        "end_seconds": 64,
                        "layout": "bullets",
                        "headline": "How the spine works",
                        "bullets": [
                            "Each stage leaves an artifact",
                            "Facts stabilize before audio",
                            "The worker connects the pieces",
                        ],
                    },
                    {
                        "id": "scene_source",
                        "start_seconds": 64,
                        "end_seconds": 84,
                        "layout": "source",
                        "headline": "Sources",
                        "source_urls": [
                            "https://example.com/source-1",
                            "https://example.com/source-2",
                        ],
                        "emphasis": "reflective",
                    },
                    {
                        "id": "scene_outro",
                        "start_seconds": 84,
                        "end_seconds": 90,
                        "layout": "outro",
                        "headline": "Tighter output, better control",
                        "emphasis": "reflective",
                    },
                ],
                "production_notes": ["Fake local scene plan."],
            }
            return TextGeneration(text=json.dumps(scene_plan_data))
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
