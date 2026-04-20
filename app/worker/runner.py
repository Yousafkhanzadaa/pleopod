from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agents.base import AgentContext
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.queue import QueueRepository
from app.db.repositories import JobRepository
from app.db.session import get_sessionmaker
from app.models.enums import AgentStatus, JobStatus, PipelineStep
from app.providers.factory import create_ai_provider
from app.providers.storage import create_storage
from app.worker.pipeline import AGENTS, QUEUE_TO_STEP, STEP_TO_QUEUE

logger = logging.getLogger(__name__)


class PipelineWorker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = create_storage(settings)
        self.ai = create_ai_provider(settings)
        self.sessionmaker = get_sessionmaker()
        self.running = True

    async def run_forever(self) -> None:
        logger.info("Pleopod worker started")
        while self.running:
            processed = False
            for queue_name in QUEUE_TO_STEP:
                processed = await self._process_queue(queue_name) or processed
            if not processed:
                await asyncio.sleep(self.settings.worker_sleep_seconds)

    async def _process_queue(self, queue_name: str) -> bool:
        async with self.sessionmaker() as session:
            queue_repo = QueueRepository(session)
            messages = await queue_repo.read(
                queue_name=queue_name,
                visibility_timeout_seconds=self.settings.queue_visibility_timeout_seconds,
                qty=1,
                max_poll_seconds=self.settings.queue_poll_seconds,
            )
            if not messages:
                return False

            for message in messages:
                try:
                    await self._process_message(
                        queue_name, message.msg_id, message.read_ct, message.message
                    )
                    await queue_repo.delete(queue_name, message.msg_id)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "Pipeline message failed",
                        extra={"queue": queue_name, "msg_id": message.msg_id},
                    )
                    if message.read_ct >= self.settings.max_agent_attempts:
                        await self._fail_message(
                            queue_name, message.msg_id, message.message, str(exc)
                        )
            return True

    async def _process_message(
        self,
        queue_name: str,
        msg_id: int,
        read_ct: int,
        message: dict[str, Any],
    ) -> None:
        step = PipelineStep(message.get("step") or QUEUE_TO_STEP[queue_name])
        agent = AGENTS[step]
        job_id = message["job_id"]

        async with self.sessionmaker() as session:
            job_repo = JobRepository(session)
            queue_repo = QueueRepository(session)
            job = await job_repo.get_job(job_id)
            if not job:
                raise RuntimeError(f"Generation job not found: {job_id}")
            if job["status"] == JobStatus.CANCELED:
                logger.info("Skipping canceled job %s", job_id)
                return

            await job_repo.update_job(
                job_id, status=JobStatus.RUNNING, current_step=step, error=None
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
            )
            try:
                result = await agent.run(job, context, message)
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                await job_repo.finish_agent_run(run["id"], AgentStatus.FAILED, error=str(exc))
                if read_ct >= self.settings.max_agent_attempts:
                    await job_repo.update_job(job_id, status=JobStatus.FAILED, error=str(exc))
                else:
                    await job_repo.update_job(
                        job_id,
                        status=JobStatus.QUEUED,
                        error=f"Attempt {read_ct} failed: {exc}",
                    )
                raise

            await job_repo.finish_agent_run(
                run["id"],
                AgentStatus.COMPLETED,
                output_artifact_id=result.output_artifact_id,
                usage=result.usage,
            )
            if result.next_step and not result.stop_pipeline:
                await job_repo.update_job(
                    job_id, status=JobStatus.QUEUED, current_step=result.next_step
                )
                await queue_repo.send(
                    STEP_TO_QUEUE[result.next_step],
                    {
                        "job_id": job_id,
                        "step": result.next_step,
                        "attempt": 1,
                    },
                )

    async def _fail_message(
        self,
        queue_name: str,
        msg_id: int,
        message: dict[str, Any],
        error: str,
    ) -> None:
        async with self.sessionmaker() as session:
            queue_repo = QueueRepository(session)
            await queue_repo.archive(queue_name, msg_id)
            await queue_repo.send(
                "dead_letter_queue",
                {**message, "source_queue": queue_name, "error": error},
            )


async def async_main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await PipelineWorker(settings).run_forever()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
