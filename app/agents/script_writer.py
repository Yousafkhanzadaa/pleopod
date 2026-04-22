from __future__ import annotations

import re
from typing import Any

from app.agents.base import AgentContext, AgentResult, PipelineAgent
from app.agents.prompts import script_prompt, script_repair_prompt
from app.core.json_utils import extract_json
from app.models.enums import ArtifactType, PipelineStep

_TTS_PREAMBLE_RE = re.compile(
    r"^\s*TTS\s+the\s+following\s+conversation\s+between\s+[^:\n]+:\s*",
    re.IGNORECASE,
)
_SPEAKER_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<label>.+?)\s*(?P<sep>:| - | – | — )\s*(?P<body>.+?)\s*$"
)


class ScriptWriterAgent(PipelineAgent):
    name = "script_writer_agent"
    step = PipelineStep.SCRIPT

    async def run(
        self, job: dict[str, Any], context: AgentContext, message: dict[str, Any]
    ) -> AgentResult:
        job_id = str(job["id"])
        memory_md = await context.latest_text(job_id, ArtifactType.MEMORY_MD)
        claims = await context.latest_json(job_id, ArtifactType.CLAIM_BANK_JSON)
        response = await context.ai.generate_text(
            prompt=script_prompt(job, memory_md, claims),
            model=context.settings.gemini_script_model,
        )
        script = extract_json(response.text)
        script = self._normalize_script(script)
        try:
            self._validate_script(script)
        except ValueError as exc:
            script = await self._repair_script(context, script, str(exc))
            script = self._normalize_script(script)
            self._validate_script(script)
            script.setdefault("metadata", {})["script_repaired_after_validation_error"] = True
        await context.artifact_service.put_text(
            f"jobs/{job_id}/scripts/script_v1.md",
            script["transcript"],
            ArtifactType.SCRIPT_MD,
            "text/markdown; charset=utf-8",
            job_id=job_id,
        )
        artifact = await context.artifact_service.put_json(
            f"jobs/{job_id}/scripts/script_v1.json",
            script,
            ArtifactType.SCRIPT_JSON,
            job_id=job_id,
        )
        return AgentResult(
            output_artifact_id=str(artifact["id"]), next_step=PipelineStep.FACT_CHECK
        )

    def _normalize_script(self, script: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(script)
        transcript = str(normalized.get("transcript") or "")
        speakers = normalized.get("speakers") or []
        if transcript and speakers:
            normalized["transcript"] = self._normalize_transcript(transcript, speakers)
        return normalized

    async def _repair_script(
        self,
        context: AgentContext,
        script: dict[str, Any],
        validation_error: str,
    ) -> dict[str, Any]:
        response = await context.ai.generate_text(
            prompt=script_repair_prompt(script, validation_error),
            model=context.settings.gemini_script_model,
        )
        return extract_json(response.text)

    def _normalize_transcript(self, transcript: str, speakers: list[dict[str, Any]]) -> str:
        speaker_names = [speaker.get("name") for speaker in speakers if speaker.get("name")]
        if len(speaker_names) != 2:
            return transcript

        prefix_match = _TTS_PREAMBLE_RE.match(transcript.strip())
        prefix = (
            f"TTS the following conversation between {speaker_names[0]} and "
            f"{speaker_names[1]}:\n\n"
        )
        body = transcript.strip()
        if prefix_match:
            body = body[prefix_match.end() :].lstrip()

        normalized_lines: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                normalized_lines.append("")
                continue

            speaker_line = self._normalize_speaker_line(line, speakers)
            normalized_lines.append(speaker_line or line)

        normalized_body = "\n".join(normalized_lines).strip()
        return f"{prefix}{normalized_body}".strip()

    def _normalize_speaker_line(self, line: str, speakers: list[dict[str, Any]]) -> str | None:
        match = _SPEAKER_LINE_RE.match(line)
        if not match:
            return None

        label = self._clean_label(match.group("label"))
        canonical_speaker = self._resolve_speaker_label(label, speakers)
        if not canonical_speaker:
            return None

        body = match.group("body").strip()
        body = re.sub(r"^(?:\*+|_+|`+)\s*", "", body)
        return f"{canonical_speaker}: {body}"

    def _resolve_speaker_label(self, label: str, speakers: list[dict[str, Any]]) -> str | None:
        candidates = {
            self._normalize_label_token(label),
            *(
                self._normalize_label_token(part)
                for part in re.findall(r"[A-Za-z][A-Za-z .'-]{0,64}", label)
            ),
        }
        candidates.discard("")
        if not candidates:
            return None

        for speaker in speakers:
            name = str(speaker.get("name") or "").strip()
            role = str(speaker.get("role") or "").strip()
            speaker_aliases = {
                self._normalize_label_token(name),
                self._normalize_label_token(role),
                self._normalize_label_token(f"{name} ({role})"),
                self._normalize_label_token(f"{role} ({name})"),
            }
            speaker_aliases.discard("")
            if candidates & speaker_aliases:
                return name
        return None

    def _clean_label(self, label: str) -> str:
        cleaned = label.strip()
        cleaned = cleaned.strip("*_`[]")
        cleaned = re.sub(r"\*+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" :")

    def _normalize_label_token(self, label: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()

    def _validate_script(self, script: dict[str, Any]) -> None:
        speakers = script.get("speakers") or []
        if len(speakers) != 2:
            raise ValueError("Gemini multi-speaker TTS MVP requires exactly two speakers")
        names = {speaker.get("name") for speaker in speakers}
        transcript = script.get("transcript") or ""
        if not transcript.strip():
            raise ValueError("Script transcript is empty")
        missing = [
            name
            for name in names
            if name and not re.search(rf"(?<![A-Za-z]){re.escape(name)}:", transcript)
        ]
        if missing:
            raise ValueError(f"Transcript missing speaker labels: {', '.join(missing)}")
