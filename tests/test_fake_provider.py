import pytest

from app.agents.prompts import script_prompt, verification_prompt
from app.providers.ai import SpeakerVoice
from app.providers.fake import FakeAIProvider
from app.schemas.agent_outputs import PodcastScript, ResearchDossier, VerificationReport


@pytest.mark.asyncio
async def test_fake_provider_generates_audio() -> None:
    provider = FakeAIProvider()
    audio = await provider.generate_tts(
        "TTS the following conversation between Arman and Maya:\n\nArman: Hello\nMaya: Hi",
        "fake-tts",
        [SpeakerVoice("Arman", "Charon"), SpeakerVoice("Maya", "Aoede")],
    )
    assert audio.sample_rate == 24000
    assert len(audio.pcm_data) > 0


@pytest.mark.asyncio
async def test_fake_provider_uses_schema_over_prompt_text_for_script() -> None:
    provider = FakeAIProvider()
    response = await provider.generate_text(
        script_prompt(
            {
                "topic": "AI",
                "audience": "builders",
                "target_duration_seconds": 120,
                "language": "en",
                "tone": "clear",
            },
            "# Research Memory\n\nCreate a research dossier for this podcast topic.",
            [{"claim_text": "Verification improves trust."}],
        ),
        "fake",
        response_schema=PodcastScript,
    )

    script = PodcastScript.model_validate_json(response.text)

    assert script.title == "The AI Podcast Pipeline"
    assert "Arman:" in script.transcript


@pytest.mark.asyncio
async def test_fake_provider_uses_schema_over_prompt_text_for_verification() -> None:
    provider = FakeAIProvider()
    response = await provider.generate_text(
        verification_prompt(
            {"transcript": "Arman: This is a podcast script."},
            [{"claim_text": "Verification improves trust."}],
        ),
        "fake",
        response_schema=VerificationReport,
    )

    report = VerificationReport.model_validate_json(response.text)

    assert report.verdict == "approved"


@pytest.mark.asyncio
async def test_fake_provider_returns_research_for_research_schema() -> None:
    provider = FakeAIProvider()
    response = await provider.generate_text(
        "Create a research dossier for this podcast topic.",
        "fake",
        response_schema=ResearchDossier,
    )

    dossier = ResearchDossier.model_validate_json(response.text)

    assert dossier.claims
