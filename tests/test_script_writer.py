import json
from types import SimpleNamespace

import pytest

from app.agents.script_writer import ScriptWriterAgent
from app.models.enums import ArtifactType, PipelineStep


def _speakers() -> list[dict]:
    return [
        {"name": "Arman", "role": "Host", "voice_name": "Charon"},
        {"name": "Maya", "role": "Analyst", "voice_name": "Puck"},
    ]


def test_normalize_script_rewrites_common_speaker_label_variants() -> None:
    agent = ScriptWriterAgent()
    script = {
        "title": "Test Episode",
        "slug": "test-episode",
        "summary": "Summary",
        "description": "Description",
        "speakers": _speakers(),
        "transcript": (
            "TTS the following conversation between Arman and Maya:\n\n"
            "**Host:** Welcome back.\n"
            "Maya (Analyst): Let's unpack the story."
        ),
        "used_claims": [],
    }

    normalized = agent._normalize_script(script)

    assert normalized["transcript"].startswith(
        "TTS the following conversation between Arman and Maya:"
    )
    assert "Arman: Welcome back." in normalized["transcript"]
    assert "Maya: Let's unpack the story." in normalized["transcript"]
    agent._validate_script(normalized)


class _ArtifactService:
    async def put_text(
        self,
        key: str,
        text: str,
        artifact_type: ArtifactType | str,
        mime_type: str = "text/plain; charset=utf-8",
        job_id: str | None = None,
        episode_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        return {"id": "text-artifact-id"}

    async def put_json(
        self,
        key: str,
        data: dict | list,
        artifact_type: ArtifactType | str,
        job_id: str | None = None,
        episode_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        return {"id": "json-artifact-id"}


class _Context:
    def __init__(self, responses: list[dict]) -> None:
        self.settings = SimpleNamespace(gemini_script_model="gemini-2.5-flash")
        self.artifact_service = _ArtifactService()
        self._responses = list(responses)

        class _AI:
            def __init__(self, outer: "_Context") -> None:
                self.outer = outer
                self.calls: list[str] = []

            async def generate_text(
                self,
                prompt: str,
                model: str,
                response_schema: object | None = None,
            ) -> SimpleNamespace:
                self.calls.append(prompt)
                payload = self.outer._responses.pop(0)
                return SimpleNamespace(text=json.dumps(payload))

        self.ai = _AI(self)

    async def latest_text(self, job_id: str, artifact_type: ArtifactType) -> str:
        assert artifact_type == ArtifactType.MEMORY_MD
        return "# Memory"

    async def latest_json(self, job_id: str, artifact_type: ArtifactType) -> list[dict]:
        assert artifact_type == ArtifactType.CLAIM_BANK_JSON
        return [{"claim_text": "Claim"}]


@pytest.mark.asyncio
async def test_script_writer_repairs_invalid_script_before_failing_worker_retries() -> None:
    agent = ScriptWriterAgent()
    context = _Context(
        [
            {
                "title": "Test Episode",
                "slug": "test-episode",
                "summary": "Summary",
                "description": "Description",
                "speakers": _speakers(),
                "transcript": (
                    "TTS the following conversation between Arman and Maya:\n\n"
                    "Maya: Let me walk through the whole thing myself."
                ),
                "used_claims": [],
            },
            {
                "title": "Test Episode",
                "slug": "test-episode",
                "summary": "Summary",
                "description": "Description",
                "speakers": _speakers(),
                "transcript": (
                    "TTS the following conversation between Arman and Maya:\n\n"
                    "Arman: Welcome back.\n"
                    "Maya: Let me walk through the whole thing myself."
                ),
                "used_claims": [],
            },
        ]
    )

    result = await agent.run(
        {
            "id": "job-1",
            "topic": "AI Agents",
            "audience": "Developers",
            "target_duration_seconds": 600,
            "language": "en",
            "tone": "clear, smart, conversational",
        },
        context,
        {},
    )

    assert result.next_step == PipelineStep.FACT_CHECK
    assert len(context.ai.calls) == 2
    assert "failed backend validation" in context.ai.calls[1]
