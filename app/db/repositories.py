from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.interfaces import (
    ArtifactStore,
    EpisodeStore,
    JobStore,
    KnowledgeStore,
    TTSSegmentStore,
)

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


def _dialect_name(session: AsyncSession) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else ""


def _is_sqlite(session: AsyncSession) -> bool:
    return _dialect_name(session) == "sqlite"


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _json_dumps(value: Any, default: Any) -> str:
    return json.dumps(value if value is not None else default)


def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_dict(
    row: Any,
    json_fields: tuple[str, ...] = (),
    bool_fields: tuple[str, ...] = (),
) -> dict:
    data = dict(row)
    for field in json_fields:
        if field in data:
            data[field] = _json_loads(data[field], [] if field.endswith("urls") else {})
    for field in bool_fields:
        if field in data and data[field] is not None:
            data[field] = bool(data[field])
    return data


def _json_cast(session: AsyncSession, name: str) -> str:
    return f":{name}" if _is_sqlite(session) else f"cast(:{name} as jsonb)"


def _updated_at_sql(session: AsyncSession) -> str:
    return "CURRENT_TIMESTAMP" if _is_sqlite(session) else "now()"


class JobRepository(JobStore):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_job(
        self, payload: dict[str, Any], created_by: str | None = None
    ) -> dict[str, Any]:
        sqlite = _is_sqlite(self.session)
        columns = """
          topic, category, audience, target_duration_seconds, language, tone,
          source_urls, auto_publish, metadata, created_by
        """
        values = f"""
          :topic, :category, :audience, :target_duration_seconds, :language, :tone,
          {_json_cast(self.session, "source_urls")}, :auto_publish,
          {_json_cast(self.session, "metadata")}, :created_by
        """
        params = {
            **payload,
            "source_urls": _json_dumps(payload.get("source_urls", []), []),
            "metadata": _json_dumps(payload.get("metadata", {}), {}),
            "auto_publish": bool(payload.get("auto_publish", False)),
            "created_by": created_by,
        }
        if sqlite:
            columns = f"id, {columns}"
            values = f":id, {values}"
            params["id"] = str(uuid4())

        result = await self.session.execute(
            text(
                f"""
                insert into generation_jobs ({columns})
                values ({values})
                returning *
                """
            ),
            params,
        )
        await self.session.commit()
        return _row_dict(
            result.mappings().one(),
            json_fields=("source_urls", "metadata"),
            bool_fields=("auto_publish",),
        )

    async def get_job(self, job_id: UUID | str) -> dict[str, Any] | None:
        result = await self.session.execute(
            text("select * from generation_jobs where id = :job_id"),
            {"job_id": str(job_id)},
        )
        row = result.mappings().first()
        return (
            _row_dict(row, json_fields=("source_urls", "metadata"), bool_fields=("auto_publish",))
            if row
            else None
        )

    async def list_jobs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text(
                "select * from generation_jobs order by created_at desc limit :limit offset :offset"
            ),
            {"limit": limit, "offset": offset},
        )
        return [
            _row_dict(row, json_fields=("source_urls", "metadata"), bool_fields=("auto_publish",))
            for row in result.mappings().all()
        ]

    async def update_job(self, job_id: UUID | str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return await self.get_job(job_id)

        json_fields = {"metadata", "source_urls"}
        bool_fields = {"auto_publish"}
        params: dict[str, Any] = {"job_id": str(job_id)}
        assignments_list: list[str] = []
        for key, value in fields.items():
            if key in json_fields:
                assignments_list.append(f"{key} = {_json_cast(self.session, key)}")
                params[key] = _json_dumps(value, [] if key == "source_urls" else {})
            elif key in bool_fields:
                assignments_list.append(f"{key} = :{key}")
                params[key] = bool(value)
            else:
                assignments_list.append(f"{key} = :{key}")
                params[key] = _enum_value(value)

        assignments = ", ".join(assignments_list)
        result = await self.session.execute(
            text(
                f"""
                update generation_jobs
                set {assignments}, updated_at = {_updated_at_sql(self.session)}
                where id = :job_id
                returning *
                """
            ),
            params,
        )
        await self.session.commit()
        row = result.mappings().first()
        return (
            _row_dict(row, json_fields=("source_urls", "metadata"), bool_fields=("auto_publish",))
            if row
            else None
        )

    async def create_agent_run(
        self,
        job_id: UUID | str,
        agent_name: str,
        step: str,
        model: str | None,
        input_artifact_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        sqlite = _is_sqlite(self.session)
        columns = "job_id, agent_name, step, status, model, input_artifact_id"
        values = ":job_id, :agent_name, :step, 'running', :model, :input_artifact_id"
        params = {
            "job_id": str(job_id),
            "agent_name": agent_name,
            "step": _enum_value(step),
            "model": model,
            "input_artifact_id": str(input_artifact_id) if input_artifact_id else None,
        }
        if sqlite:
            columns = f"id, {columns}"
            values = f":id, {values}"
            params["id"] = str(uuid4())

        result = await self.session.execute(
            text(
                f"""
                insert into agent_runs ({columns})
                values ({values})
                returning *
                """
            ),
            params,
        )
        await self.session.commit()
        return _row_dict(result.mappings().one(), json_fields=("usage",))

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
                f"""
                update agent_runs
                set status = :status,
                    output_artifact_id = :output_artifact_id,
                    error = :error,
                    usage = {_json_cast(self.session, "usage")},
                    completed_at = {_updated_at_sql(self.session)}
                where id = :run_id
                """
            ),
            {
                "run_id": str(run_id),
                "status": _enum_value(status),
                "output_artifact_id": str(output_artifact_id) if output_artifact_id else None,
                "error": error,
                "usage": _json_dumps(usage or {}, {}),
            },
        )
        await self.session.commit()

    async def list_agent_runs(self, job_id: UUID | str) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text("select * from agent_runs where job_id = :job_id order by started_at asc"),
            {"job_id": str(job_id)},
        )
        return [_row_dict(row, json_fields=("usage",)) for row in result.mappings().all()]


