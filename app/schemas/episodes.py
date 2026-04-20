from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EpisodeAssetResponse(BaseModel):
    id: UUID
    asset_type: str
    public_url: str | None
    r2_key: str
    mime_type: str


class EpisodeResponse(BaseModel):
    id: UUID
    title: str
    slug: str
    category: str
    status: str
    summary: str | None = None
    description: str | None = None
    duration_seconds: int | None = None
    language: str = "en"
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    assets: list[EpisodeAssetResponse] = Field(default_factory=list)


class StreamUrlResponse(BaseModel):
    episode_id: UUID
    audio_url: str
    expires_in_seconds: int | None = None
