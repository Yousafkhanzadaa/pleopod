from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.models.enums import ArtifactType, JobStatus, PipelineStep


class YouTubeUploadAgent(PipelineAgent):
    name = "youtube_upload_agent"
    step = PipelineStep.YOUTUBE_UPLOAD

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        force = bool(message.get("force"))
        dry_run = bool(message.get("dry_run"))
        episode_id = self._episode_id(job)
        if not episode_id:
            raise RuntimeError(f"Missing episode_id metadata for YouTube upload job {job_id}")

        existing_result = await context.artifact_repo.get_latest_for_job(
            job_id, ArtifactType.YOUTUBE_UPLOAD_RESULT_JSON
        )
        if existing_result and not force and not dry_run:
            result = await context.latest_json(job_id, ArtifactType.YOUTUBE_UPLOAD_RESULT_JSON)
            if is_successful_upload_result(result):
                await self._attach_youtube_asset(context, episode_id, result)
                await self._complete_job(context, job, episode_id, result)
                return AgentResult(
                    output_artifact_id=str(existing_result["id"]),
                    stop_pipeline=True,
                )

        episode_metadata = await context.latest_json(job_id, ArtifactType.EPISODE_METADATA_JSON)
        script = episode_metadata.get("script") or {}
        episode = episode_metadata.get("episode") or {}
        video = await context.latest_artifact(job_id, ArtifactType.VIDEO_MP4)
        thumbnail = await context.latest_artifact(job_id, ArtifactType.THUMBNAIL_IMAGE)

        if not dry_run:
            self._validate_settings(context)
        with tempfile.TemporaryDirectory(prefix=f"pleopod-youtube-{job_id[:8]}-") as temp_dir:
            temp_path = Path(temp_dir)
            video_path = temp_path / "final.mp4"
            thumbnail_path = temp_path / "thumbnail.png"
            manifest_path = temp_path / "youtube_manifest.json"
            result_path = temp_path / "youtube_result.json"

            video_path.write_bytes(await context.storage.get_bytes(video["r2_key"]))
            thumbnail_path.write_bytes(await context.storage.get_bytes(thumbnail["r2_key"]))

            runtime_manifest = build_youtube_manifest(
                job=job,
                episode=episode,
                script=script,
                video_path=video_path,
                thumbnail_path=thumbnail_path,
                context=context,
            )
            manifest_path.write_text(json.dumps(runtime_manifest, indent=2), encoding="utf-8")

            artifact_manifest = {
                **runtime_manifest,
                "videoPath": None,
                "thumbnailPath": None,
                "videoArtifactId": str(video["id"]),
                "thumbnailArtifactId": str(thumbnail["id"]),
            }
            manifest_artifact = await context.artifact_service.put_json(
                f"jobs/{job_id}/youtube/upload_manifest.json",
                artifact_manifest,
                ArtifactType.YOUTUBE_UPLOAD_MANIFEST_JSON,
                job_id=job_id,
                episode_id=episode_id,
            )

            await self._run_uploader(context, manifest_path, result_path, dry_run=dry_run)
            result = json.loads(result_path.read_text(encoding="utf-8"))

        result_artifact = await context.artifact_service.put_json(
            f"episodes/{episode_id}/youtube/upload_result.json",
            result,
            ArtifactType.YOUTUBE_UPLOAD_RESULT_JSON,
            job_id=job_id,
            episode_id=episode_id,
            metadata={"manifest_artifact_id": str(manifest_artifact["id"])},
        )
        if dry_run:
            return AgentResult(output_artifact_id=str(result_artifact["id"]), stop_pipeline=True)

        await self._attach_youtube_asset(context, episode_id, result)
        await self._complete_job(context, job, episode_id, result)
        return AgentResult(output_artifact_id=str(result_artifact["id"]), stop_pipeline=True)

    async def _run_uploader(
        self,
        context: AgentContext,
        manifest_path: Path,
        result_path: Path,
        *,
        dry_run: bool = False,
    ) -> None:
        uploader_path = context.settings.youtube_uploader_path.resolve()
        if not uploader_path.exists():
            raise RuntimeError(f"YouTube uploader path does not exist: {uploader_path}")

        env = os.environ.copy()
        env["YOUTUBE_CLIENT_ID"] = context.settings.youtube_client_id or ""
        env["YOUTUBE_REFRESH_TOKEN"] = context.settings.youtube_refresh_token or ""
        if context.settings.youtube_client_secret:
            env["YOUTUBE_CLIENT_SECRET"] = context.settings.youtube_client_secret

        command = [
            sys.executable,
            "-m",
            "youtube_uploader",
            "upload",
            "--manifest",
            str(manifest_path),
            "--out",
            str(result_path),
            "--timeout-seconds",
            str(context.settings.youtube_upload_timeout_seconds),
        ]
        if dry_run:
            command.append("--dry-run")
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=uploader_path,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=context.settings.youtube_upload_timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError("YouTube upload timed out") from exc

        if process.returncode != 0:
            output = "\n".join(
                part.decode("utf-8", errors="replace").strip()
                for part in (stdout, stderr)
                if part
            )
            raise RuntimeError(f"YouTube uploader failed code={process.returncode}\n{output}")

    async def _attach_youtube_asset(
        self,
        context: AgentContext,
        episode_id: str,
        result: dict[str, Any],
    ) -> None:
        video_id = str(result.get("videoId") or "")
        url = str(result.get("youtubeUrl") or "")
        if not video_id or not url:
            raise RuntimeError("YouTube upload result is missing videoId or youtubeUrl")

        await context.episode_repo.create_asset(
            {
                "episode_id": episode_id,
                "asset_type": "youtube_video",
                "r2_key": f"youtube/videos/{video_id}",
                "public_url": url,
                "mime_type": "text/html",
                "size_bytes": None,
                "checksum_sha256": None,
                "metadata": {
                    "source": "youtube",
                    "video_id": video_id,
                    "privacy_status": result.get("privacyStatus"),
                    "thumbnail_uploaded": result.get("thumbnailUploaded"),
                    "thumbnail_error": result.get("thumbnailError"),
                },
            }
        )

    async def _complete_job(
        self,
        context: AgentContext,
        job: dict[str, Any],
        episode_id: str,
        result: dict[str, Any],
    ) -> None:
        await context.job_repo.update_job(
            job["id"],
            status=JobStatus.COMPLETED,
            current_step=None,
            metadata={
                **(job.get("metadata") or {}),
                "episode_id": episode_id,
                "youtube_video_id": result.get("videoId"),
                "youtube_url": result.get("youtubeUrl"),
            },
        )

    def _episode_id(self, job: dict[str, Any]) -> str | None:
        metadata = job.get("metadata") or {}
        episode_id = metadata.get("episode_id")
        return str(episode_id) if episode_id else None

    def _validate_settings(self, context: AgentContext) -> None:
        missing = [
            name
            for name in ("youtube_client_id", "youtube_refresh_token")
            if not getattr(context.settings, name)
        ]
        if missing:
            raise RuntimeError(f"Missing YouTube upload settings: {', '.join(missing)}")


