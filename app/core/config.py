from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    database_url: str = Field(default="postgresql://postgres:postgres@localhost:5432/postgres")
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
    gemini_research_model: str = "gemini-2.5-flash"
    gemini_script_model: str = "gemini-2.5-flash"
    gemini_verification_model: str = "gemini-2.5-flash"
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    gemini_tts_fallback_model: str | None = "gemini-2.5-flash-preview-tts"
    gemini_image_model: str = "gemini-2.5-flash-image"

    default_category: str = "Tech"
    require_human_approval: bool = False
    max_agent_attempts: int = 3
    queue_visibility_timeout_seconds: int = 900
    queue_poll_seconds: int = 5
    audio_export_format: Literal["mp3", "wav"] = "mp3"

    worker_sleep_seconds: float = 1.0
    max_tts_chunk_chars: int = 1200

    @computed_field  # type: ignore[misc]
    @property
    def async_database_url(self) -> str:
        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url
        if self.database_url.startswith("postgres://"):
            return self.database_url.replace("postgres://", "postgresql+asyncpg://", 1)
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url

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
        if parsed.scheme not in {"postgresql", "postgres", "postgresql+asyncpg"}:
            raise RuntimeError("DATABASE_URL must be a Postgres connection string")

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
    return Settings()
