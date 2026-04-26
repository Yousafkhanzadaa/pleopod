from __future__ import annotations

from app.agents.audio_config import AudioConfigAgent
from app.agents.audio_generation import AudioGenerationAgent
from app.agents.base import AgentContract, AgentResult, PipelineAgent
from app.agents.fact_verifier import FactVerifierAgent
from app.agents.publisher import PublisherAgent
from app.agents.research import ResearchAgent
from app.agents.script_writer import ScriptWriterAgent
from app.agents.thumbnail import ThumbnailAgent
from app.agents.video_render import VideoRenderAgent
from app.agents.youtube_upload import YouTubeUploadAgent
from app.models.enums import ArtifactType, PipelineStep

AGENT_CONTRACTS: dict[PipelineStep, AgentContract] = {
    PipelineStep.RESEARCH: AgentContract(
        name="research_agent",
        step=PipelineStep.RESEARCH,
        queue="research_queue",
        produces=(
            ArtifactType.MEMORY_MD,
            ArtifactType.RESEARCH_JSON,
            ArtifactType.SOURCES_JSON,
            ArtifactType.CLAIM_BANK_JSON,
        ),
        triggers=(PipelineStep.SCRIPT,),
    ),
    PipelineStep.SCRIPT: AgentContract(
        name="script_writer_agent",
        step=PipelineStep.SCRIPT,
        queue="script_queue",
        consumes=(ArtifactType.MEMORY_MD, ArtifactType.CLAIM_BANK_JSON),
        produces=(ArtifactType.SCRIPT_MD, ArtifactType.SCRIPT_JSON),
        triggers=(PipelineStep.FACT_CHECK,),
    ),
    PipelineStep.FACT_CHECK: AgentContract(
        name="fact_verifier_agent",
        step=PipelineStep.FACT_CHECK,
        queue="fact_check_queue",
        consumes=(ArtifactType.SCRIPT_JSON, ArtifactType.CLAIM_BANK_JSON),
        produces=(ArtifactType.VERIFICATION_REPORT_MD, ArtifactType.VERIFIED_SCRIPT_JSON),
        triggers=(PipelineStep.THUMBNAIL,),
    ),
    PipelineStep.THUMBNAIL: AgentContract(
        name="thumbnail_agent",
        step=PipelineStep.THUMBNAIL,
        queue="thumbnail_queue",
        consumes=(ArtifactType.VERIFIED_SCRIPT_JSON,),
        produces=(ArtifactType.THUMBNAIL_PROMPT, ArtifactType.THUMBNAIL_IMAGE),
        triggers=(PipelineStep.AUDIO_CONFIG,),
    ),
    PipelineStep.AUDIO_CONFIG: AgentContract(
        name="audio_config_agent",
        step=PipelineStep.AUDIO_CONFIG,
        queue="audio_config_queue",
        consumes=(ArtifactType.VERIFIED_SCRIPT_JSON,),
        produces=(ArtifactType.TTS_CONFIG_JSON,),
        triggers=(PipelineStep.AUDIO_GENERATION,),
    ),
    PipelineStep.AUDIO_GENERATION: AgentContract(
        name="audio_generation_agent",
        step=PipelineStep.AUDIO_GENERATION,
        queue="audio_generation_queue",
        consumes=(ArtifactType.TTS_CONFIG_JSON,),
        produces=(ArtifactType.AUDIO_SEGMENT, ArtifactType.FINAL_AUDIO),
        triggers=(PipelineStep.PUBLISH,),
    ),
    PipelineStep.PUBLISH: AgentContract(
        name="publisher_agent",
        step=PipelineStep.PUBLISH,
        queue="publish_queue",
        consumes=(
            ArtifactType.VERIFIED_SCRIPT_JSON,
            ArtifactType.FINAL_AUDIO,
            ArtifactType.THUMBNAIL_IMAGE,
        ),
        produces=(ArtifactType.EPISODE_METADATA_JSON,),
        triggers=(PipelineStep.VIDEO_RENDER,),
    ),
    PipelineStep.VIDEO_RENDER: AgentContract(
        name="video_render_agent",
        step=PipelineStep.VIDEO_RENDER,
        queue="video_render_queue",
        consumes=(
            ArtifactType.EPISODE_METADATA_JSON,
            ArtifactType.FINAL_AUDIO,
            ArtifactType.THUMBNAIL_IMAGE,
        ),
        produces=(
            ArtifactType.VIDEO_PAYLOAD_JSON,
            ArtifactType.VIDEO_PLAN_JSON,
            ArtifactType.VIDEO_MP4,
        ),
        triggers=(PipelineStep.YOUTUBE_UPLOAD,),
    ),
    PipelineStep.YOUTUBE_UPLOAD: AgentContract(
        name="youtube_upload_agent",
        step=PipelineStep.YOUTUBE_UPLOAD,
        queue="youtube_upload_queue",
        consumes=(
            ArtifactType.EPISODE_METADATA_JSON,
            ArtifactType.VIDEO_MP4,
            ArtifactType.THUMBNAIL_IMAGE,
        ),
        produces=(
            ArtifactType.YOUTUBE_UPLOAD_MANIFEST_JSON,
            ArtifactType.YOUTUBE_UPLOAD_RESULT_JSON,
        ),
    ),
}

