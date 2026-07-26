import json
from types import SimpleNamespace

import pytest

from app.agents.fact_verifier import FactVerifierAgent
from app.models.enums import ArtifactType


class _ArtifactService:
    def __init__(self) -> None:
        self.verified_script: dict | None = None

    async def put_text(
        self,
        key: str,
        text: str,
        artifact_type: ArtifactType | str,
        mime_type: str,
        job_id: str | None = None,
    ) -> dict:
        return {"id": "report-id"}

    async def put_json(
        self,
        key: str,
        data: dict,
        artifact_type: ArtifactType | str,
        job_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        if artifact_type == ArtifactType.VERIFIED_SCRIPT_JSON:
            self.verified_script = data
        return {"id": "verified-script-id"}


class _Context:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            gemini_verification_model="gemini-2.5-flash-lite",
            require_human_approval=False,
        )
        self.artifact_service = _ArtifactService()

        class _AI:
            async def generate_text(
                self,
                prompt: str,
                model: str,
                response_schema: object | None = None,
            ) -> SimpleNamespace:
                return SimpleNamespace(
                    text=json.dumps(
                        {
                            "verdict": "fixed",
                            "score": 1.0,
                            "fixed_transcript": (
                                "### TRANSCRIPT\n"
                                "Arman: This opening is supported.\n"
                                "This corrected continuation is supported too."
                            ),
                            "line_checks": [],
                        }
                    )
                )

        self.ai = _AI()

    async def latest_json(self, job_id: str, artifact_type: ArtifactType) -> dict | list:
        if artifact_type == ArtifactType.SCRIPT_JSON:
            return {
                "title": "Verified episode",
                "slug": "verified-episode",
                "summary": "Summary",
                "description": "Description",
                "speakers": [
                    {
                        "name": "Arman",
                        "role": "Presenter",
                        "voice_name": "Algenib",
                    }
                ],
                "transcript": (
                    "TTS the following talk by Arman:\n\n"
                    "Arman: Original opening.\n"
                    "Arman: Original closing."
                ),
                "used_claims": [],
            }
        if artifact_type == ArtifactType.CLAIM_BANK_JSON:
            return []
        raise AssertionError(f"Unexpected artifact type: {artifact_type}")


@pytest.mark.asyncio
async def test_fact_verifier_normalizes_and_revalidates_fixed_transcript() -> None:
    context = _Context()

    result = await FactVerifierAgent().run(
        {
            "id": "job-1",
            "target_duration_seconds": 60,
        },
        context,  # type: ignore[arg-type]
        {},
    )

    assert result.output_artifact_id == "verified-script-id"
    verified = context.artifact_service.verified_script
    assert verified is not None
    assert "TRANSCRIPT" not in verified["transcript"]
    assert "Arman: This opening is supported." in verified["transcript"]
    assert (
        "Arman: This corrected continuation is supported too."
        in verified["transcript"]
    )
    assert verified["metadata"]["fact_verifier_changed_transcript"] is True