class ArtifactRepository(ArtifactStore):
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
        sqlite = _is_sqlite(self.session)
        columns = """
          job_id, episode_id, artifact_type, r2_key, mime_type,
          size_bytes, checksum_sha256, metadata
        """
        values = f"""
          :job_id, :episode_id, :artifact_type, :r2_key, :mime_type,
          :size_bytes, :checksum_sha256, {_json_cast(self.session, "metadata")}
        """
        params = {
            "job_id": str(job_id) if job_id else None,
            "episode_id": str(episode_id) if episode_id else None,
            "artifact_type": _enum_value(artifact_type),
            "r2_key": r2_key,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "checksum_sha256": checksum_sha256,
            "metadata": _json_dumps(metadata or {}, {}),
        }
        if sqlite:
            columns = f"id, {columns}"
            values = f":id, {values}"
            params["id"] = str(uuid4())

        result = await self.session.execute(
            text(
                f"""
                insert into artifacts ({columns})
                values ({values})
                returning *
                """
            ),
            params,
        )
        await self.session.commit()
        return _row_dict(result.mappings().one(), json_fields=("metadata",))

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
            {"job_id": str(job_id), "artifact_type": _enum_value(artifact_type)},
        )
        row = result.mappings().first()
        return _row_dict(row, json_fields=("metadata",)) if row else None

    async def list_for_job(self, job_id: UUID | str) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text("select * from artifacts where job_id = :job_id order by created_at asc"),
            {"job_id": str(job_id)},
        )
        return [_row_dict(row, json_fields=("metadata",)) for row in result.mappings().all()]


