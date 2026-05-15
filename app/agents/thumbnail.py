from __future__ import annotations

from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.agents.prompts import thumbnail_prompt
from app.models.enums import ArtifactType, PipelineStep

_EXTENSION_BY_MIME_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


class ThumbnailAgent(PipelineAgent):
    name = "thumbnail_agent"
    step = PipelineStep.THUMBNAIL

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        script = await context.latest_json(job_id, ArtifactType.VERIFIED_SCRIPT_JSON)
        prompt = thumbnail_prompt(script)
        await context.artifact_service.put_text(
            f"jobs/{job_id}/thumbnail/prompt.txt",
            prompt,
            ArtifactType.THUMBNAIL_PROMPT,
            "text/plain; charset=utf-8",
            job_id=job_id,
        )
        image = await context.thumbnail_ai.generate_image(
            prompt=prompt,
            model=context.settings.resolved_thumbnail_image_model,
        )
        extension = _EXTENSION_BY_MIME_TYPE.get(image.mime_type, "bin")
        artifact = await context.artifact_service.put_bytes(
            f"jobs/{job_id}/thumbnail/cover.{extension}",
            image.data,
            ArtifactType.THUMBNAIL_IMAGE,
            image.mime_type,
            job_id=job_id,
            metadata={
                "prompt": image.prompt,
                "provider": context.settings.resolved_thumbnail_image_provider,
                "model": context.settings.resolved_thumbnail_image_model,
            },
        )
        return AgentResult(output_artifact_id=str(artifact["id"]))
