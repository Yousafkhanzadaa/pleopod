from app.core.config import Settings
from app.models.enums import JobStatus, PipelineStep
from app.worker.pipeline import AGENTS, STEP_TO_QUEUE
from app.worker.runner import (
    active_queue_names,
    is_transient_database_disconnect,
    should_skip_job_message,
)


def test_should_skip_job_message_for_completed_job() -> None:
    assert should_skip_job_message(
        {"status": JobStatus.COMPLETED, "current_step": None},
        PipelineStep.AUDIO_GENERATION,
    )


def test_should_skip_job_message_for_stale_advanced_step() -> None:
    assert should_skip_job_message(
        {"status": JobStatus.QUEUED, "current_step": PipelineStep.PUBLISH},
        PipelineStep.AUDIO_GENERATION,
    )


def test_should_not_skip_job_message_for_initial_research_step() -> None:
    assert not should_skip_job_message(
        {"status": JobStatus.QUEUED, "current_step": None},
        PipelineStep.RESEARCH,
    )


def test_should_not_skip_job_message_for_active_matching_step() -> None:
    assert not should_skip_job_message(
        {"status": JobStatus.RUNNING, "current_step": PipelineStep.AUDIO_GENERATION},
        PipelineStep.AUDIO_GENERATION,
    )


def test_should_not_skip_job_message_for_retired_step_value() -> None:
    assert not should_skip_job_message(
        {"status": JobStatus.QUEUED, "current_step": "research_review"},
        PipelineStep.SCRIPT,
    )


def test_video_render_step_is_registered() -> None:
    assert STEP_TO_QUEUE[PipelineStep.VIDEO_RENDER] == "video_render_queue"
    assert AGENTS[PipelineStep.VIDEO_RENDER].name == "video_render_agent"
    assert STEP_TO_QUEUE[PipelineStep.YOUTUBE_UPLOAD] == "youtube_upload_queue"
    assert AGENTS[PipelineStep.YOUTUBE_UPLOAD].name == "youtube_upload_agent"


def test_video_render_queue_is_not_polled_until_enabled() -> None:
    settings = Settings(_env_file=None, enable_video_rendering=False)  # type: ignore[call-arg]

    assert "video_render_queue" not in active_queue_names(settings)
    assert "youtube_upload_queue" not in active_queue_names(settings)


def test_video_render_queue_is_polled_when_enabled() -> None:
    settings = Settings(_env_file=None, enable_video_rendering=True)  # type: ignore[call-arg]

    assert "video_render_queue" in active_queue_names(settings)
    assert "youtube_upload_queue" not in active_queue_names(settings)


def test_youtube_upload_queue_polls_video_and_upload_steps_when_enabled() -> None:
    settings = Settings(_env_file=None, enable_youtube_uploading=True)  # type: ignore[call-arg]

    assert "video_render_queue" in active_queue_names(settings)
    assert "youtube_upload_queue" in active_queue_names(settings)


def test_transient_database_disconnect_detection_matches_asyncpg_reset() -> None:
    exc = Exception("ConnectionDoesNotExistError: connection was closed in the middle of operation")

    assert is_transient_database_disconnect(exc)


def test_transient_database_disconnect_detection_matches_statement_timeout() -> None:
    exc = Exception("QueryCanceledError: canceling statement due to statement timeout")

    assert is_transient_database_disconnect(exc)


def test_transient_database_disconnect_detection_rejects_unrelated_error() -> None:
    assert not is_transient_database_disconnect(ValueError("bad queue payload"))
