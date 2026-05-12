from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.db.sqlite_schema import SQLITE_SCHEMA


def _sqlite_path(database_url: str) -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix) or database_url.endswith(":memory:"):
        return None
    path = Path(database_url.removeprefix(prefix))
    return path if path.is_absolute() else Path.cwd() / path


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    settings = settings or get_settings()
    settings.validate_database_url()
    database_url = settings.async_database_url
    sqlite_path = _sqlite_path(database_url)
    if sqlite_path:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    if settings.resolved_database_backend == "sqlite":
        engine = create_async_engine(database_url, pool_pre_ping=True)

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        return engine

    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_initialized_database_url: str | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings)
    return _engine


def get_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(settings), expire_on_commit=False)
    return _sessionmaker


async def initialize_database(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.resolved_database_backend != "sqlite":
        return

    global _initialized_database_url
    database_url = settings.async_database_url
    if _initialized_database_url == database_url:
        return

    engine = get_engine(settings)
    async with engine.begin() as conn:
        for statement in SQLITE_SCHEMA:
            await conn.execute(text(statement))
    _initialized_database_url = database_url


async def get_db_session() -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    await initialize_database(settings)
    async with get_sessionmaker(settings)() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker, _initialized_database_url
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
    _initialized_database_url = None
