from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestration import orchestrate_generation_job
from app.api.deps import admin_dep, db_session_dep, settings_dep
from app.core.config import Settings
from app.db.queue import QueueRepository
from app.db.repositories import ArtifactRepository, JobRepository
from app.models.enums import ArtifactType, JobStatus, PipelineStep
from app.providers.factory import create_ai_provider
from app.schemas.jobs import (
    GenerationJobRequest,
    GenerationJobResponse,
    JobApprovalRequest,
    JobDetailResponse,
)
from app.worker.pipeline import STEP_TO_QUEUE

router = APIRouter(prefix="/admin/generation-jobs", tags=["admin-generation-jobs"])


def _created_by_from_admin_context(admin_context: dict) -> str:
    claims = admin_context.get("claims") or {}
    return str(
        claims.get("sub")
        or claims.get("email")
        or claims.get("phone")
        or admin_context.get("auth_type")
        or "admin"
    )


async def _require_job_artifacts(
    artifact_repo: ArtifactRepository,
    job_id: UUID,
    artifact_types: list[ArtifactType | str],
) -> None:
    missing = []
    for artifact_type in artifact_types:
        if not await artifact_repo.get_latest_for_job(job_id, artifact_type):
            missing.append(str(artifact_type))
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is missing required artifacts: {', '.join(missing)}",
        )


@router.post(
    "",
    response_model=GenerationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_generation_job(
    payload: GenerationJobRequest,
    admin_context: dict = Depends(admin_dep),
    session: AsyncSession = Depends(db_session_dep),
    settings: Settings = Depends(settings_dep),
) -> dict:
    job_repo = JobRepository(session)
    queue_repo = QueueRepository(session)
    job_payload = await orchestrate_generation_job(payload, create_ai_provider(settings), settings)
    job = await job_repo.create_job(
        job_payload.model_dump(mode="json"),
        created_by=_created_by_from_admin_context(admin_context),
    )
    await queue_repo.send(
        STEP_TO_QUEUE[PipelineStep.RESEARCH],
        {"job_id": str(job["id"]), "step": PipelineStep.RESEARCH, "attempt": 1},
    )
    return job


@router.get("", response_model=list[GenerationJobResponse], dependencies=[Depends(admin_dep)])
async def list_generation_jobs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session_dep),
) -> list[dict]:
    return await JobRepository(session).list_jobs(limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobDetailResponse, dependencies=[Depends(admin_dep)])
async def get_generation_job(
    job_id: UUID,
    session: AsyncSession = Depends(db_session_dep),
) -> dict:
    job_repo = JobRepository(session)
    artifact_repo = ArtifactRepository(session)
    job = await job_repo.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Generation job not found"
        )
    job["agent_runs"] = await job_repo.list_agent_runs(job_id)
    job["artifacts"] = await artifact_repo.list_for_job(job_id)
    return job


@router.post(
    "/{job_id}/cancel", response_model=GenerationJobResponse, dependencies=[Depends(admin_dep)]
)
async def cancel_generation_job(
    job_id: UUID,
    session: AsyncSession = Depends(db_session_dep),
) -> dict:
    job = await JobRepository(session).update_job(
        job_id,
        status=JobStatus.CANCELED,
        current_step=None,
        error="Canceled by admin",
    )
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Generation job not found"
        )
    return job


@router.post(
    "/{job_id}/approve-script",
    response_model=GenerationJobResponse,
)
async def approve_script(
    job_id: UUID,
    payload: JobApprovalRequest,
    admin_context: dict = Depends(admin_dep),
    session: AsyncSession = Depends(db_session_dep),
) -> dict:
    job_repo = JobRepository(session)
    queue_repo = QueueRepository(session)
    artifact_repo = ArtifactRepository(session)
    job = await job_repo.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Generation job not found"
        )
    if job["status"] != JobStatus.AWAITING_SCRIPT_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job is not awaiting script approval",
        )
    await _require_job_artifacts(artifact_repo, job_id, [ArtifactType.VERIFIED_SCRIPT_JSON])
    metadata = dict(job.get("metadata") or {})
    metadata["script_approval"] = {
        "approved_at": datetime.now(UTC).isoformat(),
        "approved_by": _created_by_from_admin_context(admin_context),
        "note": payload.note,
    }
    job = await job_repo.update_job(
        job_id,
        status=JobStatus.QUEUED,
        current_step=PipelineStep.THUMBNAIL,
        metadata=metadata,
    )
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Generation job not found"
        )
    await queue_repo.send(
        STEP_TO_QUEUE[PipelineStep.THUMBNAIL],
        {"job_id": str(job_id), "step": PipelineStep.THUMBNAIL, "attempt": 1},
    )
    return job


@router.post(
    "/{job_id}/publish", response_model=GenerationJobResponse, dependencies=[Depends(admin_dep)]
)
async def publish_generation_job(
    job_id: UUID,
    session: AsyncSession = Depends(db_session_dep),
) -> dict:
    job_repo = JobRepository(session)
    queue_repo = QueueRepository(session)
    job = await job_repo.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Generation job not found"
        )
    if job["status"] in {JobStatus.CANCELED, JobStatus.FAILED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot publish a {job['status']} job",
        )
    await _require_job_artifacts(
        ArtifactRepository(session),
        job_id,
        [
            ArtifactType.VERIFIED_SCRIPT_JSON,
            ArtifactType.THUMBNAIL_IMAGE,
            ArtifactType.FINAL_AUDIO,
        ],
    )
    await queue_repo.send(
        STEP_TO_QUEUE[PipelineStep.PUBLISH],
        {"job_id": str(job_id), "step": PipelineStep.PUBLISH, "attempt": 1, "force_publish": True},
    )
    updated = await job_repo.update_job(
        job_id, status=JobStatus.QUEUED, current_step=PipelineStep.PUBLISH
    )
    return updated or job
