"""Scene + chart director.

Turns a verified script + fact-checked claim bank into a ``ScenePlan``: an
ordered set of presentation scenes, some carrying chart data. Every chart number
is validated against the claim bank so a renderer never draws a figure that is
not backed by a fact-checked claim.

This is engine-agnostic: it produces the plan (JSON contract) that a
presentation renderer (Remotion, Motion Canvas, ...) will draw. It runs on the
project's ``AIProvider`` abstraction, so it works with the fake provider offline
and Gemini in production, and it always degrades to a deterministic fallback
plan when the model output is unusable.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from pydantic import ValidationError

from app.agents.prompts import scene_director_prompt
from app.core.json_utils import parse_model_json
from app.core.text import strip_speaker_labels
from app.providers.ai import AIProvider
from app.schemas.video_plan import (
    PlannedLineTiming,
    PlannedScene,
    PlannedWordTiming,
    SceneChart,
    ScenePlan,
)

logger = logging.getLogger(__name__)

_PREAMBLE_RE = re.compile(
    r"^\s*TTS\s+the\s+following\s+"
    r"(?:conversation\s+between|talk\s+by|monologue\s+by)\s+[^:\n]+:\s*",
    re.IGNORECASE,
)
_DIALOGUE_LINE_RE = re.compile(r"^([^:]{1,48}):\s*(.+)$")
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

MIN_SCENE_SECONDS = 2.0
_BODY_LAYOUTS = ("statement", "bullets", "statement", "diagram")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def plan_video_scenes(
    *,
    script: dict[str, Any],
    claims: list[dict[str, Any]],
    line_timings: list[dict[str, Any]] | None,
    duration_seconds: float,
    category: str,
    ai: AIProvider,
    model: str,
    source_urls: list[str] | None = None,
    word_timings: list[dict[str, Any]] | None = None,
) -> ScenePlan:
    duration = max(1.0, float(duration_seconds))
    timings = _coerce_line_timings(line_timings, script, duration)
    words = _coerce_word_timings(word_timings, duration)
    fallback = build_fallback_scene_plan(
        script=script,
        line_timings=[timing.model_dump() for timing in timings],
        duration_seconds=duration,
        category=category,
        source_urls=source_urls,
        word_timings=[word.model_dump() for word in words],
    )

    try:
        response = await ai.generate_text(
            prompt=scene_director_prompt(
                script,
                claims,
                [timing.model_dump() for timing in timings],
                duration,
                category,
                fallback.model_dump(),
            ),
            model=model,
            response_schema=ScenePlan,
        )
        plan = ScenePlan.model_validate(parse_model_json(response.text, ScenePlan))
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Scene director returned an unusable plan; using fallback: %s", exc)
        return fallback

    plan = plan.model_copy(
        update={
            "duration_seconds": duration,
            "line_timings": timings,
            "word_timings": words,
            "director_model": model,
            "scenes": normalize_scenes(list(plan.scenes), duration),
        }
    )
    return ground_scene_charts(hydrate_source_scenes(plan, source_urls), claims)


def build_fallback_scene_plan(
    *,
    script: dict[str, Any],
    line_timings: list[dict[str, Any]] | None,
    duration_seconds: float,
    category: str,
    source_urls: list[str] | None = None,
    director_model: str = "deterministic-fallback",
    word_timings: list[dict[str, Any]] | None = None,
) -> ScenePlan:
    duration = max(1.0, float(duration_seconds))
    timings = _coerce_line_timings(line_timings, script, duration)
    words = _coerce_word_timings(word_timings, duration)
    title = str(script.get("title") or "Untitled").strip() or "Untitled"
    summary = str(script.get("summary") or "").strip()
    sources = _clean_urls(source_urls or [])

    scenes: list[PlannedScene] = [
        PlannedScene(
            id="scene_title",
            start_seconds=0.0,
            end_seconds=1.0,
            layout="title",
            headline=title[:90],
            subheadline=(summary[:160] or None),
            emphasis="curious",
        )
    ]

    body_count = max(2, min(4, math.ceil(duration / 22)))
    groups = _chunk(timings, body_count)
    for index, group in enumerate(groups):
        layout = _BODY_LAYOUTS[index % len(_BODY_LAYOUTS)]
        headline = _headline_from_group(group) or _headline_from_text(summary or title)
        scenes.append(
            PlannedScene(
                id=f"scene_body_{index + 1}",
                start_seconds=0.0,
                end_seconds=1.0,
                layout="bullets" if layout == "bullets" and group else "statement",
                headline=headline[:90],
                bullets=_bullets_from_group(group) if layout == "bullets" else [],
                caption_line_ids=[timing.id for timing in group],
            )
        )

    scenes.append(
        PlannedScene(
            id="scene_source",
            start_seconds=0.0,
            end_seconds=1.0,
            layout="source" if sources else "outro",
            headline="Sources" if sources else "Thanks for watching",
            source_urls=sources[:4],
            emphasis="reflective",
        )
    )

    return ScenePlan(
        version=1,
        director_model=director_model,
        duration_seconds=duration,
        line_timings=timings,
        word_timings=words,
        scenes=normalize_scenes(scenes, duration),
        production_notes=["Deterministic fallback plan (no chart data extraction)."],
    )


def ground_scene_charts(plan: ScenePlan, claims: list[dict[str, Any]] | None) -> ScenePlan:
    """Drop chart numbers that are not present in the claim bank.

    A chart datum survives only if its value appears as a number in a claim.
    Charts left with too few grounded points are downgraded to a text scene so a
    renderer never draws a fabricated figure.
    """
    claim_numbers = _claim_numbers(claims)
    notes = list(plan.production_notes)
    scenes: list[PlannedScene] = []
    for scene in plan.scenes:
        if scene.layout != "chart" or scene.chart is None:
            scenes.append(scene)
            continue

        chart = scene.chart
        grounded = [datum for datum in chart.data if _value_is_grounded(datum.value, claim_numbers)]
        dropped = len(chart.data) - len(grounded)
        min_points = 1 if chart.type == "stat" else 2

        if len(grounded) >= min_points:
            if chart.type != "stat" and not chart.unit.strip():
                notes.append(
                    f"Scene {scene.id}: chart removed because multiple values had no "
                    "shared unit; rendered as separate facts instead."
                )
                scenes.append(
                    scene.model_copy(
                        update={
                            "layout": "bullets",
                            "bullets": [datum.label for datum in grounded],
                            "chart": None,
                        }
                    )
                )
                continue
            scenes.append(
                scene.model_copy(update={"chart": chart.model_copy(update={"data": grounded})})
            )
            if dropped:
                notes.append(f"Scene {scene.id}: dropped {dropped} ungrounded chart value(s).")
        else:
            notes.append(
                f"Scene {scene.id}: chart removed (only {len(grounded)} grounded value(s)); "
                "downgraded to a statement scene."
            )
            scenes.append(scene.model_copy(update={"layout": "statement", "chart": None}))

    return plan.model_copy(update={"scenes": scenes, "production_notes": notes})


def hydrate_source_scenes(
    plan: ScenePlan,
    source_urls: list[str] | None,
) -> ScenePlan:
    """Populate empty source scenes from the verified source artifact."""
    sources = _clean_urls(source_urls or [])
    if not sources:
        return plan
    scenes = [
        scene.model_copy(
            update={
                "headline": scene.headline or "Sources",
                "source_urls": sources[:4],
            }
        )
        if scene.layout == "source" and not scene.source_urls
        else scene
        for scene in plan.scenes
    ]
    return plan.model_copy(update={"scenes": scenes})


def retime_existing_scene_plan(
    plan: ScenePlan,
    *,
    duration_seconds: float,
    line_timings: list[dict[str, Any]] | None,
    word_timings: list[dict[str, Any]] | None,
    source_urls: list[str] | None,
    claims: list[dict[str, Any]] | None,
) -> ScenePlan:
    """Reuse approved visuals while replacing timing from a regenerated narration."""
    duration = max(1.0, float(duration_seconds))
    retimed = plan.model_copy(
        update={
            "director_model": f"{plan.director_model}:retimed",
            "duration_seconds": duration,
            "line_timings": _coerce_line_timings(line_timings, {}, duration),
            "word_timings": _coerce_word_timings(word_timings, duration),
            "scenes": normalize_scenes(list(plan.scenes), duration),
            "production_notes": [
                *plan.production_notes,
                "Existing grounded visual plan re-timed to regenerated narration.",
            ],
        }
    )
    return ground_scene_charts(hydrate_source_scenes(retimed, source_urls), claims)


def normalize_scenes(scenes: list[PlannedScene], duration_seconds: float) -> list[PlannedScene]:
    """Reflow scenes to cover [0, duration] contiguously with no gaps/overlaps."""
    duration = max(1.0, float(duration_seconds))
    ordered = sorted(
        [scene for scene in scenes if scene.end_seconds >= scene.start_seconds],
        key=lambda scene: scene.start_seconds,
    ) or list(scenes)
    if not ordered:
        return ordered

    total = sum(
        max(MIN_SCENE_SECONDS, scene.end_seconds - scene.start_seconds) for scene in ordered
    )
    total = total or float(len(ordered))
    cursor = 0.0
    reflowed: list[PlannedScene] = []
    for index, scene in enumerate(ordered):
        weight = max(MIN_SCENE_SECONDS, scene.end_seconds - scene.start_seconds) / total
        start = cursor
        if index == len(ordered) - 1:
            end = duration
        else:
            end = min(duration, round(cursor + weight * duration, 2))
            end = max(end, start + 0.5)
        reflowed.append(
            scene.model_copy(
                update={"start_seconds": round(start, 2), "end_seconds": round(end, 2)}
            )
        )
        cursor = reflowed[-1].end_seconds

    reflowed[-1] = reflowed[-1].model_copy(update={"end_seconds": duration})
    return reflowed


# --------------------------------------------------------------------------- #
# Line timings
# --------------------------------------------------------------------------- #


def line_timings_from_segment_timings(
    segment_timings: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build per-line timings from audio segment timings (accurate path)."""
    timings: list[dict[str, Any]] = []
    counter = 1
    for segment in segment_timings or []:
        if not isinstance(segment, dict):
            continue
        start = _to_float(segment.get("start_seconds"))
        end = _to_float(segment.get("end_seconds"))
        if start is None or end is None or end <= start:
            continue
        lines = _parse_dialogue(str(segment.get("source_transcript") or ""))
        if not lines:
            continue
        weights = [max(24, len(line["text"])) for line in lines]
        total = sum(weights) or len(lines)
        elapsed = 0
        span = end - start
        for index, (line, weight) in enumerate(zip(lines, weights, strict=False)):
            line_start = start + span * elapsed / total
            elapsed += weight
            line_end = end if index == len(lines) - 1 else start + span * elapsed / total
            timings.append(
                {
                    "id": f"line_{counter:03d}",
                    "speaker": line["speaker"],
                    "text": line["text"],
                    "start_seconds": round(line_start, 2),
                    "end_seconds": round(line_end, 2),
                }
            )
            counter += 1
    return timings


