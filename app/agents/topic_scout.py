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
TOPIC_SCOUT_MAX_SELECTION_ATTEMPTS = 4

_STOPWORDS = {
    "a",
    "about",
    "after",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "can",
    "could",
    "does",
    "do",
    "for",
    "from",
    "has",
    "have",
    "how",
    "in",
    "inside",
    "is",
    "it",
    "its",
    "latest",
    "more",
    "new",
    "of",
    "on",
    "or",
    "over",
    "the",
    "their",
    "this",
    "to",
    "today",
    "will",
    "what",
    "when",
    "why",
    "with",
    "would",
}

@dataclass(frozen=True)
class TopicScoutResult:
    payload: GenerationJobCreate
    decision: dict[str, Any]

class TopicScoutAgent:
    name = "topic_scout_agent"

    async def run(
        self,
        *,
        settings: Settings,
        ai: AIProvider,
        recent_jobs: list[dict[str, Any]],
    ) -> TopicScoutResult:
        prompt = topic_scout_prompt(settings, recent_jobs)
        decision: dict[str, Any] | None = None
        for attempt in range(1, TOPIC_SCOUT_MAX_SELECTION_ATTEMPTS + 1):
            decision = await run_topic_scout_search_prompt(
                prompt=prompt,
                settings=settings,
                ai=ai,
                recent_jobs=recent_jobs,
            )
            duplicate_match = decision_recent_topic_match(decision, recent_jobs)
            if not duplicate_match:
                break
            logger.info(
                "Topic Scout returned an already-used topic on attempt %s/%s; asking Gemini "
                "for a different single topic",
                attempt,
                TOPIC_SCOUT_MAX_SELECTION_ATTEMPTS,
            )
            prompt = topic_scout_retry_prompt(
                recent_jobs=recent_jobs,
                previous_decision=decision,
                duplicate_match=duplicate_match,
                attempt=attempt + 1,
            )
        assert decision is not None
        payload = generation_job_from_decision(decision, settings)
        return TopicScoutResult(payload=payload, decision=decision)


def topic_scout_prompt(settings: Settings, recent_jobs: list[dict[str, Any]]) -> str:
    recent_topics = recent_topic_prompt_records(recent_jobs)
    return f"""
You are Pleopod's podcast topic editor.

Pick one very fresh news topic for today's podcast episode.
Current UTC datetime: {datetime.now(UTC).isoformat(timespec="seconds")}

Target audience:
{settings.autopublish_audience}

Signal focus:
{settings.autopublish_region}

Already used topics and titles. Do not repeat or rephrase these:
{to_pretty_json(recent_topics)}

Use live Google Search grounding. Find a very fresh, popular story that many
people would actually want to hear discussed in a podcast today. Prioritize
developments from the last 24-48 hours when possible, and only choose older
stories if they are still actively developing today.

Editorial lanes:
- technology and AI
- biotech, health science, and biosecurity
- business, markets, startups, and major companies
- politics, policy, regulation, geopolitics, and elections when they directly
  affect technology, AI, biotech, business, platforms, cybersecurity, energy,
  chips, or the internet

Prefer topics with broad curiosity, clear stakes, credible reporting, and
enough depth for a full conversation. Avoid niche maintenance updates,
evergreen explainers, soft rumors, generic trend pieces, and anything already
covered above. Do not rephrase a recent topic as a new one.

Return exactly one best topic. The topic and title are the priority.
Return JSON only, with no extra keys:
{{
  "topic": "specific podcast topic",
  "title": "clear clickable episode title",
  "source_urls": ["https://..."]
}}
""".strip()


async def run_topic_scout_search_prompt(
    *,
    prompt: str,
    settings: Settings,
    ai: AIProvider,
    recent_jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    response = await ai.generate_text(
        prompt=prompt,
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
    return await complete_decision_sources_if_needed(
        decision,
        settings=settings,
        ai=ai,
        recent_jobs=recent_jobs,
    )


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
        }
        for citation in citations
        if citation.title
    ]
    return f"""
You are repairing Pleopod topic scout output.

Do not search again. Convert the available text into one simple podcast-topic
JSON object. If there are multiple options, keep only the strongest one.

Parse/validation error:
{error}

Already used topics and titles:
{to_pretty_json(recent_topic_prompt_records(recent_jobs))}

Grounding citation titles from the search pass:
{to_pretty_json(citation_data)}

Previous raw output:
{response_text[:8000] if response_text.strip() else "(empty)"}

Return JSON only:
{{
  "topic": "specific podcast topic",
  "title": "clear clickable episode title",
  "source_urls": ["https://..."]
}}
""".strip()


