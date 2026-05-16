from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from contextlib import suppress
from typing import Any
from uuid import uuid4

from app.agents.base import AgentContext
from app.agents.topic_scout import (
    TopicScoutAgent,
    public_topic_scout_decision,
)
from app.core.config import Settings, get_settings
from app.core.json_utils import to_pretty_json
from app.core.logging import configure_logging
from app.db.repositories import (
    ArtifactRepository,
    AutomationLockRepository,
    JobRepository,
)
from app.db.session import dispose_engine, get_sessionmaker, initialize_database
from app.models.enums import AgentStatus, JobStatus, PipelineStep
from app.providers.ai import AIProvider
from app.providers.factory import create_ai_provider, create_thumbnail_image_provider
from app.providers.storage import ObjectStorage, create_storage
from app.worker.pipeline import AGENT_CONTRACTS, AGENTS, next_steps_for_result

logger = logging.getLogger(__name__)
AUTOPUBLISH_LOCK_NAME = "autopublish"


class AutopublishRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage: ObjectStorage = create_storage(settings)
        self.ai: AIProvider = create_ai_provider(settings)
        self._thumbnail_image_ai: AIProvider | None = None
        self.sessionmaker = get_sessionmaker(settings)

    async def run_once(self) -> dict[str, Any]:
        await initialize_database(self.settings)
        owner_id = str(uuid4())
        acquired = await self._acquire_lock(owner_id)
        if not acquired:
            logger.info("Autopublish run skipped because another run holds the lock")
            return {"status": "skipped", "reason": "lock_not_acquired"}

        try:
            async with asyncio.timeout(self.settings.autopublish_max_runtime_seconds):
                recent_jobs = await self._recent_jobs()
                scout_result = await TopicScoutAgent().run(
                    settings=self.settings,
                    ai=self.ai,
                    recent_jobs=recent_jobs,
                )
                job = await self._create_job(scout_result.payload.model_dump(mode="json"))
                logger.info(
                    "Autopublish selected topic for job %s: %s",
                    job["id"],
                    job["topic"],
                )
                pipeline_result = await self._run_pipeline(str(job["id"]))
                return {
                    "status": pipeline_result["status"],
                    "jobId": str(job["id"]),
                    "topic": job["topic"],
                    "topicScout": scout_result.decision.get("rationale"),
                    **pipeline_result,
                }
        finally:
            await self._release_lock(owner_id)

    async def scout_only(self) -> dict[str, Any]:
        await initialize_database(self.settings)
        recent_jobs = await self._recent_jobs()
        scout_result = await TopicScoutAgent().run(
            settings=self.settings,
            ai=self.ai,
            recent_jobs=recent_jobs,
        )
        return {
            "status": "scouted",
            "payload": scout_result.payload.model_dump(mode="json"),
            "decision": public_topic_scout_decision(scout_result.decision),
        }

    async def _acquire_lock(self, owner_id: str) -> bool:
        async with self.sessionmaker() as session:
            return await AutomationLockRepository(session).acquire(
                AUTOPUBLISH_LOCK_NAME,
                owner_id,
                self.settings.autopublish_lock_ttl_seconds,
            )

    async def _release_lock(self, owner_id: str) -> None:
        async with self.sessionmaker() as session:
            await AutomationLockRepository(session).release(AUTOPUBLISH_LOCK_NAME, owner_id)

    async def _recent_jobs(self) -> list[dict[str, Any]]:
        async with self.sessionmaker() as session:
            return await JobRepository(session).list_jobs(
                limit=self.settings.autopublish_recent_job_limit,
                offset=0,
            )

    async def _create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            return await JobRepository(session).create_job(
                payload,
                created_by=self.settings.autopublish_created_by,
            )

    async def _run_pipeline(self, job_id: str) -> dict[str, Any]:
        step = PipelineStep.RESEARCH
        completed_steps: list[str] = []

        while True:
            result = await self._run_step(
                job_id,
                step,
                {"job_id": job_id, "step": step.value, "attempt": 1},
            )
            completed_steps.append(step.value)
            next_steps = next_steps_for_result(step, result, self.settings)
            if not next_steps:
                job = await self._job(job_id)
                return {
                    "status": str(job.get("status") or "unknown"),
                    "currentStep": job.get("current_step"),
                    "completedSteps": completed_steps,
                    "error": job.get("error"),
                }
            if len(next_steps) > 1:
                raise RuntimeError(
                    "Autopublish runner only supports linear next steps, got: "
                    + ", ".join(next_step.value for next_step in next_steps)
                )

            step = next_steps[0]

    async def _run_step(
        self,
        job_id: str,
        step: PipelineStep,
        message: dict[str, Any],
    ):
        agent = AGENTS[step]
        async with self.sessionmaker() as session:
            job_repo = JobRepository(session)
            artifact_repo = ArtifactRepository(session)
            job = await job_repo.get_job(job_id)
            if not job:
                raise RuntimeError(f"Generation job not found: {job_id}")

            missing = await missing_required_artifacts(artifact_repo, job_id, step)
            if missing:
                raise RuntimeError(
                    f"Stage {step.value} is missing required artifacts: {', '.join(missing)}"
                )

            await job_repo.update_job(
                job_id,
                status=JobStatus.RUNNING,
                current_step=step,
                error=None,
            )
            run = await job_repo.create_agent_run(
                job_id=job_id,
                agent_name=agent.name,
                step=step,
                model=getattr(agent, "model_name", None),
            )
            context = AgentContext(
                settings=self.settings,
                session=session,
                storage=self.storage,
                ai=self.ai,
                image_ai=self._image_provider_for_step(step),
            )
            try:
                result = await agent.run(job, context, message)
            except asyncio.CancelledError:
                await session.rollback()
                await job_repo.finish_agent_run(
                    run["id"],
                    AgentStatus.FAILED,
                    error="Autopublish step was cancelled",
                )
                await job_repo.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    current_step=None,
                    error="Autopublish run was cancelled",
                )
                raise
            except Exception as exc:
                await session.rollback()
                await job_repo.finish_agent_run(run["id"], AgentStatus.FAILED, error=str(exc))
                await job_repo.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    current_step=None,
                    error=str(exc),
                )
                raise

            await job_repo.finish_agent_run(
                run["id"],
                AgentStatus.COMPLETED,
                output_artifact_id=result.output_artifact_id,
                usage=result.usage,
            )
            next_steps = next_steps_for_result(step, result, self.settings)
            if next_steps:
                await job_repo.update_job(
                    job_id,
                    status=JobStatus.QUEUED,
                    current_step=next_steps[0] if len(next_steps) == 1 else None,
                )
            return result

    async def _job(self, job_id: str) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            job = await JobRepository(session).get_job(job_id)
            if not job:
                raise RuntimeError(f"Generation job not found: {job_id}")
            return job

    def _image_provider_for_step(self, step: PipelineStep) -> AIProvider | None:
        if step != PipelineStep.THUMBNAIL:
            return None
        if self._thumbnail_image_ai is None:
            self._thumbnail_image_ai = create_thumbnail_image_provider(
                self.settings,
                default_provider=self.ai,
            )
        return self._thumbnail_image_ai


async def missing_required_artifacts(
    artifact_repo: ArtifactRepository,
    job_id: str,
    step: PipelineStep,
) -> list[str]:
    missing = []
    for artifact_type in AGENT_CONTRACTS[step].consumes:
        if not await artifact_repo.get_latest_for_job(job_id, artifact_type):
            missing.append(artifact_type.value)
    return missing


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pleopod-autopublish",
        description="Pick a timely topic and run one finite Pleopod publishing job.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "scout"),
        default="run",
        help="Use 'scout' to run only Topic Scout without creating a job.",
    )
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    runner = AutopublishRunner(settings)
    result = await runner.scout_only() if args.command == "scout" else await runner.run_once()
    print(to_pretty_json(result))
    return 0 if result.get("status") in {"completed", "skipped", "scouted"} else 1


def main(argv: list[str] | None = None) -> None:
    try:
        raise SystemExit(asyncio.run(async_main(argv)))
    except KeyboardInterrupt:
        logger.info("Autopublish run interrupted")
        raise SystemExit(130) from None
    except Exception as exc:
        logger.exception("Autopublish run failed")
        print(f"pleopod-autopublish: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        with suppress(RuntimeError):
            asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
