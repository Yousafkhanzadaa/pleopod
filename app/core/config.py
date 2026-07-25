from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.duration import MAX_GENERATION_DURATION_SECONDS

LOW_COST_GEMINI_TEXT_MODEL = "gemini-2.5-flash-lite"
LOW_COST_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
LOW_COST_IMAGE_MODEL = "imagen-4.0-fast-generate-001"
OPENAI_IMAGE_MODEL = "gpt-image-2"
SQLITE_ASYNC_PREFIX = "sqlite+aiosqlite:///"


def discover_project_root(
    *,
    cwd: Path | None = None,
    module_path: Path | None = None,
) -> Path:
    """Find source assets when the Python package is installed into site-packages."""
    working_directory = (cwd or Path.cwd()).resolve()
    package_file = (module_path or Path(__file__)).resolve()

    for candidate in (working_directory, *working_directory.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    package_directory = package_file.parent
    for candidate in (package_directory, *package_directory.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    return package_file.parents[2]


PROJECT_ROOT = discover_project_root()


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

    storage_backend: Literal["r2", "local", "temporary"] = "local"
    local_storage_path: Path = Path("local-artifacts")
    temporary_storage_path: Path = Path("/tmp/pleopod-artifacts")
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
    gemini_thumbnail_model: str = LOW_COST_GEMINI_TEXT_MODEL
    gemini_text_fallback_model: str | None = LOW_COST_GEMINI_TEXT_MODEL
    gemini_tts_model: str = LOW_COST_GEMINI_TTS_MODEL
    gemini_tts_fallback_model: str | None = LOW_COST_GEMINI_TTS_MODEL
    gemini_image_model: str = LOW_COST_IMAGE_MODEL
    thumbnail_image_provider: Literal["auto", "fake", "gemini", "openai"] = "auto"
    openai_api_key: str | None = None
    openai_image_model: str = OPENAI_IMAGE_MODEL
    openai_image_size: str = "1280x720"
    openai_image_quality: Literal["low", "medium", "high", "auto"] = "medium"
    openai_image_output_format: Literal["png", "jpeg", "webp"] = "png"

    # Professional narration voice. "auto" uses OpenAI gpt-4o-mini-tts when an
    # OpenAI key is present (documentary-grade, directable delivery), falling
    # back to Gemini TTS, and to the fake tone in fake mode.
    voice_provider: Literal["auto", "openai", "gemini", "fake"] = "auto"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "onyx"
    openai_tts_instructions: str = (
        "You are a professional documentary narrator. Deliver the line with a calm, "
        "confident, authoritative tone; warm but serious; clear diction; natural "
        "pacing with subtle emphasis on key facts. Do not rush. No theatrics."
    )
    openai_tts_speed: float = 1.0

    # Word-level caption alignment. Transcribes the final audio to get real
    # per-word timings so captions land exactly on the spoken word instead of
    # being estimated. Best-effort: falls back to estimated timings on failure.
    enable_word_alignment: bool = True
    alignment_model: str = "whisper-1"

    default_category: str = "Tech"
    require_human_approval: bool = False
    max_agent_attempts: int = 3
    queue_visibility_timeout_seconds: int = 900
    queue_poll_seconds: int = 5
    audio_export_format: Literal["mp3", "wav"] = "mp3"

    worker_sleep_seconds: float = 1.0
    tts_generation_mode: Literal["single_request", "chunked"] = "chunked"
    max_tts_chunk_chars: int = 1200

    # Default ffmpeg motion-caption renderer, used when ENABLE_VIDEO_RENDERING=false.
    # It burns animated captions over a Ken Burns background with a waveform and
    # progress bar. It needs only ffmpeg (no headless browser), so it is safe and
    # cheap on small hosts. Caption text needs an ffmpeg built with libass, which
    # the Docker image provides via fonts-dejavu-core.
    video_waveform: bool = True
    video_caption_font_name: str = "DejaVu Sans"
    video_caption_font_path: Path | None = None
    video_caption_max_words: int = 3

    autopublish_topic_model: str = LOW_COST_GEMINI_TEXT_MODEL
    autopublish_category: str = "Tech"
    autopublish_audience: str = "curious tech listeners and software builders"
    autopublish_target_duration_seconds: int = MAX_GENERATION_DURATION_SECONDS
    autopublish_language: str = "en"
    autopublish_tone: str = "clear, smart, conversational, timely"
    autopublish_region: str = "US and global English-language technology news"
    autopublish_recent_job_limit: int = 25
    autopublish_min_source_urls: int = 3
    autopublish_require_trusted_sources: bool = True
    autopublish_trusted_source_domains: str = (
        "openai.com,googleblog.com,blog.google,deepmind.google,ai.google.dev,"
        "developers.googleblog.com,anthropic.com,meta.com,about.fb.com,ai.meta.com,"
        "microsoft.com,blogs.microsoft.com,azure.microsoft.com,github.blog,github.com,"
        "nvidia.com,blogs.nvidia.com,apple.com,amazon.science,aws.amazon.com,x.ai,"
        "perplexity.ai,arxiv.org,nature.com,science.org,nist.gov,nvd.nist.gov,cisa.gov,"
        "sec.gov,ftc.gov,justice.gov,europa.eu,whitehouse.gov,theverge.com,"
        "arstechnica.com,wired.com,technologyreview.com,techcrunch.com,semianalysis.com,"
        "stratechery.com,bloomberg.com,reuters.com,apnews.com,cnbc.com,wsj.com,ft.com,"
        "axios.com,theinformation.com,platformer.news,404media.co,engadget.com,cnet.com,"
        "zdnet.com,venturebeat.com,theregister.com,tomshardware.com,bleepingcomputer.com,"
        "krebsonsecurity.com,securityweek.com,darkreading.com,cyberscoop.com,nytimes.com,"
        "washingtonpost.com,bbc.com,theguardian.com,fortune.com"
    )
    autopublish_trend_source_domains: str = (
        "news.ycombinator.com,github.com,reddit.com,producthunt.com"
    )
    autopublish_lock_ttl_seconds: int = 7200
    autopublish_max_runtime_seconds: int = 7200
    autopublish_created_by: str = "autopublish"

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
        self.temporary_storage_path = resolve_project_path(self.temporary_storage_path)
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

    @property
    def resolved_thumbnail_image_provider(self) -> Literal["fake", "gemini", "openai"]:
        if self.thumbnail_image_provider != "auto":
            return self.thumbnail_image_provider
        if self.ai_provider == "fake":
            return "fake"
        return "openai"

    @property
    def resolved_voice_provider(self) -> Literal["fake", "gemini", "openai"]:
        if self.voice_provider != "auto":
            return self.voice_provider
        if self.ai_provider == "fake":
            return "fake"
        if self.openai_api_key:
            return "openai"
        return "gemini"

    @property
    def resolved_thumbnail_image_model(self) -> str:
        provider = self.resolved_thumbnail_image_provider
        if provider == "openai":
            return self.openai_image_model
        if provider == "fake":
            return "fake-image"
        return self.gemini_image_model

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

    def validate_voice(self) -> None:
        if self.resolved_voice_provider == "openai" and not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required when the voice provider resolves to openai"
            )

    def validate_thumbnail_image(self) -> None:
        provider = self.resolved_thumbnail_image_provider
        if provider == "gemini" and not self.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required when THUMBNAIL_IMAGE_PROVIDER=gemini"
            )
        if provider == "openai" and not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required when THUMBNAIL_IMAGE_PROVIDER resolves to openai"
            )

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
    return discover_project_root() / expanded


def resolve_sqlite_database_url(database_url: str) -> str:
    if not database_url.startswith(SQLITE_ASYNC_PREFIX) or database_url.endswith(":memory:"):
        return database_url

    sqlite_path = Path(database_url.removeprefix(SQLITE_ASYNC_PREFIX))
    if sqlite_path.is_absolute():
        return database_url

    resolved_path = (PROJECT_ROOT / sqlite_path).resolve()
    return f"{SQLITE_ASYNC_PREFIX}{resolved_path.as_posix()}"
