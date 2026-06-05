from __future__ import annotations

import re
from typing import Any

from app.core.duration import (
    MAX_GENERATION_DURATION_SECONDS,
    clamp_generation_duration_seconds,
)
from app.core.json_utils import to_pretty_json


def max_spoken_words_for_duration(duration_seconds: int) -> int:
    return min(190, max(70, int(duration_seconds * 2.1)))


def orchestration_prompt(title: str, overrides: dict[str, Any]) -> str:
    return f"""
You are the Orchestration Agent for Pleopod.

The user has provided a short video title. Design the payload used to create a generation job.

User title:
{title}

Explicit user overrides:
{to_pretty_json(overrides)}

Rules:
- Keep the topic tightly aligned with the user's title.
- Infer a sensible category, audience, duration, language, and tone for a factual
  short-form video talk.
- Respect explicit user overrides.
- The finished video must be short-form: target duration must never exceed
  {MAX_GENERATION_DURATION_SECONDS} seconds.
- Default language to `en` unless the title clearly implies another language.
- Keep tone concise, natural, and suitable for spoken audio.
- Keep source_urls empty unless explicit URLs were provided.
- Return JSON only.
""".strip()


def research_prompt(job: dict[str, Any]) -> str:
    return f"""
You are the Research Agent for Pleopod, an AI-generated Tech short video product.

Create an evidence-backed research dossier for this video topic:
Topic: {job["topic"]}
Category: {job["category"]}
Audience: {job["audience"]}
Language: {job["language"]}

Rules:
- Do the research now. Do not return a plan, checklist, or list of things to investigate.
- Use recent, authentic, high-quality sources.
- Prefer primary sources: official docs, company posts, papers, public filings,
  and regulator or government sources.
- Use reputable journalism only when primary sources are unavailable.
- Do not invent facts, dates, numbers, product names, or quotes.
- Separate confirmed facts from analysis.
- Include at least 5 sources when the topic has public information.
- Include at least 8 atomic supported claims when the topic has public information.
- Every claim should cite one or more URLs from the sources list.
- Key points must be factual findings, not action verbs like "investigate", "examine",
  "quantify", "outline", or "research".
- Return JSON only.

JSON shape:
{{
  "summary": "short factual dossier summary",
  "key_points": ["point"],
  "open_questions": ["question"],
  "sources": [
    {{
      "url": "https://...",
      "title": "source title",
      "publisher": "publisher",
      "author": "author or null",
      "published_at": "ISO datetime or null",
      "source_tier": "A or B or C",
      "credibility_score": 0.0,
      "notes": "why source matters"
    }}
  ],
  "claims": [
    {{
      "claim_text": "atomic factual claim",
      "source_urls": ["https://..."],
      "verification_status": "supported",
      "confidence": 0.0,
      "notes": "context or caveat"
    }}
  ]
}}
""".strip()


def research_quality_repair_prompt(
    job: dict[str, Any],
    research: Any,
    issues: list[str],
) -> str:
    return f"""
You returned a research dossier that passed JSON parsing but failed quality checks.
Redo the research and return a complete evidence-backed dossier as JSON only.

Topic: {job["topic"]}
Category: {job["category"]}
Audience: {job["audience"]}
Language: {job["language"]}

Quality issues:
{to_pretty_json(issues)}

Hard requirements:
- Do the research now. Do not return a plan, checklist, or "things to investigate".
- Prefer primary sources: official docs, company posts, papers, public filings,
  court/regulatory/government pages, and direct statements.
- Use reputable journalism only when primary sources are unavailable.
- Include at least 5 sources when the topic has public information.
- Include at least 8 atomic supported claims when the topic has public information.
- Every claim should cite one or more URLs from the sources list.
- Key points must be factual findings, not research tasks.
- If a detail is uncertain, include it in open_questions rather than as a claim.
- Return JSON only.

Previous weak dossier:
{to_pretty_json(research)}

Return JSON with this shape:
{{
  "summary": "short factual dossier summary",
  "key_points": ["factual finding"],
  "open_questions": ["question"],
  "sources": [
    {{
      "url": "https://...",
      "title": "source title",
      "publisher": "publisher",
      "author": "author or null",
      "published_at": "ISO datetime or null",
      "source_tier": "A or B or C",
      "credibility_score": 0.0,
      "notes": "why source matters"
    }}
  ],
  "claims": [
    {{
      "claim_text": "atomic factual claim",
      "source_urls": ["https://..."],
      "verification_status": "supported",
      "confidence": 0.0,
      "notes": "context or caveat"
    }}
  ]
}}
""".strip()


