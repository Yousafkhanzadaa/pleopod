from __future__ import annotations

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
    target_duration_seconds = clamp_generation_duration_seconds(job.get("target_duration_seconds"))
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


def thumbnail_prompt(
    script: Any,
    job: Any | None = None,
) -> str:
    script_data = script if isinstance(script, dict) else {}
    job_data = job if isinstance(job, dict) else {}
    title = " ".join(
        str(script_data.get("title") or job_data.get("topic") or "Untitled video").split()
    )
    information = " ".join(
        str(
            script_data.get("summary")
            or script_data.get("description")
            or job_data.get("topic")
            or ""
        ).split()
    )

    prompt = f'Generate a YouTube thumbnail for the video titled "{title}".'
    if information and information.casefold() != title.casefold():
        prompt += f" Video information: {information}"
    return prompt


def scene_director_prompt(
    script: Any,
    claims: Any,
    line_timings: Any,
    duration_seconds: float,
    category: str,
    fallback_plan: Any,
) -> str:
    indexed_claims = [
        {
            "claim_index": index,
            "claim_text": claim.get("claim_text") if isinstance(claim, dict) else str(claim),
            "source_urls": claim.get("source_urls", []) if isinstance(claim, dict) else [],
        }
        for index, claim in enumerate(claims or [])
    ]
    return f"""
You are the Scene Director Agent for Pleopod.

Turn this short single-speaker video into a data-driven presentation plan: an
ordered list of scenes that a code renderer will draw as animated graphics
(titles, statements, bullet builds, charts, timelines, quotes, diagrams, and a
source card). There is NO AI video generation. You only decide what appears on
screen at each moment.

Video length: {int(duration_seconds)} seconds. Category: {category}.

Scene rules:
- Cover the whole video from 0 to {int(duration_seconds)} seconds with no gaps or
  overlaps. The last scene must end exactly at {int(duration_seconds)}.
- Open with a `title` scene (the hook) and end with a `source` or `outro` scene.
- Use short, punchy headlines (2-7 words). Never paragraphs.
- Align each scene to what the speaker is saying at that time. Set
  `caption_line_ids` to the line ids from lineTimings that fall in the scene.
- Prefer variety and momentum: change the layout every scene.
- Allowed layouts: title, statement, bullets, chart, timeline, quote, diagram,
  source, outro.

Chart rules (critical - this is a fact-checked product):
- Only use a `chart` layout when the claim bank contains concrete NUMBERS you can
  show honestly (percentages, counts, money, dates, comparisons).
- chart.type is one of: bar, line, donut, stat, comparison.
  - stat: one big number (1 data point). comparison: 2 items. bar/line/donut: 2-8.
- Every chart must use one comparable unit and scale. NEVER compare unlike
  metrics (for example dollars versus parameter counts) in the same chart.
  Use separate stat scenes for unrelated numbers.
- Every chart data point MUST come from a claim. Set `claim_index` to the claim
  it came from, and `value` to a number STATED in that claim. Put the unit (%,
  $B, M, x) in chart.unit, not in the value.
- NEVER invent, estimate, round hard, or infer numbers that are not in a claim.
  If the claims have no usable numbers, do NOT use a chart. Use statement,
  bullets, timeline, quote, or diagram instead.
- Set source_url on data points when the claim has a source.

Return JSON only, matching the schema. Do not restate lineTimings; they are
provided and will be reused as-is.

Script:
{to_pretty_json(script)}

Claim bank (use claim_index to reference these):
{to_pretty_json(indexed_claims)}

Line timings (ids to reference in caption_line_ids):
{to_pretty_json(line_timings)}

Deterministic fallback scene draft (improve on this):
{to_pretty_json(fallback_plan)}
""".strip()