STEP_TO_QUEUE: dict[PipelineStep, str] = {
    step: contract.queue for step, contract in AGENT_CONTRACTS.items()
}
QUEUE_TO_STEP = {queue: step for step, queue in STEP_TO_QUEUE.items()}

AGENTS: dict[PipelineStep, PipelineAgent] = {
    PipelineStep.RESEARCH: ResearchAgent(),
    PipelineStep.SCRIPT: ScriptWriterAgent(),
    PipelineStep.FACT_CHECK: FactVerifierAgent(),
    PipelineStep.THUMBNAIL: ThumbnailAgent(),
    PipelineStep.AUDIO_CONFIG: AudioConfigAgent(),
    PipelineStep.AUDIO_GENERATION: AudioGenerationAgent(),
    PipelineStep.PUBLISH: PublisherAgent(),
    PipelineStep.VIDEO_RENDER: VideoRenderAgent(),
    PipelineStep.YOUTUBE_UPLOAD: YouTubeUploadAgent(),
}


def enabled_step(step: PipelineStep, settings: object) -> bool:
    if step == PipelineStep.VIDEO_RENDER:
        return bool(
            getattr(settings, "enable_video_rendering", False)
            or getattr(settings, "enable_youtube_uploading", False)
        )
    if step == PipelineStep.YOUTUBE_UPLOAD:
        return bool(getattr(settings, "enable_youtube_uploading", False))
    return True


def next_steps_for_result(
    step: PipelineStep,
    result: AgentResult,
    settings: object,
) -> tuple[PipelineStep, ...]:
    if result.stop_pipeline:
        return ()
    contract = AGENT_CONTRACTS[step]
    return tuple(
        next_step for next_step in contract.triggers if enabled_step(next_step, settings)
    )


def validate_agent_graph() -> None:
    missing_agents = set(AGENT_CONTRACTS) - set(AGENTS)
    if missing_agents:
        raise RuntimeError(f"Missing agent implementations: {sorted(missing_agents)}")

    for step, agent in AGENTS.items():
        contract = AGENT_CONTRACTS[step]
        if agent.name != contract.name or agent.step != contract.step:
            raise RuntimeError(
                f"Agent implementation does not match contract for {step}: "
                f"{agent.name}/{agent.step}"
            )
        for next_step in contract.triggers:
            if next_step not in AGENT_CONTRACTS:
                raise RuntimeError(f"{step} triggers unknown step {next_step}")


validate_agent_graph()
