from datetime import UTC, datetime

import pytest

from app.db.repositories import normalize_claim_verification_status, parse_optional_datetime


def test_parse_optional_datetime_accepts_zulu_iso_string() -> None:
    assert parse_optional_datetime("2026-04-19T00:00:00Z") == datetime(
        2026, 4, 19, tzinfo=UTC
    )


def test_parse_optional_datetime_accepts_none() -> None:
    assert parse_optional_datetime(None) is None


def test_parse_optional_datetime_rejects_unknown_type() -> None:
    with pytest.raises(TypeError):
        parse_optional_datetime(123)


def test_normalize_claim_verification_status_maps_model_aliases() -> None:
    assert normalize_claim_verification_status("weakly_supported") == "needs_context"
    assert normalize_claim_verification_status("not supported") == "unsupported"
    assert normalize_claim_verification_status("supported") == "supported"
    assert normalize_claim_verification_status("surprising_new_label") == "unverified"
