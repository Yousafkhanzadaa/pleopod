from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agents.video_director import (
    approximate_line_timings,
    build_fallback_scene_plan,
    ground_scene_charts,
    hydrate_source_scenes,
    line_timings_from_segment_timings,
    normalize_scenes,
    plan_video_scenes,
    retime_existing_scene_plan,
)
from app.models.enums import ArtifactType
from app.providers.ai import TextGeneration
from app.providers.fake import FakeAIProvider
from app.schemas.video_plan import ChartDatum, PlannedScene, SceneChart, ScenePlan
from app.worker.scene_plan_runner import build_scene_plan_for_job


def _script() -> dict:
    return {
        "title": "The AI Media Pipeline",
        "summary": "A short talk about trustworthy AI media.",
        "transcript": (
            "TTS the following talk by Arman:\n\n"
            "Arman: Welcome back, today we unpack the pipeline.\n"
            "Arman: Research first, then verify every important claim.\n"
            "Arman: Each stage leaves an artifact you can inspect.\n"
            "Arman: Then the worker connects the pieces into a flow."
        ),
    }


class _StubAI(FakeAIProvider):
    """Returns a fixed generate_text payload; reuses fake image/tts."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: object | None = None,
    ) -> TextGeneration:
        return TextGeneration(text=self._text)


# --------------------------------------------------------------------------- #
# Line timings
# --------------------------------------------------------------------------- #


def test_approximate_line_timings_are_ordered_and_fill_duration() -> None:
    timings = approximate_line_timings(
        "Arman: hello world here.\nArman: a second spoken line.", 20
    )
    assert [t["id"] for t in timings] == ["line_001", "line_002"]
    assert timings[0]["start_seconds"] == 0.0
    assert timings[-1]["end_seconds"] == 20.0
    # Contiguous: each line starts where the previous ended.
    assert timings[0]["end_seconds"] == timings[1]["start_seconds"]


def test_line_timings_from_segment_timings_splits_lines() -> None:
    timings = line_timings_from_segment_timings(
        [
            {
                "index": 1,
                "start_seconds": 0,
                "end_seconds": 10,
                "source_transcript": "Arman: alpha beta.\nArman: gamma delta epsilon.",
            }
        ]
    )
    assert len(timings) == 2
    assert timings[0]["id"] == "line_001"
    assert timings[0]["start_seconds"] == 0.0
    assert timings[-1]["end_seconds"] == 10.0


# --------------------------------------------------------------------------- #
# Fallback + normalization
# --------------------------------------------------------------------------- #


def test_build_fallback_scene_plan_covers_full_duration() -> None:
    plan = build_fallback_scene_plan(
        script=_script(),
        line_timings=None,
        duration_seconds=60,
        category="Tech",
        source_urls=["https://a.com/x"],
    )
    assert plan.scenes[0].layout == "title"
    assert plan.scenes[0].start_seconds == 0.0
    assert plan.scenes[-1].end_seconds == 60.0
    # Contiguous, no gaps or overlaps.
    for earlier, later in zip(plan.scenes, plan.scenes[1:], strict=False):
        assert earlier.end_seconds == later.start_seconds
    # A source scene appears because source urls were supplied.
    assert any(scene.layout == "source" for scene in plan.scenes)


def test_normalize_scenes_reflows_to_duration() -> None:
    scenes = [
        PlannedScene(id="a", start_seconds=0, end_seconds=5, layout="title"),
        PlannedScene(id="b", start_seconds=5, end_seconds=10, layout="statement"),
        PlannedScene(id="c", start_seconds=10, end_seconds=15, layout="outro"),
    ]
    out = normalize_scenes(scenes, 30)
    assert out[0].start_seconds == 0.0
    assert out[-1].end_seconds == 30.0
    for earlier, later in zip(out, out[1:], strict=False):
        assert earlier.end_seconds == later.start_seconds
    assert [scene.id for scene in out] == ["a", "b", "c"]


def test_hydrate_source_scenes_fills_empty_model_output() -> None:
    plan = ScenePlan(
        version=1,
        duration_seconds=10,
        scenes=[
            PlannedScene(
                id="sources",
                start_seconds=0,
                end_seconds=10,
                layout="source",
            )
        ],
    )

    hydrated = hydrate_source_scenes(
        plan,
        ["https://example.com/report", "https://example.org/analysis"],
    )

    assert hydrated.scenes[0].headline == "Sources"
    assert hydrated.scenes[0].source_urls == [
        "https://example.com/report",
        "https://example.org/analysis",
    ]


def test_retime_existing_scene_plan_keeps_visuals_and_replaces_audio_timing() -> None:
    plan = ScenePlan(
        version=1,
        director_model="approved",
        duration_seconds=20,
        scenes=[
            PlannedScene(id="title", start_seconds=0, end_seconds=8, layout="title"),
            PlannedScene(id="source", start_seconds=8, end_seconds=20, layout="source"),
        ],
    )

    retimed = retime_existing_scene_plan(
        plan,
        duration_seconds=10,
        line_timings=[
            {
                "id": "line_001",
                "speaker": "Arman",
                "text": "New narration.",
                "start_seconds": 0.2,
                "end_seconds": 8.8,
            }
        ],
        word_timings=[
            {"word": "New", "start_seconds": 0.2, "end_seconds": 0.5},
            {"word": "narration.", "start_seconds": 0.5, "end_seconds": 1.0},
        ],
        source_urls=["https://example.com/report"],
        claims=[],
    )

    assert retimed.director_model == "approved:retimed"
    assert retimed.duration_seconds == 10
    assert retimed.scenes[0].id == "title"
    assert retimed.scenes[-1].end_seconds == 10
    assert retimed.scenes[-1].source_urls == ["https://example.com/report"]
    assert retimed.line_timings[0].text == "New narration."
    assert [word.word for word in retimed.word_timings] == ["New", "narration."]


# --------------------------------------------------------------------------- #
# Chart grounding (the fact-honesty gate)
# --------------------------------------------------------------------------- #


def test_ground_scene_charts_downgrades_ungrounded_chart() -> None:
    plan = ScenePlan(
        version=1,
        duration_seconds=30,
        scenes=[
            PlannedScene(
                id="chart",
                start_seconds=0,
                end_seconds=30,
                layout="chart",
                headline="Made up numbers",
                chart=SceneChart(
                    type="bar",
                    data=[ChartDatum(label="x", value=35), ChartDatum(label="y", value=999)],
                ),
            )
        ],
    )
    grounded = ground_scene_charts(plan, [{"claim_text": "It grew 35% last year."}])
    # Only 35 is grounded (< 2 needed for a bar) -> the chart is removed.
    assert grounded.scenes[0].layout == "statement"
    assert grounded.scenes[0].chart is None
    assert any("chart" in note for note in grounded.production_notes)


def test_ground_scene_charts_keeps_fully_grounded_chart() -> None:
    plan = ScenePlan(
        version=1,
        duration_seconds=30,
        scenes=[
            PlannedScene(
                id="chart",
                start_seconds=0,
                end_seconds=30,
                layout="chart",
                headline="Real numbers",
                chart=SceneChart(
                    type="bar",
                    unit="%",
                    data=[ChartDatum(label="2023", value=35), ChartDatum(label="2024", value=12)],
                ),
            )
        ],
    )
    grounded = ground_scene_charts(
        plan, [{"claim_text": "Adoption rose from 35% to 12 million users in 2024."}]
    )
    assert grounded.scenes[0].layout == "chart"
    assert grounded.scenes[0].chart is not None
    assert [datum.value for datum in grounded.scenes[0].chart.data] == [35, 12]


def test_ground_scene_charts_separates_values_without_a_shared_unit() -> None:
    plan = ScenePlan(
        version=1,
        duration_seconds=30,
        scenes=[
            PlannedScene(
                id="mixed_metrics",
                start_seconds=0,
                end_seconds=30,
                layout="chart",
                headline="Two different facts",
                chart=SceneChart(
                    type="comparison",
                    unit="",
                    data=[
                        ChartDatum(label="$50B valuation", value=50),
                        ChartDatum(label="2.8T parameters", value=2.8),
                    ],
                ),
            )
        ],
    )

    grounded = ground_scene_charts(
        plan,
        [
            {"claim_text": "The company targets a $50B valuation."},
            {"claim_text": "The model has 2.8T parameters."},
        ],
    )

    assert grounded.scenes[0].layout == "bullets"
    assert grounded.scenes[0].chart is None
    assert grounded.scenes[0].bullets == ["$50B valuation", "2.8T parameters"]
    assert any("shared unit" in note for note in grounded.production_notes)


# --------------------------------------------------------------------------- #
# plan_video_scenes
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_plan_video_scenes_with_fake_provider() -> None:
    plan = await plan_video_scenes(
        script=_script(),
        claims=[],
        line_timings=None,
        duration_seconds=90,
        category="Tech",
        ai=FakeAIProvider(),
        model="fake",
    )
    assert isinstance(plan, ScenePlan)
    assert plan.duration_seconds == 90
    assert plan.director_model == "fake"
    assert plan.scenes[0].layout == "title"
    assert plan.scenes[0].start_seconds == 0.0
    assert plan.scenes[-1].end_seconds == 90.0
    # Line timings were approximated from the transcript (4 spoken lines).
    assert len(plan.line_timings) == 4


@pytest.mark.asyncio
async def test_plan_video_scenes_falls_back_on_bad_json() -> None:
    plan = await plan_video_scenes(
        script=_script(),
        claims=[],
        line_timings=None,
        duration_seconds=45,
        category="Tech",
        ai=_StubAI("this is not json {"),
        model="stub",
    )
    assert plan.director_model == "deterministic-fallback"
    assert plan.scenes[0].layout == "title"
    assert plan.scenes[-1].end_seconds == 45.0


@pytest.mark.asyncio
async def test_plan_video_scenes_grounds_charts_from_model_output() -> None:
    model_plan = {
        "version": 1,
        "director_model": "stub",
        "duration_seconds": 60,
        "line_timings": [],
        "scenes": [
            {"id": "t", "start_seconds": 0, "end_seconds": 6, "layout": "title", "headline": "Hi"},
            {
                "id": "chart_ok",
                "start_seconds": 6,
                "end_seconds": 26,
                "layout": "chart",
                "headline": "Growth",
                "chart": {
                    "type": "bar",
                    "unit": "%",
                    "data": [
                        {"label": "2023", "value": 35},
                        {"label": "rev", "value": 12},
                    ],
                },
            },
            {
                "id": "chart_bad",
                "start_seconds": 26,
                "end_seconds": 50,
                "layout": "chart",
                "headline": "Fabricated",
                "chart": {
                    "type": "bar",
                    "data": [
                        {"label": "a", "value": 999},
                        {"label": "b", "value": 888},
                    ],
                },
            },
            {
                "id": "o",
                "start_seconds": 50,
                "end_seconds": 60,
                "layout": "outro",
                "headline": "Bye",
            },
        ],
        "production_notes": [],
    }
    plan = await plan_video_scenes(
        script=_script(),
        claims=[{"claim_text": "Revenue grew 35% to $12 billion in 2024."}],
        line_timings=[
            {"id": "line_001", "speaker": "A", "text": "hi", "start_seconds": 0, "end_seconds": 3},
            {"id": "line_002", "speaker": "A", "text": "bye", "start_seconds": 3, "end_seconds": 6},
        ],
        duration_seconds=60,
        category="Tech",
        ai=_StubAI(json.dumps(model_plan)),
        model="stub",
    )
    scenes = {scene.id: scene for scene in plan.scenes}
    # The grounded chart survives with both values (35 and 12 are in the claim).
    assert scenes["chart_ok"].layout == "chart"
    assert scenes["chart_ok"].chart is not None
    assert [datum.value for datum in scenes["chart_ok"].chart.data] == [35, 12]
    # The fabricated chart is downgraded to a statement.
    assert scenes["chart_bad"].layout == "statement"
    assert scenes["chart_bad"].chart is None
    # Coverage + authoritative line timings preserved.
    assert plan.scenes[0].start_seconds == 0.0
    assert plan.scenes[-1].end_seconds == 60.0
    assert [timing.id for timing in plan.line_timings] == ["line_001", "line_002"]


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #


class _FakeArtifactRepo:
    def __init__(self, audio: dict | None) -> None:
        self._audio = audio

    async def get_latest_for_job(self, job_id: str, artifact_type: ArtifactType) -> dict | None:
        return self._audio if artifact_type == ArtifactType.FINAL_AUDIO else None


class _FakeContext:
    def __init__(self, *, script: dict, claims: list, audio: dict | None, sources: list) -> None:
        self.ai = FakeAIProvider()
        self.settings = SimpleNamespace(remotion_video_director_model="fake")
        self.artifact_repo = _FakeArtifactRepo(audio)
        self._data = {
            ArtifactType.VERIFIED_SCRIPT_JSON: script,
            ArtifactType.CLAIM_BANK_JSON: claims,
            ArtifactType.SOURCES_JSON: sources,
        }

    async def latest_json(self, job_id: str, artifact_type: ArtifactType):
        if artifact_type in self._data:
            return self._data[artifact_type]
        raise RuntimeError(f"Missing artifact {artifact_type}")


@pytest.mark.asyncio
async def test_build_scene_plan_for_job_uses_audio_timings() -> None:
    context = _FakeContext(
        script=_script(),
        claims=[{"claim_text": "It grew 35%."}],
        audio={
            "metadata": {
                "duration_seconds": 40,
                "segment_timings": [
                    {
                        "start_seconds": 0,
                        "end_seconds": 40,
                        "source_transcript": "Arman: one two.\nArman: three four five.",
                    }
                ],
            }
        },
        sources=[{"url": "https://a.com/x"}],
    )
    plan = await build_scene_plan_for_job(
        context,  # type: ignore[arg-type]
        {"id": "job-1", "target_duration_seconds": 90, "category": "Tech"},
    )
    # Duration comes from the audio (ceil(40 + 1)), not the job target.
    assert plan.duration_seconds == 41
    assert plan.scenes[-1].end_seconds == 41.0
    # Line timings were derived from the audio segment transcript.
    assert [timing.id for timing in plan.line_timings] == ["line_001", "line_002"]
