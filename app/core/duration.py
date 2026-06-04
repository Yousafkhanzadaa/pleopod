from __future__ import annotations

from typing import Any

MIN_GENERATION_DURATION_SECONDS = 30
MAX_GENERATION_DURATION_SECONDS = 90
MAX_VIDEO_DURATION_SECONDS = MAX_GENERATION_DURATION_SECONDS


def clamp_generation_duration_seconds(
    value: Any,
    *,
    default: int = MAX_GENERATION_DURATION_SECONDS,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(
        MIN_GENERATION_DURATION_SECONDS,
        min(parsed, MAX_GENERATION_DURATION_SECONDS),
    )


def clamp_video_duration_seconds(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = MAX_VIDEO_DURATION_SECONDS
    return max(5, min(parsed, MAX_VIDEO_DURATION_SECONDS))
