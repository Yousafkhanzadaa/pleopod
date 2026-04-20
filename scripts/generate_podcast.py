#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import httpx

from app.core.config import Settings

TERMINAL_STATUSES = {"completed", "failed", "canceled"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a podcast generation job, poll it, and print the final audio URL."
    )
    parser.add_argument("topic", help="Podcast topic to generate.")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Pleopod API base URL.")
    parser.add_argument(
        "--admin-key", default=None, help="Admin API key. Defaults to ADMIN_API_KEY."
    )
    parser.add_argument("--category", default="Tech")
    parser.add_argument("--audience", default="curious tech listeners and startup builders")
    parser.add_argument("--duration", type=int, default=300, help="Target duration in seconds.")
    parser.add_argument("--language", default="en")
    parser.add_argument("--tone", default="clear, smart, conversational")
    parser.add_argument("--source-url", action="append", default=[], help="Optional source URL.")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Create a draft episode instead of auto-publishing it.",
    )
    return parser.parse_args()


def admin_headers(admin_key: str | None) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    if admin_key:
        headers["x-admin-api-key"] = admin_key
    return headers


def create_job(
    client: httpx.Client, args: argparse.Namespace, admin_key: str | None
) -> dict[str, Any]:
    payload = {
        "topic": args.topic,
        "category": args.category,
        "audience": args.audience,
        "target_duration_seconds": args.duration,
        "language": args.language,
        "tone": args.tone,
        "source_urls": args.source_url,
        "auto_publish": not args.draft,
    }
    response = client.post(
        "/admin/generation-jobs",
        json=payload,
        headers=admin_headers(admin_key),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_job(client: httpx.Client, job_id: str, admin_key: str | None) -> dict[str, Any]:
    response = client.get(
        f"/admin/generation-jobs/{job_id}",
        headers=admin_headers(admin_key),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_stream_url(client: httpx.Client, episode_id: str) -> dict[str, Any]:
    response = client.get(f"/episodes/{episode_id}/stream-url", timeout=30)
    response.raise_for_status()
    return response.json()


def print_progress(job: dict[str, Any], last_signature: tuple[Any, ...] | None) -> tuple[Any, ...]:
    agent_runs = job.get("agent_runs") or []
    artifacts = job.get("artifacts") or []
    latest_run = agent_runs[-1] if agent_runs else {}
    signature = (
        job.get("status"),
        job.get("current_step"),
        latest_run.get("agent_name"),
        latest_run.get("status"),
        len(artifacts),
    )
    if signature == last_signature:
        return signature

    step = job.get("current_step") or "-"
    latest_agent = latest_run.get("agent_name") or "-"
    latest_status = latest_run.get("status") or "-"
    print(
        "status={status} step={step} latest_agent={agent} "
        "latest_agent_status={agent_status} artifacts={artifacts}".format(
            status=job.get("status"),
            step=step,
            agent=latest_agent,
            agent_status=latest_status,
            artifacts=len(artifacts),
        ),
        flush=True,
    )
    return signature


def print_failure(job: dict[str, Any]) -> None:
    print("\nGeneration failed.", file=sys.stderr)
    if job.get("error"):
        print(f"Job error: {job['error']}", file=sys.stderr)
    for run in job.get("agent_runs") or []:
        if run.get("status") == "failed" or run.get("error"):
            print(
                f"- {run.get('agent_name')} ({run.get('step')}): {run.get('error')}",
                file=sys.stderr,
            )


def main() -> int:
    args = parse_args()
    settings = Settings()
    admin_key = args.admin_key if args.admin_key is not None else settings.admin_api_key

    with httpx.Client(base_url=args.api_url.rstrip("/")) as client:
        try:
            job = create_job(client, args, admin_key)
        except httpx.HTTPStatusError as exc:
            print(
                f"Could not create job: {exc.response.status_code} {exc.response.text}",
                file=sys.stderr,
            )
            return 1
        except httpx.HTTPError as exc:
            print(f"Could not reach API at {args.api_url}: {exc}", file=sys.stderr)
            return 1

        job_id = job["id"]
        print(f"Created job: {job_id}")
        print("Polling until completion. Keep pleopod-worker running in another terminal.")

        deadline = time.monotonic() + args.timeout_seconds
        last_signature: tuple[Any, ...] | None = None
        while time.monotonic() < deadline:
            try:
                job = get_job(client, job_id, admin_key)
            except httpx.HTTPError as exc:
                print(f"Could not fetch job status: {exc}", file=sys.stderr)
                return 1

            last_signature = print_progress(job, last_signature)
            if job.get("status") in TERMINAL_STATUSES:
                break
            time.sleep(args.poll_seconds)
        else:
            print(
                f"Timed out after {args.timeout_seconds} seconds. Job id: {job_id}", file=sys.stderr
            )
            return 2

        if job.get("status") != "completed":
            print_failure(job)
            return 1

        episode_id = (job.get("metadata") or {}).get("episode_id")
        if not episode_id:
            print("Job completed, but no episode_id was found in job metadata.", file=sys.stderr)
            return 1

        try:
            stream = get_stream_url(client, episode_id)
        except httpx.HTTPStatusError as exc:
            print(
                f"Job completed, but stream URL lookup failed: "
                f"{exc.response.status_code} {exc.response.text}",
                file=sys.stderr,
            )
            return 1

        print("\nPodcast generation complete.")
        print(f"Job ID: {job_id}")
        print(f"Episode ID: {episode_id}")
        print(f"Audio URL: {stream['audio_url']}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
