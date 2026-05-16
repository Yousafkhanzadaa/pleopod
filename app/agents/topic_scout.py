from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from app.core.config import Settings
from app.core.json_utils import extract_json, to_pretty_json
from app.providers.ai import AIProvider, Citation
from app.schemas.agent_outputs import TopicScoutDecision
from app.schemas.jobs import GenerationJobCreate

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "a",
    "about",
    "after",
    "and",
    "as",
    "at",
    "for",
    "from",
    "how",
    "in",
    "inside",
    "is",
    "it",
    "new",
    "of",
    "on",
    "the",
    "to",
    "today",
    "what",
    "why",
    "with",
}


@dataclass(frozen=True)
class TopicScoutResult:
    payload: GenerationJobCreate
    decision: dict[str, Any]


class TopicScoutInsufficientSourcesError(ValueError):
    def __init__(
        self,
        *,
        message: str,
        required: int,
        found: int,
        source_urls: list[str],
        decision: dict[str, Any],
    ):
        super().__init__(message)
        self.required = required
        self.found = found
        self.source_urls = source_urls
        self.decision = decision

    def to_result(self) -> dict[str, Any]:
        return {
            "requiredSourceUrls": self.required,
            "foundSourceUrls": self.found,
            "sourceUrls": self.source_urls,
            "decision": public_topic_scout_decision(self.decision),
        }


class TopicScoutAgent:
    name = "topic_scout_agent"

    async def run(
        self,
        *,
        settings: Settings,
        ai: AIProvider,
        recent_jobs: list[dict[str, Any]],
    ) -> TopicScoutResult:
        response = await ai.generate_text(
            prompt=topic_scout_prompt(settings, recent_jobs),
            model=settings.autopublish_topic_model,
            use_google_search=True,
            response_schema=TopicScoutDecision,
        )
        decision = await parse_or_repair_topic_scout_decision(
            response_text=response.text,
            citations=response.citations,
            settings=settings,
            ai=ai,
            recent_jobs=recent_jobs,
        )
        decision = enrich_decision_source_quality(decision, settings, response.citations)
        decision = select_publishable_decision(
            decision,
            recent_jobs,
            min_source_urls=settings.autopublish_min_source_urls,
            require_trusted_sources=settings.autopublish_require_trusted_sources,
            trusted_domains=trusted_source_domains(settings),
        )
        decision = await complete_decision_sources_if_needed(
            decision,
            settings=settings,
            ai=ai,
            recent_jobs=recent_jobs,
        )
        payload = generation_job_from_decision(decision, settings)
        return TopicScoutResult(payload=payload, decision=decision)


