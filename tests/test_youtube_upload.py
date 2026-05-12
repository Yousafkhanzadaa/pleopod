from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.youtube_upload import (
    YouTubeUploadAgent,
    build_description,
    build_youtube_manifest,
)
from app.models.enums import ArtifactType


class _Storage:
    async def get_bytes(self, key: str) -> bytes:
        if key.endswith(".mp4"):
            return b"video"
        return b"thumb"


class _ArtifactRepo:
    async def get_latest_for_job(self, job_id: str, artifact_type: str) -> None:
        return None


class _ArtifactService:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict]] = []

    async def put_json(
        self,
        key: str,
        data: dict,
        artifact_type: ArtifactType | str,
        job_id: str | None = None,
        episode_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        self.records.append((str(artifact_type), key, data))
        return {
            "id": f"{artifact_type}-id",
            "r2_key": key,
            "mime_type": "application/json",
            "metadata": metadata or {},
        }


class _JobRepo:
    def __init__(self) -> None:
        self.updated: dict | None = None

    async def update_job(self, job_id: str, **fields: object) -> dict:
        self.updated = {"job_id": job_id, **fields}
        return self.updated


class _Context:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            youtube_uploader_path=Path("youtube-uploader"),
            youtube_client_id="client-id",
            youtube_client_secret="client-secret",
            youtube_refresh_token="refresh-token",
            youtube_default_privacy_status="private",
            youtube_default_category_id="28",
            youtube_upload_timeout_seconds=30,
            youtube_notify_subscribers=False,
            youtube_self_declared_made_for_kids=False,
        )
        self.storage = _Storage()
        self.artifact_repo = _ArtifactRepo()
        self.artifact_service = _ArtifactService()
        self.job_repo = _JobRepo()
        self.session = object()

    async def latest_json(self, job_id: str, artifact_type: ArtifactType) -> dict:
        if artifact_type == ArtifactType.EPISODE_METADATA_JSON:
            return {"episode": _episode(), "script": _script()}
        raise AssertionError(f"Unexpected artifact type: {artifact_type}")

    async def latest_artifact(self, job_id: str, artifact_type: ArtifactType) -> dict:
        if artifact_type == ArtifactType.VIDEO_MP4:
            return {
                "id": "video-id",
                "r2_key": "episodes/episode-1/video/final.mp4",
                "mime_type": "video/mp4",
            }
        if artifact_type == ArtifactType.THUMBNAIL_IMAGE:
            return {
                "id": "thumb-id",
                "r2_key": "jobs/job-1/thumbnail/cover.png",
                "mime_type": "image/png",
            }
        raise AssertionError(f"Unexpected artifact type: {artifact_type}")


def _job() -> dict:
    return {
        "id": "job-1",
        "topic": "AI Pipelines",
        "category": "Tech",
        "language": "en",
        "metadata": {"episode_id": "episode-1"},
    }


def _episode() -> dict:
    return {
        "id": "episode-1",
        "title": "AI Pipelines",
        "summary": "A practical overview.",
        "description": "A long description.",
        "category": "Tech",
        "language": "en",
    }


def _script() -> dict:
    return {
        "title": "AI Pipelines",
        "summary": "Script summary",
        "description": "Script description",
        "used_claims": [{"claim": "Verification improves trust."}],
    }


def test_build_youtube_manifest_uses_episode_metadata() -> None:
    context = _Context()

    manifest = build_youtube_manifest(
        _job(),
        _episode(),
        _script(),
        Path("/tmp/final.mp4"),
        Path("/tmp/cover.png"),
        context,  # type: ignore[arg-type]
    )

    assert manifest["title"] == "AI Pipelines"
    assert manifest["videoPath"] == "/tmp/final.mp4"
    assert manifest["thumbnailPath"] == "/tmp/cover.png"
    assert manifest["privacyStatus"] == "private"
    assert manifest["categoryId"] == "28"
    assert "Verification improves trust." in manifest["description"]
    assert "Video Podcast" in manifest["tags"]


def test_build_description_accepts_schema_claim_strings() -> None:
    description = build_description(
        _episode(),
        {
            **_script(),
            "used_claims": [
                "Verification improves trust.",
                {"claim_text": "Structured claim text still works."},
            ],
        },
    )

    assert "Verification improves trust." in description
    assert "Structured claim text still works." in description


@pytest.mark.asyncio
async def test_youtube_upload_agent_writes_manifest_result_and_completes_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context()
    agent = YouTubeUploadAgent()
    attached: dict[str, object] = {}

    async def _run_uploader(self, context, manifest_path, result_path, dry_run=False) -> None:
        result_path.write_text(
            '{"videoId":"yt-123","youtubeUrl":"https://www.youtube.com/watch?v=yt-123",'
            '"privacyStatus":"private","thumbnailUploaded":true}',
            encoding="utf-8",
        )

    async def _attach_youtube_asset(self, context, episode_id, result) -> None:
        attached["episode_id"] = episode_id
        attached["video_id"] = result["videoId"]

    monkeypatch.setattr(YouTubeUploadAgent, "_run_uploader", _run_uploader)
    monkeypatch.setattr(YouTubeUploadAgent, "_attach_youtube_asset", _attach_youtube_asset)

    result = await agent.run(_job(), context, {})  # type: ignore[arg-type]

    assert result.stop_pipeline is True
    assert result.output_artifact_id == "youtube_upload_result_json-id"
    assert attached == {"episode_id": "episode-1", "video_id": "yt-123"}
    assert context.artifact_service.records[0][:2] == (
        ArtifactType.YOUTUBE_UPLOAD_MANIFEST_JSON,
        "jobs/job-1/youtube/upload_manifest.json",
    )
    assert context.artifact_service.records[1][:2] == (
        ArtifactType.YOUTUBE_UPLOAD_RESULT_JSON,
        "episodes/episode-1/youtube/upload_result.json",
    )
    assert context.job_repo.updated is not None
    assert context.job_repo.updated["status"] == "completed"
    assert context.job_repo.updated["metadata"]["youtube_video_id"] == "yt-123"
