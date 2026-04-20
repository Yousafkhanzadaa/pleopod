from __future__ import annotations

from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.agents.prompts import research_review_prompt
from app.core.json_utils import extract_json, to_pretty_json
from app.db.repositories import KnowledgeRepository
from app.models.enums import ArtifactType, JobStatus, PipelineStep


class ResearchReviewAgent(PipelineAgent):
    name = "research_review_agent"
    step = PipelineStep.RESEARCH_REVIEW

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        research = await context.latest_json(job_id, ArtifactType.RESEARCH_JSON)
        response = await context.ai.generate_text(
            prompt=research_review_prompt(research),
            model=context.settings.gemini_verification_model,
        )
        review = extract_json(response.text)
        fixed_claims = review.get("fixed_claims") or research.get("claims", [])
        await KnowledgeRepository(context.session).replace_claims(job_id, fixed_claims)
        claim_artifact = await context.artifact_service.put_json(
            f"jobs/{job_id}/research/claim_bank.reviewed.json",
            fixed_claims,
            ArtifactType.CLAIM_BANK_JSON,
            job_id=job_id,
            metadata={"review_score": review.get("score")},
        )
        report = self._report_markdown(review)
        report_artifact = await context.artifact_service.put_text(
            f"jobs/{job_id}/research/research_review.md",
            report,
            ArtifactType.RESEARCH_REVIEW_MD,
            "text/markdown; charset=utf-8",
            job_id=job_id,
        )
        if context.settings.require_human_approval:
            await context.job_repo.update_job(
                job_id,
                status=JobStatus.AWAITING_RESEARCH_APPROVAL,
                current_step=None,
            )
            return AgentResult(output_artifact_id=str(report_artifact["id"]), stop_pipeline=True)
        return AgentResult(
            output_artifact_id=str(claim_artifact["id"]), next_step=PipelineStep.SCRIPT
        )

    def _report_markdown(self, review: dict[str, Any]) -> str:
        lines = [
            "# Research Review",
            "",
            f"- Verdict: {review.get('verdict', 'approved')}",
            f"- Score: {review.get('score', 'n/a')}",
            "",
            "## Issues",
        ]
        issues = review.get("issues") or []
        lines.extend(f"- {issue}" for issue in issues) if issues else lines.append("- None")
        lines.extend(
            [
                "",
                "## Fixed Claims",
                "```json",
                to_pretty_json(review.get("fixed_claims", [])),
                "```",
            ]
        )
        return "\n".join(lines)
