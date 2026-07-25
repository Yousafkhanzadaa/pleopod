import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.agents.video_render as video_render_module
from app.agents.video_render import (
    VideoRenderAgent,
    build_video_payload,
    local_storage_root,
    renderable_payload,
    static_video_plan,
)
from app.models.enums import ArtifactType


class _Storage:
    def __init__(self) -> None:
        self.objects = {
            "jobs/job-1/audio/final.mp3": b"audio",
            "jobs/job-1/thumbnail/cover.png": b"thumbnail",
        }

    async def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        return f"/tmp/{key.split('/')[-1]}"

    async def get_bytes(self, key: str) -> bytes:
        return self.objects[key]


class _ArtifactRepo:
    async def get_latest_for_job(self, job_id: str, artifact_type: str) -> None:
        return None


class _ArtifactService:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    async def put_json(
        self,
        key: str,
        data: dict,
        artifact_type: ArtifactType | str,
        job_id: str | None = None,
        episode_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        self.records.append((str(artifact_type), key))
        return {
            "id": f"{artifact_type}-id",
            "r2_key": key,
            "mime_type": "application/json",
            "metadata": metadata or {},
        }

    async def put_text(
        self,
        key: str,
        text: str,
        artifact_type: ArtifactType | str,
        mime_type: str = "text/plain; charset=utf-8",
        job_id: str | None = None,
        episode_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        self.records.append((str(artifact_type), key))
        return {
            "id": f"{artifact_type}-id",
            "r2_key": key,
            "mime_type": mime_type,
            "metadata": metadata or {},
        }

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        artifact_type: ArtifactType | str,
        mime_type: str,
        job_id: str | None = None,
        episode_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        self.records.append((str(artifact_type), key))
        return {
            "id": f"{artifact_type}-id",
            "r2_key": key,
            "mime_type": mime_type,
            "size_bytes": len(data),
            "checksum_sha256": "checksum",
            "metadata": metadata or {},
        }


class _JobRepo:
    def __init__(self) -> None:
        self.updated: dict | None = None

    async def update_job(self, job_id: str, **fields: object) -> dict:
        self.updated = {"job_id": job_id, **fields}
        return self.updated


class _Context:
    def __init__(
        self,
        local_storage_path: Path = Path("/tmp"),
        *,
        storage_backend: str = "local",
        temporary_storage_path: Path | None = None,
        enable_video_rendering: bool = True,
        enable_youtube_uploading: bool = False,
    ) -> None:
        self.settings = SimpleNamespace(
            gemini_api_key=None,
            remotion_render_output_format="mp4",
            remotion_renderer_path="remotion-renderer",
            remotion_video_director_model="gemini-2.5-flash-lite",
            remotion_render_timeout_seconds=30,
            enable_video_rendering=enable_video_rendering,
            enable_youtube_uploading=enable_youtube_uploading,
            r2_public_base_url=None,
            storage_backend=storage_backend,
            local_storage_path=local_storage_path,
            temporary_storage_path=temporary_storage_path or local_storage_path,
        )
        self.storage = _Storage()
        self.artifact_repo = _ArtifactRepo()
        self.artifact_service = _ArtifactService()
        self.job_repo = _JobRepo()
        self.session = object()

    async def latest_json(self, job_id: str, artifact_type: ArtifactType) -> dict:
        if artifact_type == ArtifactType.VERIFIED_SCRIPT_JSON:
            return _script()
        if artifact_type == ArtifactType.EPISODE_METADATA_JSON:
            return {"episode": _episode()}
        raise AssertionError(f"Unexpected artifact type: {artifact_type}")

    async def latest_artifact(self, job_id: str, artifact_type: ArtifactType) -> dict:
        if artifact_type == ArtifactType.FINAL_AUDIO:
            return {"id": "audio-id", "r2_key": "jobs/job-1/audio/final.mp3"}
        if artifact_type == ArtifactType.THUMBNAIL_IMAGE:
            return {"id": "thumb-id", "r2_key": "jobs/job-1/thumbnail/cover.png"}
        raise AssertionError(f"Unexpected artifact type: {artifact_type}")


def _job() -> dict:
    return {
        "id": "job-1",
        "topic": "AI Pipelines",
        "category": "Tech",
        "language": "en",
        "target_duration_seconds": 600,
        "metadata": {"episode_id": "episode-1"},
    }


def _script() -> dict:
    return {
        "title": "AI Pipelines",
        "summary": "Short summary",
        "description": "Long description",
        "speakers": [
            {
                "name": "Arman",
                "role": "Presenter",
                "voice_name": "Algenib",
                "style": "low-pitched and authoritative",
            },
        ],
        "transcript": "Arman: Welcome.\nArman: Let's unpack it.",
    }


def _episode() -> dict:
    return {
        "id": "episode-1",
        "title": "AI Pipelines",
        "summary": "Episode summary",
        "description": "Episode description",
        "category": "Tech",
        "language": "en",
        "duration_seconds": None,
    }


@pytest.mark.asyncio
async def test_build_video_payload_uses_public_asset_urls_and_script_speakers() -> None:
    context = _Context()

    payload = await build_video_payload(
        _job(),
        _script(),
        _episode(),
        {"r2_key": "jobs/job-1/audio/final.mp3"},
        {"r2_key": "jobs/job-1/thumbnail/cover.png"},
        context,  # type: ignore[arg-type]
    )

    assert payload["episodeId"] == "episode-1"
    assert payload["durationSeconds"] == 90
    assert payload["audioUrl"] == "file:///tmp/final.mp3"
    assert payload["thumbnailUrl"] == "file:///tmp/cover.png"
    assert payload["speakers"][0]["voiceName"] == "Algenib"


@pytest.mark.asyncio
async def test_build_video_payload_uses_audio_duration_with_tail_pad() -> None:
    context = _Context()

    payload = await build_video_payload(
        _job(),
        _script(),
        _episode(),
        {
            "r2_key": "jobs/job-1/audio/final.mp3",
            "mime_type": "audio/mpeg",
            "metadata": {"duration_seconds": 61.2},
        },
        {"r2_key": "jobs/job-1/thumbnail/cover.png"},
        context,  # type: ignore[arg-type]
    )

    assert payload["audioDurationSeconds"] == 61.2
    assert payload["durationSeconds"] == 63
    assert payload["format"]["platform"] == "youtube"
    assert payload["format"]["aspectRatio"] == "16:9"


@pytest.mark.asyncio
async def test_build_video_payload_includes_audio_segment_line_timings() -> None:
    context = _Context()

    payload = await build_video_payload(
        _job(),
        _script(),
        _episode(),
        {
            "r2_key": "jobs/job-1/audio/final.mp3",
            "mime_type": "audio/mpeg",
            "metadata": {
                "duration_seconds": 10,
                "segment_timings": [
                    {
                        "index": 1,
                        "start_seconds": 0,
                        "end_seconds": 10,
                        "source_transcript": "Arman: Welcome.\nArman: Let's unpack it.",
                    }
                ],
            },
        },
        {"r2_key": "jobs/job-1/thumbnail/cover.png"},
        context,  # type: ignore[arg-type]
    )

    assert payload["lineTimings"] == [
        {
            "id": "line_001",
            "speaker": "Arman",
            "text": "Welcome.",
            "startSeconds": 0.0,
            "endSeconds": 5.0,
        },
        {
            "id": "line_002",
            "speaker": "Arman",
            "text": "Let's unpack it.",
            "startSeconds": 5.0,
            "endSeconds": 10.0,
        },
    ]


def test_renderable_payload_rewrites_local_assets_to_http_urls() -> None:
    payload = {
        "audioUrl": "file:///tmp/final.mp3",
        "thumbnailUrl": "file:///tmp/cover.png",
        "title": "AI Pipelines",
    }

    rendered = renderable_payload(
        payload,
        audio_key="jobs/job-1/audio/final.mp3",
        thumbnail_key="jobs/job-1/thumbnail/cover image.png",
        local_asset_base_url="http://127.0.0.1:51234",
    )

    assert rendered["audioUrl"] == "http://127.0.0.1:51234/jobs/job-1/audio/final.mp3"
    assert (
        rendered["thumbnailUrl"]
        == "http://127.0.0.1:51234/jobs/job-1/thumbnail/cover%20image.png"
    )
    assert payload["thumbnailUrl"] == "file:///tmp/cover.png"


def test_static_video_plan_describes_thumbnail_render() -> None:
    plan = static_video_plan(
        {
            "durationSeconds": 120,
            "audioUrl": "file:///tmp/final.mp3",
            "thumbnailUrl": "file:///tmp/cover.png",
        }
    )

    assert plan["renderMode"] == "static_thumbnail"
    assert plan["format"]["width"] == 1280
    assert plan["format"]["height"] == 720
    assert plan["format"]["fps"] == 30
    assert plan["source"]["audioUrl"] == "file:///tmp/final.mp3"


@pytest.mark.asyncio
async def test_static_video_command_uses_payload_duration_without_shortest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _Context(tmp_path)
    agent = VideoRenderAgent()
    captured: dict[str, list[str]] = {}

    async def _run_ffmpeg_command(self, context, command) -> None:
        captured["command"] = command

    monkeypatch.setattr(VideoRenderAgent, "_run_ffmpeg_command", _run_ffmpeg_command)

    await agent._run_static_video(
        context,  # type: ignore[arg-type]
        {"r2_key": "jobs/job-1/audio/final.mp3"},
        {"r2_key": "jobs/job-1/thumbnail/cover.png"},
        tmp_path / "final.mp4",
        tmp_path,
        duration_seconds=59,
    )

    command = captured["command"]
    assert command[command.index("-framerate") + 1] == "30"
    assert "-shortest" not in command
    assert command[command.index("-t") + 1] == "59"


@pytest.mark.asyncio
async def test_static_video_has_clear_error_when_ffmpeg_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = VideoRenderAgent()
    monkeypatch.setattr(video_render_module.shutil, "which", lambda command: None)

    with pytest.raises(RuntimeError, match="ffmpeg is required"):
        await agent._run_ffmpeg_command(_Context(), ["ffmpeg", "-version"])  # type: ignore[arg-type]


def test_local_storage_root_uses_temporary_path_for_temporary_backend(tmp_path: Path) -> None:
    context = _Context(
        Path("/tmp/local-artifacts"),
        storage_backend="temporary",
        temporary_storage_path=tmp_path / "temporary-artifacts",
    )

    assert local_storage_root(context) == (tmp_path / "temporary-artifacts").resolve()


@pytest.mark.asyncio
async def test_video_render_agent_renders_presentation_and_completes_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _Context(tmp_path)
    agent = VideoRenderAgent()
    attached: dict[str, object] = {}
    render_props: dict[str, object] = {}
    scene_plan = {
        "version": 1,
        "director_model": "test",
        "duration_seconds": 90,
        "line_timings": [],
        "scenes": [
            {"id": "s", "start_seconds": 0, "end_seconds": 90, "layout": "title", "headline": "Hi"}
        ],
        "production_notes": [],
    }

    async def _build_scene_plan(
        self,
        context,
        job,
        script,
        audio,
        *,
        duration_seconds,
        reuse_existing=False,
    ) -> dict:
        render_props["scene_plan_duration"] = duration_seconds
        render_props["reuse_existing"] = reuse_existing
        return scene_plan

    async def _run_render(
        self, context, props_path, output_path, *, composition="PresentationEpisode"
    ) -> None:
        render_props.update(json.loads(props_path.read_text(encoding="utf-8")))
        render_props["composition"] = composition
        output_path.write_bytes(b"video")

    async def _attach_video_asset(self, context, episode_id, video_artifact) -> None:
        attached["episode_id"] = episode_id
        attached["r2_key"] = video_artifact["r2_key"]

    @contextmanager
    def _local_asset_server(context):
        yield "http://127.0.0.1:51234"

    monkeypatch.setattr(VideoRenderAgent, "_build_scene_plan", _build_scene_plan)
    monkeypatch.setattr(VideoRenderAgent, "_run_render", _run_render)
    monkeypatch.setattr(VideoRenderAgent, "_attach_video_asset", _attach_video_asset)
    monkeypatch.setattr(video_render_module, "local_asset_server", _local_asset_server)

    result = await agent.run(_job(), context, {})  # type: ignore[arg-type]

    assert result.stop_pipeline is True
    assert result.output_artifact_id == "video_mp4-id"
    assert render_props["composition"] == "PresentationEpisode"
    assert render_props["scene_plan_duration"] == 90
    assert render_props["scenePlan"]["scenes"][0]["layout"] == "title"  # type: ignore[index]
    assert render_props["audioUrl"] == "http://127.0.0.1:51234/jobs/job-1/audio/final.mp3"
    assert (
        render_props["thumbnailUrl"]
        == "http://127.0.0.1:51234/jobs/job-1/thumbnail/cover.png"
    )
    assert attached["episode_id"] == "episode-1"
    assert (
        ArtifactType.SCENE_PLAN_JSON,
        "jobs/job-1/video/scene_plan.json",
    ) in context.artifact_service.records
    assert (
        ArtifactType.VIDEO_PLAN_JSON,
        "jobs/job-1/video/video_plan.json",
    ) in context.artifact_service.records
    assert (
        ArtifactType.VIDEO_MP4,
        "episodes/episode-1/video/final.mp4",
    ) in context.artifact_service.records
    assert context.job_repo.updated is not None
    assert context.job_repo.updated["status"] == "completed"


@pytest.mark.asyncio
async def test_video_render_agent_uses_motion_caption_video_when_remotion_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _Context(
        tmp_path,
        enable_video_rendering=False,
        enable_youtube_uploading=True,
    )
    agent = VideoRenderAgent()
    calls: dict[str, object] = {}

    async def _run_director(self, context, props_path, plan_path) -> None:
        raise AssertionError("Remotion director should not run for the ffmpeg renderer")

    async def _run_render(self, context, props_path, plan_path, output_path) -> None:
        raise AssertionError("Remotion render should not run for the ffmpeg renderer")

    async def _run_motion_caption_video(
        self,
        context,
        payload,
        audio,
        thumbnail,
        output_path,
        temp_path,
        *,
        props_path,
        plan_path,
    ) -> str:
        calls["duration_seconds"] = int(payload["durationSeconds"])
        props_path.write_text("{}", encoding="utf-8")
        plan_path.write_text('{"renderMode":"motion_caption"}', encoding="utf-8")
        output_path.write_bytes(b"motion-video")
        return "motion_caption"

    async def _attach_video_asset(self, context, episode_id, video_artifact) -> None:
        calls["attached_episode_id"] = episode_id
        calls["attached_render_mode"] = video_artifact["metadata"]["render_mode"]

    monkeypatch.setattr(VideoRenderAgent, "_run_director", _run_director)
    monkeypatch.setattr(VideoRenderAgent, "_run_render", _run_render)
    monkeypatch.setattr(VideoRenderAgent, "_run_motion_caption_video", _run_motion_caption_video)
    monkeypatch.setattr(VideoRenderAgent, "_attach_video_asset", _attach_video_asset)

    result = await agent.run(_job(), context, {})  # type: ignore[arg-type]

    assert result.stop_pipeline is False
    assert result.output_artifact_id == "video_mp4-id"
    assert calls["duration_seconds"] == 90
    assert calls["attached_render_mode"] == "motion_caption"
    assert calls["attached_episode_id"] == "episode-1"
    assert (
        ArtifactType.VIDEO_MP4,
        "episodes/episode-1/video/final.mp4",
    ) in context.artifact_service.records
    assert context.job_repo.updated is not None
    assert context.job_repo.updated["metadata"]["video_artifact_id"] == "video_mp4-id"


@pytest.mark.asyncio
async def test_run_motion_caption_video_falls_back_to_static_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _Context(tmp_path, enable_video_rendering=False, enable_youtube_uploading=True)
    context.settings.video_waveform = True
    context.settings.video_caption_max_words = 3
    context.settings.video_caption_font_name = "DejaVu Sans"
    context.settings.video_caption_font_path = None
    agent = VideoRenderAgent()

    monkeypatch.setattr(video_render_module, "motion_background_supported", lambda: True)
    monkeypatch.setattr(video_render_module, "captions_supported", lambda: False)
    monkeypatch.setattr(video_render_module.shutil, "which", lambda command: "/usr/bin/ffmpeg")

    async def _boom(self, context, command) -> None:
        raise RuntimeError("ffmpeg motion render failed")

    static_calls: dict[str, object] = {}

    async def _run_static_video(
        self, context, audio, thumbnail, output_path, temp_path, duration_seconds
    ) -> None:
        static_calls["duration_seconds"] = duration_seconds
        output_path.write_bytes(b"static-fallback")

    monkeypatch.setattr(VideoRenderAgent, "_run_ffmpeg_command", _boom)
    monkeypatch.setattr(VideoRenderAgent, "_run_static_video", _run_static_video)

    payload = {
        "jobId": "job-1",
        "title": "AI Pipelines",
        "durationSeconds": 90,
        "format": {"width": 1920, "height": 1080, "fps": 30},
        "brand": {"name": "Pleopod", "accentColor": "#22d3ee"},
        "lineTimings": [
            {
                "id": "l1",
                "speaker": "Arman",
                "text": "Welcome to the show",
                "startSeconds": 0.0,
                "endSeconds": 2.0,
            }
        ],
    }
    props_path = tmp_path / "props.json"
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "final.mp4"

    mode = await agent._run_motion_caption_video(
        context,  # type: ignore[arg-type]
        payload,
        {"r2_key": "jobs/job-1/audio/final.mp3"},
        {"r2_key": "jobs/job-1/thumbnail/cover.png"},
        output_path,
        tmp_path,
        props_path=props_path,
        plan_path=plan_path,
    )

    assert mode == "static_thumbnail"
    assert static_calls["duration_seconds"] == 90
    assert output_path.read_bytes() == b"static-fallback"
    assert json.loads(plan_path.read_text())["renderMode"] == "static_thumbnail"
