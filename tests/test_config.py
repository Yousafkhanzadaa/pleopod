import pytest

from app.core.config import Settings


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
    assert settings.remotion_video_director_model == "gemini-2.5-flash-lite"


def test_default_runtime_is_local_first() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.resolved_database_backend == "sqlite"
    assert settings.resolved_queue_backend == "sqlite"
    assert settings.storage_backend == "local"
    assert settings.async_database_url.startswith("sqlite+aiosqlite:///")


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
