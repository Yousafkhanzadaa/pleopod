from __future__ import annotations

import asyncio
import math
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.core.json_utils import to_pretty_json
from app.db.repositories import EpisodeRepository
from app.models.enums import ArtifactType, JobStatus, PipelineStep
from app.providers.storage import public_object_url
from app.services.audio import audio_bytes_duration_seconds


class VideoRenderAgent(PipelineAgent):
    name = "video_render_agent"
    step = PipelineStep.VIDEO_RENDER

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        episode_id = self._episode_id(job)
        if not episode_id:
            raise RuntimeError(f"Missing episode_id metadata for video render job {job_id}")

        existing_video = await context.artifact_repo.get_latest_for_job(
            job_id, ArtifactType.VIDEO_MP4
        )
        if existing_video:
            await self._attach_video_asset(context, episode_id, existing_video)
            await self._complete_job(context, job, episode_id, existing_video["id"])
            return AgentResult(output_artifact_id=str(existing_video["id"]), stop_pipeline=True)

        script = await context.latest_json(job_id, ArtifactType.VERIFIED_SCRIPT_JSON)
        episode_metadata = await context.latest_json(job_id, ArtifactType.EPISODE_METADATA_JSON)
        audio = await context.latest_artifact(job_id, ArtifactType.FINAL_AUDIO)
        thumbnail = await context.latest_artifact(job_id, ArtifactType.THUMBNAIL_IMAGE)
        episode = episode_metadata.get("episode") or {}

        payload = await build_video_payload(job, script, episode, audio, thumbnail, context)
        payload_artifact = await context.artifact_service.put_json(
            f"jobs/{job_id}/video/video_payload.json",
            payload,
            ArtifactType.VIDEO_PAYLOAD_JSON,
            job_id=job_id,
            episode_id=episode_id,
        )

        with tempfile.TemporaryDirectory(prefix=f"pleopod-video-{job_id[:8]}-") as temp_dir:
            temp_path = Path(temp_dir)
            props_path = temp_path / "video_payload.json"
            plan_path = temp_path / "video_plan.json"
            output_path = temp_path / f"final.{context.settings.remotion_render_output_format}"

            props_path.write_text(to_pretty_json(payload), encoding="utf-8")
            await self._run_director(context, props_path, plan_path)
            plan = plan_path.read_text(encoding="utf-8")
            plan_artifact = await context.artifact_service.put_text(
                f"jobs/{job_id}/video/video_plan.json",
                plan,
                ArtifactType.VIDEO_PLAN_JSON,
                "application/json",
                job_id=job_id,
                episode_id=episode_id,
                metadata={"payload_artifact_id": str(payload_artifact["id"])},
            )

            await self._run_render(context, props_path, plan_path, output_path)
            video_bytes = output_path.read_bytes()

        video_artifact = await context.artifact_service.put_bytes(
            f"episodes/{episode_id}/video/final.mp4",
            video_bytes,
            ArtifactType.VIDEO_MP4,
            "video/mp4",
            job_id=job_id,
            episode_id=episode_id,
            metadata={
                "payload_artifact_id": str(payload_artifact["id"]),
                "plan_artifact_id": str(plan_artifact["id"]),
            },
        )
        await self._attach_video_asset(context, episode_id, video_artifact)
        await self._complete_job(context, job, episode_id, video_artifact["id"])
        return AgentResult(output_artifact_id=str(video_artifact["id"]), stop_pipeline=True)

    async def _run_director(
        self,
        context: AgentContext,
        props_path: Path,
        plan_path: Path,
    ) -> None:
        command = [
            "npm",
            "run",
            "plan",
            "--",
            "--props",
            str(props_path),
            "--out",
            str(plan_path),
        ]
        if context.settings.gemini_api_key:
            command.extend(["--model", context.settings.remotion_video_director_model])
        else:
            command.append("--fallback")
        await self._run_remotion_command(context, command)

    async def _run_render(
        self,
        context: AgentContext,
        props_path: Path,
        plan_path: Path,
        output_path: Path,
    ) -> None:
        await self._run_remotion_command(
            context,
            [
                "npm",
                "run",
                "render",
                "--",
                "--props",
                str(props_path),
                "--plan",
                str(plan_path),
                "--out",
                str(output_path),
            ],
        )

    async def _run_remotion_command(
        self,
        context: AgentContext,
        command: list[str],
    ) -> None:
        renderer_path = context.settings.remotion_renderer_path.resolve()
        if not renderer_path.exists():
            raise RuntimeError(f"Remotion renderer path does not exist: {renderer_path}")

        env = os.environ.copy()
        if context.settings.gemini_api_key:
            env["GEMINI_API_KEY"] = context.settings.gemini_api_key

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=renderer_path,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=context.settings.remotion_render_timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError(f"Remotion command timed out: {' '.join(command)}") from exc

        if process.returncode != 0:
            output = "\n".join(
                part.decode("utf-8", errors="replace").strip()
                for part in (stdout, stderr)
                if part
            )
            raise RuntimeError(
                f"Remotion command failed code={process.returncode}: {' '.join(command)}\n{output}"
            )

    async def _attach_video_asset(
        self,
        context: AgentContext,
        episode_id: str,
        video_artifact: dict[str, Any],
    ) -> None:
        await EpisodeRepository(context.session).create_asset(
            {
                "episode_id": episode_id,
                "asset_type": "video",
                "r2_key": video_artifact["r2_key"],
                "public_url": public_url(context, video_artifact["r2_key"]),
                "mime_type": video_artifact["mime_type"],
                "size_bytes": video_artifact.get("size_bytes"),
                "checksum_sha256": video_artifact.get("checksum_sha256"),
                "metadata": {"source": "remotion"},
            }
        )

    async def _complete_job(
        self,
        context: AgentContext,
        job: dict[str, Any],
        episode_id: str,
        video_artifact_id: str,
    ) -> None:
        await context.job_repo.update_job(
            job["id"],
            status=JobStatus.COMPLETED,
            current_step=None,
            metadata={
                **(job.get("metadata") or {}),
                "episode_id": episode_id,
                "video_artifact_id": str(video_artifact_id),
            },
        )

    def _episode_id(self, job: dict[str, Any]) -> str | None:
        metadata = job.get("metadata") or {}
        episode_id = metadata.get("episode_id")
        return str(episode_id) if episode_id else None


