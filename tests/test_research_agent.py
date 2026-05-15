import json
from types import SimpleNamespace

import pytest

from app.agents.research import ResearchAgent, research_quality_issues
from app.models.enums import ArtifactType


def _job() -> dict:
    return {
        "id": "job-1",
        "topic": "AI governance",
        "category": "Tech",
        "audience": "Builders",
        "language": "en",
        "source_urls": [],
    }


def _weak_research() -> dict:
    return {
        "summary": "This research aims to investigate AI governance.",
        "key_points": ["Investigate the current state of AI governance."],
        "open_questions": ["What should be researched?"],
        "sources": [],
        "claims": [],
    }


def _strong_research() -> dict:
    sources = [
        {
            "url": f"https://example.com/source-{index}",
            "title": f"Source {index}",
            "publisher": "Example",
            "author": None,
            "published_at": None,
            "source_tier": "B",
            "credibility_score": 0.8,
            "notes": "Test source.",
        }
        for index in range(1, 6)
    ]
    claims = [
        {
            "claim_text": f"Supported claim {index}.",
            "source_urls": [sources[(index - 1) % len(sources)]["url"]],
            "verification_status": "supported",
            "confidence": 0.8,
            "notes": "Test claim.",
        }
        for index in range(1, 9)
    ]
    return {
        "summary": "AI governance has active public guidance and implementation details.",
        "key_points": ["Public guidance defines concrete AI governance practices."],
        "open_questions": [],
        "sources": sources,
        "claims": claims,
    }


class _ArtifactService:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, object]] = []

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
        self.records.append((str(artifact_type), key, text))
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
        self.records.append((str(artifact_type), key, data))
        return {"id": f"{artifact_type}-id"}


class _KnowledgeRepo:
    def __init__(self) -> None:
        self.sources: list[dict] = []
        self.claims: list[dict] = []

    async def replace_sources(self, job_id: str, sources: list[dict]) -> None:
        self.sources = sources

    async def replace_claims(self, job_id: str, claims: list[dict]) -> None:
        self.claims = claims


class _Context:
    def __init__(self, responses: list[dict]) -> None:
        self.settings = SimpleNamespace(gemini_research_model="gemini-2.5-flash-lite")
        self.artifact_service = _ArtifactService()
        self.knowledge_repo = _KnowledgeRepo()
        self._responses = list(responses)

        class _AI:
            def __init__(self, outer: "_Context") -> None:
                self.outer = outer
                self.calls: list[str] = []

            async def generate_text(
                self,
                prompt: str,
                model: str,
                use_google_search: bool = False,
                urls: list[str] | None = None,
                response_schema: object | None = None,
            ) -> SimpleNamespace:
                self.calls.append(prompt)
                payload = self.outer._responses.pop(0)
                return SimpleNamespace(text=json.dumps(payload), citations=[])

        self.ai = _AI(self)


def test_research_quality_issues_detects_empty_plan() -> None:
    issues = research_quality_issues(_weak_research())

    assert "expected at least 5 sources, got 0" in issues
    assert "expected at least 8 claims, got 0" in issues
    assert "key_points look like research tasks instead of factual findings" in issues


@pytest.mark.asyncio
async def test_research_agent_repairs_low_quality_research() -> None:
    context = _Context([_weak_research(), _strong_research()])
    agent = ResearchAgent()

    result = await agent.run(_job(), context, {})  # type: ignore[arg-type]

    assert result.output_artifact_id == "claim_bank_json-id"
    assert len(context.ai.calls) == 2
    assert "failed quality checks" in context.ai.calls[1]
    assert len(context.knowledge_repo.sources) == 5
    assert len(context.knowledge_repo.claims) == 8


@pytest.mark.asyncio
async def test_research_agent_fails_after_low_quality_repair() -> None:
    context = _Context([_weak_research(), _weak_research()])
    agent = ResearchAgent()

    with pytest.raises(ValueError, match="Research quality gate failed"):
        await agent.run(_job(), context, {})  # type: ignore[arg-type]
