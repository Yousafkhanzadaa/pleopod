from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.agents.audio_config import build_tts_config, tts_config_needs_rebuild
from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.models.enums import ArtifactType, PipelineStep
from app.providers.ai import AudioGeneration, SpeakerVoice
from app.services.audio import (
    audio_duration_seconds,
    audio_from_wav_bytes,
    stitch_pcm_to_wav,
    wav_bytes,
    wav_to_mp3,
)

logger = logging.getLogger(__name__)


class AudioGenerationAgent(PipelineAgent):
    name = "audio_generation_agent"
    step = PipelineStep.AUDIO_GENERATION

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        existing_final = await context.artifact_repo.get_latest_for_job(
            job_id, ArtifactType.FINAL_AUDIO
        )
        if existing_final:
            logger.info("Final audio already exists for job %s, skipping regeneration", job_id)
            return AgentResult(
                output_artifact_id=str(existing_final["id"]),
            )

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
        chunk_count = len(config["chunks"])
        for chunk in config["chunks"]:
            index = int(chunk["index"])
            transcript = chunk["transcript"]
            existing_segment = await self._get_completed_segment_audio(context, job_id, index)
            if existing_segment is not None:
                logger.info(
                    "Reusing completed TTS segment %s/%s for job %s",
                    index,
                    chunk_count,
                    job_id,
                )
                audio_segments.append(existing_segment)
                continue

            logger.info(
                "Generating TTS chunk %s/%s for job %s",
                index,
                chunk_count,
                job_id,
            )
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
        final_duration_seconds = sum(audio_duration_seconds(segment) for segment in audio_segments)
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
            metadata={
                "segment_count": len(audio_segments),
                "duration_seconds": round(final_duration_seconds, 3),
            },
        )
        return AgentResult(output_artifact_id=str(artifact["id"]))

    async def _get_completed_segment_audio(
        self,
        context: AgentContext,
        job_id: str,
        index: int,
    ) -> AudioGeneration | None:
        result = await context.session.execute(
            text(
                """
                select r2_key
                from tts_segments
                where job_id = :job_id
                  and segment_index = :segment_index
                  and status = 'completed'
                  and r2_key is not null
                """
            ),
            {"job_id": job_id, "segment_index": index},
        )
        row = result.mappings().first()
        if not row:
            return None

        wav_data = await context.storage.get_bytes(row["r2_key"])
        return audio_from_wav_bytes(wav_data)

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
