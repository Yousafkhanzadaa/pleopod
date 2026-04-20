from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_RESEARCH_APPROVAL = "awaiting_research_approval"
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
    RESEARCH_REVIEW = "research_review"
    SCRIPT = "script"
    FACT_CHECK = "fact_check"
    THUMBNAIL = "thumbnail"
    AUDIO_CONFIG = "audio_config"
    AUDIO_GENERATION = "audio_generation"
    PUBLISH = "publish"


class ArtifactType(StrEnum):
    MEMORY_MD = "memory_md"
    RESEARCH_JSON = "research_json"
    SOURCES_JSON = "sources_json"
    CLAIM_BANK_JSON = "claim_bank_json"
    RESEARCH_REVIEW_MD = "research_review_md"
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
