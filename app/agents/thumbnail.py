from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.agents.prompts import (
    fallback_thumbnail_brief,
    normalized_thumbnail_brief,
    thumbnail_director_prompt,
    thumbnail_prompt,
)
from app.core.json_utils import parse_model_json
from app.models.enums import ArtifactType, PipelineStep
from app.schemas.agent_outputs import ThumbnailCreativeBrief
from app.services.thumbnail import render_thumbnail_artwork

logger = logging.getLogger(__name__)

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
        brief = await create_thumbnail_brief(script, context)
        prompt = thumbnail_prompt(script, brief)
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
        output_data = image.data
        output_mime_type = image.mime_type
        render_metadata: dict[str, Any] = {"typography_composited": False}
        try:
            rendered = render_thumbnail_artwork(image.data, brief)
            output_data = rendered.data
            output_mime_type = "image/png"
            render_metadata = rendered.metadata
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not composite deterministic thumbnail typography; "
                "publishing text-free artwork: %s",
                exc,
            )

        extension = _EXTENSION_BY_MIME_TYPE.get(output_mime_type, "bin")
        artifact = await context.artifact_service.put_bytes(
            f"jobs/{job_id}/thumbnail/cover.{extension}",
            output_data,
            ArtifactType.THUMBNAIL_IMAGE,
            output_mime_type,
            job_id=job_id,
            metadata={
                "prompt": image.prompt,
                "provider": context.settings.resolved_thumbnail_image_provider,
                "model": context.settings.resolved_thumbnail_image_model,
                "creative_brief": brief,
                **render_metadata,
            },
        )
        return AgentResult(output_artifact_id=str(artifact["id"]))


async def create_thumbnail_brief(
    script: dict[str, Any],
    context: AgentContext,
) -> dict[str, Any]:
    try:
        response = await context.ai.generate_text(
            prompt=thumbnail_director_prompt(script),
            model=context.settings.gemini_thumbnail_model,
            response_schema=ThumbnailCreativeBrief,
        )
        brief = parse_model_json(response.text, ThumbnailCreativeBrief)
        return normalized_thumbnail_brief(script, brief)
    except (OSError, TypeError, ValueError, ValidationError) as exc:
        logger.warning("Thumbnail creative director failed; using deterministic brief: %s", exc)
        return fallback_thumbnail_brief(script)
