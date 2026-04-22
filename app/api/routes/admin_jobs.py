from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import admin_dep, db_session_dep
from app.db.queue import QueueRepository
from app.db.repositories import ArtifactRepository, JobRepository
from app.models.enums import JobStatus, PipelineStep
from app.schemas.jobs import (
    GenerationJobCreate,
    GenerationJobResponse,
    JobApprovalRequest,
    JobDetailResponse,
)
from app.worker.pipeline import STEP_TO_QUEUE

router = APIRouter(prefix="/admin/generation-jobs", tags=["admin-generation-jobs"])


@router.post(
    "",
    response_model=GenerationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(admin_dep)],
)
async def create_generation_job(
    payload: GenerationJobCreate,
    session: AsyncSession = Depends(db_session_dep),
) -> dict:
    job_repo = JobRepository(session)
    queue_repo = QueueRepository(session)
    job = await job_repo.create_job(payload.model_dump(mode="json"))
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
    dependencies=[Depends(admin_dep)],
)
async def approve_script(
    job_id: UUID,
    _: JobApprovalRequest,
    session: AsyncSession = Depends(db_session_dep),
) -> dict:
    job_repo = JobRepository(session)
    queue_repo = QueueRepository(session)
    job = await job_repo.update_job(
        job_id, status=JobStatus.QUEUED, current_step=PipelineStep.THUMBNAIL
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
    await queue_repo.send(
        STEP_TO_QUEUE[PipelineStep.PUBLISH],
        {"job_id": str(job_id), "step": PipelineStep.PUBLISH, "attempt": 1, "force_publish": True},
    )
    updated = await job_repo.update_job(
        job_id, status=JobStatus.QUEUED, current_step=PipelineStep.PUBLISH
    )
    return updated or job
