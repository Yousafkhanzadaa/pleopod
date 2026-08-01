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


def thumbnail_director_prompt(script: Any, job: Any | None = None) -> str:
    episode_data = _thumbnail_episode_data(script, job)
    return f"""
You are a senior YouTube thumbnail strategist and art director.

Understand the episode, the intended audience, and the promise made by the title. Then
design the strongest truthful thumbnail concept for this specific video. Use your
knowledge of how people discover and evaluate videos in this content market.

EPISODE AND MARKET DATA
{to_pretty_json(episode_data)}

The title and thumbnail must work together. Decide what the image should communicate
instantly, what visual will create relevant curiosity, and what short hook adds value
without simply repeating the title.

You have full creative freedom. Choose the subject, visual medium, art direction,
setting, perspective, framing, lighting, color palette, mood, and level of realism that
best fit this episode and audience. Make a fresh decision from the supplied content;
do not reuse a default style or force every topic into the same visual formula.

The generated image will be used as a 16:9 YouTube thumbnail and viewed at small sizes.
The backend adds the hook afterward, so choose which side should contain the subject and
which side should remain usable for the text overlay. The image itself must not contain
readable text. Keep the concept accurate and avoid implying events or claims that are
not supported by the episode.

Write image_prompt as a complete, standalone direction for the image-generation model.
Describe the final image you chose—not your reasoning, a list of options, or a reusable
template. Be specific where specificity improves this concept, and leave stylistic
choices open only when they genuinely do not matter.

Return JSON only, with no Markdown or commentary.
{{
  "hook": "2-4 word thumbnail hook",
  "accent_word": "one exact word copied from hook",
  "layout": "subject_right_text_left | subject_left_text_right",
  "accent_color": "#RRGGBB color chosen for the hook accent",
  "image_prompt": "standalone, episode-specific direction for the final thumbnail artwork"
}}
""".strip()


def thumbnail_prompt(
    script: Any,
    brief: Any | None = None,
    job: Any | None = None,
) -> str:
    creative = normalized_thumbnail_brief(script, brief, job)
    subject_side = "right" if creative["layout"] == "subject_right_text_left" else "left"
    text_side = "left" if subject_side == "right" else "right"
    episode_data = _thumbnail_episode_data(script, job)
    episode_data.pop("transcript", None)
    return f"""
Create the final background artwork for a YouTube thumbnail using the content and
creative direction below.

EPISODE CONTEXT
{to_pretty_json(episode_data)}

CREATIVE DIRECTION
{creative["image_prompt"]}

Use your visual judgment to turn this direction into one cohesive, original image for
this specific episode. The result must be a 16:9 composition that reads clearly at
mobile thumbnail size and remains truthful to the supplied content.

The subject belongs on the {subject_side}. Keep sufficient uncluttered space on the
{text_side} for a large text overlay added after generation. Do not render the hook or
any other readable text, logos, or watermarks in the image. Keep the bottom-right area
free of essential detail because the platform may cover it with a duration badge.
""".strip()


def normalized_thumbnail_brief(
    script: Any,
    brief: Any | None = None,
    job: Any | None = None,
) -> dict[str, Any]:
    fallback = fallback_thumbnail_brief(script, job)
    if not isinstance(brief, dict):
        return fallback

    normalized = dict(fallback)
    for key in normalized:
        value = brief.get(key)
        if value not in (None, ""):
            normalized[key] = value

    hook = normalize_thumbnail_hook(normalized.get("hook"))
    if not hook:
        hook = fallback["hook"]
    normalized["hook"] = hook
    hook_words = thumbnail_hook_words(hook)

    accent_tokens = thumbnail_hook_words(str(normalized.get("accent_word") or ""))
    accent_word = accent_tokens[0] if len(accent_tokens) == 1 else ""
    if accent_word not in hook_words:
        accent_word = hook_words[-1] if hook_words else fallback["accent_word"]
    normalized["accent_word"] = accent_word

    if normalized.get("layout") not in {
        "subject_right_text_left",
        "subject_left_text_right",
    }:
        normalized["layout"] = fallback["layout"]

    image_prompt = str(normalized.get("image_prompt") or "").strip()
    normalized["image_prompt"] = image_prompt or fallback["image_prompt"]
    normalized["accent_color"] = normalize_thumbnail_color(
        normalized.get("accent_color"),
        fallback=fallback["accent_color"],
    )
    return normalized


def fallback_thumbnail_brief(
    script: Any,
    job: Any | None = None,
) -> dict[str, Any]:
    hook = thumbnail_hook_text(script)
    episode_data = _thumbnail_episode_data(script, job)
    episode_data.pop("transcript", None)

    return {
        "hook": hook,
        "accent_word": thumbnail_hook_words(hook)[-1],
        "layout": "subject_right_text_left",
        "accent_color": "#FFD43B",
        "image_prompt": (
            "Design an original thumbnail image specifically for this episode. Infer the "
            "strongest visual concept from the episode context, then choose the subject, "
            "visual medium, setting, composition, lighting, and color treatment that best "
            "communicate it to the intended audience. Make a decisive, content-specific "
            "creative choice rather than a generic technology image. Context: "
            f"{to_pretty_json(episode_data)}"
        ),
    }


def thumbnail_hook_text(script: Any) -> str:
    title = str(script.get("title") or "").strip()
    summary = str(script.get("summary") or "").strip()

    words: list[str] = []
    for source in (title.split(":", 1)[0], title, summary):
        candidate_words = thumbnail_hook_words(source)
        if len(candidate_words) >= 2:
            words = candidate_words
            break
        if len(candidate_words) > len(words):
            words = candidate_words
    if not words:
        return "WHAT CHANGED?"
    if len(words) == 1:
        return f"WHY {words[0]}?"
    return " ".join(words[:3]).upper()


def normalize_thumbnail_color(value: Any, *, fallback: str = "#FFD43B") -> str:
    color = str(value or "").strip().upper()
    if re.fullmatch(r"#[0-9A-F]{6}", color):
        return color
    return fallback


def _thumbnail_episode_data(script: Any, job: Any | None = None) -> dict[str, Any]:
    script_data = script if isinstance(script, dict) else {}
    job_data = job if isinstance(job, dict) else {}
    values = {
        "topic": job_data.get("topic"),
        "title": script_data.get("title"),
        "summary": script_data.get("summary"),
        "description": script_data.get("description"),
        "transcript": script_data.get("transcript"),
        "category": job_data.get("category"),
        "audience": job_data.get("audience"),
        "language": job_data.get("language"),
        "tone": job_data.get("tone"),
    }
    return {key: value for key, value in values.items() if value not in (None, "", [], {})}


def normalize_thumbnail_hook(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).upper()
    if not text:
        return ""
    words = thumbnail_hook_words(text)
    if not 2 <= len(words) <= 4:
        return ""
    if len(text) > 40:
        return ""
    return text


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
