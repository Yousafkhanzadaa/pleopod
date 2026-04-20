from __future__ import annotations

import re
from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.core.text import chunk_dialogue
from app.models.enums import ArtifactType, PipelineStep

_TTS_PREAMBLE_RE = re.compile(
    r"^\s*TTS\s+the\s+following\s+conversation\s+between\s+[^:\n]+:\s*", re.IGNORECASE
)
_TRANSCRIPT_HEADER_RE = re.compile(r"^\s*#{0,6}\s*TRANSCRIPT:?\s*", re.IGNORECASE)


class AudioConfigAgent(PipelineAgent):
    name = "audio_config_agent"
    step = PipelineStep.AUDIO_CONFIG

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        script = await context.latest_json(job_id, ArtifactType.VERIFIED_SCRIPT_JSON)
        speakers = script["speakers"][:2]
        transcript = normalize_tts_transcript(script["transcript"])
        if not transcript:
            raise ValueError("Verified script transcript is empty")
        chunks = []
        for index, chunk in enumerate(
            chunk_dialogue(transcript, context.settings.max_tts_chunk_chars), start=1
        ):
            prompt = build_tts_prompt(chunk, speakers)
            chunks.append(
                {
                    "index": index,
                    "transcript": prompt,
                    "source_char_count": len(chunk),
                    "prompt_char_count": len(prompt),
                }
            )

        config = {
            "tts_model": context.settings.gemini_tts_model,
            "export_format": context.settings.audio_export_format,
            "speakers": [
                {
                    "speaker": speaker["name"],
                    "voice_name": speaker.get("voice_name") or ("Charon" if i == 0 else "Puck"),
                    "style": speaker.get("style"),
                }
                for i, speaker in enumerate(speakers)
            ],
            "chunks": chunks,
        }
        artifact = await context.artifact_service.put_json(
            f"jobs/{job_id}/audio/tts_config.json",
            config,
            ArtifactType.TTS_CONFIG_JSON,
            job_id=job_id,
        )
        return AgentResult(
            output_artifact_id=str(artifact["id"]), next_step=PipelineStep.AUDIO_GENERATION
        )


def normalize_tts_transcript(transcript: str) -> str:
    text = transcript.strip()
    text = _TTS_PREAMBLE_RE.sub("", text, count=1).strip()
    text = _TRANSCRIPT_HEADER_RE.sub("", text, count=1).strip()
    return text


def build_tts_prompt(transcript_chunk: str, speakers: list[dict[str, Any]]) -> str:
    speaker_names = " and ".join(speaker["name"] for speaker in speakers)
    speaker_guidance = "\n".join(
        f"- {speaker['name']}: {speaker.get('style') or 'natural podcast delivery'}."
        for speaker in speakers
    )
    return f"""
TTS the following conversation between {speaker_names}. Return audio only.

### DIRECTOR'S NOTES
Format: A clear, polished two-speaker technology podcast segment.
Pacing: Natural, steady, and easy to follow.
Speaker guidance:
{speaker_guidance}
Do not read speaker labels, headings, or these notes aloud.

### TRANSCRIPT
{transcript_chunk.strip()}
""".strip()
