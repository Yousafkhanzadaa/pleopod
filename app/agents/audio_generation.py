from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.agents.audio_config import (
    build_tts_config,
    source_transcript_from_tts_prompt,
    tts_config_needs_rebuild,
)
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
        force = bool(message.get("force"))

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
        config_fingerprint = tts_config_fingerprint(config)
        existing_final = await context.artifact_repo.get_latest_for_job(
            job_id, ArtifactType.FINAL_AUDIO
        )
        if (
            existing_final
            and not force
            and final_audio_matches_tts_config(existing_final, config_fingerprint)
        ):
            logger.info("Final audio already matches current TTS config for job %s", job_id)
            return AgentResult(output_artifact_id=str(existing_final["id"]))

        speakers = [
            SpeakerVoice(
                speaker=item["speaker"],
                voice_name=item["voice_name"],
                style=item.get("style"),
            )
            for item in config["speakers"]
        ]
        audio_segments: list[AudioGeneration] = []
        segment_timings: list[dict[str, Any]] = []
        segment_start_seconds = 0.0
        chunk_count = len(config["chunks"])
        for chunk in config["chunks"]:
            index = int(chunk["index"])
            transcript = chunk["transcript"]
            source_transcript = chunk.get("source_transcript") or source_transcript_from_tts_prompt(
                transcript
            )
            existing_segment = (
                None
                if force
                else await self._get_completed_segment_audio(context, job_id, index, transcript)
            )
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
            await context.tts_segment_repo.upsert_segment(job_id, index, transcript, "running")
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
            await context.tts_segment_repo.upsert_segment(
                job_id, index, transcript, "completed", r2_key=segment_key
            )
            segment_duration_seconds = audio_duration_seconds(audio_segments[-1])
            segment_end_seconds = segment_start_seconds + segment_duration_seconds
            segment_timings.append(
                {
                    "index": index,
                    "start_seconds": round(segment_start_seconds, 3),
                    "end_seconds": round(segment_end_seconds, 3),
                    "duration_seconds": round(segment_duration_seconds, 3),
                    "source_transcript": source_transcript,
                }
            )
            segment_start_seconds = segment_end_seconds

        if len(segment_timings) < len(audio_segments):
            segment_timings = build_segment_timings(config["chunks"], audio_segments)

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
                "tts_config_fingerprint": config_fingerprint,
                "segment_timings": segment_timings,
            },
        )
        return AgentResult(output_artifact_id=str(artifact["id"]))

    async def _get_completed_segment_audio(
        self,
        context: AgentContext,
        job_id: str,
        index: int,
        transcript: str,
    ) -> AudioGeneration | None:
        r2_key = await context.tts_segment_repo.get_completed_segment_key(job_id, index, transcript)
        if not r2_key:
            return None

        wav_data = await context.storage.get_bytes(r2_key)
        return audio_from_wav_bytes(wav_data)


def final_audio_matches_tts_config(
    existing_final: dict[str, Any],
    config_fingerprint: str,
) -> bool:
    metadata = existing_final.get("metadata") or {}
    return metadata.get("tts_config_fingerprint") == config_fingerprint


def tts_config_fingerprint(config: dict[str, Any]) -> str:
    payload = {
        "tts_model": config.get("tts_model"),
        "export_format": config.get("export_format"),
        "speakers": config.get("speakers") or [],
        "chunks": [
            {"index": int(chunk["index"]), "transcript": str(chunk.get("transcript") or "")}
            for chunk in config.get("chunks") or []
        ],
    }
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def build_segment_timings(
    chunks: list[dict[str, Any]],
    audio_segments: list[AudioGeneration],
) -> list[dict[str, Any]]:
    timings: list[dict[str, Any]] = []
    cursor = 0.0
    for chunk, audio in zip(chunks, audio_segments, strict=False):
        duration = audio_duration_seconds(audio)
        end_seconds = cursor + duration
        transcript = str(chunk.get("transcript") or "")
        timings.append(
            {
                "index": int(chunk["index"]),
                "start_seconds": round(cursor, 3),
                "end_seconds": round(end_seconds, 3),
                "duration_seconds": round(duration, 3),
                "source_transcript": chunk.get("source_transcript")
                or source_transcript_from_tts_prompt(transcript),
            }
        )
        cursor = end_seconds
    return timings
