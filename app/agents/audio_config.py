from __future__ import annotations

import re
from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.core.config import Settings
from app.core.text import chunk_dialogue
from app.core.tts import GEMINI_TTS_VOICE_NAMES, coerce_gemini_tts_voice_name
from app.models.enums import ArtifactType, PipelineStep

_TTS_PREAMBLE_RE = re.compile(
    r"^\s*TTS\s+the\s+following\s+conversation\s+between\s+[^:\n]+:\s*", re.IGNORECASE
)
_TRANSCRIPT_HEADER_RE = re.compile(r"^\s*#{0,6}\s*TRANSCRIPT:?\s*", re.IGNORECASE)
GEMINI_TTS_SAFE_SOURCE_CHARS = 1200
GEMINI_TTS_SAFE_PROMPT_CHARS = 1800


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
    speakers = script["speakers"][:2]
    transcript = normalize_tts_transcript(script["transcript"])
    if not transcript:
        raise ValueError("Verified script transcript is empty")
    max_chunk_chars = min(settings.max_tts_chunk_chars, GEMINI_TTS_SAFE_SOURCE_CHARS)
    chunks = []
    for index, chunk in enumerate(chunk_dialogue(transcript, max_chunk_chars), start=1):
        prompt = build_tts_prompt(chunk, speakers)
        chunks.append(
            {
                "index": index,
                "transcript": prompt,
                "source_transcript": chunk,
                "source_char_count": len(chunk),
                "prompt_char_count": len(prompt),
            }
        )

    return {
        "tts_model": settings.gemini_tts_model,
        "export_format": settings.audio_export_format,
        "max_source_chunk_chars": max_chunk_chars,
        "max_prompt_chars": GEMINI_TTS_SAFE_PROMPT_CHARS,
        "speakers": [
            {
                "speaker": speaker["name"],
                "voice_name": coerce_gemini_tts_voice_name(speaker.get("voice_name"), i),
                "style": speaker.get("style"),
            }
            for i, speaker in enumerate(speakers)
        ],
        "chunks": chunks,
    }


def tts_config_needs_rebuild(config: dict[str, Any]) -> bool:
    chunks = config.get("chunks") or []
    if not chunks:
        return True
    if int(config.get("max_source_chunk_chars") or 10**9) > GEMINI_TTS_SAFE_SOURCE_CHARS:
        return True
    speakers = config.get("speakers") or []
    if not speakers or len(speakers) > 2:
        return True
    for speaker in speakers:
        voice_name = str(speaker.get("voice_name") or "").strip().lower()
        if voice_name not in GEMINI_TTS_VOICE_NAMES:
            return True
    for chunk in chunks:
        transcript = chunk.get("transcript") or ""
        prompt_char_count = int(chunk.get("prompt_char_count") or len(transcript))
        if prompt_char_count > GEMINI_TTS_SAFE_PROMPT_CHARS:
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


def build_tts_prompt(transcript_chunk: str, speakers: list[dict[str, Any]]) -> str:
    speaker_names = " and ".join(speaker["name"] for speaker in speakers)
    style_instruction = speaker_style_instruction(speakers)
    preamble = f"{style_instruction}\n\n" if style_instruction else ""
    return f"""
{preamble}TTS the following conversation between {speaker_names}:

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
