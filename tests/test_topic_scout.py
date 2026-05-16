import json
from typing import Any

import pytest

from app.agents.topic_scout import (
    TopicScoutAgent,
    enrich_decision_source_quality,
    generation_job_from_decision,
    parse_topic_scout_decision_text,
    select_publishable_decision,
    topic_is_recent_duplicate,
    topic_scout_prompt,
)
from app.core.config import Settings
from app.providers.ai import AudioGeneration, Citation, ImageGeneration, TextGeneration


def test_topic_duplicate_detection_uses_normalized_overlap() -> None:
    assert topic_is_recent_duplicate(
        "Why AI coding agents are changing software teams",
        ["AI coding agents changing software teams"],
    )
    assert topic_is_recent_duplicate(
        "AI Coding Agents in 2026",
        ["AI Coding Agents Are Becoming Real Software Teammates"],
    )
    assert not topic_is_recent_duplicate(
        "A new semiconductor export rule",
        ["AI coding agents changing software teams"],
    )


def test_topic_scout_keeps_ai_selected_top_level_topic() -> None:
    decision = {
        "topic": "AI coding agents changing software teams",
        "title": "AI Coding Agents",
        "source_urls": ["https://example.com/old-1", "https://example.com/old-2"],
        "candidates": [
            {
                "topic": "AI coding agents changing software teams",
                "title": "Duplicate",
                "source_urls": ["https://example.com/old-1", "https://example.com/old-2"],
                "score": 0.99,
            },
            {
                "topic": "A new AI hardware launch for developers",
                "title": "New AI Hardware Launch",
                "rationale": "A fresher story.",
                "source_urls": ["https://example.com/new-1", "https://example.com/new-2"],
                "score": 0.8,
            },
        ],
    }

    selected = select_publishable_decision(
        decision,
        [{"topic": "AI coding agents changing software teams"}],
        min_source_urls=2,
    )

    assert selected["topic"] == "AI coding agents changing software teams"
    assert selected["title"] == "AI Coding Agents"


def test_topic_scout_does_not_programmatically_reject_repeated_source_url() -> None:
    decision = {
        "topic": "OpenAI ships Codex team controls",
        "title": "New Codex team controls arrive",
        "source_urls": ["https://openai.com/blog/codex-team-controls"],
        "candidates": [
            {
                "topic": "OpenAI launches Codex controls for teams",
                "title": "OpenAI Codex team controls",
                "source_urls": ["https://openai.com/blog/codex-team-controls?utm=feed"],
                "score": 0.95,
            },
            {
                "topic": "CISA adds a new exploited software flaw",
                "title": "CISA Adds New Exploited Software Flaw",
                "rationale": "A different current event.",
                "source_urls": ["https://cisa.gov/news/example-flaw"],
                "score": 0.8,
            },
        ],
    }

    selected = select_publishable_decision(
        decision,
        [
            {
                "topic": "OpenAI unveils Codex team controls",
                "source_urls": ["https://openai.com/blog/codex-team-controls"],
            }
        ],
        min_source_urls=1,
    )

    assert selected["topic"] == "OpenAI ships Codex team controls"


def test_generation_job_from_decision_continues_with_too_few_sources() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        autopublish_min_source_urls=2,
        autopublish_require_trusted_sources=False,
    )

    payload = generation_job_from_decision(
        {
            "topic": "A timely topic",
            "title": "A timely topic",
            "source_urls": ["https://example.com/one"],
        },
        settings,
    )

    assert [str(url) for url in payload.source_urls] == ["https://example.com/one"]
    assert payload.metadata["topic_scout"]["source_warning"] == {
        "minimum_requested": 2,
        "publishable_source_urls_found": 1,
        "source_urls_used": 1,
        "trusted_sources_required": False,
        "action": "continued_without_skipping",
    }


