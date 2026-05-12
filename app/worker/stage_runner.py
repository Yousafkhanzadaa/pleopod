from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import suppress
from typing import Any

from app.agents.base import AgentContext
from app.core.config import Settings, get_settings
from app.core.json_utils import to_pretty_json
from app.core.logging import configure_logging
from app.db.queue import QueueRepository
from app.db.repositories import ArtifactRepository, JobRepository
from app.db.session import dispose_engine, get_sessionmaker, initialize_database
from app.models.enums import AgentStatus, PipelineStep
from app.providers.factory import create_ai_provider
from app.providers.storage import create_storage
from app.worker.pipeline import AGENT_CONTRACTS, AGENTS, STEP_TO_QUEUE, next_steps_for_result


class StageRunnerError(RuntimeError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pleopod-stage",
        description="Run or inspect one Pleopod pipeline stage without starting the worker.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List pipeline stages and artifact contracts.")

    inspect_parser = subparsers.add_parser("inspect", help="Show one stage contract as JSON.")
    inspect_parser.add_argument("step", choices=pipeline_step_values())

    run_parser = subparsers.add_parser("run", help="Run one stage for an existing job.")
    run_parser.add_argument("step", choices=pipeline_step_values())
    run_parser.add_argument("job_id")
    run_parser.add_argument(
        "--message-json",
        default="{}",
        help="Extra JSON message fields passed to the agent.",
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        help="Ask stages that support it to regenerate existing outputs.",
    )
    run_parser.add_argument(
        "--force-publish",
        action="store_true",
        help="Pass force_publish=true to the publish stage.",
    )
    run_parser.add_argument(
        "--dry-run-upload",
        action="store_true",
        help="For youtube_upload only, validate the upload manifest without uploading.",
    )
    run_parser.add_argument(
        "--skip-required-check",
        action="store_true",
        help="Run even if declared input artifacts are missing.",
    )
    run_parser.add_argument(
        "--enqueue-next",
        action="store_true",
        help="After success, enqueue the contract-defined next stage.",
    )

    return parser.parse_args(argv)


def pipeline_step_values() -> list[str]:
    return [step.value for step in PipelineStep]


def stage_contract_dict(step: PipelineStep) -> dict[str, Any]:
    contract = AGENT_CONTRACTS[step]
    return {
        "step": step.value,
        "agent": contract.name,
        "queue": contract.queue,
        "consumes": [artifact.value for artifact in contract.consumes],
        "produces": [artifact.value for artifact in contract.produces],
        "triggers": [trigger.value for trigger in contract.triggers],
    }


def list_stages() -> list[dict[str, Any]]:
    return [stage_contract_dict(step) for step in AGENT_CONTRACTS]


def build_message(args: argparse.Namespace) -> dict[str, Any]:
    try:
        message = json.loads(args.message_json)
    except json.JSONDecodeError as exc:
        raise StageRunnerError(f"--message-json is not valid JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise StageRunnerError("--message-json must decode to an object")

    message.setdefault("job_id", args.job_id)
    message.setdefault("step", args.step)
    if args.force:
        message["force"] = True
    if args.force_publish:
        message["force_publish"] = True
    if args.dry_run_upload:
        if args.step != PipelineStep.YOUTUBE_UPLOAD:
            raise StageRunnerError("--dry-run-upload is only valid for youtube_upload")
        message["dry_run"] = True
    return message


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


async def run_stage(
    step: PipelineStep,
    job_id: str,
    message: dict[str, Any] | None = None,
    *,
    settings: Settings | None = None,
    enqueue_next: bool = False,
    skip_required_check: bool = False,
) -> dict[str, Any]:
    settings = settings or get_settings()
    await initialize_database(settings)

    sessionmaker = get_sessionmaker(settings)
    storage = create_storage(settings)
    ai = create_ai_provider(settings)
    agent = AGENTS[step]
    message = dict(message or {})
    message.setdefault("job_id", job_id)
    message.setdefault("step", step.value)

    async with sessionmaker() as session:
        job_repo = JobRepository(session)
        artifact_repo = ArtifactRepository(session)
        queue_repo = QueueRepository(session)
        job = await job_repo.get_job(job_id)
        if not job:
            raise StageRunnerError(f"Generation job not found: {job_id}")

        if not skip_required_check:
            missing = await missing_required_artifacts(artifact_repo, job_id, step)
            if missing:
                raise StageRunnerError(
                    f"Stage {step.value} is missing required artifacts: {', '.join(missing)}"
                )

        run = await job_repo.create_agent_run(
            job_id=job_id,
            agent_name=agent.name,
            step=step,
            model=getattr(agent, "model_name", None),
        )
        context = AgentContext(settings=settings, session=session, storage=storage, ai=ai)
        try:
            result = await agent.run(job, context, message)
        except Exception as exc:
            await session.rollback()
            await job_repo.finish_agent_run(run["id"], AgentStatus.FAILED, error=str(exc))
            raise

        await job_repo.finish_agent_run(
            run["id"],
            AgentStatus.COMPLETED,
            output_artifact_id=result.output_artifact_id,
            usage=result.usage,
        )

        next_steps = list(next_steps_for_result(step, result, settings))
        enqueued_steps: list[PipelineStep] = []
        if enqueue_next and next_steps:
            current_step = next_steps[0] if len(next_steps) == 1 else None
            await job_repo.update_job(job_id, status="queued", current_step=current_step)
            for next_step in next_steps:
                await queue_repo.send(
                    STEP_TO_QUEUE[next_step],
                    {"job_id": job_id, "step": next_step.value, "attempt": 1},
                )
                enqueued_steps.append(next_step)

        return {
            "jobId": job_id,
            "step": step.value,
            "agent": agent.name,
            "agentRunId": str(run["id"]),
            "outputArtifactId": result.output_artifact_id,
            "stopPipeline": result.stop_pipeline,
            "nextSteps": [next_step.value for next_step in next_steps],
            "enqueuedNextSteps": [next_step.value for next_step in enqueued_steps],
        }


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)

    if args.command == "list":
        print(to_pretty_json(list_stages()))
        return 0

    if args.command == "inspect":
        print(to_pretty_json(stage_contract_dict(PipelineStep(args.step))))
        return 0

    message = build_message(args)
    result = await run_stage(
        PipelineStep(args.step),
        args.job_id,
        message,
        settings=settings,
        enqueue_next=args.enqueue_next,
        skip_required_check=args.skip_required_check,
    )
    print(to_pretty_json(result))
    return 0


def main(argv: list[str] | None = None) -> None:
    try:
        raise SystemExit(asyncio.run(async_main(argv)))
    except StageRunnerError as exc:
        print(f"pleopod-stage: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        with suppress(RuntimeError):
            asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
