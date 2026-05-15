from __future__ import annotations

from typing import Any

from app.core.json_utils import to_pretty_json


def orchestration_prompt(title: str, overrides: dict[str, Any]) -> str:
    return f"""
You are the Orchestration Agent for Pleopod.

The user has provided a podcast title. Design the payload used to create a generation job.

User title:
{title}

Explicit user overrides:
{to_pretty_json(overrides)}

Rules:
- Keep the topic tightly aligned with the user's title.
- Infer a sensible category, audience, duration, language, and tone for a factual podcast episode.
- Respect explicit user overrides.
- Default language to `en` unless the title clearly implies another language.
- Keep tone concise, natural, and suitable for spoken audio.
- Keep source_urls empty unless explicit URLs were provided.
- Return JSON only.
""".strip()


def research_prompt(job: dict[str, Any]) -> str:
    return f"""
You are the Research Agent for Pleopod, an AI-generated Tech podcast product.

Create an evidence-backed research dossier for this podcast topic:
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
    return f"""
You are the Podcast Script Agent for Pleopod.

Write a factual, conversational two-speaker Tech podcast script.
It must be ready for Gemini 3.1 Flash TTS.

Topic: {job["topic"]}
Audience: {job["audience"]}
Target duration seconds: {job["target_duration_seconds"]}
Language: {job["language"]}
Tone: {job["tone"]}

TTS rules:
- Use exactly two speakers.
- Speaker names must be stable and simple.
- Use the exact speaker labels `Arman:` and `Maya:` in the transcript body.
- Every spoken line must start with either `Arman:` or `Maya:`.
- Do not wrap speaker labels in markdown like `**Arman:**`.
- Voice names must be Gemini TTS prebuilt voices, such as Charon and Aoede.
- Do not use Google Cloud TTS voice ids such as en-US-Neural2-C.
- Keep the transcript clean: no markdown tables, no citations spoken aloud, no URLs in dialogue.
- Keep factual claims grounded in the claim bank.
- Use natural conversational turns.
- Write a complete episode sized for the target duration.
- Finish with a natural closing exchange.
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
    {{"name": "Arman", "role": "Host", "voice_name": "Charon", "style": "clear, warm, informed"}},
    {{"name": "Maya", "role": "Analyst", "voice_name": "Aoede", "style": "breezy, curious"}}
  ],
  "transcript": "TTS the following conversation between Arman and Maya:\\n\\n...",
  "used_claims": ["claim text"]
}}
""".strip()


def script_repair_prompt(script: Any, validation_error: str) -> str:
    return f"""
You previously returned a podcast script JSON that failed backend validation.
Repair it and return JSON only.

Validation error:
{validation_error}

Hard requirements:
- Keep exactly two speakers.
- Preserve the episode topic, title, summary, description, and used claims when possible.
- Transcript dialogue lines must use only the exact labels `Arman:` and `Maya:`.
- Do not use markdown around speaker labels.
- Do not use alternate labels such as `Host:`, `Analyst:`, `Speaker 1:`, or `**Arman:**`.
- Rewrite the full transcript if it is too short, ends mid-sentence, or lacks a closing exchange.
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
    {{"name": "Arman", "role": "Host", "voice_name": "Charon", "style": "clear, warm, informed"}},
    {{"name": "Maya", "role": "Analyst", "voice_name": "Aoede", "style": "breezy, curious"}}
  ],
  "transcript": (
    "TTS the following conversation between Arman and Maya:\\n\\n"
    "Arman: ...\\nMaya: ..."
  ),
  "used_claims": ["claim text"]
}}
""".strip()


def verification_prompt(script: Any, claims: Any) -> str:
    return f"""
You are the Fact Verification Agent. Review the podcast script line by line.

Tasks:
- Confirm every factual claim against the claim bank.
- Fix unsupported, misleading, or overconfident lines.
- Preserve a natural podcast voice.
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
    return f"""
Create a premium podcast thumbnail for a Tech podcast episode.

Episode title: {script.get("title")}
Summary: {script.get("summary")}

Direction:
- Modern editorial tech visual.
- Strong focal point.
- No fake logos.
- No unreadable tiny text.
- Suitable for a podcast app card.
- Avoid clickbait.
- Use high contrast and clean composition.
""".strip()
