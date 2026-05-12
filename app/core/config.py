from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

LOW_COST_GEMINI_TEXT_MODEL = "gemini-2.5-flash-lite"
LOW_COST_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
LOW_COST_IMAGE_MODEL = "imagen-4.0-fast-generate-001"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQLITE_ASYNC_PREFIX = "sqlite+aiosqlite:///"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    admin_api_key: str | None = None

    database_backend: Literal["auto", "sqlite", "postgres"] = "auto"
    queue_backend: Literal["auto", "sqlite", "pgmq"] = "auto"
    database_url: str = Field(default="sqlite+aiosqlite:///./local-data/pleopod.db")
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_publishable_key: str | None = None
    supabase_secret_key: str | None = None
    supabase_jwks_url: str | None = None
    supabase_jwks_json: str | None = None
    supabase_legacy_jwt_secret: str | None = None

    storage_backend: Literal["r2", "local"] = "local"
    local_storage_path: Path = Path("local-artifacts")
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket_name: str | None = None
    r2_public_base_url: str | None = None

    ai_provider: Literal["gemini", "fake"] = "fake"
    gemini_api_key: str | None = None
    gemini_orchestration_model: str = LOW_COST_GEMINI_TEXT_MODEL
    gemini_research_model: str = LOW_COST_GEMINI_TEXT_MODEL
    gemini_script_model: str = LOW_COST_GEMINI_TEXT_MODEL
    gemini_verification_model: str = LOW_COST_GEMINI_TEXT_MODEL
    gemini_tts_model: str = LOW_COST_GEMINI_TTS_MODEL
    gemini_tts_fallback_model: str | None = LOW_COST_GEMINI_TTS_MODEL
    gemini_image_model: str = LOW_COST_IMAGE_MODEL

    default_category: str = "Tech"
    require_human_approval: bool = False
    max_agent_attempts: int = 3
    queue_visibility_timeout_seconds: int = 900
    queue_poll_seconds: int = 5
    audio_export_format: Literal["mp3", "wav"] = "mp3"

    worker_sleep_seconds: float = 1.0
    max_tts_chunk_chars: int = 1200

    enable_video_rendering: bool = False
    remotion_renderer_path: Path = Path("remotion-renderer")
    remotion_video_director_model: str = LOW_COST_GEMINI_TEXT_MODEL
    remotion_render_timeout_seconds: int = 1800
    remotion_render_output_format: Literal["mp4"] = "mp4"

    enable_youtube_uploading: bool = False
    youtube_uploader_path: Path = Path("youtube-uploader")
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    youtube_refresh_token: str | None = None
    youtube_default_privacy_status: Literal["private", "unlisted", "public"] = "private"
    youtube_default_category_id: str = "28"
    youtube_upload_timeout_seconds: int = 3600
    youtube_notify_subscribers: bool = False
    youtube_self_declared_made_for_kids: bool = False

    def model_post_init(self, __context: Any) -> None:
        self.local_storage_path = resolve_project_path(self.local_storage_path)
        self.remotion_renderer_path = resolve_project_path(self.remotion_renderer_path)
        self.youtube_uploader_path = resolve_project_path(self.youtube_uploader_path)

    @computed_field  # type: ignore[misc]
    @property
    def async_database_url(self) -> str:
        if self.database_url.startswith("sqlite+aiosqlite://"):
            return resolve_sqlite_database_url(self.database_url)
        if self.database_url.startswith("sqlite://"):
            return resolve_sqlite_database_url(
                self.database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
            )
        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url
        if self.database_url.startswith("postgres://"):
            return self.database_url.replace("postgres://", "postgresql+asyncpg://", 1)
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url

    @property
    def resolved_database_backend(self) -> Literal["sqlite", "postgres"]:
        if self.database_backend != "auto":
            return self.database_backend
        if self.database_url.startswith(("sqlite://", "sqlite+aiosqlite://")):
            return "sqlite"
        return "postgres"

    @property
    def resolved_queue_backend(self) -> Literal["sqlite", "pgmq"]:
        if self.queue_backend != "auto":
            return self.queue_backend
        return "sqlite" if self.resolved_database_backend == "sqlite" else "pgmq"

    @computed_field  # type: ignore[misc]
    @property
    def r2_endpoint_url(self) -> str | None:
        if not self.r2_account_id:
            return None
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    @computed_field  # type: ignore[misc]
    @property
    def resolved_supabase_jwks_url(self) -> str | None:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if not self.supabase_url:
            return None
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    def validate_storage(self) -> None:
        if self.storage_backend != "r2":
            return
        missing = [
            name
            for name in (
                "r2_account_id",
                "r2_access_key_id",
                "r2_secret_access_key",
                "r2_bucket_name",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise RuntimeError(f"Missing R2 settings: {', '.join(missing)}")

    def validate_ai(self) -> None:
        if self.ai_provider == "gemini" and not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required when AI_PROVIDER=gemini")

    def validate_database_url(self) -> None:
        if self.database_url.startswith("DATABASE_URL="):
            raise RuntimeError(
                "DATABASE_URL value includes the literal 'DATABASE_URL=' prefix. "
                "In .env.local, the line should be DATABASE_URL=postgresql://... "
                "not DATABASE_URL=DATABASE_URL=postgresql://..."
            )

        parsed = urlparse(self.database_url)
        sqlite_scheme = parsed.scheme in {"sqlite", "sqlite+aiosqlite"}
        postgres_scheme = parsed.scheme in {"postgresql", "postgres", "postgresql+asyncpg"}
        if not sqlite_scheme and not postgres_scheme:
            raise RuntimeError("DATABASE_URL must be a Postgres or SQLite connection string")

        if sqlite_scheme:
            if self.resolved_database_backend != "sqlite":
                raise RuntimeError("SQLite DATABASE_URL requires DATABASE_BACKEND=sqlite or auto")
            if self.resolved_queue_backend != "sqlite":
                raise RuntimeError("SQLite DATABASE_URL requires QUEUE_BACKEND=sqlite or auto")
            return

        if self.resolved_database_backend != "postgres":
            raise RuntimeError("Postgres DATABASE_URL requires DATABASE_BACKEND=postgres or auto")
        if self.resolved_queue_backend != "pgmq":
            raise RuntimeError("Postgres DATABASE_URL requires QUEUE_BACKEND=pgmq or auto")

        try:
            _ = parsed.port
        except ValueError as exc:
            raise RuntimeError(
                "DATABASE_URL is malformed. If your Supabase password contains "
                "special characters like '/', '%', '@', ':', '#', or '?', percent-encode "
                "the password before putting it into the connection string."
            ) from exc

        if not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
            raise RuntimeError(
                "DATABASE_URL is incomplete. Expected a URL like "
                "postgresql://postgres.project-ref:<encoded-password>@host:5432/postgres"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local"))  # type: ignore[call-arg]


def resolve_project_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return PROJECT_ROOT / expanded


def resolve_sqlite_database_url(database_url: str) -> str:
    if not database_url.startswith(SQLITE_ASYNC_PREFIX) or database_url.endswith(":memory:"):
        return database_url

    sqlite_path = Path(database_url.removeprefix(SQLITE_ASYNC_PREFIX))
    if sqlite_path.is_absolute():
        return database_url

    resolved_path = (PROJECT_ROOT / sqlite_path).resolve()
    return f"{SQLITE_ASYNC_PREFIX}{resolved_path.as_posix()}"
