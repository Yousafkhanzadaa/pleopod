from scripts.generate_podcast import (
    BACKEND_MAX_TONE_CHARS,
    BACKEND_MIN_DURATION_SECONDS,
    SMOKE_TEST_MAX_DURATION_SECONDS,
    SMOKE_TEST_MIN_DURATION_SECONDS,
    backend_request_duration_seconds,
    build_smoke_test_tone,
    smoke_test_duration_seconds,
)


def test_backend_request_duration_seconds_respects_backend_minimum() -> None:
    assert backend_request_duration_seconds(60) == BACKEND_MIN_DURATION_SECONDS


def test_smoke_test_duration_seconds_clamps_upper_bound() -> None:
    assert smoke_test_duration_seconds(300) == SMOKE_TEST_MAX_DURATION_SECONDS


def test_smoke_test_duration_seconds_clamps_lower_bound() -> None:
    assert smoke_test_duration_seconds(5) == SMOKE_TEST_MIN_DURATION_SECONDS


def test_build_smoke_test_tone_adds_strict_brevity_instruction() -> None:
    tone = build_smoke_test_tone("clear, smart, conversational", 60)

    assert "~60s" in tone
    assert "<= 140 words" in tone
    assert "<= 6 turns" in tone
    assert tone.startswith("clear, smart, conversational.")


def test_build_smoke_test_tone_respects_backend_limit() -> None:
    tone = build_smoke_test_tone("x" * 300, 60)

    assert len(tone) <= BACKEND_MAX_TONE_CHARS
    assert "~60s" in tone
