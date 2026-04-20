from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import require_admin_request
from app.db.session import get_db_session
from app.providers.storage import ObjectStorage, create_storage


def settings_dep() -> Settings:
    return get_settings()


async def db_session_dep() -> AsyncIterator[AsyncSession]:
    async for session in get_db_session():
        yield session


def storage_dep(settings: Settings = Depends(settings_dep)) -> ObjectStorage:
    return create_storage(settings)


async def admin_dep(request: Request, settings: Settings = Depends(settings_dep)) -> dict:
    return await require_admin_request(request, settings)