class KnowledgeRepository(KnowledgeStore):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_sources(self, job_id: UUID | str, sources: list[dict[str, Any]]) -> None:
        await self.session.execute(
            text("delete from sources where job_id = :job_id"), {"job_id": str(job_id)}
        )
        if sources:
            sqlite = _is_sqlite(self.session)
            columns = """
              job_id, url, title, publisher, author, published_at, retrieved_at,
              source_tier, credibility_score, notes
            """
            values = """
              :job_id, :url, :title, :publisher, :author, :published_at, CURRENT_TIMESTAMP,
              :source_tier, :credibility_score, :notes
            """
            if sqlite:
                columns = f"id, {columns}"
                values = f":id, {values}"
            await self.session.execute(
                text(
                    f"""
                    insert into sources ({columns})
                    values ({values})
                    on conflict do nothing
                    """
                ),
                [self._source_params(job_id, source) for source in sources],
            )
        await self.session.commit()

    def _source_params(self, job_id: UUID | str, source: dict[str, Any]) -> dict[str, Any]:
        params = {
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
        if _is_sqlite(self.session):
            params["id"] = str(uuid4())
            if isinstance(params["published_at"], datetime):
                params["published_at"] = params["published_at"].isoformat()
        return params

    async def replace_claims(self, job_id: UUID | str, claims: list[dict[str, Any]]) -> None:
        await self.session.execute(
            text("delete from claims where job_id = :job_id"), {"job_id": str(job_id)}
        )
        if claims:
            sqlite = _is_sqlite(self.session)
            columns = """
              job_id, claim_text, source_urls, verification_status,
              confidence, notes, used_in_script
            """
            values = f"""
              :job_id, :claim_text, {_json_cast(self.session, "source_urls")},
              :verification_status, :confidence, :notes, :used_in_script
            """
            if sqlite:
                columns = f"id, {columns}"
                values = f":id, {values}"
            await self.session.execute(
                text(
                    f"""
                    insert into claims ({columns})
                    values ({values})
                    on conflict do nothing
                    """
                ),
                [
                    {
                        **({"id": str(uuid4())} if sqlite else {}),
                        "job_id": str(job_id),
                        "claim_text": claim["claim_text"],
                        "source_urls": _json_dumps(claim.get("source_urls", []), []),
                        "verification_status": normalize_claim_verification_status(
                            claim.get("verification_status")
                        ),
                        "confidence": claim.get("confidence"),
                        "notes": claim.get("notes"),
                        "used_in_script": bool(claim.get("used_in_script", False)),
                    }
                    for claim in claims
                ],
            )
        await self.session.commit()


class EpisodeRepository(EpisodeStore):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_episode(self, payload: dict[str, Any]) -> dict[str, Any]:
        sqlite = _is_sqlite(self.session)
        status = _enum_value(payload["status"])
        columns = """
          generation_job_id, title, slug, category, status, summary, description,
          duration_seconds, language, metadata, published_at
        """
        values = f"""
          :generation_job_id, :title, :slug, :category, :status, :summary, :description,
          :duration_seconds, :language, {_json_cast(self.session, "metadata")},
          case when :status = 'published' then {_updated_at_sql(self.session)} else null end
        """
        if sqlite:
            columns = f"id, {columns}"
            values = f":id, {values}"

        result = await self.session.execute(
            text(
                f"""
                insert into episodes ({columns})
                values ({values})
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
                                  then coalesce(
                                    episodes.published_at,
                                    {_updated_at_sql(self.session)}
                                  )
                                else episodes.published_at
                              end,
                              updated_at = {_updated_at_sql(self.session)}
                where episodes.generation_job_id = excluded.generation_job_id
                returning *
                """
            ),
            {
                **({"id": str(uuid4())} if sqlite else {}),
                **payload,
                "status": status,
                "generation_job_id": str(payload["generation_job_id"]),
                "metadata": _json_dumps(payload.get("metadata", {}), {}),
            },
        )
        await self.session.commit()
        row = result.mappings().first()
        if row:
            return _row_dict(row, json_fields=("metadata",))
        raise RuntimeError(f"Episode slug already exists for another job: {payload['slug']}")

    async def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        sqlite = _is_sqlite(self.session)
        columns = """
          episode_id, asset_type, r2_key, public_url, mime_type,
          size_bytes, checksum_sha256, metadata
        """
        values = f"""
          :episode_id, :asset_type, :r2_key, :public_url, :mime_type,
          :size_bytes, :checksum_sha256, {_json_cast(self.session, "metadata")}
        """
        if sqlite:
            columns = f"id, {columns}"
            values = f":id, {values}"

        result = await self.session.execute(
            text(
                f"""
                insert into episode_assets ({columns})
                values ({values})
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
            {
                **({"id": str(uuid4())} if sqlite else {}),
                **payload,
                "episode_id": str(payload["episode_id"]),
                "metadata": _json_dumps(payload.get("metadata", {}), {}),
            },
        )
        await self.session.commit()
        return _row_dict(result.mappings().one(), json_fields=("metadata",))

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
        return [_row_dict(row, json_fields=("metadata",)) for row in result.mappings().all()]

    async def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            text("select * from episodes where slug = :slug and status = 'published'"),
            {"slug": slug},
        )
        row = result.mappings().first()
        return _row_dict(row, json_fields=("metadata",)) if row else None

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
        return [_row_dict(row, json_fields=("metadata",)) for row in result.mappings().all()]

    async def get_assets_for_episodes(
        self, episode_ids: list[UUID | str]
    ) -> dict[str, list[dict[str, Any]]]:
        if not episode_ids:
            return {}

        stmt = text(
            """
            select *
            from episode_assets
            where episode_id in :episode_ids
            order by episode_id, created_at asc
            """
        ).bindparams(bindparam("episode_ids", expanding=True))
        result = await self.session.execute(
            stmt,
            {"episode_ids": [str(episode_id) for episode_id in episode_ids]},
        )
        assets_by_episode: dict[str, list[dict[str, Any]]] = {}
        for row in result.mappings().all():
            asset = _row_dict(row, json_fields=("metadata",))
            assets_by_episode.setdefault(str(asset["episode_id"]), []).append(asset)
        return assets_by_episode


class TTSSegmentRepository(TTSSegmentStore):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_completed_segment_key(
        self, job_id: UUID | str, index: int, transcript: str | None = None
    ) -> str | None:
        result = await self.session.execute(
            text(
                """
                select r2_key
                from tts_segments
                where job_id = :job_id
                  and segment_index = :segment_index
                  and status = 'completed'
                  and r2_key is not null
                  and (:transcript is null or transcript = :transcript)
                """
            ),
            {"job_id": str(job_id), "segment_index": index, "transcript": transcript},
        )
        row = result.mappings().first()
        return str(row["r2_key"]) if row else None

    async def upsert_segment(
        self,
        job_id: UUID | str,
        index: int,
        transcript: str,
        status: str,
        r2_key: str | None = None,
    ) -> None:
        sqlite = _is_sqlite(self.session)
        columns = "job_id, segment_index, transcript, status, r2_key, mime_type"
        values = ":job_id, :segment_index, :transcript, :status, :r2_key, 'audio/wav'"
        if sqlite:
            columns = f"id, {columns}"
            values = f":id, {values}"
        await self.session.execute(
            text(
                f"""
                insert into tts_segments ({columns})
                values ({values})
                on conflict (job_id, segment_index)
                do update set status = excluded.status,
                              transcript = excluded.transcript,
                              r2_key = coalesce(excluded.r2_key, tts_segments.r2_key),
                              updated_at = {_updated_at_sql(self.session)}
                """
            ),
            {
                **({"id": str(uuid4())} if sqlite else {}),
                "job_id": str(job_id),
                "segment_index": index,
                "transcript": transcript,
                "status": status,
                "r2_key": r2_key,
            },
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
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    raise TypeError(f"Expected datetime, ISO datetime string, or None, got {type(value)!r}")
