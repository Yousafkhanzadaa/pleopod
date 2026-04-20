from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session_dep, storage_dep
from app.db.repositories import EpisodeRepository
from app.providers.storage import ObjectStorage
from app.schemas.episodes import EpisodeResponse, StreamUrlResponse

router = APIRouter(prefix="/episodes", tags=["episodes"])


async def _with_assets(session: AsyncSession, episode: dict) -> dict:
    assets = await EpisodeRepository(session).get_assets(episode["id"])
    episode["assets"] = assets
    return episode


@router.get("", response_model=list[EpisodeResponse])
async def list_episodes(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session_dep),
) -> list[dict]:
    repo = EpisodeRepository(session)
    episodes = await repo.list_published(limit=limit, offset=offset)
    return [await _with_assets(session, episode) for episode in episodes]


@router.get("/{slug}", response_model=EpisodeResponse)
async def get_episode(
    slug: str,
    session: AsyncSession = Depends(db_session_dep),
) -> dict:
    episode = await EpisodeRepository(session).get_by_slug(slug)
    if not episode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")
    return await _with_assets(session, episode)


@router.get("/{episode_id}/stream-url", response_model=StreamUrlResponse)
async def get_stream_url(
    episode_id: UUID,
    session: AsyncSession = Depends(db_session_dep),
    storage: ObjectStorage = Depends(storage_dep),
) -> StreamUrlResponse:
    assets = await EpisodeRepository(session).get_assets(episode_id)
    audio = next((asset for asset in assets if asset["asset_type"] == "audio"), None)
    if not audio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio asset not found")
    if audio.get("public_url"):
        return StreamUrlResponse(
            episode_id=episode_id, audio_url=audio["public_url"], expires_in_seconds=None
        )
    url = await storage.presigned_get_url(audio["r2_key"], expires_in=3600)
    return StreamUrlResponse(episode_id=episode_id, audio_url=url, expires_in_seconds=3600)
