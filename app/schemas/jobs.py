from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator


class GenerationJobRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    topic: str | None = Field(default=None, min_length=3, max_length=300)
    category: str | None = Field(default=None, max_length=80)
    audience: str | None = Field(default=None, max_length=200)
    target_duration_seconds: int | None = Field(default=None, ge=120, le=3600)
    language: str | None = Field(default=None, max_length=16)
    tone: str | None = Field(default=None, max_length=200)
    source_urls: list[HttpUrl] = Field(default_factory=list, max_length=20)
    auto_publish: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_title_or_topic(self) -> "GenerationJobRequest":
        if not self.title and not self.topic:
            raise ValueError("Either title or topic is required")
        return self

    @property
    def requested_title(self) -> str:
        return (self.title or self.topic or "").strip()


class OrchestratedJobPayload(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    category: str = Field(default="Tech", max_length=80)
    audience: str = Field(default="curious tech listeners", max_length=200)
    target_duration_seconds: int = Field(default=600, ge=120, le=3600)
    language: str = Field(default="en", max_length=16)
    tone: str = Field(default="clear, smart, conversational", max_length=200)
    source_urls: list[HttpUrl] = Field(default_factory=list, max_length=20)


class GenerationJobCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    category: str = Field(default="Tech", max_length=80)
    audience: str = Field(default="curious tech listeners", max_length=200)
    target_duration_seconds: int = Field(default=600, ge=120, le=3600)
    language: str = Field(default="en", max_length=16)
    tone: str = Field(default="clear, smart, conversational", max_length=200)
    source_urls: list[HttpUrl] = Field(default_factory=list, max_length=20)
    auto_publish: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationJobResponse(BaseModel):
    id: UUID
    topic: str
    category: str
    audience: str
    target_duration_seconds: int
    language: str
    tone: str
    status: str
    current_step: str | None
    auto_publish: bool
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AgentRunResponse(BaseModel):
    id: UUID
    job_id: UUID
    agent_name: str
    step: str
    status: str
    model: str | None
    error: str | None
    started_at: datetime
    completed_at: datetime | None


class ArtifactResponse(BaseModel):
    id: UUID
    job_id: UUID | None = None
    episode_id: UUID | None = None
    artifact_type: str
    r2_key: str
    mime_type: str
    size_bytes: int | None
    checksum_sha256: str | None
    created_at: datetime


class JobDetailResponse(GenerationJobResponse):
    agent_runs: list[AgentRunResponse] = Field(default_factory=list)
    artifacts: list[ArtifactResponse] = Field(default_factory=list)


class JobApprovalRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
