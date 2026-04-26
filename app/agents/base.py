from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.json_utils import extract_json
from app.db.repositories import ArtifactRepository, JobRepository
from app.models.enums import ArtifactType, PipelineStep
from app.providers.ai import AIProvider
from app.providers.storage import ObjectStorage
from app.services.artifacts import ArtifactService


@dataclass
class AgentResult:
    output_artifact_id: str | None = None
    stop_pipeline: bool = False
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentContract:
    name: str
    step: PipelineStep
    queue: str
    consumes: tuple[ArtifactType, ...] = ()
    produces: tuple[ArtifactType, ...] = ()
    triggers: tuple[PipelineStep, ...] = ()


@dataclass
class AgentContext:
    settings: Settings
    session: AsyncSession
    storage: ObjectStorage
    ai: AIProvider

    @property
    def artifact_repo(self) -> ArtifactRepository:
        return ArtifactRepository(self.session)

    @property
    def artifact_service(self) -> ArtifactService:
        return ArtifactService(self.storage, self.artifact_repo)

    @property
    def job_repo(self) -> JobRepository:
        return JobRepository(self.session)

    async def latest_artifact(self, job_id: str, artifact_type: ArtifactType) -> dict[str, Any]:
        artifact = await self.artifact_repo.get_latest_for_job(job_id, artifact_type)
        if not artifact:
            raise RuntimeError(f"Missing required artifact {artifact_type} for job {job_id}")
        return artifact

    async def latest_text(self, job_id: str, artifact_type: ArtifactType) -> str:
        artifact = await self.latest_artifact(job_id, artifact_type)
        return await self.storage.get_text(artifact["r2_key"])

    async def latest_json(self, job_id: str, artifact_type: ArtifactType) -> Any:
        return extract_json(await self.latest_text(job_id, artifact_type))


class PipelineAgent:
    name: str
    step: PipelineStep
    model_name: str | None = None

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        raise NotImplementedError
