from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.json_utils import to_pretty_json
from app.db.interfaces import ArtifactStore
from app.models.enums import ArtifactType
from app.providers.storage import ObjectStorage, StoredObject


class ArtifactService:
    def __init__(self, storage: ObjectStorage, repo: ArtifactStore):
        self.storage = storage
        self.repo = repo

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        artifact_type: ArtifactType | str,
        mime_type: str,
        job_id: UUID | str | None = None,
        episode_id: UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stored = await self.storage.put_bytes(key=key, data=data, mime_type=mime_type)
        return await self._record(stored, artifact_type, job_id, episode_id, metadata)

    async def put_text(
        self,
        key: str,
        text: str,
        artifact_type: ArtifactType | str,
        mime_type: str = "text/plain; charset=utf-8",
        job_id: UUID | str | None = None,
        episode_id: UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stored = await self.storage.put_text(key=key, text=text, mime_type=mime_type)
        return await self._record(stored, artifact_type, job_id, episode_id, metadata)

    async def put_json(
        self,
        key: str,
        data: Any,
        artifact_type: ArtifactType | str,
        job_id: UUID | str | None = None,
        episode_id: UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.put_text(
            key=key,
            text=to_pretty_json(data),
            artifact_type=artifact_type,
            mime_type="application/json",
            job_id=job_id,
            episode_id=episode_id,
            metadata=metadata,
        )

    async def _record(
        self,
        stored: StoredObject,
        artifact_type: ArtifactType | str,
        job_id: UUID | str | None,
        episode_id: UUID | str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return await self.repo.create_artifact(
            job_id=job_id,
            episode_id=episode_id,
            artifact_type=str(artifact_type),
            r2_key=stored.key,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            metadata=metadata or {},
        )