def build_youtube_manifest(
    job: dict[str, Any],
    episode: dict[str, Any],
    script: dict[str, Any],
    video_path: Path,
    thumbnail_path: Path,
    context: AgentContext,
) -> dict[str, Any]:
    title = clean_title(episode.get("title") or script.get("title") or job["topic"])
    description = build_description(episode, script)
    tags = build_tags(job, episode, script)

    return {
        "version": 1,
        "videoPath": str(video_path),
        "thumbnailPath": str(thumbnail_path),
        "title": title,
        "description": description,
        "tags": tags,
        "categoryId": context.settings.youtube_default_category_id,
        "privacyStatus": context.settings.youtube_default_privacy_status,
        "selfDeclaredMadeForKids": context.settings.youtube_self_declared_made_for_kids,
        "embeddable": True,
        "license": "youtube",
        "publicStatsViewable": True,
        "notifySubscribers": context.settings.youtube_notify_subscribers,
        "thumbnailRequired": False,
        "language": episode.get("language") or job.get("language") or "en",
    }


def is_successful_upload_result(result: dict[str, Any]) -> bool:
    return bool(str(result.get("videoId") or "") and str(result.get("youtubeUrl") or ""))


def build_description(episode: dict[str, Any], script: dict[str, Any]) -> str:
    parts = [
        str(episode.get("description") or script.get("description") or "").strip(),
        str(episode.get("summary") or script.get("summary") or "").strip(),
        (
            "Generated by Pleopod: factual tech podcasts created with research, "
            "verification, and audio."
        ),
    ]
    claims = claim_texts(script.get("used_claims") or [])
    if claims:
        parts.append("Referenced claims:")
        for claim in claims[:8]:
            parts.append(f"- {claim}")

    return clean_text("\n\n".join(part for part in parts if part), max_bytes=5000)


def claim_texts(claims: Any) -> list[str]:
    if isinstance(claims, dict | str):
        candidates = [claims]
    elif isinstance(claims, list | tuple):
        candidates = claims
    else:
        return []

    texts: list[str] = []
    for claim in candidates:
        text: Any
        if isinstance(claim, dict):
            text = claim.get("claim") or claim.get("claim_text") or claim.get("text")
        else:
            text = claim
        cleaned = clean_text(str(text or ""), max_chars=500)
        if cleaned:
            texts.append(cleaned)
    return texts


def build_tags(job: dict[str, Any], episode: dict[str, Any], script: dict[str, Any]) -> list[str]:
    candidates = [
        "Pleopod",
        "Podcast",
        "Video Podcast",
        "Tech",
        "AI",
        episode.get("category"),
        job.get("category"),
        script.get("title"),
        episode.get("title"),
    ]
    tags: list[str] = []
    for value in candidates:
        for tag in split_tag_value(value):
            if tag and tag.lower() not in {item.lower() for item in tags}:
                tags.append(tag[:50])
    return tags[:20]


def split_tag_value(value: Any) -> list[str]:
    text = clean_text(str(value or ""), max_chars=80)
    if not text:
        return []
    if len(text) <= 30:
        return [text]
    return [word for word in text.replace(":", " ").split() if len(word) > 2]


def clean_title(value: Any) -> str:
    title = clean_text(str(value or ""), max_chars=100)
    if not title:
        raise ValueError("YouTube title cannot be empty")
    return title


def clean_text(value: str, max_chars: int | None = None, max_bytes: int | None = None) -> str:
    text = value.replace("<", "").replace(">", "").strip()
    if max_chars is not None:
        text = text[:max_chars].rstrip()
    if max_bytes is not None:
        encoded = text.encode("utf-8")
        if len(encoded) > max_bytes:
            text = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()
    return text
