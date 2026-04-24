from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_SCRIPT_APPROVAL = "awaiting_script_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class EpisodeStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AgentStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineStep(StrEnum):
    RESEARCH = "research"
    SCRIPT = "script"
    FACT_CHECK = "fact_check"
    THUMBNAIL = "thumbnail"
    AUDIO_CONFIG = "audio_config"
    AUDIO_GENERATION = "audio_generation"
    PUBLISH = "publish"
    VIDEO_RENDER = "video_render"


class ArtifactType(StrEnum):
    MEMORY_MD = "memory_md"
    RESEARCH_JSON = "research_json"
    SOURCES_JSON = "sources_json"
    CLAIM_BANK_JSON = "claim_bank_json"
    SCRIPT_JSON = "script_json"
    SCRIPT_MD = "script_md"
    VERIFIED_SCRIPT_JSON = "verified_script_json"
    VERIFICATION_REPORT_MD = "verification_report_md"
    THUMBNAIL_IMAGE = "thumbnail_image"
    THUMBNAIL_PROMPT = "thumbnail_prompt"
    TTS_CONFIG_JSON = "tts_config_json"
    AUDIO_SEGMENT = "audio_segment"
    FINAL_AUDIO = "final_audio"
    EPISODE_METADATA_JSON = "episode_metadata_json"
    VIDEO_PAYLOAD_JSON = "video_payload_json"
    VIDEO_PLAN_JSON = "video_plan_json"
    VIDEO_MP4 = "video_mp4"
