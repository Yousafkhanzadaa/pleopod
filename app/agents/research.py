from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.agents.prompts import (
    research_prompt,
    research_quality_repair_prompt,
    research_repair_prompt,
)
from app.core.json_utils import parse_model_json, to_pretty_json
from app.models.enums import ArtifactType, PipelineStep
from app.schemas.agent_outputs import ResearchDossier

logger = logging.getLogger(__name__)

MIN_RESEARCH_SOURCES = 5
MIN_RESEARCH_CLAIMS = 8
_PLAN_LIKE_PREFIXES = (
    "investigate",
    "examine",
    "detail",
    "quantify",
    "outline",
    "research",
    "analyze",
    "determine",
    "explore",
    "assess",
)


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
        merge_citations_into_sources(research, response.citations)
        quality_issues = research_quality_issues(research)
        if quality_issues:
            logger.warning(
                "Repairing low-quality research response for job %s: %s",
                job_id,
                "; ".join(quality_issues),
            )
            repaired_response = await context.ai.generate_text(
                prompt=research_quality_repair_prompt(job, research, quality_issues),
                model=context.settings.gemini_research_model,
                use_google_search=True,
                urls=job.get("source_urls") or [],
                response_schema=ResearchDossier,
            )
            research = await self._parse_research_response(
                job_id, context, repaired_response.text
            )
            merge_citations_into_sources(research, repaired_response.citations)
            quality_issues = research_quality_issues(research)
            if quality_issues:
                raise ValueError(
                    "Research quality gate failed: " + "; ".join(quality_issues)
                )

        sources = research.get("sources", [])
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

        await context.knowledge_repo.replace_sources(job_id, sources)
        await context.knowledge_repo.replace_claims(job_id, claims)
        return AgentResult(output_artifact_id=str(claim_artifact["id"]))

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


def merge_citations_into_sources(research: dict[str, Any], citations: list[Any]) -> None:
    sources = research.get("sources", [])
    known = {source.get("url") for source in sources if isinstance(source, dict)}
    for citation in citations:
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
            known.add(citation.url)
    research["sources"] = sources


def research_quality_issues(research: dict[str, Any]) -> list[str]:
    sources = [source for source in research.get("sources", []) if source.get("url")]
    claims = [claim for claim in research.get("claims", []) if claim.get("claim_text")]
    sourced_claims = [claim for claim in claims if claim.get("source_urls")]
    key_points = [str(point or "").strip() for point in research.get("key_points", [])]
    issues = []

    if len(sources) < MIN_RESEARCH_SOURCES:
        issues.append(
            f"expected at least {MIN_RESEARCH_SOURCES} sources, got {len(sources)}"
        )
    if len(claims) < MIN_RESEARCH_CLAIMS:
        issues.append(f"expected at least {MIN_RESEARCH_CLAIMS} claims, got {len(claims)}")
    if len(sourced_claims) < min(MIN_RESEARCH_CLAIMS, len(claims)):
        issues.append("claims must cite source URLs")
    if key_points and most_points_are_research_tasks(key_points):
        issues.append("key_points look like research tasks instead of factual findings")
    if not str(research.get("summary") or "").strip():
        issues.append("summary is empty")

    return issues


def most_points_are_research_tasks(points: list[str]) -> bool:
    plan_like = 0
    for point in points:
        normalized = point.lower().lstrip("-•0123456789. )")
        if normalized.startswith(_PLAN_LIKE_PREFIXES):
            plan_like += 1
    return plan_like >= max(1, len(points) // 2)
