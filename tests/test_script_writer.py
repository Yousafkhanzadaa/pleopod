import json
from types import SimpleNamespace

import pytest

from app.agents.script_writer import ScriptWriterAgent, canonical_dialogue_turns
from app.models.enums import ArtifactType


def _speakers() -> list[dict]:
    return [
        {"name": "Arman", "role": "Presenter", "voice_name": "Algenib"},
    ]


def _complete_transcript() -> str:
    return (
        "TTS the following talk by Arman:\n\n"
        "Arman: Welcome back. The first point is grounded in the research.\n"
        "Arman: The second point adds practical context without turning this into a long show.\n"
        "Arman: That gives viewers a clear path through the topic and keeps the facts moving.\n"
        "Arman: That is the key lesson for this episode, and it is where we will leave it."
    )


def test_normalize_script_rewrites_common_speaker_label_variants() -> None:
    agent = ScriptWriterAgent()
    script = {
        "title": "Test Episode",
        "slug": "test-episode",
        "summary": "Summary",
        "description": "Description",
        "speakers": _speakers(),
        "transcript": (
            "TTS the following talk by Arman:\n\n"
            "**Presenter:** Welcome back.\n"
            "Arman: Let's unpack the story."
        ),
        "used_claims": [],
    }

    normalized = agent._normalize_script(script)

    assert normalized["transcript"].startswith(
        "TTS the following talk by Arman:"
    )
    assert "Arman: Welcome back." in normalized["transcript"]
    assert "Arman: Let's unpack the story." in normalized["transcript"]
    agent._validate_script(normalized)


def test_validate_script_allows_transcript_over_word_budget() -> None:
    agent = ScriptWriterAgent()
    script = {
        "title": "Test Episode",
        "slug": "test-episode",
        "summary": "Summary",
        "description": "Description",
        "speakers": _speakers(),
        "transcript": (
            "TTS the following talk by Arman:\n\n"
            f"Arman: {' '.join(['alpha'] * 80)}.\n"
            f"Arman: {' '.join(['bravo'] * 80)}.\n"
            f"Arman: {' '.join(['charlie'] * 80)}."
        ),
        "used_claims": [],
    }

    agent._validate_script(
        script,
        {
            "target_duration_seconds": 90,
        },
    )


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
        self.settings = SimpleNamespace(gemini_script_model="gemini-2.5-flash-lite")
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
                    "TTS the following talk by Arman:\n\n"
                    "Arman: Let me walk through the whole thing myself."
                ),
                "used_claims": [],
            },
            {
                "title": "Test Episode",
                "slug": "test-episode",
                "summary": "Summary",
                "description": "Description",
                "speakers": _speakers(),
                "transcript": _complete_transcript(),
                "used_claims": [],
            },
        ]
    )

    result = await agent.run(
        {
            "id": "job-1",
            "topic": "AI Agents",
            "audience": "Developers",
            "target_duration_seconds": 90,
            "language": "en",
            "tone": "clear, smart, conversational",
        },
        context,
        {},
    )

    assert result.output_artifact_id == "json-artifact-id"
    assert len(context.ai.calls) == 2
    assert "failed backend validation" in context.ai.calls[1]


@pytest.mark.asyncio
async def test_script_writer_repairs_truncated_final_line() -> None:
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
                    "TTS the following talk by Arman:\n\n"
                    "Arman: Welcome back.\n"
                    "Arman: The research gives us a useful baseline.\n"
                    "Arman: That’s where its"
                ),
                "used_claims": [],
            },
            {
                "title": "Test Episode",
                "slug": "test-episode",
                "summary": "Summary",
                "description": "Description",
                "speakers": _speakers(),
                "transcript": _complete_transcript(),
                "used_claims": [],
            },
        ]
    )

    result = await agent.run(
        {
            "id": "job-1",
            "topic": "AI Agents",
            "audience": "Developers",
            "target_duration_seconds": 90,
            "language": "en",
            "tone": "clear, smart, conversational",
        },
        context,
        {},
    )

    assert result.output_artifact_id == "json-artifact-id"
    assert len(context.ai.calls) == 2
    assert "final spoken line is not a complete sentence" in context.ai.calls[1]


def test_enforce_min_turns_resplits_single_line() -> None:
    agent = ScriptWriterAgent()
    script = {
        "speakers": [{"name": "Arman"}],
        "transcript": (
            "TTS the following talk by Arman:\n\n"
            "Arman: First point here. Second point follows. Third wraps it up."
        ),
    }

    out = agent._enforce_min_turns(script, {"target_duration_seconds": 60})

    turns = canonical_dialogue_turns(out["transcript"])
    assert len(turns) >= 2
    assert all(turn["speaker"] == "Arman" for turn in turns)
    assert out["metadata"]["transcript_resplit_for_turns"] is True
