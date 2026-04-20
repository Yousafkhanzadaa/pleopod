from __future__ import annotations

from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.core.text import chunk_dialogue
from app.models.enums import ArtifactType, PipelineStep


class AudioConfigAgent(PipelineAgent):
    name = "audio_config_agent"
    step = PipelineStep.AUDIO_CONFIG

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        script = await context.latest_json(job_id, ArtifactType.VERIFIED_SCRIPT_JSON)
        speakers = script["speakers"][:2]
        speaker_names = " and ".join(speaker["name"] for speaker in speakers)
        transcript = script["transcript"].strip()
        chunks = []
        for index, chunk in enumerate(
            chunk_dialogue(transcript, context.settings.max_tts_chunk_chars), start=1
        ):
            if not chunk.lower().startswith("tts "):
                chunk = f"TTS the following conversation between {speaker_names}:\n\n{chunk}"
            chunks.append({"index": index, "transcript": chunk})

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
