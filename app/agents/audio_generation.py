from __future__ import annotations

import hashlib
import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any

from app.agents.audio_config import (
    build_tts_config,
    narration_text,
    source_transcript_from_tts_prompt,
    tts_config_needs_rebuild,
)
from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.core.text import strip_speaker_labels
from app.models.enums import ArtifactType, PipelineStep
from app.providers.ai import AudioGeneration, SpeakerVoice, WordTiming
from app.services.audio import (
    audio_duration_seconds,
    audio_from_wav_bytes,
    stitch_pcm_to_wav,
    wav_bytes,
    wav_to_mp3,
)

logger = logging.getLogger(__name__)
_DIALOGUE_LINE_RE = re.compile(r"^([^:]{1,48}):\s*(.+)$")
_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
_CAPTION_WORD_RE = re.compile(
    r"\$?\d+(?:[.,]\d+)*|[^\W_]+(?:[-'][^\W_]+)*[.,!?;:]?",
    re.UNICODE,
)


class AudioGenerationAgent(PipelineAgent):
    name = "audio_generation_agent"
    step = PipelineStep.AUDIO_GENERATION

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        force = bool(message.get("force"))

        config = await context.latest_json(job_id, ArtifactType.TTS_CONFIG_JSON)
        if tts_config_needs_rebuild(config, context.settings):
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
        aligner = getattr(context, "word_aligner", None)
        alignment_required = bool(
            getattr(context.settings, "enable_word_alignment", False) and aligner is not None
        )
        existing_final = await context.artifact_repo.get_latest_for_job(
            job_id, ArtifactType.FINAL_AUDIO
        )
        if (
            existing_final
            and not force
            and final_audio_matches_tts_config(existing_final, config_fingerprint)
            and (
                not alignment_required
                or bool((existing_final.get("metadata") or {}).get("word_timings"))
            )
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
            segment_fingerprint = tts_segment_fingerprint(config, chunk)
            source_transcript = chunk.get("source_transcript") or source_transcript_from_tts_prompt(
                transcript
            )
            existing_segment = (
                None
                if force
                else await self._get_completed_segment_audio(
                    context,
                    job_id,
                    index,
                    segment_fingerprint,
                )
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
                "Generating TTS segment %s/%s for job %s",
                index,
                chunk_count,
                job_id,
            )
            await context.tts_segment_repo.upsert_segment(
                job_id,
                index,
                segment_fingerprint,
                "running",
            )
            narration_ai = getattr(context, "narration_ai", context.ai)
            audio = await narration_ai.generate_tts(
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
                metadata={
                    "segment_index": index,
                    "tts_segment_fingerprint": segment_fingerprint,
                },
            )
            await context.tts_segment_repo.upsert_segment(
                job_id,
                index,
                segment_fingerprint,
                "completed",
                r2_key=segment_key,
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

        alignment_metadata: dict[str, Any] = {}
        if alignment_required and aligner is not None:
            try:
                alignment = await aligner.align_words(
                    final_wav,
                    mime_type="audio/wav",
                    model=str(
                        getattr(context.settings, "alignment_model", "whisper-1")
                    ),
                    language=str(job.get("language") or "en"),
                )
                source_transcript = "\n".join(
                    str(chunk.get("source_transcript") or "")
                    for chunk in config.get("chunks") or []
                )
                canonical_words = canonical_word_timings(
                    source_transcript,
                    alignment.words,
                )
                alignment_metadata = {
                    "alignment_model": str(
                        getattr(context.settings, "alignment_model", "whisper-1")
                    ),
                    "aligned_transcript": alignment.text,
                    "word_timings": serialize_word_timings(canonical_words),
                    "line_timings": line_timings_from_word_alignment(
                        source_transcript,
                        canonical_words,
                    ),
                }
            except Exception:  # noqa: BLE001 - alignment is an optional quality enhancement
                logger.warning(
                    "Word-level alignment failed for job %s; using segment timing fallback",
                    job_id,
                    exc_info=True,
                )

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
                **alignment_metadata,
            },
        )
        return AgentResult(output_artifact_id=str(artifact["id"]))

    async def _get_completed_segment_audio(
        self,
        context: AgentContext,
        job_id: str,
        index: int,
        segment_fingerprint: str,
    ) -> AudioGeneration | None:
        r2_key = await context.tts_segment_repo.get_completed_segment_key(
            job_id,
            index,
            segment_fingerprint,
        )
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
        "voice_provider": config.get("voice_provider"),
        "tts_model": config.get("tts_model"),
        "tts_instructions": config.get("tts_instructions"),
        "tts_speed": config.get("tts_speed"),
        "export_format": config.get("export_format"),
        "generation_mode": config.get("generation_mode"),
        "speakers": config.get("speakers") or [],
        "chunks": [
            {"index": int(chunk["index"]), "transcript": str(chunk.get("transcript") or "")}
            for chunk in config.get("chunks") or []
        ],
    }
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def tts_segment_fingerprint(config: dict[str, Any], chunk: dict[str, Any]) -> str:
    payload = {
        "voice_provider": config.get("voice_provider"),
        "tts_model": config.get("tts_model"),
        "tts_instructions": config.get("tts_instructions"),
        "tts_speed": config.get("tts_speed"),
        "speakers": config.get("speakers") or [],
        "transcript": str(chunk.get("transcript") or ""),
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


def serialize_word_timings(words: list[WordTiming]) -> list[dict[str, Any]]:
    return [
        {
            "word": word.word,
            "start_seconds": round(word.start_seconds, 3),
            "end_seconds": round(word.end_seconds, 3),
        }
        for word in words
        if word.word.strip() and word.end_seconds > word.start_seconds >= 0
    ]


def canonical_word_timings(
    transcript: str,
    aligned_words: list[WordTiming],
) -> list[WordTiming]:
    """Keep measured ASR timing while restoring words from the verified script."""
    canonical_text = " ".join(line["text"] for line in _parse_dialogue_lines(transcript))
    expected_words = _CAPTION_WORD_RE.findall(canonical_text)
    measured_words = sorted(
        (
            word
            for word in aligned_words
            if word.word.strip()
            and word.start_seconds >= 0
            and word.end_seconds > word.start_seconds
        ),
        key=lambda word: word.start_seconds,
    )
    if not expected_words or not measured_words:
        return measured_words

    expected_tokens = [_normalize_word(word) for word in expected_words]
    measured_tokens = [_normalize_word(word.word) for word in measured_words]
    matcher = SequenceMatcher(a=expected_tokens, b=measured_tokens, autojunk=False)
    canonical: list[WordTiming] = []
    start_overrides: dict[int, float] = {}

    def append_span(words: list[str], start: float, end: float) -> None:
        if not words:
            return
        end = max(end, start + 0.04 * len(words))
        weights = [max(1, len(_normalize_word(word))) for word in words]
        total_weight = sum(weights)
        cursor = start
        elapsed_weight = 0
        for index, (word, weight) in enumerate(zip(words, weights, strict=False)):
            elapsed_weight += weight
            word_end = (
                end
                if index == len(words) - 1
                else start + (end - start) * elapsed_weight / total_weight
            )
            canonical.append(
                WordTiming(
                    word=word,
                    start_seconds=round(cursor, 3),
                    end_seconds=round(max(cursor + 0.03, word_end), 3),
                )
            )
            cursor = word_end

    for tag, expected_start, expected_end, measured_start, measured_end in matcher.get_opcodes():
        expected_span = expected_words[expected_start:expected_end]
        if tag == "equal":
            for offset, word in enumerate(expected_span):
                measured_index = measured_start + offset
                measured = measured_words[measured_index]
                start = max(
                    measured.start_seconds,
                    start_overrides.get(measured_index, measured.start_seconds),
                    canonical[-1].end_seconds if canonical else 0.0,
                )
                canonical.append(
                    WordTiming(
                        word=word,
                        start_seconds=round(start, 3),
                        end_seconds=round(max(start + 0.03, measured.end_seconds), 3),
                    )
                )
            continue

        if not expected_span:
            continue
        if measured_end > measured_start:
            append_span(
                expected_span,
                measured_words[measured_start].start_seconds,
                measured_words[measured_end - 1].end_seconds,
            )
            continue

        previous_end = canonical[-1].end_seconds if canonical else 0.0
        if measured_start < len(measured_words):
            next_word = measured_words[measured_start]
            available = max(0.08, next_word.end_seconds - next_word.start_seconds)
            span_start = max(previous_end, next_word.start_seconds)
            span_end = min(
                next_word.end_seconds - 0.03,
                span_start + max(0.04 * len(expected_span), available * 0.55),
            )
            span_end = max(span_end, span_start + 0.04 * len(expected_span))
            start_overrides[measured_start] = span_end
        else:
            span_start = previous_end
            span_end = span_start + 0.12 * len(expected_span)
        append_span(expected_span, span_start, span_end)

    return canonical or measured_words


def line_timings_from_word_alignment(
    source_transcript: str,
    words: list[WordTiming],
) -> list[dict[str, Any]]:
    """Map measured word timestamps back onto the script's dialogue lines."""
    lines = _parse_dialogue_lines(source_transcript)
    valid_words = [
        word
        for word in words
        if word.word.strip() and word.end_seconds > word.start_seconds >= 0
    ]
    if not lines or not valid_words:
        return []

    expected_tokens: list[str] = []
    line_ranges: list[tuple[int, int]] = []
    for line in lines:
        start = len(expected_tokens)
        expected_tokens.extend(_normalized_words(line["text"]))
        line_ranges.append((start, len(expected_tokens)))
    aligned_words = [
        (word, normalized)
        for word in valid_words
        if (normalized := _normalize_word(word.word))
    ]
    actual_tokens = [normalized for _, normalized in aligned_words]
    if not expected_tokens or not actual_tokens:
        return []

    matcher = SequenceMatcher(a=expected_tokens, b=actual_tokens, autojunk=False)
    matched_pairs: list[tuple[int, int]] = []
    for block in matcher.get_matching_blocks():
        matched_pairs.extend(
            (block.a + offset, block.b + offset) for offset in range(block.size)
        )

    timings: list[dict[str, Any]] = []
    expected_count = len(expected_tokens)
    actual_count = len(aligned_words)
    for index, (line, (expected_start, expected_end)) in enumerate(
        zip(lines, line_ranges, strict=False),
        start=1,
    ):
        matched_indices = [
            actual_index
            for expected_index, actual_index in matched_pairs
            if expected_start <= expected_index < expected_end
        ]
        if matched_indices:
            actual_start = min(matched_indices)
            actual_end = max(matched_indices) + 1
        else:
            actual_start = round(expected_start / expected_count * actual_count)
            actual_end = round(expected_end / expected_count * actual_count)
        actual_start = max(0, min(actual_start, actual_count - 1))
        actual_end = max(actual_start + 1, min(actual_end, actual_count))
        timings.append(
            {
                "id": f"line_{index:03d}",
                "speaker": line["speaker"],
                "text": line["text"],
                "start_seconds": round(aligned_words[actual_start][0].start_seconds, 3),
                "end_seconds": round(aligned_words[actual_end - 1][0].end_seconds, 3),
            }
        )
    return timings


def _parse_dialogue_lines(transcript: str) -> list[dict[str, str]]:
    lines: list[dict[str, str]] = []
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _DIALOGUE_LINE_RE.match(line)
        if match:
            speaker = match.group(1).strip()
            lines.append(
                {
                    "speaker": speaker,
                    "text": strip_speaker_labels(match.group(2), [speaker]),
                }
            )
        else:
            text = narration_text(line)
            if text:
                lines.append({"speaker": "", "text": text})
    return lines


def _normalized_words(text: str) -> list[str]:
    return [
        normalized
        for token in _WORD_RE.findall(text)
        if (normalized := _normalize_word(token))
    ]


def _normalize_word(word: str) -> str:
    return "".join(character for character in word.casefold() if character.isalnum())