def topic_scout_retry_prompt(
    *,
    recent_jobs: list[dict[str, Any]],
    previous_decision: dict[str, Any],
    duplicate_match: dict[str, Any],
    attempt: int,
) -> str:
    return f"""
You are Pleopod's podcast topic editor.

Attempt {attempt} of {TOPIC_SCOUT_MAX_SELECTION_ATTEMPTS}.

Your previous topic was too close to an already used topic. Choose a completely
different, very fresh current story that a broad podcast audience would care
about.

Already used topics and titles. Do not repeat or rephrase these:
{to_pretty_json(recent_topic_prompt_records(recent_jobs))}

Previous rejected decision, do not repeat these topics at all:
{to_pretty_json(model_visible_topic_decision(previous_decision))}

Why it was considered already used:
{to_pretty_json(duplicate_match)}

Use live Google Search grounding. Prefer developments from the last 24-48
hours across technology, AI, biotech, business, and politics or policy when
they affect technology, AI, biotech, business, cybersecurity, energy, chips,
platforms, or the internet. Return exactly one best podcast topic. The topic
and title are the priority.

Return JSON only, with no extra keys:
{{
  "topic": "specific podcast topic",
  "title": "clear clickable episode title",
  "source_urls": ["https://..."]
}}
""".strip()