def research_repair_prompt(raw_response: str) -> str:
    return f"""
You previously returned research output that failed JSON parsing or validation.
Repair it into valid JSON only.

Rules:
- Preserve source URLs, claims, dates, and details already present when possible.
- Do not invent new sources, quotes, numbers, or product facts.
- If information is missing, use empty strings, empty arrays, or null values.

Return JSON with this shape:
{{
  "summary": "short factual dossier summary",
  "key_points": ["point"],
  "open_questions": ["question"],
  "sources": [
    {{
      "url": "https://...",
      "title": "source title",
      "publisher": "publisher",
      "author": "author or null",
      "published_at": "ISO datetime or null",
      "source_tier": "A or B or C",
      "credibility_score": 0.0,
      "notes": "why source matters"
    }}
  ],
  "claims": [
    {{
      "claim_text": "atomic factual claim",
      "source_urls": ["https://..."],
      "verification_status": "supported",
      "confidence": 0.0,
      "notes": "context or caveat"
    }}
  ]
}}

Malformed output to repair:
{raw_response}
""".strip()


def script_prompt(job: dict[str, Any], memory_md: str, claims: Any) -> str:
    target_duration_seconds = clamp_generation_duration_seconds(
        job.get("target_duration_seconds")
    )
    max_spoken_words = max_spoken_words_for_duration(target_duration_seconds)
    return f"""
You are the Short Video Script Agent for Pleopod.

Write a factual, conversational single-speaker Tech video talk script.
It must be ready for Gemini 3.1 Flash TTS.

Topic: {job["topic"]}
Audience: {job["audience"]}
Target duration seconds: {target_duration_seconds}
Language: {job["language"]}
Tone: {job["tone"]}

TTS rules:
- Use exactly one speaker.
- The speaker name must be stable and simple.
- Use the exact speaker label `Arman:` in the transcript body.
- Every spoken line must start with `Arman:`.
- Do not introduce a co-host, guest, analyst, interview, Q&A, banter, or back-and-forth.
- This should feel like one person talking directly to the viewer, not a podcast.
- Do not wrap speaker labels in markdown like `**Arman:**`.
- Voice names must be Gemini TTS prebuilt voices. Use `Algenib`.
- Do not use Google Cloud TTS voice ids such as en-US-Neural2-C.
- Keep the transcript clean: no markdown tables, no citations spoken aloud, no URLs in dialogue.
- Keep factual claims grounded in the claim bank.
- Use short spoken sections with momentum.
- Keep the finished talk under {target_duration_seconds} seconds.
- Use no more than {max_spoken_words} spoken words.
- Finish with a natural closing sentence.
- Never stop mid-sentence or end with an unfinished thought.
- Include subtle audio tags only when useful, like [thoughtful], [curious], [short pause].
- Do not mention that this was generated by AI.
- Return JSON only.

Research memory:
{memory_md}

Approved claim bank:
{to_pretty_json(claims)}

JSON shape:
{{
  "title": "episode title",
  "slug": "url-safe-slug",
  "summary": "short summary",
  "description": "app-ready description",
  "speakers": [
    {{
      "name": "Arman",
      "role": "Presenter",
      "voice_name": "Algenib",
      "style": "low-pitched, grounded, authoritative, attention-grabbing"
    }}
  ],
  "transcript": "TTS the following talk by Arman:\\n\\nArman: ...",
  "used_claims": ["claim text"]
}}
""".strip()


