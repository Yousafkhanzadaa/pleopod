"""Scene plan schema: the engine-agnostic contract for data-driven videos.

A ``ScenePlan`` turns a verified script + claim bank into an ordered list of
presentation scenes. Each scene is either a text layout (title, statement,
bullets, quote, diagram, source, outro, timeline) or a ``chart`` layout that
carries structured data. Every chart datum can reference the claim it came from
so numbers can be validated against the fact-checked claim bank before any
renderer draws them.

This schema is deliberately independent of any renderer (ffmpeg, Remotion,
Motion Canvas). It is the JSON contract a presentation renderer consumes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.agent_outputs import AgentOutputModel

SceneLayout = Literal[
    "title",
    "statement",
    "bullets",
    "chart",
    "timeline",
    "quote",
    "diagram",
    "source",
    "outro",
]
ChartType = Literal["bar", "line", "donut", "stat", "comparison"]
Emphasis = Literal["calm", "curious", "urgent", "technical", "reflective"]

MAX_BULLETS = 5
MAX_DIAGRAM_ITEMS = 6
MAX_SOURCE_URLS = 4
MAX_CHART_DATA = 8


class ChartDatum(AgentOutputModel):
    label: str = Field(min_length=1, max_length=48)
    value: float
    # Grounding: the index of the claim in the claim bank this number came from,
    # and/or the source URL to show on screen. These let the backend verify the
    # number is real before a renderer draws it.
    claim_index: int | None = Field(default=None, ge=0)
    source_url: str | None = None


class SceneChart(AgentOutputModel):
    type: ChartType
    title: str = Field(default="", max_length=80)
    unit: str = Field(default="", max_length=16)
    data: list[ChartDatum] = Field(default_factory=list, max_length=MAX_CHART_DATA)
    caption: str = Field(default="", max_length=140)


class PlannedLineTiming(AgentOutputModel):
    id: str = Field(min_length=1)
    speaker: str = ""
    text: str = ""
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)


class PlannedWordTiming(AgentOutputModel):
    word: str = Field(min_length=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)


class PlannedScene(AgentOutputModel):
    id: str = Field(min_length=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    layout: SceneLayout
    headline: str = Field(default="", max_length=90)
    subheadline: str | None = Field(default=None, max_length=160)
    bullets: list[str] = Field(default_factory=list, max_length=MAX_BULLETS)
    chart: SceneChart | None = None
    quote: str | None = Field(default=None, max_length=220)
    diagram_items: list[str] = Field(default_factory=list, max_length=MAX_DIAGRAM_ITEMS)
    source_urls: list[str] = Field(default_factory=list, max_length=MAX_SOURCE_URLS)
    caption_line_ids: list[str] = Field(default_factory=list)
    emphasis: Emphasis = "calm"


class ScenePlan(AgentOutputModel):
    version: Literal[1] = 1
    director_model: str = "manual"
    duration_seconds: float = Field(ge=1)
    line_timings: list[PlannedLineTiming] = Field(default_factory=list)
    word_timings: list[PlannedWordTiming] = Field(default_factory=list)
    scenes: list[PlannedScene] = Field(min_length=1)
    production_notes: list[str] = Field(default_factory=list)
