from __future__ import annotations

from app.agents.audio_config import AudioConfigAgent
from app.agents.audio_generation import AudioGenerationAgent
from app.agents.base import PipelineAgent
from app.agents.fact_verifier import FactVerifierAgent
from app.agents.publisher import PublisherAgent
from app.agents.research import ResearchAgent
from app.agents.script_writer import ScriptWriterAgent
from app.agents.thumbnail import ThumbnailAgent
from app.agents.video_render import VideoRenderAgent
from app.agents.youtube_upload import YouTubeUploadAgent
from app.models.enums import PipelineStep

STEP_TO_QUEUE: dict[PipelineStep, str] = {
    PipelineStep.RESEARCH: "research_queue",
    PipelineStep.SCRIPT: "script_queue",
    PipelineStep.FACT_CHECK: "fact_check_queue",
    PipelineStep.THUMBNAIL: "thumbnail_queue",
    PipelineStep.AUDIO_CONFIG: "audio_config_queue",
    PipelineStep.AUDIO_GENERATION: "audio_generation_queue",
    PipelineStep.PUBLISH: "publish_queue",
    PipelineStep.VIDEO_RENDER: "video_render_queue",
    PipelineStep.YOUTUBE_UPLOAD: "youtube_upload_queue",
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
