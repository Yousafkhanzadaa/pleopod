from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.agents.prompts import research_prompt, research_repair_prompt
from app.core.json_utils import parse_model_json, to_pretty_json
from app.db.repositories import KnowledgeRepository
from app.models.enums import ArtifactType, PipelineStep
from app.schemas.agent_outputs import ResearchDossier
from pydantic import ValidationError

logger = logging.getLogger(__name__)


def build_research_memory_markdown(
    job: dict[str, Any],
    research: dict[str, Any],
) -> str:
    now = datetime.now(UTC).isoformat()
    lines = [
        f"# Research Memory: {job['topic']}",
        "",
        f"- Category: {job['category']}",
        f"- Audience: {job['audience']}",
        f"- Generated at: {now}",
        "",
        "## Summary",
        research.get("summary", ""),
        "",
        "## Key Points",
    ]
    lines.extend(f"- {point}" for point in research.get("key_points", []))
    lines.extend(["", "## Claims"])
    for claim in research.get("claims", []):
        lines.append(
            f"- {claim.get('claim_text')} Sources: {', '.join(claim.get('source_urls', []))}"
        )
    lines.extend(["", "## Sources", "```json", to_pretty_json(research.get("sources", [])), "```"])
    return "\n".join(lines)


class ResearchAgent(PipelineAgent):
    name = "research_agent"
    step = PipelineStep.RESEARCH

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        response = await context.ai.generate_text(
            prompt=research_prompt(job),
            model=context.settings.gemini_research_model,
            use_google_search=True,
            urls=job.get("source_urls") or [],
            response_schema=ResearchDossier,
        )
        research = await self._parse_research_response(job_id, context, response.text)
        sources = research.get("sources", [])
        if response.citations:
            known = {source.get("url") for source in sources}
            for citation in response.citations:
                if citation.url and citation.url not in known:
                    sources.append(
                        {
                            "url": citation.url,
                            "title": citation.title,
                            "publisher": None,
                            "author": None,
                            "published_at": None,
                            "source_tier": "B",
                            "credibility_score": 0.5,
                            "notes": "Citation returned by grounding metadata.",
                        }
                    )
        research["sources"] = sources
        claims = research.get("claims", [])

        memory = build_research_memory_markdown(job, research)
        service = context.artifact_service
        await service.put_text(
            f"jobs/{job_id}/research/memory.md",
            memory,
            ArtifactType.MEMORY_MD,
            "text/markdown; charset=utf-8",
            job_id=job_id,
        )
        await service.put_json(
            f"jobs/{job_id}/research/research.json",
            research,
            ArtifactType.RESEARCH_JSON,
            job_id=job_id,
        )
        await service.put_json(
            f"jobs/{job_id}/research/sources.json",
            sources,
            ArtifactType.SOURCES_JSON,
            job_id=job_id,
        )
        claim_artifact = await service.put_json(
            f"jobs/{job_id}/research/claim_bank.json",
            claims,
            ArtifactType.CLAIM_BANK_JSON,
            job_id=job_id,
        )

        knowledge_repo = KnowledgeRepository(context.session)
        await knowledge_repo.replace_sources(job_id, sources)
        await knowledge_repo.replace_claims(job_id, claims)
        return AgentResult(
            output_artifact_id=str(claim_artifact["id"]), next_step=PipelineStep.SCRIPT
        )

    async def _parse_research_response(
        self,
        job_id: str,
        context: AgentContext,
        response_text: str,
    ) -> dict[str, Any]:
        try:
            return parse_model_json(response_text, ResearchDossier)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "Repairing malformed research response for job %s after parse failure: %s",
                job_id,
                exc,
            )
            repaired = await context.ai.generate_text(
                prompt=research_repair_prompt(response_text),
                model=context.settings.gemini_research_model,
                response_schema=ResearchDossier,
            )
            return parse_model_json(repaired.text, ResearchDossier)
