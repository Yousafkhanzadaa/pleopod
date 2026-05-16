from __future__ import annotations

import asyncio
import math
import os
import re
import tempfile
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import quote, urlparse

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.core.json_utils import to_pretty_json
from app.models.enums import ArtifactType, JobStatus, PipelineStep
from app.providers.storage import public_object_url
from app.services.audio import audio_bytes_duration_seconds

_DIALOGUE_LINE_RE = re.compile(r"^([^:]{1,48}):\s*(.+)$")


class VideoRenderAgent(PipelineAgent):
    name = "video_render_agent"
    step = PipelineStep.VIDEO_RENDER

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        force = bool(message.get("force"))
        episode_id = self._episode_id(job)
        if not episode_id:
            raise RuntimeError(f"Missing episode_id metadata for video render job {job_id}")

        existing_video = await context.artifact_repo.get_latest_for_job(
            job_id, ArtifactType.VIDEO_MP4
        )
        if existing_video and not force:
            await self._attach_video_asset(context, episode_id, existing_video)
            return await self._result_after_video(context, job, episode_id, existing_video["id"])

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

            with local_asset_server(context) as local_asset_base_url:
                render_payload = renderable_payload(
                    payload,
                    audio_key=audio["r2_key"],
                    thumbnail_key=thumbnail["r2_key"],
                    local_asset_base_url=local_asset_base_url,
                )
                props_path.write_text(to_pretty_json(render_payload), encoding="utf-8")
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
        return await self._result_after_video(context, job, episode_id, video_artifact["id"])

    async def _result_after_video(
        self,
        context: AgentContext,
        job: dict[str, Any],
        episode_id: str,
        video_artifact_id: str,
    ) -> AgentResult:
        if context.settings.enable_youtube_uploading:
            await self._record_video_metadata(context, job, episode_id, video_artifact_id)
            return AgentResult(output_artifact_id=str(video_artifact_id))

        await self._complete_job(context, job, episode_id, video_artifact_id)
        return AgentResult(output_artifact_id=str(video_artifact_id), stop_pipeline=True)

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
        await context.episode_repo.create_asset(
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

    async def _record_video_metadata(
        self,
        context: AgentContext,
        job: dict[str, Any],
        episode_id: str,
        video_artifact_id: str,
    ) -> None:
        await context.job_repo.update_job(
            job["id"],
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
        "lineTimings": build_dialogue_timings(audio_artifact),
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


def build_dialogue_timings(audio_artifact: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = audio_artifact.get("metadata") or {}
    if not isinstance(metadata, dict):
        return []

    segment_timings = metadata.get("segment_timings") or []
    if not isinstance(segment_timings, list):
        return []

    timings: list[dict[str, Any]] = []
    line_number = 1
    for segment in segment_timings:
        if not isinstance(segment, dict):
            continue
        start_seconds = nonnegative_float(segment.get("start_seconds"))
        end_seconds = nonnegative_float(segment.get("end_seconds"))
        if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
            continue
        lines = parse_dialogue_lines(str(segment.get("source_transcript") or ""))
        if not lines:
            continue

        duration = end_seconds - start_seconds
        weights = [max(24, len(line["text"])) for line in lines]
        total_weight = sum(weights) or len(lines)
        elapsed_weight = 0
        for index, (line, weight) in enumerate(zip(lines, weights, strict=False)):
            line_start = start_seconds + (duration * elapsed_weight / total_weight)
            elapsed_weight += weight
            line_end = (
                end_seconds
                if index == len(lines) - 1
                else start_seconds + (duration * elapsed_weight / total_weight)
            )
            timings.append(
                {
                    "id": f"line_{line_number:03d}",
                    "speaker": line["speaker"],
                    "text": line["text"],
                    "startSeconds": round_seconds(line_start),
                    "endSeconds": round_seconds(line_end),
                }
            )
            line_number += 1

    return timings


def parse_dialogue_lines(transcript: str) -> list[dict[str, str]]:
    lines = []
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _DIALOGUE_LINE_RE.match(line)
        if not match:
            continue
        lines.append({"speaker": match.group(1).strip(), "text": match.group(2).strip()})
    return lines


def nonnegative_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def round_seconds(value: float) -> float:
    return round(value, 3)


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


def renderable_payload(
    payload: dict[str, Any],
    *,
    audio_key: str,
    thumbnail_key: str,
    local_asset_base_url: str | None,
) -> dict[str, Any]:
    if not local_asset_base_url:
        return payload

    return {
        **payload,
        "audioUrl": local_asset_url(local_asset_base_url, audio_key),
        "thumbnailUrl": local_asset_url(local_asset_base_url, thumbnail_key),
    }


def local_asset_url(base_url: str, key: str) -> str:
    return f"{base_url.rstrip('/')}/{quote(key.lstrip('/'), safe='/')}"


@contextmanager
def local_asset_server(context: AgentContext):
    if getattr(context.settings, "storage_backend", None) not in {"local", "temporary"}:
        yield None
        return

    root = local_storage_root(context)
    if root is None:
        yield None
        return

    root.mkdir(parents=True, exist_ok=True)
    handler = partial(_QuietStaticFileHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def local_storage_root(context: AgentContext) -> Path | None:
    storage_root = getattr(context.storage, "root", None)
    if storage_root is not None:
        return Path(storage_root).resolve()

    if getattr(context.settings, "storage_backend", None) == "temporary":
        settings_root = getattr(context.settings, "temporary_storage_path", None)
        if settings_root is not None:
            return Path(settings_root).resolve()

    settings_root = getattr(context.settings, "local_storage_path", None)
    if settings_root is not None:
        return Path(settings_root).resolve()

    return None


class _QuietStaticFileHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return
