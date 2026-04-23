from types import SimpleNamespace

from scripts.generate_podcast import (
    BACKEND_MAX_TONE_CHARS,
    BACKEND_MIN_DURATION_SECONDS,
    SMOKE_TEST_MAX_DURATION_SECONDS,
    SMOKE_TEST_MIN_DURATION_SECONDS,
    backend_request_duration_seconds,
    build_smoke_test_tone,
    create_job,
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


def test_create_job_uses_title_for_orchestration_entrypoint() -> None:
    captured: dict[str, object] = {}

    class _Client:
        def post(self, path: str, json: dict, headers: dict, timeout: int) -> SimpleNamespace:
            captured["path"] = path
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"id": "job-1"},
            )

    args = SimpleNamespace(
        title="AI Coding Agents in 2026",
        category="Tech",
        audience="curious tech listeners",
        duration=60,
        language="en",
        tone="clear, smart, conversational",
        source_url=[],
        draft=False,
    )

    create_job(_Client(), args, "admin-secret")

    assert captured["path"] == "/admin/generation-jobs"
    assert captured["json"]["title"] == "AI Coding Agents in 2026"
    assert "topic" not in captured["json"]