def script_repair_prompt(
    script: Any,
    validation_error: str,
    *,
    target_duration_seconds: int = MAX_GENERATION_DURATION_SECONDS,
) -> str:
    target_duration_seconds = clamp_generation_duration_seconds(target_duration_seconds)
    max_spoken_words = max_spoken_words_for_duration(target_duration_seconds)
    return f"""
You previously returned a short video script JSON that failed backend validation.
Repair it and return JSON only.

Validation error:
{validation_error}

Hard requirements:
- Keep exactly one speaker.
- Preserve the episode topic, title, summary, description, and used claims when possible.
- Transcript dialogue lines must use only the exact label `Arman:`.
- Do not use markdown around speaker labels.
- Do not use alternate labels such as `Host:`, `Analyst:`, `Speaker 1:`, or `**Arman:**`.
- Do not introduce a co-host, guest, interview, banter, Q&A, or podcast exchange.
- Keep the finished talk under {target_duration_seconds} seconds.
- Use no more than {max_spoken_words} spoken words.
- Rewrite the full transcript if it is too short, ends mid-sentence, or lacks a closing sentence.
- End with a complete sentence and natural closing.

Current script JSON:
{to_pretty_json(script)}

Return JSON with this shape:
{{
  "title": "episode title",
  "slug": "url-safe-slug",
  "summary": "short summary",
  "description": "app-ready description",
  "speakers": [
    {{
      "name": "Arman",
      "role": "Presenter",
      "voice_name": "Algenib",
      "style": "low-pitched, grounded, authoritative, attention-grabbing"
    }}
  ],
  "transcript": (
    "TTS the following talk by Arman:\\n\\n"
    "Arman: ..."
  ),
  "used_claims": ["claim text"]
}}
""".strip()


def verification_prompt(script: Any, claims: Any) -> str:
    return f"""
You are the Fact Verification Agent. Review the single-speaker video script line by line.

Tasks:
- Confirm every factual claim against the claim bank.
- Fix unsupported, misleading, or overconfident lines.
- Preserve a natural direct-to-viewer voice.
- Return JSON only.

Script:
{to_pretty_json(script)}

Claim bank:
{to_pretty_json(claims)}

JSON shape:
{{
  "verdict": "approved | fixed | rejected",
  "score": 0.0,
  "issues": ["issue"],
  "fixed_transcript": "full fixed transcript or null",
  "line_checks": [
    {{
      "line": "speaker line",
      "claim": "claim or null",
      "verdict": "supported | unsupported | misleading | needs_context | non_factual",
      "source_urls": ["https://..."],
      "fix": "fixed line or null"
    }}
  ]
}}
""".strip()


def thumbnail_prompt(script: Any) -> str:
    hook_text = thumbnail_hook_text(script)
    return f"""
Create a high-performing YouTube thumbnail for a Tech short-form video.

Episode title: {script.get("title")}
Summary: {script.get("summary")}
Exact large text hook: {hook_text}

Direction:
- 16:9 YouTube thumbnail, 1280x720, optimized for mobile Home/Suggested feeds.
- One dominant focal subject tied to the episode topic.
- Use the exact large text hook above as the only readable text, 2-4 very large words.
- Do not render any other readable text, numbers, badges, captions, UI labels, charts,
  lower-thirds, feature cards, stats panels, watermarks, or logos.
- Leave the bottom-right corner visually clean for YouTube's duration badge.
- Make the hook readable at phone size with bold type and strong contrast.
- Use a simple composition: foreground subject, clean background, clear negative space.
- Use 2 main color families plus one accent color; avoid busy rainbow palettes.
- No fake logos.
- Avoid fake screenshots, fake product markings, and misleading imagery.
- Avoid clickbait; the thumbnail promise must match the episode.
- Use high contrast and clean composition.
""".strip()


def thumbnail_hook_text(script: Any) -> str:
    title = str(script.get("title") or "").strip()
    summary = str(script.get("summary") or "").strip()
    combined = f"{title} {summary}".lower()

    if "ai" in combined and re.search(
        r"\b(catastroph\w*|risk\w*|threat\w*|danger\w*|warning\w*)\b", combined
    ):
        return "AI WARNING"
    if "ai" in combined and re.search(
        r"\b(order|oversight|regulat\w*|policy|government|framework)\b", combined
    ):
        return "AI OVERSIGHT"

    words: list[str] = []
    for source in (title.split(":", 1)[0], title, summary):
        candidate_words = thumbnail_hook_words(source)
        if len(candidate_words) >= 2:
            words = candidate_words
            break
        if len(candidate_words) > len(words):
            words = candidate_words
    if not words:
        return "TECH SHIFT"
    if len(words) == 1:
        return f"{words[0]} UPDATE"
    return " ".join(words[:3]).upper()


_THUMBNAIL_HOOK_STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "new",
    "of",
    "on",
    "or",
    "our",
    "the",
    "this",
    "to",
    "with",
    "your",
}


def thumbnail_hook_words(text: str) -> list[str]:
    words: list[str] = []
    for match in re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", text):
        word = re.sub(r"'s$", "", match, flags=re.IGNORECASE).upper()
        if len(word) <= 1:
            continue
        if word.lower() in _THUMBNAIL_HOOK_STOP_WORDS:
            continue
        words.append(word)
    return words