async def build_video_payload(
    job: dict[str, Any],
    script: dict[str, Any],
    episode: dict[str, Any],
    audio_artifact: dict[str, Any],
    thumbnail_artifact: dict[str, Any],
    context: AgentContext,
) -> dict[str, Any]:
    audio_duration_seconds = await resolve_audio_duration_seconds(audio_artifact, context)
    duration_seconds = video_duration_seconds(job, episode, audio_duration_seconds)
    return {
        "jobId": str(job["id"]),
        "episodeId": str(episode.get("id") or (job.get("metadata") or {}).get("episode_id") or ""),
        "title": episode.get("title") or script.get("title") or job["topic"],
        "summary": episode.get("summary") or script.get("summary"),
        "description": episode.get("description") or script.get("description"),
        "category": episode.get("category") or job["category"],
        "language": episode.get("language") or job["language"],
        "durationSeconds": duration_seconds,
        "audioDurationSeconds": audio_duration_seconds,
        "audioUrl": await asset_url(context, audio_artifact["r2_key"]),
        "thumbnailUrl": await asset_url(context, thumbnail_artifact["r2_key"]),
        "speakers": [
            {
                "name": speaker.get("name"),
                "role": speaker.get("role"),
                "voiceName": speaker.get("voice_name"),
                "style": speaker.get("style"),
            }
            for speaker in script.get("speakers", [])
        ],
        "transcript": script.get("transcript") or "",
        "chapters": normalize_chapters(script.get("chapters") or []),
        "format": {
            "platform": "youtube",
            "aspectRatio": "16:9",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "tailPadSeconds": 1,
        },
        "brand": {
            "name": "Pleopod",
            "tagline": "Factual tech podcasts, generated with evidence.",
            "primaryColor": "#22d3ee",
            "accentColor": "#f59e0b",
            "backgroundColor": "#101216",
        },
    }


async def resolve_audio_duration_seconds(
    audio_artifact: dict[str, Any],
    context: AgentContext,
) -> float | None:
    metadata = audio_artifact.get("metadata") or {}
    duration = positive_float(metadata.get("duration_seconds"))
    if duration:
        return duration

    try:
        audio_data = await context.storage.get_bytes(audio_artifact["r2_key"])
    except Exception:
        return None
    return audio_bytes_duration_seconds(audio_data, audio_artifact.get("mime_type"))


def video_duration_seconds(
    job: dict[str, Any],
    episode: dict[str, Any],
    audio_duration_seconds: float | None,
) -> int:
    if audio_duration_seconds:
        return max(5, math.ceil(audio_duration_seconds + 1))

    episode_duration = positive_float(episode.get("duration_seconds"))
    if episode_duration:
        return max(5, math.ceil(episode_duration))

    return max(5, int(job["target_duration_seconds"]))


def positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def normalize_chapters(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for chapter in chapters:
        title = str(chapter.get("title") or "").strip()
        if not title:
            continue
        start_seconds = chapter.get("startSeconds", chapter.get("start_seconds", 0))
        normalized.append({"title": title, "startSeconds": float(start_seconds or 0)})
    return normalized


async def asset_url(context: AgentContext, key: str) -> str:
    url = await context.storage.presigned_get_url(key, expires_in=3600)
    parsed = urlparse(url)
    if parsed.scheme:
        return url

    path = Path(url)
    if path.is_absolute():
        return path.as_uri()
    return path.resolve().as_uri()


def public_url(context: AgentContext, key: str) -> str | None:
    return public_object_url(context.settings, key)
