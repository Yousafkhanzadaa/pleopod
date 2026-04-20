from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.agents.audio_config import build_tts_config, tts_config_needs_rebuild
from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.models.enums import ArtifactType, PipelineStep
from app.providers.ai import AudioGeneration, SpeakerVoice
from app.services.audio import stitch_pcm_to_wav, wav_bytes, wav_to_mp3


class AudioGenerationAgent(PipelineAgent):
    name = "audio_generation_agent"
    step = PipelineStep.AUDIO_GENERATION

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        config = await context.latest_json(job_id, ArtifactType.TTS_CONFIG_JSON)
        if tts_config_needs_rebuild(config):
            script = await context.latest_json(job_id, ArtifactType.VERIFIED_SCRIPT_JSON)
            config = build_tts_config(script, context.settings)
            await context.artifact_service.put_json(
                f"jobs/{job_id}/audio/tts_config_rebuilt.json",
                config,
                ArtifactType.TTS_CONFIG_JSON,
                job_id=job_id,
                metadata={"reason": "rebuilt stale or oversized TTS config"},
            )
        speakers = [
            SpeakerVoice(
                speaker=item["speaker"],
                voice_name=item["voice_name"],
                style=item.get("style"),
            )
            for item in config["speakers"]
        ]
        audio_segments: list[AudioGeneration] = []
        for chunk in config["chunks"]:
            index = int(chunk["index"])
            transcript = chunk["transcript"]
            await self._upsert_segment(context, job_id, index, transcript, "running")
            audio = await context.ai.generate_tts(
                prompt=transcript,
                model=config["tts_model"],
                speakers=speakers,
            )
            audio_segments.append(audio)
            segment_wav = wav_bytes(audio)
            segment_key = f"jobs/{job_id}/audio/segments/{index:03d}.wav"
            await context.artifact_service.put_bytes(
                segment_key,
                segment_wav,
                ArtifactType.AUDIO_SEGMENT,
                "audio/wav",
                job_id=job_id,
                metadata={"segment_index": index},
            )
            await self._upsert_segment(
                context, job_id, index, transcript, "completed", r2_key=segment_key
            )

        final_wav = stitch_pcm_to_wav(audio_segments)
        final_data = final_wav
        mime_type = "audio/wav"
        extension = "wav"
        if config.get("export_format") == "mp3":
            try:
                final_data = wav_to_mp3(final_wav)
                mime_type = "audio/mpeg"
                extension = "mp3"
            except RuntimeError:
                # Local machines often do not have ffmpeg; production Dockerfile does.
                final_data = final_wav

        artifact = await context.artifact_service.put_bytes(
            f"jobs/{job_id}/audio/final.{extension}",
            final_data,
            ArtifactType.FINAL_AUDIO,
            mime_type,
            job_id=job_id,
            metadata={"segment_count": len(audio_segments)},
        )
        return AgentResult(output_artifact_id=str(artifact["id"]), next_step=PipelineStep.PUBLISH)

    async def _upsert_segment(
        self,
        context: AgentContext,
        job_id: str,
        index: int,
        transcript: str,
        status: str,
        r2_key: str | None = None,
    ) -> None:
        await context.session.execute(
            text(
                """
                insert into tts_segments (
                  job_id, segment_index, transcript, status, r2_key, mime_type
                )
                values (:job_id, :segment_index, :transcript, :status, :r2_key, 'audio/wav')
                on conflict (job_id, segment_index)
                do update set status = excluded.status,
                              r2_key = coalesce(excluded.r2_key, tts_segments.r2_key),
                              updated_at = now()
                """
            ),
            {
                "job_id": job_id,
                "segment_index": index,
                "transcript": transcript,
                "status": status,
                "r2_key": r2_key,
            },
        )
        await context.session.commit()
