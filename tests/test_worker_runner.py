from app.models.enums import JobStatus, PipelineStep
from app.worker.runner import should_skip_job_message


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
