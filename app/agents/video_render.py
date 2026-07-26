from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import quote, urlparse

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.agents.video_director import (
    line_timings_from_segment_timings,
    plan_video_scenes,
    retime_existing_scene_plan,
)
from app.core.duration import clamp_video_duration_seconds
from app.core.json_utils import to_pretty_json
from app.core.text import strip_speaker_labels
from app.models.enums import ArtifactType, JobStatus, PipelineStep
from app.providers.storage import public_object_url
from app.schemas.video_plan import ScenePlan
from app.services.audio import audio_bytes_duration_seconds
from app.services.motion_video import (
    MotionVideoSpec,
    build_ass_document,
    build_ffmpeg_command,
    caption_cues_from_line_timings,
    captions_supported,
    motion_background_supported,
    motion_caption_plan,
    resolve_caption_font_file,
)

logger = logging.getLogger(__name__)

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
        render_mode = "remotion"
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

            if context.settings.enable_video_rendering:
                render_mode = "remotion"
                scene_plan = await self._build_scene_plan(
                    context,
                    job,
                    script,
                    audio,
                    duration_seconds=int(payload["durationSeconds"]),
                    reuse_existing=bool(message.get("reuse_scene_plan")),
                )
                await context.artifact_service.put_json(
                    f"jobs/{job_id}/video/scene_plan.json",
                    scene_plan,
                    ArtifactType.SCENE_PLAN_JSON,
                    job_id=job_id,
                    episode_id=episode_id,
                )
                plan_path.write_text(to_pretty_json(scene_plan), encoding="utf-8")
                with local_asset_server(context) as local_asset_base_url:
                    render_payload = renderable_payload(
                        {**payload, "scenePlan": scene_plan},
                        audio_key=audio["r2_key"],
                        thumbnail_key=thumbnail["r2_key"],
                        local_asset_base_url=local_asset_base_url,
                    )
                    props_path.write_text(to_pretty_json(render_payload), encoding="utf-8")
                    await self._run_render(context, props_path, output_path)
            else:
                render_mode = await self._run_motion_caption_video(
                    context,
                    payload,
                    audio,
                    thumbnail,
                    output_path,
                    temp_path,
                    props_path=props_path,
                    plan_path=plan_path,
                )

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
                "render_mode": render_mode,
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
        output_path: Path,
        *,
        composition: str = "PresentationEpisode",
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
                "--composition",
                composition,
                "--out",
                str(output_path),
            ],
        )
        await self._normalize_render_audio(context, output_path)

    async def _normalize_render_audio(
        self,
        context: AgentContext,
        output_path: Path,
    ) -> None:
        """Normalize narration for web-video playback without re-encoding frames."""
        if not shutil.which("ffmpeg"):
            logger.warning("ffmpeg is unavailable; skipping final audio loudness normalization")
            return
        normalized_path = output_path.with_name(
            f"{output_path.stem}.normalized{output_path.suffix}"
        )
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(output_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "copy",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(normalized_path),
        ]
        try:
            await self._run_ffmpeg_command(context, command)
        except RuntimeError:
            logger.warning(
                "Final audio loudness normalization failed; keeping the Remotion output",
                exc_info=True,
            )
            return
        shutil.move(normalized_path, output_path)

    async def _build_scene_plan(
        self,
        context: AgentContext,
        job: dict[str, Any],
        script: dict[str, Any],
        audio: dict[str, Any],
        *,
        duration_seconds: int,
        reuse_existing: bool = False,
    ) -> dict[str, Any]:
        job_id = str(job["id"])
        claims = await self._latest_list(context, job_id, ArtifactType.CLAIM_BANK_JSON)
        raw_sources = await self._latest_list(context, job_id, ArtifactType.SOURCES_JSON)
        source_urls = [
            str(source.get("url") if isinstance(source, dict) else source)
            for source in raw_sources
            if (source.get("url") if isinstance(source, dict) else source)
        ]
        metadata = audio.get("metadata") or {}
        line_timings = metadata.get("line_timings") or line_timings_from_segment_timings(
            metadata.get("segment_timings") or []
        )
        if reuse_existing:
            existing = ScenePlan.model_validate(
                await context.latest_json(job_id, ArtifactType.SCENE_PLAN_JSON)
            )
            return retime_existing_scene_plan(
                existing,
                duration_seconds=duration_seconds,
                line_timings=line_timings or None,
                word_timings=metadata.get("word_timings") or None,
                source_urls=source_urls,
                claims=claims,
            ).model_dump(mode="json")
        plan = await plan_video_scenes(
            script=script if isinstance(script, dict) else {},
            claims=claims,
            line_timings=line_timings or None,
            duration_seconds=duration_seconds,
            category=str(job.get("category") or "Tech"),
            ai=context.ai,
            model=context.settings.remotion_video_director_model,
            source_urls=source_urls,
            word_timings=metadata.get("word_timings") or None,
        )
        return plan.model_dump(mode="json")

    async def _latest_list(
        self,
        context: AgentContext,
        job_id: str,
        artifact_type: ArtifactType,
    ) -> list[Any]:
        try:
            value = await context.latest_json(job_id, artifact_type)
        except RuntimeError:
            return []
        return value if isinstance(value, list) else []

    async def _run_static_video(
        self,
        context: AgentContext,
        audio: dict[str, Any],
        thumbnail: dict[str, Any],
        output_path: Path,
        temp_path: Path,
        duration_seconds: int,
    ) -> None:
        audio_path = temp_path / f"input-audio{artifact_suffix(audio, '.mp3')}"
        thumbnail_path = temp_path / f"thumbnail{artifact_suffix(thumbnail, '.png')}"
        audio_path.write_bytes(await context.storage.get_bytes(audio["r2_key"]))
        thumbnail_path.write_bytes(await context.storage.get_bytes(thumbnail["r2_key"]))
        render_duration_seconds = clamp_video_duration_seconds(duration_seconds)

        await self._run_ffmpeg_command(
            context,
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                str(thumbnail_path),
                "-i",
                str(audio_path),
                "-vf",
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-tune",
                "stillimage",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-t",
                str(render_duration_seconds),
                "-movflags",
                "+faststart",
                str(output_path),
            ],
        )

    async def _run_motion_caption_video(
        self,
        context: AgentContext,
        payload: dict[str, Any],
        audio: dict[str, Any],
        thumbnail: dict[str, Any],
        output_path: Path,
        temp_path: Path,
        *,
        props_path: Path,
        plan_path: Path,
    ) -> str:
        """Render an engaging caption + Ken Burns video with ffmpeg.

        Falls back to the plain static thumbnail video if ffmpeg cannot build
        the motion background, so scheduled autopublish runs never break on a
        rendering edge case.
        """
        props_path.write_text(to_pretty_json(payload), encoding="utf-8")
        fmt = payload.get("format") or {}
        width = int(fmt.get("width") or 1920)
        height = int(fmt.get("height") or 1080)
        fps = int(fmt.get("fps") or 30)
        duration_seconds = int(payload["durationSeconds"])
        settings = context.settings

        if shutil.which("ffmpeg") and motion_background_supported():
            audio_path = temp_path / f"input-audio{artifact_suffix(audio, '.mp3')}"
            image_path = temp_path / f"background{artifact_suffix(thumbnail, '.png')}"
            audio_path.write_bytes(await context.storage.get_bytes(audio["r2_key"]))
            image_path.write_bytes(await context.storage.get_bytes(thumbnail["r2_key"]))

            brand = payload.get("brand") or {}
            accent_color = str(brand.get("accentColor") or "#22d3ee")
            waveform = bool(getattr(settings, "video_waveform", True))
            captions_on = captions_supported()

            ass_path: Path | None = None
            fonts_dir: str | None = None
            if captions_on:
                cues = caption_cues_from_line_timings(
                    payload.get("lineTimings") or [],
                    max_words=int(getattr(settings, "video_caption_max_words", 3)),
                )
                font_file = resolve_caption_font_file(settings)
                fonts_dir = str(Path(font_file).parent) if font_file else None
                ass_document = build_ass_document(
                    cues,
                    video_width=width,
                    video_height=height,
                    font_name=str(getattr(settings, "video_caption_font_name", "DejaVu Sans")),
                    accent_color=accent_color,
                    title=payload.get("title"),
                    brand=brand.get("name"),
                    source_label=await self._source_label(context, payload),
                    duration=duration_seconds,
                )
                ass_path = temp_path / "captions.ass"
                ass_path.write_text(ass_document, encoding="utf-8")

            plan_path.write_text(
                to_pretty_json(
                    motion_caption_plan(payload, captions=captions_on, waveform=waveform)
                ),
                encoding="utf-8",
            )
            spec = MotionVideoSpec(
                image_path=str(image_path),
                audio_path=str(audio_path),
                output_path=str(output_path),
                duration_seconds=duration_seconds,
                width=width,
                height=height,
                fps=fps,
                accent_color=accent_color,
                ass_path=str(ass_path) if ass_path else None,
                fonts_dir=fonts_dir,
                waveform=waveform,
                render_timeout_seconds=settings.remotion_render_timeout_seconds,
            )
            try:
                await self._run_ffmpeg_command(context, build_ffmpeg_command(spec))
                return "motion_caption"
            except RuntimeError:
                logger.warning(
                    "Motion caption render failed; falling back to static thumbnail video",
                    exc_info=True,
                )

        plan_path.write_text(to_pretty_json(static_video_plan(payload)), encoding="utf-8")
        await self._run_static_video(
            context,
            audio,
            thumbnail,
            output_path,
            temp_path,
            duration_seconds=duration_seconds,
        )
        return "static_thumbnail"

    async def _source_label(
        self,
        context: AgentContext,
        payload: dict[str, Any],
    ) -> str | None:
        job_id = str(payload.get("jobId") or "")
        if not job_id:
            return None
        try:
            sources = await context.latest_json(job_id, ArtifactType.SOURCES_JSON)
        except Exception:  # noqa: BLE001 - source card is best effort
            return None

        domains: list[str] = []
        for source in sources if isinstance(sources, list) else []:
            url = source.get("url") if isinstance(source, dict) else source
            domain = _source_domain(str(url or ""))
            if domain and domain not in domains:
                domains.append(domain)
            if len(domains) >= 3:
                break
        if not domains:
            return None
        return "Sources: " + " · ".join(domains)

    async def _run_ffmpeg_command(
        self,
        context: AgentContext,
        command: list[str],
    ) -> None:
        if not shutil.which(command[0]):
            raise RuntimeError(
                "ffmpeg is required to create the static thumbnail video. "
                "Install ffmpeg locally, or run in the Docker/Railway environment "
                "where the Dockerfile installs it."
            )

        process = await asyncio.create_subprocess_exec(
            *command,
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
            raise RuntimeError(f"Static video command timed out: {' '.join(command)}") from exc

        if process.returncode != 0:
            output = "\n".join(
                part.decode("utf-8", errors="replace").strip()
                for part in (stdout, stderr)
                if part
            )
            raise RuntimeError(
                f"Static video command failed code={process.returncode}: "
                f"{' '.join(command)}\n{output}"
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
                "metadata": {
                    "source": (video_artifact.get("metadata") or {}).get(
                        "render_mode", "remotion"
                    )
                },
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
    default_speaker = primary_script_speaker_name(script)
    line_timings = clip_line_timings(
        build_dialogue_timings(audio_artifact, default_speaker=default_speaker),
        duration_seconds,
    )
    word_timings = clip_word_timings(
        (audio_artifact.get("metadata") or {}).get("word_timings") or [],
        duration_seconds,
    )
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
        "lineTimings": line_timings,
        "wordTimings": word_timings,
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
            "tagline": "Factual tech videos, generated with evidence.",
            "primaryColor": "#5B7CFA",
            "accentColor": "#F4C95D",
            "backgroundColor": "#0B0D10",
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
        return clamp_video_duration_seconds(math.ceil(audio_duration_seconds + 1))

    episode_duration = positive_float(episode.get("duration_seconds"))
    if episode_duration:
        return clamp_video_duration_seconds(math.ceil(episode_duration))

    return clamp_video_duration_seconds(job["target_duration_seconds"])


def clip_line_timings(
    line_timings: list[dict[str, Any]],
    duration_seconds: int,
) -> list[dict[str, Any]]:
    clipped = []
    for timing in line_timings:
        start_seconds = nonnegative_float(timing.get("startSeconds"))
        end_seconds = nonnegative_float(timing.get("endSeconds"))
        if start_seconds is None or end_seconds is None:
            continue
        if start_seconds >= duration_seconds:
            continue
        clipped_end = min(end_seconds, float(duration_seconds))
        if clipped_end <= start_seconds:
            continue
        clipped.append(
            {
                **timing,
                "startSeconds": round_seconds(start_seconds),
                "endSeconds": round_seconds(clipped_end),
            }
        )
    return clipped


def clip_word_timings(
    word_timings: list[dict[str, Any]],
    duration_seconds: int,
) -> list[dict[str, Any]]:
    clipped: list[dict[str, Any]] = []
    for timing in word_timings:
        if not isinstance(timing, dict):
            continue
        word = str(timing.get("word") or "").strip()
        start_seconds = nonnegative_float(
            timing.get("startSeconds", timing.get("start_seconds"))
        )
        end_seconds = nonnegative_float(timing.get("endSeconds", timing.get("end_seconds")))
        if not word or start_seconds is None or end_seconds is None:
            continue
        if start_seconds >= duration_seconds:
            continue
        clipped_end = min(end_seconds, float(duration_seconds))
        if clipped_end <= start_seconds:
            continue
        clipped.append(
            {
                "word": word,
                "startSeconds": round_seconds(start_seconds),
                "endSeconds": round_seconds(clipped_end),
            }
        )
    return clipped


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


def primary_script_speaker_name(script: dict[str, Any]) -> str:
    return next(
        (
            str(speaker.get("name") or "").strip()
            for speaker in script.get("speakers") or []
            if isinstance(speaker, dict) and str(speaker.get("name") or "").strip()
        ),
        "",
    )


def build_dialogue_timings(
    audio_artifact: dict[str, Any],
    *,
    default_speaker: str = "",
) -> list[dict[str, Any]]:
    metadata = audio_artifact.get("metadata") or {}
    if not isinstance(metadata, dict):
        return []

    aligned_line_timings = metadata.get("line_timings") or []
    if isinstance(aligned_line_timings, list) and aligned_line_timings:
        aligned_timings: list[dict[str, Any]] = []
        for index, timing in enumerate(aligned_line_timings, start=1):
            if not isinstance(timing, dict):
                continue
            start_seconds = nonnegative_float(timing.get("start_seconds"))
            end_seconds = nonnegative_float(timing.get("end_seconds"))
            if (
                start_seconds is None
                or end_seconds is None
                or end_seconds <= start_seconds
            ):
                continue
            speaker = str(timing.get("speaker") or "").strip() or default_speaker.strip()
            text = str(timing.get("text") or "").strip()
            if not speaker or not text:
                continue
            timing_id = str(timing.get("id") or "").strip() or f"line_{index:03d}"
            aligned_timings.append(
                {
                    "id": timing_id,
                    "speaker": speaker,
                    "text": text,
                    "startSeconds": round_seconds(start_seconds),
                    "endSeconds": round_seconds(end_seconds),
                }
            )
        if aligned_timings:
            return aligned_timings

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
        lines = parse_dialogue_lines(
            str(segment.get("source_transcript") or ""),
            default_speaker=default_speaker,
        )
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


def parse_dialogue_lines(
    transcript: str,
    *,
    default_speaker: str = "",
) -> list[dict[str, str]]:
    resolved_speaker = default_speaker.strip()
    if not resolved_speaker:
        resolved_speaker = next(
            (
                match.group(1).strip()
                for raw_line in transcript.splitlines()
                if (match := _DIALOGUE_LINE_RE.match(raw_line.strip()))
            ),
            "",
        )

    lines: list[dict[str, str]] = []
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _DIALOGUE_LINE_RE.match(line)
        if not match:
            if resolved_speaker:
                text = strip_speaker_labels(line, [resolved_speaker])
                if text:
                    lines.append({"speaker": resolved_speaker, "text": text})
            continue
        source_speaker = match.group(1).strip()
        speaker = resolved_speaker or source_speaker
        text = strip_speaker_labels(match.group(2), [source_speaker, speaker])
        if not speaker or not text:
            continue
        lines.append(
            {
                "speaker": speaker,
                "text": text,
            }
        )
    return lines


def _source_domain(url: str) -> str:
    try:
        hostname = urlparse(url).hostname or ""
    except ValueError:
        return ""
    hostname = hostname.lower().strip(".")
    return hostname[4:] if hostname.startswith("www.") else hostname


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


def static_video_plan(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "renderMode": "static_thumbnail",
        "durationSeconds": payload.get("durationSeconds"),
        "format": {
            "width": 1280,
            "height": 720,
            "fps": 30,
            "videoCodec": "h264",
            "audioCodec": "aac",
        },
        "source": {
            "audioUrl": payload.get("audioUrl"),
            "thumbnailUrl": payload.get("thumbnailUrl"),
        },
    }


def artifact_suffix(artifact: dict[str, Any], fallback: str) -> str:
    suffix = Path(str(artifact.get("r2_key") or "")).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        return suffix

    mime_type = str(artifact.get("mime_type") or "").lower()
    if mime_type == "audio/wav":
        return ".wav"
    if mime_type in {"audio/mpeg", "audio/mp3"}:
        return ".mp3"
    if mime_type == "image/jpeg":
        return ".jpg"
    if mime_type == "image/webp":
        return ".webp"
    if mime_type == "image/png":
        return ".png"
    return fallback


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
