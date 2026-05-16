from pathlib import Path

import pytest

from app.core.config import PROJECT_ROOT, Settings


def test_default_gemini_models_use_low_cost_development_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "GEMINI_ORCHESTRATION_MODEL",
        "GEMINI_RESEARCH_MODEL",
        "GEMINI_SCRIPT_MODEL",
        "GEMINI_VERIFICATION_MODEL",
        "GEMINI_TTS_MODEL",
        "GEMINI_TTS_FALLBACK_MODEL",
        "GEMINI_IMAGE_MODEL",
        "THUMBNAIL_IMAGE_PROVIDER",
        "OPENAI_API_KEY",
        "OPENAI_IMAGE_MODEL",
        "OPENAI_IMAGE_SIZE",
        "OPENAI_IMAGE_QUALITY",
        "OPENAI_IMAGE_OUTPUT_FORMAT",
        "TTS_GENERATION_MODE",
        "TEMPORARY_STORAGE_PATH",
        "AUTOPUBLISH_TOPIC_MODEL",
        "AUTOPUBLISH_REQUIRE_TRUSTED_SOURCES",
        "AUTOPUBLISH_TRUSTED_SOURCE_DOMAINS",
        "AUTOPUBLISH_TREND_SOURCE_DOMAINS",
        "REMOTION_VIDEO_DIRECTOR_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.gemini_orchestration_model == "gemini-2.5-flash-lite"
    assert settings.gemini_research_model == "gemini-2.5-flash-lite"
    assert settings.gemini_script_model == "gemini-2.5-flash-lite"
    assert settings.gemini_verification_model == "gemini-2.5-flash-lite"
    assert settings.gemini_tts_model == "gemini-2.5-flash-preview-tts"
    assert settings.gemini_tts_fallback_model == "gemini-2.5-flash-preview-tts"
    assert settings.gemini_image_model == "imagen-4.0-fast-generate-001"
    assert settings.resolved_thumbnail_image_provider == "fake"
    assert settings.resolved_thumbnail_image_model == "fake-image"
    assert settings.openai_image_model == "gpt-image-2"
    assert settings.openai_image_size == "1280x720"
    assert settings.openai_image_quality == "medium"
    assert settings.tts_generation_mode == "chunked"
    assert settings.autopublish_topic_model == "gemini-2.5-flash-lite"
    assert settings.autopublish_target_duration_seconds == 600
    assert settings.autopublish_min_source_urls == 3
    assert settings.autopublish_require_trusted_sources is True
    assert "openai.com" in settings.autopublish_trusted_source_domains
    assert "news.ycombinator.com" in settings.autopublish_trend_source_domains
    assert settings.remotion_video_director_model == "gemini-2.5-flash-lite"


def test_thumbnail_image_auto_uses_openai_for_real_ai_provider() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        ai_provider="gemini",
        gemini_api_key="gemini-key",
        openai_api_key="openai-key",
    )

    assert settings.resolved_thumbnail_image_provider == "openai"
    assert settings.resolved_thumbnail_image_model == "gpt-image-2"
    settings.validate_ai()
    settings.validate_thumbnail_image()


def test_thumbnail_image_requires_openai_key_when_resolved_to_openai() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        ai_provider="gemini",
        gemini_api_key="gemini-key",
    )

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        settings.validate_thumbnail_image()


def test_default_runtime_is_local_first() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.resolved_database_backend == "sqlite"
    assert settings.resolved_queue_backend == "sqlite"
    assert settings.storage_backend == "local"
    assert settings.async_database_url.startswith("sqlite+aiosqlite:///")
    assert "/local-data/pleopod.db" in settings.async_database_url
    assert str(PROJECT_ROOT) in settings.async_database_url
    assert settings.local_storage_path == PROJECT_ROOT / "local-artifacts"
    assert settings.temporary_storage_path == Path("/tmp/pleopod-artifacts")


def test_relative_runtime_paths_resolve_from_project_root() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="sqlite+aiosqlite:///./local-data/custom.db",
        local_storage_path="local-artifacts",
        temporary_storage_path="tmp-artifacts",
        remotion_renderer_path="remotion-renderer",
        youtube_uploader_path="youtube-uploader",
    )

    assert settings.async_database_url == (
        f"sqlite+aiosqlite:///{(PROJECT_ROOT / 'local-data/custom.db').as_posix()}"
    )
    assert settings.local_storage_path == PROJECT_ROOT / "local-artifacts"
    assert settings.temporary_storage_path == PROJECT_ROOT / "tmp-artifacts"
    assert settings.remotion_renderer_path == PROJECT_ROOT / "remotion-renderer"
    assert settings.youtube_uploader_path == PROJECT_ROOT / "youtube-uploader"


def test_temporary_storage_backend_is_configurable() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        storage_backend="temporary",
        temporary_storage_path="/tmp/custom-pleopod-artifacts",
    )

    assert settings.storage_backend == "temporary"
    assert settings.temporary_storage_path == Path("/tmp/custom-pleopod-artifacts")


def test_postgres_url_selects_postgres_and_pgmq_when_backend_is_auto() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="postgresql://postgres:password@db.example.supabase.co:5432/postgres",
    )

    assert settings.resolved_database_backend == "postgres"
    assert settings.resolved_queue_backend == "pgmq"
    assert settings.async_database_url.startswith("postgresql+asyncpg://")


def test_malformed_database_url_with_unencoded_slash_has_clear_error() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="postgresql://postgres:abc/def%ghi@db.example.supabase.co:5432/postgres",
    )

    with pytest.raises(RuntimeError, match="percent-encode"):
        settings.validate_database_url()


def test_database_url_with_duplicate_env_key_has_clear_error() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="DATABASE_URL=postgresql://postgres:password@db.example.supabase.co:5432/postgres",
    )

    with pytest.raises(RuntimeError, match="literal 'DATABASE_URL=' prefix"):
        settings.validate_database_url()
