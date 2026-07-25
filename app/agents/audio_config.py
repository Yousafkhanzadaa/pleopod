from __future__ import annotations

import re
from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.core.config import Settings
from app.core.text import chunk_dialogue, strip_speaker_labels
from app.core.tts import GEMINI_TTS_VOICE_NAMES, coerce_gemini_tts_voice_name
from app.models.enums import ArtifactType, PipelineStep

_TTS_PREAMBLE_RE = re.compile(
    r"^\s*TTS\s+the\s+following\s+"
    r"(?:conversation\s+between|talk\s+by|monologue\s+by)\s+[^:\n]+:\s*",
    re.IGNORECASE,
)
_TRANSCRIPT_HEADER_RE = re.compile(r"^\s*#{0,6}\s*TRANSCRIPT:?\s*", re.IGNORECASE)
GEMINI_TTS_SAFE_SOURCE_CHARS = 1200
GEMINI_TTS_SAFE_PROMPT_CHARS = 1800
OPENAI_TTS_SAFE_SOURCE_CHARS = 3800
_SPEAKER_PREFIX_RE = re.compile(r"^([^:\n]{1,48}):\s*")


class AudioConfigAgent(PipelineAgent):
    name = "audio_config_agent"
    step = PipelineStep.AUDIO_CONFIG

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        script = await context.latest_json(job_id, ArtifactType.VERIFIED_SCRIPT_JSON)
        config = build_tts_config(script, context.settings)
        artifact = await context.artifact_service.put_json(
            f"jobs/{job_id}/audio/tts_config.json",
            config,
            ArtifactType.TTS_CONFIG_JSON,
            job_id=job_id,
        )
        return AgentResult(output_artifact_id=str(artifact["id"]))


def build_tts_config(script: dict[str, Any], settings: Settings) -> dict[str, Any]:
    speakers = script["speakers"][:1]
    transcript = normalize_tts_transcript(script["transcript"])
    if not transcript:
        raise ValueError("Verified script transcript is empty")

    voice_provider = settings.resolved_voice_provider
    source_limit = (
        OPENAI_TTS_SAFE_SOURCE_CHARS
        if voice_provider == "openai"
        else GEMINI_TTS_SAFE_SOURCE_CHARS
    )
    generation_mode = settings.tts_generation_mode
    max_chunk_chars = (
        len(transcript)
        if generation_mode == "single_request"
        else min(settings.max_tts_chunk_chars, source_limit)
    )
    chunks: list[dict[str, Any]] = []
    transcript_chunks = (
        [transcript]
        if generation_mode == "single_request"
        else chunk_dialogue(transcript, max_chunk_chars)
    )
    for index, chunk in enumerate(transcript_chunks, start=1):
        prompt = (
            narration_text(chunk, [speaker["name"] for speaker in speakers])
            if voice_provider == "openai"
            else build_tts_prompt(chunk, speakers)
        )
        chunks.append(
            {
                "index": index,
                "transcript": prompt,
                "source_transcript": chunk,
                "source_char_count": len(chunk),
                "prompt_char_count": len(prompt),
            }
        )
    max_prompt_chars = (
        max(chunk["prompt_char_count"] for chunk in chunks)
        if generation_mode == "single_request"
        else (
            OPENAI_TTS_SAFE_SOURCE_CHARS
            if voice_provider == "openai"
            else GEMINI_TTS_SAFE_PROMPT_CHARS
        )
    )

    if voice_provider == "openai":
        tts_model = settings.openai_tts_model
        voice_name = settings.openai_tts_voice
    else:
        tts_model = settings.gemini_tts_model
        voice_name = coerce_gemini_tts_voice_name(speakers[0].get("voice_name"), 0)

    return {
        "voice_provider": voice_provider,
        "tts_model": tts_model,
        "tts_instructions": (
            settings.openai_tts_instructions if voice_provider == "openai" else None
        ),
        "tts_speed": settings.openai_tts_speed if voice_provider == "openai" else 1.0,
        "export_format": settings.audio_export_format,
        "generation_mode": generation_mode,
        "max_source_chunk_chars": max_chunk_chars,
        "max_prompt_chars": max_prompt_chars,
        "speakers": [
            {
                "speaker": speaker["name"],
                "voice_name": (
                    voice_name
                    if voice_provider == "openai"
                    else coerce_gemini_tts_voice_name(speaker.get("voice_name"), i)
                ),
                "style": speaker.get("style"),
            }
            for i, speaker in enumerate(speakers)
        ],
        "chunks": chunks,
    }