def approximate_line_timings(
    transcript: str,
    duration_seconds: float,
) -> list[dict[str, Any]]:
    """Estimate per-line timings from the transcript when no audio exists yet."""
    duration = max(1.0, float(duration_seconds))
    dialogue = _parse_dialogue(transcript)
    if not dialogue:
        return []
    total = sum(max(24, len(line["text"])) for line in dialogue) or len(dialogue)
    cursor = 0.0
    timings: list[dict[str, Any]] = []
    for index, line in enumerate(dialogue):
        weight = max(24, len(line["text"])) / total
        start = cursor
        end = (
            duration
            if index == len(dialogue) - 1
            else min(duration, cursor + max(1.5, duration * weight))
        )
        cursor = end
        timings.append(
            {
                "id": f"line_{index + 1:03d}",
                "speaker": line["speaker"],
                "text": line["text"],
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
            }
        )
    return timings


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _coerce_line_timings(
    line_timings: list[dict[str, Any]] | None,
    script: dict[str, Any],
    duration: float,
) -> list[PlannedLineTiming]:
    raw = line_timings or approximate_line_timings(str(script.get("transcript") or ""), duration)
    coerced: list[PlannedLineTiming] = []
    for timing in raw:
        start = _to_float(timing.get("start_seconds"))
        end = _to_float(timing.get("end_seconds"))
        if start is None or end is None:
            continue
        start = min(max(0.0, start), duration)
        end = min(max(0.0, end), duration)
        if end <= start:
            continue
        coerced.append(
            PlannedLineTiming(
                id=str(timing.get("id") or f"line_{len(coerced) + 1:03d}"),
                speaker=str(timing.get("speaker") or ""),
                text=str(timing.get("text") or ""),
                start_seconds=round(start, 2),
                end_seconds=round(end, 2),
            )
        )
    return coerced