def test_generation_job_from_decision_builds_autopublish_payload() -> None:
    settings = Settings(_env_file=None, autopublish_min_source_urls=2)  # type: ignore[call-arg]

    payload = generation_job_from_decision(
        {
            "topic": "A timely technology topic",
            "title": "A Timely Technology Topic",
            "source_urls": [
                "https://openai.com/blog/one",
                "https://openai.com/blog/one",
                "https://theverge.com/two",
                "not-a-url",
            ],
            "rationale": "It is fresh and source-backed.",
        },
        settings,
    )

    assert payload.topic == "A timely technology topic"
    assert payload.auto_publish is True
    assert [str(url) for url in payload.source_urls] == [
        "https://openai.com/blog/one",
        "https://theverge.com/two",
    ]
    assert payload.metadata["autopublish"] is True
    assert payload.metadata["topic_scout"]["rationale"] == "It is fresh and source-backed."


def test_generation_job_from_decision_counts_source_quality_urls() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        autopublish_min_source_urls=3,
        autopublish_trusted_source_domains="openai.com,theverge.com,arstechnica.com",
    )

    payload = generation_job_from_decision(
        {
            "topic": "A timely technology topic",
            "title": "A Timely Technology Topic",
            "source_urls": ["https://openai.com/blog/one"],
            "source_quality": {
                "primary_sources": ["https://openai.com/blog/one"],
                "reputable_coverage": [
                    "https://theverge.com/two",
                    "https://arstechnica.com/three",
                ],
            },
        },
        settings,
    )

    assert [str(url) for url in payload.source_urls] == [
        "https://openai.com/blog/one",
        "https://theverge.com/two",
        "https://arstechnica.com/three",
    ]


def test_generation_job_from_decision_continues_with_too_few_trusted_sources() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        autopublish_min_source_urls=2,
        autopublish_require_trusted_sources=True,
        autopublish_trusted_source_domains="openai.com,theverge.com",
    )

    payload = generation_job_from_decision(
        {
            "topic": "A timely topic",
            "title": "A timely topic",
            "source_urls": [
                "https://openai.com/blog/source",
                "https://example.com/scraped-summary",
            ],
        },
        settings,
    )

    assert [str(url) for url in payload.source_urls] == ["https://openai.com/blog/source"]
    assert payload.metadata["topic_scout"]["source_warning"] == {
        "minimum_requested": 2,
        "publishable_source_urls_found": 1,
        "source_urls_used": 1,
        "trusted_sources_required": True,
        "action": "continued_without_skipping",
    }


def test_enrich_decision_source_quality_uses_grounding_citations() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        autopublish_require_trusted_sources=True,
        autopublish_trusted_source_domains="openai.com,theverge.com",
        autopublish_trend_source_domains="news.ycombinator.com",
    )

    enriched = enrich_decision_source_quality(
        {
            "topic": "A timely topic",
            "title": "A timely topic",
            "source_urls": ["https://example.com/scraped-summary"],
            "candidates": [],
        },
        settings,
        [
            Citation(url="https://openai.com/blog/source"),
            Citation(url="https://news.ycombinator.com/item?id=123"),
        ],
    )

    assert enriched["source_urls"] == ["https://openai.com/blog/source"]
    assert enriched["source_quality"]["trusted_source_count"] == 1
    assert enriched["source_quality"]["trend_signal_count"] == 1
    assert enriched["source_quality"]["untrusted_or_supporting_urls"] == [
        "https://example.com/scraped-summary"
    ]


def test_parse_topic_scout_decision_accepts_top_level_candidate_list() -> None:
    decision = parse_topic_scout_decision_text(
        json.dumps(
            [
                {
                    "topic": "Lower score topic",
                    "title": "Lower score topic",
                    "sources": [{"url": "https://theverge.com/source"}],
                    "score": 0.4,
                },
                {
                    "topic": "The stronger breaking topic",
                    "headline": "The stronger breaking topic",
                    "urls": [
                        "https://openai.com/blog/source",
                        "https://arstechnica.com/source",
                    ],
                    "why_now": "It has better source support.",
                    "score": 0.9,
                },
            ]
        )
    )

    assert decision["topic"] == "The stronger breaking topic"
    assert decision["title"] == "The stronger breaking topic"
    assert decision["source_urls"] == [
        "https://openai.com/blog/source",
        "https://arstechnica.com/source",
    ]
    assert len(decision["candidates"]) == 2