def tts_config_needs_rebuild(
    config: dict[str, Any],
    settings: Settings | None = None,
) -> bool:
    chunks = config.get("chunks") or []
    if not chunks:
        return True
    generation_mode = config.get("generation_mode")
    if generation_mode not in {"single_request", "chunked"}:
        return True
    if settings and generation_mode != settings.tts_generation_mode:
        return True
    provider = str(config.get("voice_provider") or "gemini")
    resolved_provider = (
        str(getattr(settings, "resolved_voice_provider", provider)) if settings else provider
    )
    if settings and provider != resolved_provider:
        return True
    if settings:
        expected_model = (
            getattr(settings, "openai_tts_model", config.get("tts_model"))
            if provider == "openai"
            else getattr(settings, "gemini_tts_model", config.get("tts_model"))
        )
        if config.get("tts_model") != expected_model:
            return True
        if provider == "openai":
            if config.get("tts_instructions") != getattr(
                settings, "openai_tts_instructions", config.get("tts_instructions")
            ):
                return True
            if float(config.get("tts_speed") or 1.0) != float(
                getattr(settings, "openai_tts_speed", config.get("tts_speed") or 1.0)
            ):
                return True
    if generation_mode == "single_request" and len(chunks) != 1:
        return True
    source_limit = (
        OPENAI_TTS_SAFE_SOURCE_CHARS if provider == "openai" else GEMINI_TTS_SAFE_SOURCE_CHARS
    )
    prompt_limit = (
        OPENAI_TTS_SAFE_SOURCE_CHARS if provider == "openai" else GEMINI_TTS_SAFE_PROMPT_CHARS
    )
    if generation_mode == "chunked" and int(
        config.get("max_source_chunk_chars") or 10**9
    ) > source_limit:
        return True
    speakers = config.get("speakers") or []
    if len(speakers) != 1:
        return True
    for speaker in speakers:
        voice_name = str(speaker.get("voice_name") or "").strip().lower()
        if provider == "openai" and not voice_name:
            return True
        if provider != "openai" and voice_name not in GEMINI_TTS_VOICE_NAMES:
            return True
    for chunk in chunks:
        transcript = chunk.get("transcript") or ""
        prompt_char_count = int(chunk.get("prompt_char_count") or len(transcript))
        if generation_mode == "chunked" and prompt_char_count > prompt_limit:
            return True
        if "### DIRECTOR'S NOTES" in transcript:
            return True
    return False


def normalize_tts_transcript(transcript: str) -> str:
    text = transcript.strip()
    text = _TTS_PREAMBLE_RE.sub("", text, count=1).strip()
    text = _TRANSCRIPT_HEADER_RE.sub("", text, count=1).strip()
    return text


def source_transcript_from_tts_prompt(prompt: str) -> str:
    _, marker, source = prompt.partition("### TRANSCRIPT")
    if marker:
        return source.strip()
    return normalize_tts_transcript(prompt)


def narration_text(
    transcript_chunk: str,
    speaker_names: list[str] | None = None,
) -> str:
    """Remove dialogue labels so a single-narrator TTS model does not read them."""
    normalized = normalize_tts_transcript(transcript_chunk)
    known_speakers = list(speaker_names or [])
    if not known_speakers:
        known_speakers.extend(
            match.group(1).strip()
            for raw_line in normalized.splitlines()
            if (match := _SPEAKER_PREFIX_RE.match(raw_line.strip()))
        )
    lines: list[str] = []
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lines.append(strip_speaker_labels(line, known_speakers))
    return "\n".join(line for line in lines if line)


def build_tts_prompt(transcript_chunk: str, speakers: list[dict[str, Any]]) -> str:
    speaker_names = " and ".join(speaker["name"] for speaker in speakers)
    style_instruction = speaker_style_instruction(speakers)
    if len(speakers) == 1:
        continuity_instruction = (
            f"Keep {speakers[0]['name']}'s low-pitched voice identity, pacing, and tone "
            "consistent across all segments of this short video talk."
        )
        tts_instruction = f"TTS the following talk by {speaker_names}:"
    else:
        continuity_instruction = (
            "Keep each speaker's voice identity, pacing, and tone consistent across "
            "all segments of this episode."
        )
        tts_instruction = f"TTS the following conversation between {speaker_names}:"
    instructions = [item for item in (style_instruction, continuity_instruction) if item]
    instruction_text = "\n".join(instructions)
    preamble = f"{instruction_text}\n\n" if instruction_text else ""
    return f"""
{preamble}{tts_instruction}

### TRANSCRIPT
{transcript_chunk.strip()}
""".strip()


def speaker_style_instruction(speakers: list[dict[str, Any]]) -> str:
    styled_speakers = [
        (speaker["name"], (speaker.get("style") or "").strip())
        for speaker in speakers
        if (speaker.get("style") or "").strip()
    ]
    if not styled_speakers:
        return ""
    if len(styled_speakers) == 1:
        name, style = styled_speakers[0]
        return f"Make {name} sound {style}."
    first_name, first_style = styled_speakers[0]
    second_name, second_style = styled_speakers[1]
    return f"Make {first_name} sound {first_style}, and {second_name} sound {second_style}."