def topic_scout_prompt(settings: Settings, recent_jobs: list[dict[str, Any]]) -> str:
    recent_topics = [
        {
            "topic": job.get("topic"),
            "status": job.get("status"),
            "created_at": str(job.get("created_at") or ""),
        }
        for job in recent_jobs
        if job.get("topic")
    ]
    trusted_examples = ", ".join(sorted(trusted_source_domains(settings))[:35])
    trusted_search_plan = to_pretty_json(trusted_source_search_plan())
    return f"""
You are the Topic Scout Agent for Pleopod.

Choose one timely, source-backed technology podcast topic to publish today.
Current UTC datetime: {datetime.now(UTC).isoformat(timespec="seconds")}

Audience:
{settings.autopublish_audience}

Category:
{settings.autopublish_category}

Region/signal focus:
{settings.autopublish_region}

Recent Pleopod jobs to avoid repeating:
{to_pretty_json(recent_topics)}

Use Gemini's Google Search grounding for discovery. Search trusted sources first.
Do not start from a broad generic topic. Start from source-targeted searches,
then pick the strongest concrete story from what those trusted sources reveal.

Trusted source examples:
{trusted_examples}

Trusted-source search plan:
{trusted_search_plan}

Search procedure:
1. Run source-targeted searches first, using queries like:
   site:openai.com latest announcement today
   site:blog.google.com OR site:blog.google AI announcement today
   site:theverge.com AI today
   site:arstechnica.com security today
   site:nvd.nist.gov vulnerability today
2. Inspect original result pages from those trusted domains.
3. Pick a topic only if direct trusted pages support it.
4. Use broad Google Search only to corroborate a trusted-source story, not to
   invent a generic topic.
5. If trusted-source searches do not reveal a concrete story with enough direct
   source URLs, return the best concrete candidate and its URLs; do not fall back
   to evergreen predictions.

Scouting rules:
- Search live sources now with Gemini Google Search; do not rely on memory.
- Pick a concrete current event from the last 24-48 hours: release, outage,
  security advisory, funding/acquisition, regulation, lawsuit, benchmark, paper,
  product launch, or major official announcement.
- Do not pick evergreen explainers, broad future predictions, or "state of X"
  topics unless they are tied to a concrete new source today.
- Prefer primary sources, official posts, papers, filings, security advisories,
  regulator/government pages, and reputable tech journalism.
- Avoid pure rumors, tragedy coverage, partisan politics, stock-price-only stories,
  celebrity gossip, and evergreen explainers.
- The selected topic must have enough substance for a complete factual episode.
- Include 3-8 direct source URLs for the selected topic. Use original article,
  announcement, paper, advisory, filing, or reputable publication URLs.
- Prefer at least one primary/official source when available.
- Reject SEO roundups, scraper pages, thin summaries, and unsupported viral posts.
- Provide 2-3 candidates and pick the strongest one.
- Do not repeat recent Pleopod topics unless there is a major new development.
- Score candidates using freshness, source authority, corroboration, audience fit,
  and episode depth.
- Return JSON only.

JSON shape:
{{
  "topic": "specific episode topic",
  "title": "YouTube-friendly working title",
  "rationale": "why this is timely and worth publishing now",
  "source_urls": ["https://..."],
  "candidates": [
    {{
      "topic": "candidate topic",
      "title": "candidate title",
      "rationale": "why it matters",
      "source_urls": ["https://..."],
      "score": 0.0
    }}
  ],
  "rejected_topics": ["topic and short reason"]
}}
""".strip()


def trusted_source_search_plan() -> list[dict[str, Any]]:
    return [
        {
            "group": "official_ai_company_sources",
            "domains": [
                "openai.com",
                "blog.google",
                "deepmind.google",
                "anthropic.com",
                "microsoft.com",
                "github.blog",
                "nvidia.com",
                "aws.amazon.com",
                "apple.com/newsroom",
                "meta.com",
            ],
            "queries": [
                "site:openai.com latest announcement AI today",
                "site:blog.google AI announcement today",
                "site:anthropic.com news AI today",
                "site:github.blog AI developer tools today",
                "site:nvidia.com AI announcement today",
            ],
        },
        {
            "group": "trusted_tech_journalism",
            "domains": [
                "theverge.com",
                "arstechnica.com",
                "wired.com",
                "techcrunch.com",
                "technologyreview.com",
                "bloomberg.com",
                "reuters.com",
                "apnews.com",
                "cnbc.com",
            ],
            "queries": [
                "site:theverge.com AI today",
                "site:arstechnica.com AI OR security today",
                "site:techcrunch.com AI startup today",
                "site:wired.com artificial intelligence today",
                "site:reuters.com technology AI today",
            ],
        },
        {
            "group": "security_and_regulatory_sources",
            "domains": [
                "nvd.nist.gov",
                "cisa.gov",
                "sec.gov",
                "ftc.gov",
                "justice.gov",
                "europa.eu",
                "bleepingcomputer.com",
                "krebsonsecurity.com",
                "securityweek.com",
            ],
            "queries": [
                "site:nvd.nist.gov vulnerability today",
                "site:cisa.gov advisory today",
                "site:sec.gov technology enforcement today",
                "site:ftc.gov AI technology today",
                "site:bleepingcomputer.com vulnerability today",
            ],
        },
    ]