def _coerce_word_timings(
    word_timings: list[dict[str, Any]] | None,
    duration: float,
) -> list[PlannedWordTiming]:
    coerced: list[PlannedWordTiming] = []
    for timing in word_timings or []:
        word = str(timing.get("word") or "").strip()
        start = _to_float(timing.get("start_seconds"))
        end = _to_float(timing.get("end_seconds"))
        if not word or start is None or end is None:
            continue
        start = min(max(0.0, start), duration)
        end = min(max(0.0, end), duration)
        if end <= start:
            continue
        coerced.append(
            PlannedWordTiming(
                word=word,
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
            )
        )
    return coerced


def _parse_dialogue(transcript: str) -> list[dict[str, str]]:
    body = _PREAMBLE_RE.sub("", (transcript or "").strip(), count=1).strip()
    lines: list[dict[str, str]] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _DIALOGUE_LINE_RE.match(line)
        if match:
            speaker = match.group(1).strip()
            lines.append(
                {
                    "speaker": speaker,
                    "text": strip_speaker_labels(match.group(2), [speaker]),
                }
            )
        else:
            lines.append({"speaker": "", "text": line})
    return lines


def _chunk(items: list[Any], count: int) -> list[list[Any]]:
    if not items:
        return []
    count = max(1, min(count, len(items)))
    size = math.ceil(len(items) / count)
    return [items[index : index + size] for index in range(0, len(items), size)]