def test_topic_scout_prompt_uses_simple_json_contract() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    prompt = topic_scout_prompt(
        settings,
        recent_jobs=[
            {
                "topic": "OpenAI launches Codex team controls",
                "source_urls": ["https://openai.com/blog/codex-team-controls"],
                "metadata": {
                    "topic_scout": {
                        "title": "OpenAI Codex Controls Arrive",
                    }
                },
            }
        ],
    )

    assert '"topic"' in prompt
    assert '"title"' in prompt
    assert '"source_urls"' in prompt
    assert '"rationale"' not in prompt
    assert '"candidates"' not in prompt
    assert '"rejected_topics"' not in prompt
    assert '"source_quality"' not in prompt
    assert '"trend_evidence"' not in prompt
    assert '"search_queries"' not in prompt
    assert '"target_duration_seconds"' not in prompt
    assert "podcast topic editor" in prompt
    assert "popular story" in prompt
    assert "topic and title are the priority" in prompt
    assert "OpenAI launches Codex team controls" in prompt
    assert "OpenAI Codex Controls Arrive" in prompt
    assert "https://openai.com/blog/codex-team-controls" not in prompt
    assert "Trusted source examples" not in prompt
    assert "Trusted-source search plan" not in prompt
    assert "site:" not in prompt


@pytest.mark.asyncio
async def test_topic_scout_agent_uses_google_search_grounding() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        autopublish_min_source_urls=2,
        autopublish_trusted_source_domains="openai.com,theverge.com",
    )
    ai = SpyTopicScoutProvider()

    result = await TopicScoutAgent().run(settings=settings, ai=ai, recent_jobs=[])

    assert ai.calls[0]["use_google_search"] is True
    assert ai.calls[0]["model"] == "gemini-2.5-flash-lite"
    assert [str(url) for url in result.payload.source_urls] == [
        "https://openai.com/blog/source",
        "https://theverge.com/source",
    ]


@pytest.mark.asyncio
async def test_topic_scout_agent_repairs_empty_search_response() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        autopublish_min_source_urls=2,
        autopublish_trusted_source_domains="openai.com,theverge.com",
    )
    ai = RepairingTopicScoutProvider()

    result = await TopicScoutAgent().run(settings=settings, ai=ai, recent_jobs=[])

    assert ai.calls[0]["use_google_search"] is True
    assert ai.calls[1]["use_google_search"] is False
    assert [str(url) for url in result.payload.source_urls] == [
        "https://openai.com/blog/source",
        "https://theverge.com/source",
    ]


@pytest.mark.asyncio
async def test_topic_scout_agent_completes_sources_when_too_few_are_trusted() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        autopublish_min_source_urls=3,
        autopublish_trusted_source_domains="openai.com,theverge.com,arstechnica.com",
    )
    ai = SourceCompletingTopicScoutProvider()

    result = await TopicScoutAgent().run(settings=settings, ai=ai, recent_jobs=[])

    assert len(ai.calls) == 2
    assert ai.calls[0]["use_google_search"] is True
    assert ai.calls[1]["use_google_search"] is True
    assert [str(url) for url in result.payload.source_urls] == [
        "https://openai.com/blog/source",
        "https://theverge.com/source",
        "https://arstechnica.com/source",
    ]
    assert result.payload.metadata["topic_scout"]["source_completion_attempted"] is True


@pytest.mark.asyncio
async def test_topic_scout_retries_when_ai_returns_used_topic() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        autopublish_min_source_urls=1,
        autopublish_trusted_source_domains="openai.com,cisa.gov",
    )
    ai = RetryingTopicScoutProvider()

    result = await TopicScoutAgent().run(
        settings=settings,
        ai=ai,
        recent_jobs=[
            {
                "topic": "OpenAI launches Codex team controls",
                "source_urls": ["https://openai.com/blog/codex-team-controls"],
                "metadata": {
                    "topic_scout": {
                        "title": "OpenAI Codex Team Controls Arrive",
                    }
                },
            }
        ],
    )

    assert len(ai.calls) == 2
    assert "Previous rejected decision" in ai.calls[1]["prompt"]
    assert result.payload.topic == "CISA adds a new exploited software flaw"
    assert [str(url) for url in result.payload.source_urls] == [
        "https://cisa.gov/news/example-flaw"
    ]


class SpyTopicScoutProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: object | None = None,
    ) -> TextGeneration:
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "use_google_search": use_google_search,
                "urls": urls,
                "response_schema": response_schema,
            }
        )
        return TextGeneration(
            text=json.dumps(
                {
                    "topic": "A timely AI topic",
                    "title": "A timely AI topic",
                    "source_urls": [
                        "https://openai.com/blog/source",
                        "https://theverge.com/source",
                        "https://example.com/scraped-summary",
                    ],
                    "candidates": [],
                }
            )
        )

    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        raise NotImplementedError

    async def generate_tts(self, prompt: str, model: str, speakers: list[Any]) -> AudioGeneration:
        raise NotImplementedError


class SourceCompletingTopicScoutProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: object | None = None,
    ) -> TextGeneration:
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "use_google_search": use_google_search,
                "urls": urls,
                "response_schema": response_schema,
            }
        )
        if len(self.calls) == 1:
            return TextGeneration(
                text=json.dumps(
                    {
                        "topic": "A timely AI topic",
                        "title": "A timely AI topic",
                        "source_urls": ["https://openai.com/blog/source"],
                        "candidates": [],
                    }
                )
            )
        return TextGeneration(
            text=json.dumps(
                {
                    "topic": "A timely AI topic",
                    "title": "A timely AI topic",
                    "source_urls": [
                        "https://openai.com/blog/source",
                        "https://theverge.com/source",
                        "https://arstechnica.com/source",
                    ],
                    "candidates": [],
                }
            )
        )

    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        raise NotImplementedError

    async def generate_tts(self, prompt: str, model: str, speakers: list[Any]) -> AudioGeneration:
        raise NotImplementedError


class RepairingTopicScoutProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: object | None = None,
    ) -> TextGeneration:
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "use_google_search": use_google_search,
                "urls": urls,
                "response_schema": response_schema,
            }
        )
        if use_google_search:
            return TextGeneration(
                text="",
                citations=[Citation(url="https://openai.com/blog/source")],
            )
        return TextGeneration(
            text=json.dumps(
                {
                    "topic": "A repaired timely AI topic",
                    "title": "A repaired timely AI topic",
                    "source_urls": [
                        "https://openai.com/blog/source",
                        "https://theverge.com/source",
                    ],
                    "candidates": [],
                }
            )
        )

    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        raise NotImplementedError

    async def generate_tts(self, prompt: str, model: str, speakers: list[Any]) -> AudioGeneration:
        raise NotImplementedError


class RetryingTopicScoutProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_text(
        self,
        prompt: str,
        model: str,
        use_google_search: bool = False,
        urls: list[str] | None = None,
        response_schema: object | None = None,
    ) -> TextGeneration:
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "use_google_search": use_google_search,
                "urls": urls,
                "response_schema": response_schema,
            }
        )
        if len(self.calls) == 1:
            return TextGeneration(
                text=json.dumps(
                    {
                        "topic": "OpenAI launches Codex controls for teams",
                        "title": "OpenAI Codex Team Controls Arrive",
                        "source_urls": ["https://openai.com/blog/codex-team-controls"],
                    }
                )
            )
        return TextGeneration(
            text=json.dumps(
                {
                    "topic": "CISA adds a new exploited software flaw",
                    "title": "CISA Adds New Exploited Software Flaw",
                    "source_urls": ["https://cisa.gov/news/example-flaw"],
                }
            )
        )

    async def generate_image(self, prompt: str, model: str) -> ImageGeneration:
        raise NotImplementedError

    async def generate_tts(self, prompt: str, model: str, speakers: list[Any]) -> AudioGeneration:
        raise NotImplementedError
