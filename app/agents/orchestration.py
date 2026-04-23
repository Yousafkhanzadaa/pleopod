from __future__ import annotations

from app.agents.prompts import orchestration_prompt
from app.core.config import Settings
from app.core.json_utils import extract_json
from app.providers.ai import AIProvider
from app.schemas.jobs import GenerationJobCreate, GenerationJobRequest, OrchestratedJobPayload


async def orchestrate_generation_job(
    request: GenerationJobRequest,
    ai: AIProvider,
    settings: Settings,
) -> GenerationJobCreate:
    overrides = {
        key: value
        for key, value in {
            "category": request.category,
            "audience": request.audience,
            "target_duration_seconds": request.target_duration_seconds,
            "language": request.language,
            "tone": request.tone,
            "source_urls": [str(url) for url in request.source_urls],
            "auto_publish": request.auto_publish,
        }.items()
        if value not in (None, [], "")
    }
    response = await ai.generate_text(
        prompt=orchestration_prompt(request.requested_title, overrides),
        model=settings.gemini_orchestration_model,
        response_schema=OrchestratedJobPayload,
    )
    draft = OrchestratedJobPayload.model_validate(extract_json(response.text))

    return GenerationJobCreate(
        topic=draft.topic,
        category=request.category or draft.category,
        audience=request.audience or draft.audience,
        target_duration_seconds=request.target_duration_seconds or draft.target_duration_seconds,
        language=request.language or draft.language,
        tone=request.tone or draft.tone,
        source_urls=[str(url) for url in request.source_urls] or draft.source_urls,
        auto_publish=request.auto_publish,
        metadata=request.metadata,
    )