def _headline_from_group(group: list[PlannedLineTiming]) -> str:
    if not group:
        return ""
    return _headline_from_text(group[0].text)


def _headline_from_text(text: str) -> str:
    words = str(text or "").split()
    if not words:
        return "Key point"
    headline = " ".join(words[:7])
    return f"{headline}..." if len(words) > 7 else headline


def _bullets_from_group(group: list[PlannedLineTiming]) -> list[str]:
    bullets: list[str] = []
    for timing in group[:3]:
        words = timing.text.split()
        if not words:
            continue
        bullet = " ".join(words[:6])
        bullets.append(f"{bullet}..." if len(words) > 6 else bullet)
    return bullets


def _clean_urls(urls: list[Any]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for url in urls:
        value = str(url or "").strip()
        if not value or not re.match(r"^https?://", value, flags=re.IGNORECASE):
            continue
        key = value.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return cleaned


def _claim_numbers(claims: list[dict[str, Any]] | None) -> set[float]:
    numbers: set[float] = set()
    for claim in claims or []:
        if isinstance(claim, dict):
            text = str(claim.get("claim_text") or claim.get("claim") or claim.get("text") or "")
        else:
            text = str(claim or "")
        for token in _NUMBER_RE.findall(text):
            try:
                numbers.add(float(token.replace(",", "")))
            except ValueError:
                continue
    return numbers


def _value_is_grounded(value: float, claim_numbers: set[float]) -> bool:
    return any(abs(value - number) <= max(0.001, abs(number) * 1e-4) for number in claim_numbers)


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


# Re-exported for callers that build charts programmatically in tests.
__all__ = [
    "SceneChart",
    "ScenePlan",
    "approximate_line_timings",
    "build_fallback_scene_plan",
    "ground_scene_charts",
    "line_timings_from_segment_timings",
    "normalize_scenes",
    "plan_video_scenes",
]