def topic_scout_source_completion_prompt(
    *,
    decision: dict[str, Any],
) -> str:
    return f"""
You are completing source discovery for a Pleopod podcast topic.

The topic is already selected. Use live Google Search grounding to find direct
source URLs for this exact topic.

Selected topic:
{to_pretty_json(model_visible_topic_decision(decision))}

Return the same topic and title. Add direct source URLs from credible pages you
find yourself.

Return JSON only:
{{
  "topic": "{decision.get("topic") or "specific podcast topic"}",
  "title": "{decision.get("title") or "clear clickable episode title"}",
  "source_urls": ["https://..."]
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
    # The AI's top-level decision is the publishing decision. Keep code out of
    # editorial selection so the scheduled run does not get stuck in skip loops.
    return decision


def generation_job_from_decision(
    decision: dict[str, Any],
    settings: Settings,
) -> GenerationJobCreate:
    trusted_domains = trusted_source_domains(settings)
    publishable_urls = publishable_source_urls(
        decision_source_values(decision),
        require_trusted_sources=settings.autopublish_require_trusted_sources,
        trusted_domains=trusted_domains,
    )
    fallback_urls = clean_source_urls(decision_source_values(decision))
    source_urls = publishable_urls or fallback_urls
    source_warning = source_warning_metadata(
        found=len(publishable_urls),
        used=len(source_urls),
        settings=settings,
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
                "source_completion_attempted": bool(
                    decision.get("source_completion_attempted")
                ),
                "topic_fingerprint": topic_fingerprint_from_decision(decision),
                "source_url_keys": sorted(source_url_keys(decision_source_values(decision))),
                **({"source_warning": source_warning} if source_warning else {}),
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


def source_warning_metadata(*, found: int, used: int, settings: Settings) -> dict[str, Any]:
    if found >= settings.autopublish_min_source_urls:
        return {}
    return {
        "minimum_requested": settings.autopublish_min_source_urls,
        "publishable_source_urls_found": found,
        "source_urls_used": used,
        "trusted_sources_required": settings.autopublish_require_trusted_sources,
        "action": "continued_without_skipping",
    }


def model_visible_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "topic": decision.get("topic"),
        "title": decision.get("title"),
        "rationale": decision.get("rationale"),
        "source_urls": clean_source_urls(decision.get("source_urls") or []),
    }


def model_visible_topic_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "topic": decision.get("topic"),
        "title": decision.get("title"),
        "rationale": decision.get("rationale"),
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


def recent_topic_records(
    recent_jobs: list[dict[str, Any]],
    *,
    include_source_keys: bool = False,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for job in recent_jobs:
        topic = str(job.get("topic") or "").strip()
        metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
        scout = metadata.get("topic_scout") if isinstance(metadata, dict) else {}
        if not isinstance(scout, dict):
            scout = {}
        title = str(scout.get("title") or "").strip()
        if not topic and not title:
            continue
        record = {
            "topic": topic,
            "title": title,
            "status": str(job.get("status") or ""),
            "created_at": str(job.get("created_at") or ""),
        }
        if include_source_keys:
            raw_source_report = scout.get("source_report")
            source_report = raw_source_report if isinstance(raw_source_report, dict) else {}
            source_urls = clean_source_urls(
                [
                    *(job.get("source_urls") or []),
                    *source_quality_url_values(source_report),
                ]
            )
            record["topic_fingerprint"] = topic_fingerprint(topic, title)
            record["source_url_keys"] = sorted(source_url_keys(source_urls))
        records.append(record)
    return records


def recent_topic_prompt_records(recent_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "topic": record.get("topic"),
            "title": record.get("title"),
        }
        for record in recent_topic_records(recent_jobs)
    ]


def decision_recent_topic_match(
    decision: dict[str, Any],
    recent_jobs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    current_text = topic_identity_text(
        str(decision.get("topic") or ""),
        str(decision.get("title") or ""),
    )
    current_fingerprint = topic_fingerprint_from_decision(decision)
    current_source_keys = source_url_keys(decision_source_values(decision))

    for record in recent_topic_records(recent_jobs, include_source_keys=True):
        recent_text = topic_identity_text(
            str(record.get("topic") or ""),
            str(record.get("title") or ""),
        )
        if current_fingerprint and current_fingerprint == record.get("topic_fingerprint"):
            return recent_topic_match("matching_topic_fingerprint", record)
        if topic_texts_are_similar(current_text, recent_text):
            return recent_topic_match("similar_topic_or_title", record)
        shared_source_keys = sorted(current_source_keys & set(record.get("source_url_keys") or []))
        if shared_source_keys:
            return recent_topic_match(
                "matching_source_url",
                record,
            )
    return None


def recent_topic_match(reason: str, record: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "reason": reason,
        "recent_topic": record.get("topic"),
        "recent_title": record.get("title"),
        "recent_created_at": record.get("created_at"),
        **extra,
    }


def topic_identity_text(topic: str, title: str | None = None) -> str:
    return " ".join(part for part in (topic, title or "") if part).strip()


def topic_fingerprint_from_decision(decision: dict[str, Any]) -> str:
    return topic_fingerprint(
        str(decision.get("topic") or ""),
        str(decision.get("title") or ""),
    )


def topic_fingerprint(topic: str, title: str | None = None) -> str:
    return " ".join(sorted(normalized_topic_tokens(topic_identity_text(topic, title))))


def topic_texts_are_similar(topic: str, recent_topic: str) -> bool:
    topic_tokens = normalized_topic_tokens(topic)
    recent_tokens = normalized_topic_tokens(recent_topic)
    if not topic_tokens or not recent_tokens:
        return False
    if topic_tokens == recent_tokens:
        return True
    intersection = topic_tokens & recent_tokens
    union = topic_tokens | recent_tokens
    jaccard = len(intersection) / max(len(union), 1)
    containment = len(intersection) / max(min(len(topic_tokens), len(recent_tokens)), 1)
    return len(intersection) >= 3 and (jaccard >= 0.62 or containment >= 0.72)


def source_url_keys(values: list[Any]) -> set[str]:
    return {
        key
        for url in clean_source_urls(values)
        if (key := canonical_source_url_key(url))
    }


def canonical_source_url_key(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    domain = source_domain(url)
    if not domain:
        return ""
    path = "/".join(segment for segment in parsed.path.split("/") if segment)
    return f"{domain}/{path}".rstrip("/")


def topic_is_recent_duplicate(topic: str, recent_topics: list[str]) -> bool:
    return any(topic_texts_are_similar(topic, recent_topic) for recent_topic in recent_topics)


def normalized_topic_tokens(topic: str) -> set[str]:
    return {
        normalized
        for token in re.findall(r"[a-z0-9]+", topic.lower())
        if (normalized := normalize_topic_token(token))
        and normalized not in _STOPWORDS
        and len(normalized) > 1
    }


def normalize_topic_token(token: str) -> str:
    token = token.lower().strip()
    if len(token) > 5 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 5 and token.endswith(("ces", "ses")):
        return token[:-1]
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 5 and token.endswith(("ced", "sed")):
        return token[:-1]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token
