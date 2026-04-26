from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.exc import DBAPIError

from app.agents.base import AgentContext
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.queue import QueueRepository
from app.db.repositories import JobRepository
from app.db.session import dispose_engine, get_sessionmaker
from app.models.enums import AgentStatus, JobStatus, PipelineStep
from app.providers.factory import create_ai_provider
from app.providers.storage import create_storage
from app.worker.pipeline import AGENTS, QUEUE_TO_STEP, STEP_TO_QUEUE, next_steps_for_result

logger = logging.getLogger(__name__)


def active_queue_names(settings: Settings) -> tuple[str, ...]:
    return tuple(
        queue_name
        for step, queue_name in STEP_TO_QUEUE.items()
        if (step != PipelineStep.VIDEO_RENDER or should_poll_video_queue(settings))
        and (step != PipelineStep.YOUTUBE_UPLOAD or settings.enable_youtube_uploading)
    )


def should_poll_video_queue(settings: Settings) -> bool:
    return settings.enable_video_rendering or settings.enable_youtube_uploading


def should_skip_job_message(job: dict[str, Any], step: PipelineStep) -> bool:
    status = JobStatus(job["status"])
    if status in {JobStatus.CANCELED, JobStatus.COMPLETED, JobStatus.FAILED}:
        return True

    current_step = job.get("current_step")
    if not current_step or status == JobStatus.RUNNING:
        return False

    try:
        normalized_current_step = PipelineStep(current_step)
    except ValueError:
        # Allow jobs carrying retired step values to continue on the new pipeline.
        return False

    return normalized_current_step != step


def is_transient_database_disconnect(exc: BaseException) -> bool:
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True

    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "connection was closed",
            "connection reset by peer",
            "connectiondoesnotexisterror",
            "server closed the connection",
            "connection is closed",
            "querycancelederror",
            "statement timeout",
            "canceling statement due to statement timeout",
        )
    )


class PipelineWorker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = create_storage(settings)
        self.ai = create_ai_provider(settings)
        self.sessionmaker = get_sessionmaker()
        self.running = True
        self.queue_names = active_queue_names(settings)

    async def run_forever(self) -> None:
        logger.info("Pleopod worker started")
        while self.running:
            processed = False
            for queue_name in self.queue_names:
                try:
                    processed = await self._process_queue(queue_name) or processed
                except Exception as exc:  # noqa: BLE001
                    if not is_transient_database_disconnect(exc):
                        raise
                    logger.warning(
                        "Transient database disconnect while polling queue=%s; reconnecting",
                        queue_name,
                        exc_info=True,
                    )
                    await self._refresh_database_connections()
            if not processed:
                await asyncio.sleep(self.settings.worker_sleep_seconds)

    async def _refresh_database_connections(self) -> None:
        await dispose_engine()
        self.sessionmaker = get_sessionmaker()

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
            if should_skip_job_message(job, step):
                logger.info(
                    "Skipping message for job %s queue=%s step=%s status=%s current_step=%s",
                    job_id,
                    queue_name,
                    step,
                    job["status"],
                    job.get("current_step"),
                )
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
            heartbeat_stop = asyncio.Event()
            heartbeat_task = asyncio.create_task(
                self._heartbeat_message(queue_name, msg_id, heartbeat_stop)
            )
            try:
                result = await agent.run(job, context, message)
            except Exception as exc:  # noqa: BLE001
                await self._stop_heartbeat(heartbeat_stop, heartbeat_task, queue_name, msg_id)
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
            await self._stop_heartbeat(heartbeat_stop, heartbeat_task, queue_name, msg_id)

            await job_repo.finish_agent_run(
                run["id"],
                AgentStatus.COMPLETED,
                output_artifact_id=result.output_artifact_id,
                usage=result.usage,
            )
            next_steps = next_steps_for_result(step, result, self.settings)
            if next_steps:
                current_step = next_steps[0] if len(next_steps) == 1 else None
                await job_repo.update_job(
                    job_id, status=JobStatus.QUEUED, current_step=current_step
                )
                for next_step in next_steps:
                    await queue_repo.send(
                        STEP_TO_QUEUE[next_step],
                        {
                            "job_id": job_id,
                            "step": next_step,
                            "attempt": 1,
                        },
                    )

    async def _stop_heartbeat(
        self,
        heartbeat_stop: asyncio.Event,
        heartbeat_task: asyncio.Task[None],
        queue_name: str,
        msg_id: int,
    ) -> None:
        heartbeat_stop.set()
        try:
            await heartbeat_task
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Heartbeat task failed while stopping queue=%s msg_id=%s: %s",
                queue_name,
                msg_id,
                exc,
            )

    async def _heartbeat_message(
        self,
        queue_name: str,
        msg_id: int,
        stop_event: asyncio.Event,
    ) -> None:
        interval_seconds = max(30, self.settings.queue_visibility_timeout_seconds // 3)
        while True:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                return
            except TimeoutError:
                pass

            try:
                async with self.sessionmaker() as session:
                    updated = await QueueRepository(session).set_vt(
                        queue_name,
                        msg_id,
                        self.settings.queue_visibility_timeout_seconds,
                    )
                    if not updated:
                        logger.warning(
                            "Could not extend queue visibility timeout queue=%s msg_id=%s",
                            queue_name,
                            msg_id,
                        )
                        return
            except Exception as exc:  # noqa: BLE001
                if is_transient_database_disconnect(exc):
                    logger.warning(
                        "Could not extend queue visibility timeout queue=%s msg_id=%s: %s",
                        queue_name,
                        msg_id,
                        exc,
                    )
                    return
                raise

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
    try:
        await PipelineWorker(settings).run_forever()
    finally:
        await dispose_engine()


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("Pleopod worker stopped")


if __name__ == "__main__":
    main()
