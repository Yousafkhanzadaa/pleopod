from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from app.models.enums import ArtifactType


class JobStore(ABC):
    @abstractmethod
    async def create_job(
        self, payload: dict[str, Any], created_by: str | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_job(self, job_id: UUID | str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def update_job(self, job_id: UUID | str, **fields: Any) -> dict[str, Any] | None:
        raise NotImplementedError


class ArtifactStore(ABC):
    @abstractmethod
    async def create_artifact(
        self,
        artifact_type: str,
        r2_key: str,
        mime_type: str,
        job_id: UUID | str | None = None,
        episode_id: UUID | str | None = None,
        size_bytes: int | None = None,
        checksum_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_latest_for_job(
        self, job_id: UUID | str, artifact_type: ArtifactType | str
    ) -> dict[str, Any] | None:
        raise NotImplementedError


class KnowledgeStore(ABC):
    @abstractmethod
    async def replace_sources(self, job_id: UUID | str, sources: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def replace_claims(self, job_id: UUID | str, claims: list[dict[str, Any]]) -> None:
        raise NotImplementedError


class EpisodeStore(ABC):
    @abstractmethod
    async def create_episode(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class TTSSegmentStore(ABC):
    @abstractmethod
    async def get_completed_segment_key(
        self, job_id: UUID | str, index: int, transcript: str | None = None
    ) -> str | None:
        raise NotImplementedError

    @abstractmethod
    async def upsert_segment(
        self,
        job_id: UUID | str,
        index: int,
        transcript: str,
        status: str,
        r2_key: str | None = None,
    ) -> None:
        raise NotImplementedError


class QueueStore(ABC):
    @abstractmethod
    async def send(self, queue_name: str, message: dict[str, Any], delay_seconds: int = 0) -> int:
        raise NotImplementedError
