from __future__ import annotations

from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.core.text import slugify
from app.db.repositories import EpisodeRepository
from app.models.enums import ArtifactType, EpisodeStatus, JobStatus, PipelineStep
from app.providers.storage import public_object_url


class PublisherAgent(PipelineAgent):
    name = "publisher_agent"
    step = PipelineStep.PUBLISH

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        script = await context.latest_json(job_id, ArtifactType.VERIFIED_SCRIPT_JSON)
        audio = await context.latest_artifact(job_id, ArtifactType.FINAL_AUDIO)
        thumbnail = await context.latest_artifact(job_id, ArtifactType.THUMBNAIL_IMAGE)

        force_publish = bool(message.get("force_publish"))
        status = (
            EpisodeStatus.PUBLISHED
            if job.get("auto_publish") or force_publish
            else EpisodeStatus.DRAFT
        )
        base_slug = slugify(script.get("slug") or script.get("title") or job["topic"])
        slug = f"{base_slug}-{job_id[:8]}"
        repo = EpisodeRepository(context.session)
        audio_duration_seconds = duration_seconds_from_artifact(audio)
        episode = await repo.create_episode(
            {
                "generation_job_id": job_id,
                "title": script["title"],
                "slug": slug,
                "category": job["category"],
                "status": status,
                "summary": script.get("summary"),
                "description": script.get("description"),
                "duration_seconds": audio_duration_seconds,
                "language": job["language"],
                "metadata": {
                    "job_id": job_id,
                    "verification": script.get("verification", {}),
                    "used_claims": script.get("used_claims", []),
                },
            }
        )

        audio_public = public_object_url(context.settings, audio["r2_key"])
        thumb_public = public_object_url(context.settings, thumbnail["r2_key"])
        await repo.create_asset(
            {
                "episode_id": str(episode["id"]),
                "asset_type": "audio",
                "r2_key": audio["r2_key"],
                "public_url": audio_public,
                "mime_type": audio["mime_type"],
                "size_bytes": audio.get("size_bytes"),
                "checksum_sha256": audio.get("checksum_sha256"),
                "metadata": {},
            }
        )
        await repo.create_asset(
            {
                "episode_id": str(episode["id"]),
                "asset_type": "thumbnail",
                "r2_key": thumbnail["r2_key"],
                "public_url": thumb_public,
                "mime_type": thumbnail["mime_type"],
                "size_bytes": thumbnail.get("size_bytes"),
                "checksum_sha256": thumbnail.get("checksum_sha256"),
                "metadata": {},
            }
        )
        metadata_artifact = await context.artifact_service.put_json(
            f"episodes/{episode['id']}/metadata/episode.json",
            {"episode": dict(episode), "script": script},
            ArtifactType.EPISODE_METADATA_JSON,
            job_id=job_id,
            episode_id=str(episode["id"]),
        )
        job_metadata = {**(job.get("metadata") or {}), "episode_id": str(episode["id"])}
        if context.settings.enable_video_rendering:
            await context.job_repo.update_job(job_id, metadata=job_metadata)
            return AgentResult(
                output_artifact_id=str(metadata_artifact["id"]),
                next_step=PipelineStep.VIDEO_RENDER,
            )

        await context.job_repo.update_job(
            job_id, status=JobStatus.COMPLETED, current_step=None, metadata=job_metadata
        )
        return AgentResult(
            output_artifact_id=str(metadata_artifact["id"]), next_step=None, stop_pipeline=True
        )


def duration_seconds_from_artifact(artifact: dict[str, Any]) -> int | None:
    metadata = artifact.get("metadata") or {}
    raw_duration = metadata.get("duration_seconds")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError):
        return None
    if duration <= 0:
        return None
    return max(1, round(duration))
