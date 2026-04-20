from __future__ import annotations

from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.agents.prompts import script_prompt
from app.core.json_utils import extract_json
from app.models.enums import ArtifactType, PipelineStep


class ScriptWriterAgent(PipelineAgent):
    name = "script_writer_agent"
    step = PipelineStep.SCRIPT

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        memory_md = await context.latest_text(job_id, ArtifactType.MEMORY_MD)
        claims = await context.latest_json(job_id, ArtifactType.CLAIM_BANK_JSON)
        response = await context.ai.generate_text(
            prompt=script_prompt(job, memory_md, claims),
            model=context.settings.gemini_script_model,
        )
        script = extract_json(response.text)
        self._validate_script(script)
        await context.artifact_service.put_text(
            f"jobs/{job_id}/scripts/script_v1.md",
            script["transcript"],
            ArtifactType.SCRIPT_MD,
            "text/markdown; charset=utf-8",
            job_id=job_id,
        )
        artifact = await context.artifact_service.put_json(
            f"jobs/{job_id}/scripts/script_v1.json",
            script,
            ArtifactType.SCRIPT_JSON,
            job_id=job_id,
        )
        return AgentResult(
            output_artifact_id=str(artifact["id"]), next_step=PipelineStep.FACT_CHECK
        )

    def _validate_script(self, script: dict[str, Any]) -> None:
        speakers = script.get("speakers") or []
        if len(speakers) != 2:
            raise ValueError("Gemini multi-speaker TTS MVP requires exactly two speakers")
        names = {speaker.get("name") for speaker in speakers}
        transcript = script.get("transcript") or ""
        if not transcript.strip():
            raise ValueError("Script transcript is empty")
        missing = [name for name in names if name and f"{name}:" not in transcript]
        if missing:
            raise ValueError(f"Transcript missing speaker labels: {', '.join(missing)}")
