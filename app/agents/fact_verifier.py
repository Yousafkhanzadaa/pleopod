from __future__ import annotations

from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.agents.prompts import verification_prompt
from app.core.json_utils import extract_json, to_pretty_json
from app.models.enums import ArtifactType, JobStatus, PipelineStep


class FactVerifierAgent(PipelineAgent):
    name = "fact_verifier_agent"
    step = PipelineStep.FACT_CHECK

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        script = await context.latest_json(job_id, ArtifactType.SCRIPT_JSON)
        claims = await context.latest_json(job_id, ArtifactType.CLAIM_BANK_JSON)
        response = await context.ai.generate_text(
            prompt=verification_prompt(script, claims),
            model=context.settings.gemini_verification_model,
        )
        verification = extract_json(response.text)
        fixed_transcript = verification.get("fixed_transcript")
        if fixed_transcript:
            script["transcript"] = fixed_transcript
            script.setdefault("metadata", {})["fact_verifier_changed_transcript"] = True
        script["verification"] = verification
        report = self._report_markdown(verification)
        await context.artifact_service.put_text(
            f"jobs/{job_id}/verification/report.md",
            report,
            ArtifactType.VERIFICATION_REPORT_MD,
            "text/markdown; charset=utf-8",
            job_id=job_id,
        )
        artifact = await context.artifact_service.put_json(
            f"jobs/{job_id}/scripts/script_verified.json",
            script,
            ArtifactType.VERIFIED_SCRIPT_JSON,
            job_id=job_id,
            metadata={"verification_score": verification.get("score")},
        )
        if context.settings.require_human_approval:
            await context.job_repo.update_job(
                job_id,
                status=JobStatus.AWAITING_SCRIPT_APPROVAL,
                current_step=None,
            )
            return AgentResult(output_artifact_id=str(artifact["id"]), stop_pipeline=True)
        return AgentResult(output_artifact_id=str(artifact["id"]), next_step=PipelineStep.THUMBNAIL)

    def _report_markdown(self, verification: dict[str, Any]) -> str:
        lines = [
            "# Verification Report",
            "",
            f"- Verdict: {verification.get('verdict')}",
            f"- Score: {verification.get('score')}",
            "",
            "## Issues",
        ]
        issues = verification.get("issues") or []
        lines.extend(f"- {issue}" for issue in issues) if issues else lines.append("- None")
        lines.extend(
            [
                "",
                "## Line Checks",
                "```json",
                to_pretty_json(verification.get("line_checks", [])),
                "```",
            ]
        )
        return "\n".join(lines)
