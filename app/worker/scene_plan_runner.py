"""``pleopod-scene-plan``: build and inspect a data-driven scene plan for a job.

This runs the engine-agnostic scene + chart director against an existing job's
verified script, claim bank, and (if present) final-audio timings, then prints
the plan and optionally stores it as a ``scene_plan_json`` artifact. It does not
render anything, so it is cheap to iterate on prompts and grounding.

    pleopod-scene-plan <job-id>
    pleopod-scene-plan <job-id> --no-store
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from contextlib import suppress
from typing import Any

from app.agents.base import AgentContext
from app.agents.video_director import (
    line_timings_from_segment_timings,
    plan_video_scenes,
)
from app.core.config import Settings, get_settings
from app.core.duration import clamp_generation_duration_seconds
from app.core.json_utils import to_pretty_json
from app.core.logging import configure_logging
from app.db.repositories import JobRepository
from app.db.session import dispose_engine, get_sessionmaker, initialize_database
from app.models.enums import ArtifactType
from app.providers.factory import create_ai_provider
from app.providers.storage import create_storage
from app.schemas.video_plan import ScenePlan


class ScenePlanError(RuntimeError):
    pass


async def _latest_source_urls(context: AgentContext, job_id: str) -> list[str]:
    try:
        sources = await context.latest_json(job_id, ArtifactType.SOURCES_JSON)
    except Exception:  # noqa: BLE001 - source list is optional
        return []
    urls: list[str] = []
    for source in sources if isinstance(sources, list) else []:
        url = source.get("url") if isinstance(source, dict) else source
        if url:
            urls.append(str(url))
    return urls


async def build_scene_plan_for_job(context: AgentContext, job: dict[str, Any]) -> ScenePlan:
    job_id = str(job["id"])
    script = await context.latest_json(job_id, ArtifactType.VERIFIED_SCRIPT_JSON)

    try:
        claims = await context.latest_json(job_id, ArtifactType.CLAIM_BANK_JSON)
    except RuntimeError:
        claims = []
    if not isinstance(claims, list):
        claims = []

    line_timings: list[dict[str, Any]] | None = None
    duration = float(clamp_generation_duration_seconds(job.get("target_duration_seconds")))
    audio = await context.artifact_repo.get_latest_for_job(job_id, ArtifactType.FINAL_AUDIO)
    if audio:
        metadata = audio.get("metadata") or {}
        line_timings = metadata.get("line_timings") or line_timings_from_segment_timings(
            metadata.get("segment_timings") or []
        )
        audio_duration = metadata.get("duration_seconds")
        if audio_duration is not None:
            with suppress(TypeError, ValueError):
                duration = float(math.ceil(float(audio_duration) + 1))

    return await plan_video_scenes(
        script=script if isinstance(script, dict) else {},
        claims=claims,
        line_timings=line_timings,
        duration_seconds=duration,
        category=str(job.get("category") or "Tech"),
        ai=context.ai,
        model=context.settings.remotion_video_director_model,
        source_urls=await _latest_source_urls(context, job_id),
        word_timings=(audio.get("metadata") or {}).get("word_timings") if audio else None,
    )


async def run_scene_plan(
    job_id: str,
    *,
    settings: Settings | None = None,
    store: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    await initialize_database(settings)
    sessionmaker = get_sessionmaker(settings)
    storage = create_storage(settings)
    ai = create_ai_provider(settings)

    async with sessionmaker() as session:
        job = await JobRepository(session).get_job(job_id)
        if not job:
            raise ScenePlanError(f"Generation job not found: {job_id}")
        context = AgentContext(settings=settings, session=session, storage=storage, ai=ai)
        plan = await build_scene_plan_for_job(context, job)

        stored_key: str | None = None
        if store:
            artifact = await context.artifact_service.put_json(
                f"jobs/{job_id}/video/scene_plan.json",
                plan.model_dump(mode="json"),
                ArtifactType.SCENE_PLAN_JSON,
                job_id=job_id,
            )
            stored_key = str(artifact["r2_key"])

    return {
        "jobId": job_id,
        "sceneCount": len(plan.scenes),
        "chartScenes": sum(1 for scene in plan.scenes if scene.layout == "chart"),
        "storedArtifact": stored_key,
        "plan": plan.model_dump(mode="json"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pleopod-scene-plan",
        description="Build a data-driven scene + chart plan for an existing job.",
    )
    parser.add_argument("job_id", help="Generation job id to plan scenes for.")
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Print the plan without storing a scene_plan_json artifact.",
    )
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    result = await run_scene_plan(args.job_id, settings=settings, store=not args.no_store)
    print(to_pretty_json(result))
    return 0


def main(argv: list[str] | None = None) -> None:
    try:
        raise SystemExit(asyncio.run(async_main(argv)))
    except ScenePlanError as exc:
        print(f"pleopod-scene-plan: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        with suppress(RuntimeError):
            asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