async def parse_or_repair_topic_scout_decision(
    *,
    response_text: str,
    citations: list[Citation],
    settings: Settings,
    ai: AIProvider,
    recent_jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        return parse_topic_scout_decision_text(response_text)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        repair_response = await ai.generate_text(
            prompt=topic_scout_repair_prompt(
                settings=settings,
                recent_jobs=recent_jobs,
                response_text=response_text,
                citations=citations,
                error=str(exc),
            ),
            model=settings.autopublish_topic_model,
            use_google_search=False,
            response_schema=TopicScoutDecision,
        )
        return parse_topic_scout_decision_text(repair_response.text)


async def complete_decision_sources_if_needed(
    decision: dict[str, Any],
    *,
    settings: Settings,
    ai: AIProvider,
    recent_jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    trusted_domains = trusted_source_domains(settings)
    current_sources = publishable_source_urls(
        decision_source_values(decision),
        require_trusted_sources=settings.autopublish_require_trusted_sources,
        trusted_domains=trusted_domains,
    )
    if len(current_sources) >= settings.autopublish_min_source_urls:
        return decision

    logger.info(
        "Topic Scout selected %s/%s publishable sources; running source completion",
        len(current_sources),
        settings.autopublish_min_source_urls,
    )
    response = await ai.generate_text(
        prompt=topic_scout_source_completion_prompt(
            decision=decision,
            settings=settings,
            recent_jobs=recent_jobs,
            current_sources=current_sources,
        ),
        model=settings.autopublish_topic_model,
        use_google_search=True,
        response_schema=TopicScoutDecision,
    )
    completion = await parse_or_repair_topic_scout_decision(
        response_text=response.text,
        citations=response.citations,
        settings=settings,
        ai=ai,
        recent_jobs=recent_jobs,
    )
    completion = enrich_decision_source_quality(completion, settings, response.citations)
    merged = merge_topic_scout_source_completion(decision, completion)
    merged = enrich_decision_source_quality(merged, settings, response.citations)
    return select_publishable_decision(
        merged,
        recent_jobs,
        min_source_urls=settings.autopublish_min_source_urls,
        require_trusted_sources=settings.autopublish_require_trusted_sources,
        trusted_domains=trusted_domains,
    )


def parse_topic_scout_decision_text(text: str) -> dict[str, Any]:
    return normalize_topic_scout_json(extract_json(text))


def normalize_topic_scout_json(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        candidates = [
            normalize_candidate_json(item)
            for item in value
            if isinstance(item, dict) and (item.get("topic") or item.get("title"))
        ]
        if not candidates:
            raise ValueError("Topic Scout returned a JSON list without usable candidates")
        candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        selected = candidates[0]
        return TopicScoutDecision.model_validate(
            {
                **selected,
                "candidates": candidates,
                "rejected_topics": [],
            }
        ).model_dump(mode="json")

    if not isinstance(value, dict):
        raise TypeError("Topic Scout JSON must be an object or a list of candidate objects")

    normalized = dict(value)
    if "candidates" not in normalized:
        for alias in ("candidate_topics", "topics", "options"):
            if isinstance(normalized.get(alias), list):
                normalized["candidates"] = normalized[alias]
                break
    normalized["source_urls"] = normalize_source_url_aliases(normalized)
    if not normalized.get("title"):
        normalized["title"] = normalized.get("headline") or normalized.get("topic")
    if not normalized.get("rationale"):
        normalized["rationale"] = normalized.get("why_now") or normalized.get("reason") or ""

    candidates = [
        normalize_candidate_json(candidate)
        for candidate in normalized.get("candidates") or []
        if isinstance(candidate, dict)
    ]
    normalized["candidates"] = candidates
    return TopicScoutDecision.model_validate(normalized).model_dump(mode="json")


def normalize_candidate_json(candidate: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(candidate)
    normalized["source_urls"] = normalize_source_url_aliases(normalized)
    if not normalized.get("title"):
        normalized["title"] = normalized.get("headline") or normalized.get("topic")
    if not normalized.get("rationale"):
        normalized["rationale"] = normalized.get("why_now") or normalized.get("reason") or ""
    return normalized


def normalize_source_url_aliases(value: dict[str, Any]) -> list[Any]:
    for key in ("source_urls", "sources", "urls", "source_links", "links"):
        urls = value.get(key)
        if urls is None:
            continue
        if isinstance(urls, list):
            return [extract_source_url(item) for item in urls]
        return [extract_source_url(urls)]
    return []


def extract_source_url(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("url", "link", "href"):
            if value.get(key):
                return value[key]
    return value


def topic_scout_repair_prompt(
    *,
    settings: Settings,
    recent_jobs: list[dict[str, Any]],
    response_text: str,
    citations: list[Citation],
    error: str,
) -> str:
    citation_data = [
        {
            "title": citation.title,
            "url": citation.url,
        }
        for citation in citations
        if citation.url
    ]
    return f"""
You are repairing Topic Scout output for Pleopod.

The previous Gemini Google Search pass produced output that could not be parsed.
Do not search again. Convert the available text and grounding citations into one
valid JSON object matching the requested schema. If the previous output is a JSON
array of candidate topics, select the strongest candidate as the top-level topic
and keep all usable entries in "candidates".

Parse/validation error:
{error}

Recent Pleopod jobs to avoid repeating:
{to_pretty_json([job for job in recent_jobs if job.get("topic")])}

Grounding citations from the search pass:
{to_pretty_json(citation_data)}

Previous raw output:
{response_text[:8000] if response_text.strip() else "(empty)"}

Return JSON only with this shape:
{{
  "topic": "specific episode topic",
  "title": "YouTube-friendly working title",
  "rationale": "why this is timely and worth publishing now",
  "source_urls": ["https://..."],
  "candidates": [],
  "rejected_topics": []
}}
""".strip()


def topic_scout_source_completion_prompt(
    *,
    decision: dict[str, Any],
    settings: Settings,
    recent_jobs: list[dict[str, Any]],
    current_sources: list[str],
) -> str:
    trusted_examples = ", ".join(sorted(trusted_source_domains(settings))[:45])
    trusted_search_plan = to_pretty_json(trusted_source_search_plan())
    return f"""
You are completing source discovery for Pleopod Topic Scout.

The topic has already been selected. Do not pick a new story unless the selected
topic is clearly unsupported. Use Gemini Google Search grounding to find direct,
credible, current source URLs for this exact topic.

Selected topic:
{decision.get("topic")}

Working title:
{decision.get("title")}

Current accepted trusted source URLs:
{to_pretty_json(current_sources)}

Current decision:
{to_pretty_json(model_visible_decision(decision))}

Recent Pleopod jobs to avoid repeating:
{to_pretty_json([job for job in recent_jobs if job.get("topic")])}

Trusted source examples:
{trusted_examples}

Trusted-source search plan:
{trusted_search_plan}

Rules:
- Search live web results now, starting with source-targeted `site:` searches
  from the trusted-source search plan.
- Return at least {settings.autopublish_min_source_urls} direct factual source URLs.
- Prefer original announcements, official blogs, papers, filings, advisories,
  regulator/government pages, or reputable tech journalism.
- Include existing accepted sources if they are relevant.
- Do not count search-result pages, social posts, forums, SEO summaries, or
  scraper pages as factual sources.
- Return JSON only.

JSON shape:
{{
  "topic": "{decision.get("topic") or "specific episode topic"}",
  "title": "{decision.get("title") or "YouTube-friendly working title"}",
  "rationale": "why these sources support the topic",
  "source_urls": ["https://..."],
  "candidates": [],
  "rejected_topics": []
}}
""".strip()


def select_publishable_decision(
    decision: dict[str, Any],
    recent_jobs: list[dict[str, Any]],
    *,
    min_source_urls: int,
    require_trusted_sources: bool = False,
    trusted_domains: set[str] | None = None,
) -> dict[str, Any]:
    recent_topics = [str(job.get("topic") or "") for job in recent_jobs]
    selected_is_duplicate = topic_is_recent_duplicate(
        str(decision.get("topic") or ""),
        recent_topics,
    )
    selected_has_enough_sources = (
        len(
            publishable_source_urls(
                decision_source_values(decision),
                require_trusted_sources=require_trusted_sources,
                trusted_domains=trusted_domains or set(),
            )
        )
        >= min_source_urls
    )
    if not selected_is_duplicate and selected_has_enough_sources:
        return decision

    candidates = [
        candidate
        for candidate in decision.get("candidates", [])
        if isinstance(candidate, dict)
        and not topic_is_recent_duplicate(str(candidate.get("topic") or ""), recent_topics)
        and len(
            publishable_source_urls(
                decision_source_values(candidate),
                require_trusted_sources=require_trusted_sources,
                trusted_domains=trusted_domains or set(),
            )
        )
        >= min_source_urls
    ]
    if not candidates:
        return decision

    candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    selected = candidates[0]
    return {
        **decision,
        "topic": selected.get("topic") or decision.get("topic"),
        "title": selected.get("title") or decision.get("title"),
        "source_urls": selected.get("source_urls") or decision.get("source_urls") or [],
        "rationale": selected.get("rationale") or decision.get("rationale") or "",
        "source_quality": selected.get("source_quality") or decision.get("source_quality") or {},
        "selected_from_candidate_due_to_recent_duplicate": selected_is_duplicate,
        "selected_from_candidate_due_to_source_quality": not selected_has_enough_sources,
    }


def generation_job_from_decision(
    decision: dict[str, Any],
    settings: Settings,
) -> GenerationJobCreate:
    trusted_domains = trusted_source_domains(settings)
    source_urls = publishable_source_urls(
        decision_source_values(decision),
        require_trusted_sources=settings.autopublish_require_trusted_sources,
        trusted_domains=trusted_domains,
    )
    if len(source_urls) < settings.autopublish_min_source_urls:
        source_label = (
            "trusted direct source URLs"
            if settings.autopublish_require_trusted_sources
            else "source URLs"
        )
        raise TopicScoutInsufficientSourcesError(
            message=(
                f"Topic Scout selected too few {source_label}: "
                f"expected at least {settings.autopublish_min_source_urls}, "
                f"got {len(source_urls)}"
            ),
            required=settings.autopublish_min_source_urls,
            found=len(source_urls),
            source_urls=source_urls,
            decision=decision,
        )

    return GenerationJobCreate(
        topic=str(decision.get("topic") or decision.get("title") or "").strip(),
        category=str(decision.get("category") or settings.autopublish_category),
        audience=str(decision.get("audience") or settings.autopublish_audience),
        target_duration_seconds=int(
            decision.get("target_duration_seconds")
            or settings.autopublish_target_duration_seconds
        ),
        language=str(decision.get("language") or settings.autopublish_language),
        tone=str(decision.get("tone") or settings.autopublish_tone),
        source_urls=source_urls,
        auto_publish=True,
        metadata={
            "autopublish": True,
            "topic_scout": {
                "agent": TopicScoutAgent.name,
                "title": decision.get("title"),
                "rationale": decision.get("rationale"),
                "source_report": decision.get("source_quality", {}),
                "candidates": compact_topic_scout_candidates(decision.get("candidates", [])),
                "rejected_topics": decision.get("rejected_topics", []),
                "selected_from_candidate_due_to_recent_duplicate": bool(
                    decision.get("selected_from_candidate_due_to_recent_duplicate")
                ),
                "selected_from_candidate_due_to_source_quality": bool(
                    decision.get("selected_from_candidate_due_to_source_quality")
                ),
                "source_completion_attempted": bool(
                    decision.get("source_completion_attempted")
                ),
            },
        },
    )


def enrich_decision_source_quality(
    decision: dict[str, Any],
    settings: Settings,
    citations: list[Citation],
) -> dict[str, Any]:
    trusted_domains = trusted_source_domains(settings)
    trend_domains = trend_source_domains(settings)
    citation_urls = clean_source_urls([citation.url for citation in citations if citation.url])

    enriched = {**decision}
    enriched_source_urls = clean_source_urls(
        [*decision_source_values(enriched), *citation_urls]
    )
    enriched["source_urls"] = publishable_source_urls(
        enriched_source_urls,
        require_trusted_sources=settings.autopublish_require_trusted_sources,
        trusted_domains=trusted_domains,
    )
    enriched["source_quality"] = source_quality_report(
        enriched_source_urls,
        trusted_domains=trusted_domains,
        trend_domains=trend_domains,
        citation_urls=citation_urls,
        existing=enriched.get("source_quality"),
    )

    candidates: list[dict[str, Any]] = []
    for candidate in enriched.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        candidate_urls = clean_source_urls(decision_source_values(candidate))
        candidate = {
            **candidate,
            "source_urls": publishable_source_urls(
                candidate_urls,
                require_trusted_sources=settings.autopublish_require_trusted_sources,
                trusted_domains=trusted_domains,
            ),
            "source_quality": source_quality_report(
                candidate_urls,
                trusted_domains=trusted_domains,
                trend_domains=trend_domains,
                existing=candidate.get("source_quality"),
            ),
        }
        candidates.append(candidate)
    enriched["candidates"] = candidates
    return enriched


def merge_topic_scout_source_completion(
    decision: dict[str, Any],
    completion: dict[str, Any],
) -> dict[str, Any]:
    source_urls = clean_source_urls(
        [*decision_source_values(decision), *decision_source_values(completion)]
    )
    candidates = [
        candidate
        for candidate in [
            *(decision.get("candidates") or []),
            *(completion.get("candidates") or []),
        ]
        if isinstance(candidate, dict)
    ]
    return {
        **decision,
        "source_urls": source_urls,
        "source_quality": completion.get("source_quality") or decision.get("source_quality") or {},
        "candidates": candidates,
        "source_completion_attempted": True,
    }


def model_visible_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "topic": decision.get("topic"),
        "title": decision.get("title"),
        "rationale": decision.get("rationale"),
        "source_urls": clean_source_urls(decision.get("source_urls") or []),
    }


def public_topic_scout_decision(decision: dict[str, Any]) -> dict[str, Any]:
    value = {
        **model_visible_decision(decision),
        "candidates": compact_topic_scout_candidates(decision.get("candidates", [])),
        "rejected_topics": decision.get("rejected_topics", []),
        "source_report": decision.get("source_quality", {}),
    }
    if decision.get("source_completion_attempted"):
        value["source_completion_attempted"] = True
    return value


def compact_topic_scout_candidates(candidates: Any) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        compacted.append(
            {
                "topic": candidate.get("topic"),
                "title": candidate.get("title"),
                "rationale": candidate.get("rationale"),
                "source_urls": clean_source_urls(candidate.get("source_urls") or []),
                "score": candidate.get("score"),
            }
        )
    return compacted


def decision_source_values(decision: dict[str, Any]) -> list[Any]:
    return [
        *(decision.get("source_urls") or []),
        *source_quality_url_values(decision.get("source_quality")),
    ]


def source_quality_url_values(source_quality: Any) -> list[Any]:
    if not isinstance(source_quality, dict):
        return []
    values: list[Any] = []
    for key in (
        "primary_sources",
        "reputable_coverage",
        "trusted_source_urls",
    ):
        items = source_quality.get(key) or []
        if isinstance(items, list):
            values.extend(items)
        else:
            values.append(items)
    return values


def clean_source_urls(values: list[Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = str(value or "").strip()
        if not url or not re.match(r"^https?://", url, flags=re.IGNORECASE):
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append(url)
    return urls[:20]


def publishable_source_urls(
    values: list[Any],
    *,
    require_trusted_sources: bool,
    trusted_domains: set[str],
) -> list[str]:
    urls = clean_source_urls(values)
    if not require_trusted_sources:
        return urls
    return [url for url in urls if is_trusted_source_url(url, trusted_domains)]


def source_quality_report(
    values: list[Any],
    *,
    trusted_domains: set[str],
    trend_domains: set[str],
    citation_urls: list[str] | None = None,
    existing: Any | None = None,
) -> dict[str, Any]:
    urls = clean_source_urls(values)
    trusted_urls = [url for url in urls if is_trusted_source_url(url, trusted_domains)]
    trend_urls = [
        url
        for url in urls
        if not is_trusted_source_url(url, trusted_domains)
        and is_trend_signal_url(url, trend_domains)
    ]
    untrusted_urls = [
        url
        for url in urls
        if url not in trusted_urls and url not in trend_urls
    ]
    existing_notes = ""
    if isinstance(existing, dict):
        existing_notes = str(existing.get("notes") or "").strip()

    domains = sorted(
        {domain for url in trusted_urls if (domain := source_domain(url))}
    )
    report: dict[str, Any] = {
        "trusted_source_count": len(trusted_urls),
        "trusted_domains": domains,
        "trusted_source_urls": trusted_urls,
        "trend_signal_count": len(trend_urls),
        "trend_signal_urls": trend_urls,
        "untrusted_or_supporting_urls": untrusted_urls,
    }
    if citation_urls:
        report["grounding_citation_urls"] = clean_source_urls(citation_urls)
    if existing_notes:
        report["notes"] = existing_notes
    return report


def is_trusted_source_url(url: str, trusted_domains: set[str]) -> bool:
    domain = source_domain(url)
    if not domain:
        return False
    return domain_matches(domain, trusted_domains)


def is_trend_signal_url(url: str, trend_domains: set[str]) -> bool:
    domain = source_domain(url)
    if not domain:
        return False
    return domain_matches(domain, trend_domains)


def source_domain(url: str) -> str:
    try:
        hostname = urlparse(url).hostname or ""
    except ValueError:
        return ""
    hostname = hostname.lower().strip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def domain_matches(domain: str, candidates: set[str]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def trusted_source_domains(settings: Settings) -> set[str]:
    return configured_domains(settings.autopublish_trusted_source_domains)


def trend_source_domains(settings: Settings) -> set[str]:
    return configured_domains(settings.autopublish_trend_source_domains)


def configured_domains(raw: str) -> set[str]:
    domains: set[str] = set()
    for item in re.split(r"[\s,]+", raw):
        domain = item.strip().lower().removeprefix("https://").removeprefix("http://")
        domain = domain.split("/", 1)[0].strip(".")
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            domains.add(domain)
    return domains


def topic_is_recent_duplicate(topic: str, recent_topics: list[str]) -> bool:
    topic_tokens = normalized_topic_tokens(topic)
    if not topic_tokens:
        return False

    for recent_topic in recent_topics:
        recent_tokens = normalized_topic_tokens(recent_topic)
        if not recent_tokens:
            continue
        if topic_tokens == recent_tokens:
            return True
        overlap = len(topic_tokens & recent_tokens) / max(len(topic_tokens | recent_tokens), 1)
        if overlap >= 0.72:
            return True
    return False


def normalized_topic_tokens(topic: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", topic.lower())
        if token not in _STOPWORDS and len(token) > 1
    }
