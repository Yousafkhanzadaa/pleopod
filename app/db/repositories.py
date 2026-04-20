from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CLAIM_VERIFICATION_STATUSES = {
    "unverified",
    "supported",
    "unsupported",
    "misleading",
    "needs_context",
}
CLAIM_VERIFICATION_STATUS_ALIASES = {
    "weak": "needs_context",
    "weakly_supported": "needs_context",
    "partially_supported": "needs_context",
    "partly_supported": "needs_context",
    "overstated": "misleading",
    "not_supported": "unsupported",
    "false": "unsupported",
}


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_job(
        self, payload: dict[str, Any], created_by: str | None = None
    ) -> dict[str, Any]:
        result = await self.session.execute(
            text(
                """
                insert into generation_jobs (
                  topic, category, audience, target_duration_seconds, language, tone,
                  source_urls, auto_publish, metadata, created_by
                )
                values (
                  :topic, :category, :audience, :target_duration_seconds, :language, :tone,
                  cast(:source_urls as jsonb), :auto_publish, cast(:metadata as jsonb), :created_by
                )
                returning *
                """
            ),
            {
                **payload,
                "source_urls": json.dumps(payload.get("source_urls", [])),
                "metadata": json.dumps(payload.get("metadata", {})),
                "created_by": created_by,
            },
        )
        await self.session.commit()
        return dict(result.mappings().one())

    async def get_job(self, job_id: UUID | str) -> dict[str, Any] | None:
        result = await self.session.execute(
            text("select * from generation_jobs where id = :job_id"),
            {"job_id": str(job_id)},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def list_jobs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text(
                "select * from generation_jobs order by created_at desc limit :limit offset :offset"
            ),
            {"limit": limit, "offset": offset},
        )
        return [dict(row) for row in result.mappings().all()]

    async def update_job(self, job_id: UUID | str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return await self.get_job(job_id)
        json_fields = {"metadata", "source_urls"}
        params: dict[str, Any] = {"job_id": str(job_id)}
        assignments_list: list[str] = []
        for key, value in fields.items():
            if key in json_fields:
                assignments_list.append(f"{key} = cast(:{key} as jsonb)")
                params[key] = json.dumps(value or ([] if key == "source_urls" else {}))
            else:
                assignments_list.append(f"{key} = :{key}")
                params[key] = str(value) if hasattr(value, "value") else value
        assignments = ", ".join(assignments_list)
        result = await self.session.execute(
            text(
                f"""
                update generation_jobs
                set {assignments}, updated_at = now()
                where id = :job_id
                returning *
                """
            ),
            params,
        )
        await self.session.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def create_agent_run(
        self,
        job_id: UUID | str,
        agent_name: str,
        step: str,
        model: str | None,
        input_artifact_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        result = await self.session.execute(
            text(
                """
                insert into agent_runs (job_id, agent_name, step, status, model, input_artifact_id)
                values (:job_id, :agent_name, :step, 'running', :model, :input_artifact_id)
                returning *
                """
            ),
            {
                "job_id": str(job_id),
                "agent_name": agent_name,
                "step": step,
                "model": model,
                "input_artifact_id": str(input_artifact_id) if input_artifact_id else None,
            },
        )
        await self.session.commit()
        return dict(result.mappings().one())

    async def finish_agent_run(
        self,
        run_id: UUID | str,
        status: str,
        output_artifact_id: UUID | str | None = None,
        error: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        await self.session.execute(
            text(
                """
                update agent_runs
                set status = :status,
                    output_artifact_id = :output_artifact_id,
                    error = :error,
                    usage = cast(:usage as jsonb),
                    completed_at = now()
                where id = :run_id
                """
            ),
            {
                "run_id": str(run_id),
                "status": status,
                "output_artifact_id": str(output_artifact_id) if output_artifact_id else None,
                "error": error,
                "usage": json.dumps(usage or {}),
            },
        )
        await self.session.commit()

    async def list_agent_runs(self, job_id: UUID | str) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text("select * from agent_runs where job_id = :job_id order by started_at asc"),
            {"job_id": str(job_id)},
        )
        return [dict(row) for row in result.mappings().all()]


class ArtifactRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_artifact(
        self,
        artifact_type: str,
        r2_key: str,
        mime_type: str,
        job_id: UUID | str | None = None,
        episode_id: UUID | str | None = None,
        size_bytes: int | None = None,
        checksum_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await self.session.execute(
            text(
                """
                insert into artifacts (
                  job_id, episode_id, artifact_type, r2_key, mime_type,
                  size_bytes, checksum_sha256, metadata
                )
                values (
                  :job_id, :episode_id, :artifact_type, :r2_key, :mime_type,
                  :size_bytes, :checksum_sha256, cast(:metadata as jsonb)
                )
                returning *
                """
            ),
            {
                "job_id": str(job_id) if job_id else None,
                "episode_id": str(episode_id) if episode_id else None,
                "artifact_type": artifact_type,
                "r2_key": r2_key,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "checksum_sha256": checksum_sha256,
                "metadata": json.dumps(metadata or {}),
            },
        )
        await self.session.commit()
        return dict(result.mappings().one())

    async def get_latest_for_job(
        self, job_id: UUID | str, artifact_type: str
    ) -> dict[str, Any] | None:
        result = await self.session.execute(
            text(
                """
                select * from artifacts
                where job_id = :job_id and artifact_type = :artifact_type
                order by created_at desc
                limit 1
                """
            ),
            {"job_id": str(job_id), "artifact_type": artifact_type},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def list_for_job(self, job_id: UUID | str) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text("select * from artifacts where job_id = :job_id order by created_at asc"),
            {"job_id": str(job_id)},
        )
        return [dict(row) for row in result.mappings().all()]


class KnowledgeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_sources(self, job_id: UUID | str, sources: list[dict[str, Any]]) -> None:
        await self.session.execute(
            text("delete from sources where job_id = :job_id"), {"job_id": str(job_id)}
        )
        if sources:
            await self.session.execute(
                text(
                    """
                    insert into sources (
                      job_id, url, title, publisher, author, published_at, retrieved_at,
                      source_tier, credibility_score, notes
                    )
                    values (
                      :job_id, :url, :title, :publisher, :author, :published_at, now(),
                      :source_tier, :credibility_score, :notes
                    )
                    on conflict do nothing
                    """
                ),
                [self._source_params(job_id, source) for source in sources],
            )
        await self.session.commit()

    def _source_params(self, job_id: UUID | str, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": str(job_id),
            "url": source.get("url"),
            "title": source.get("title"),
            "publisher": source.get("publisher"),
            "author": source.get("author"),
            "published_at": parse_optional_datetime(source.get("published_at")),
            "source_tier": source.get("source_tier", "B"),
            "credibility_score": source.get("credibility_score"),
            "notes": source.get("notes"),
        }

    async def replace_claims(self, job_id: UUID | str, claims: list[dict[str, Any]]) -> None:
        await self.session.execute(
            text("delete from claims where job_id = :job_id"), {"job_id": str(job_id)}
        )
        if claims:
            await self.session.execute(
                text(
                    """
                    insert into claims (
                      job_id, claim_text, source_urls, verification_status,
                      confidence, notes, used_in_script
                    )
                    values (
                      :job_id, :claim_text, cast(:source_urls as jsonb), :verification_status,
                      :confidence, :notes, :used_in_script
                    )
                    on conflict do nothing
                    """
                ),
                [
                    {
                        "job_id": str(job_id),
                        "claim_text": claim["claim_text"],
                        "source_urls": json.dumps(claim.get("source_urls", [])),
                        "verification_status": normalize_claim_verification_status(
                            claim.get("verification_status")
                        ),
                        "confidence": claim.get("confidence"),
                        "notes": claim.get("notes"),
                        "used_in_script": claim.get("used_in_script", False),
                    }
                    for claim in claims
                ],
            )
        await self.session.commit()


def normalize_claim_verification_status(value: Any) -> str:
    status = str(value or "unverified").strip().lower().replace("-", "_").replace(" ", "_")
    status = CLAIM_VERIFICATION_STATUS_ALIASES.get(status, status)
    if status in CLAIM_VERIFICATION_STATUSES:
        return status
    return "unverified"


def parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        return datetime.fromisoformat(normalized)
    raise TypeError(f"Expected datetime, ISO datetime string, or None, got {type(value)!r}")


class EpisodeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_episode(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self.session.execute(
            text(
                """
                insert into episodes (
                  generation_job_id, title, slug, category, status, summary, description,
                  duration_seconds, language, metadata, published_at
                )
                values (
                  :generation_job_id, :title, :slug, :category, :status, :summary, :description,
                  :duration_seconds, :language, cast(:metadata as jsonb),
                  case when :status = 'published' then now() else null end
                )
                on conflict (slug)
                do update set title = excluded.title,
                              category = excluded.category,
                              status = excluded.status,
                              summary = excluded.summary,
                              description = excluded.description,
                              duration_seconds = excluded.duration_seconds,
                              language = excluded.language,
                              metadata = excluded.metadata,
                              published_at = case
                                when excluded.status = 'published'
                                  then coalesce(episodes.published_at, now())
                                else episodes.published_at
                              end,
                              updated_at = now()
                where episodes.generation_job_id = excluded.generation_job_id
                returning *
                """
            ),
            {**payload, "metadata": json.dumps(payload.get("metadata", {}))},
        )
        await self.session.commit()
        row = result.mappings().first()
        if row:
            return dict(row)
        raise RuntimeError(f"Episode slug already exists for another job: {payload['slug']}")

    async def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self.session.execute(
            text(
                """
                insert into episode_assets (
                  episode_id, asset_type, r2_key, public_url, mime_type,
                  size_bytes, checksum_sha256, metadata
                )
                values (
                  :episode_id, :asset_type, :r2_key, :public_url, :mime_type,
                  :size_bytes, :checksum_sha256, cast(:metadata as jsonb)
                )
                on conflict (episode_id, asset_type)
                do update set r2_key = excluded.r2_key,
                              public_url = excluded.public_url,
                              mime_type = excluded.mime_type,
                              size_bytes = excluded.size_bytes,
                              checksum_sha256 = excluded.checksum_sha256,
                              metadata = excluded.metadata
                returning *
                """
            ),
            {**payload, "metadata": json.dumps(payload.get("metadata", {}))},
        )
        await self.session.commit()
        return dict(result.mappings().one())

    async def list_published(self, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text(
                """
                select * from episodes
                where status = 'published'
                order by published_at desc nulls last, created_at desc
                limit :limit offset :offset
                """
            ),
            {"limit": limit, "offset": offset},
        )
        return [dict(row) for row in result.mappings().all()]

    async def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            text("select * from episodes where slug = :slug and status = 'published'"),
            {"slug": slug},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def get_assets(self, episode_id: UUID | str) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text(
                """
                select *
                from episode_assets
                where episode_id = :episode_id
                order by created_at asc
                """
            ),
            {"episode_id": str(episode_id)},
        )
        return [dict(row) for row in result.mappings().all()]
