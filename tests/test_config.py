import pytest

from app.core.config import Settings


def test_malformed_database_url_with_unencoded_slash_has_clear_error() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://postgres:abc/def%ghi@db.example.supabase.co:5432/postgres",
    )

    with pytest.raises(RuntimeError, match="percent-encode"):
        settings.validate_database_url()

