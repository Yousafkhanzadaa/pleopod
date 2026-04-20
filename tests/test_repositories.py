from datetime import UTC, datetime

import pytest

from app.db.repositories import parse_optional_datetime


def test_parse_optional_datetime_accepts_zulu_iso_string() -> None:
    assert parse_optional_datetime("2026-04-19T00:00:00Z") == datetime(
        2026, 4, 19, tzinfo=UTC
    )


def test_parse_optional_datetime_accepts_none() -> None:
    assert parse_optional_datetime(None) is None


def test_parse_optional_datetime_rejects_unknown_type() -> None:
    with pytest.raises(TypeError):
        parse_optional_datetime(123)

