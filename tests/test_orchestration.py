import json
from types import SimpleNamespace

import pytest

from app.agents.orchestration import orchestrate_generation_job
from app.schemas.jobs import GenerationJobRequest


class _AI:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: object | None = None,
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "response_schema": response_schema,
            }
        )
        return SimpleNamespace(
            text=json.dumps(
                {
                    "topic": "AI Coding Agents in 2026",
                    "category": "Tech",
                    "audience": "software engineers and founders",
                    "target_duration_seconds": 600,
                    "language": "en",
                    "tone": "clear, smart, conversational",
                    "source_urls": ["https://example.com/guide"],
                }
            )
        )


@pytest.mark.asyncio
async def test_orchestrate_generation_job_uses_flash_lite_and_respects_overrides() -> None:
    ai = _AI()
    settings = SimpleNamespace(gemini_orchestration_model="gemini-2.5-flash-lite")
    request = GenerationJobRequest(
        title="AI Coding Agents in 2026",
        audience="backend engineers",
        auto_publish=True,
    )

    payload = await orchestrate_generation_job(request, ai, settings)

    assert ai.calls[0]["model"] == "gemini-2.5-flash-lite"
    assert payload.topic == "AI Coding Agents in 2026"
    assert payload.audience == "backend engineers"
    assert payload.auto_publish is True
    assert [str(url) for url in payload.source_urls] == ["https://example.com/guide"]
