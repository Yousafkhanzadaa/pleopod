import pytest

from app.providers.ai import SpeakerVoice
from app.providers.fake import FakeAIProvider


@pytest.mark.asyncio
async def test_fake_provider_generates_audio() -> None:
    provider = FakeAIProvider()
    audio = await provider.generate_tts(
        "TTS the following conversation between Arman and Maya:\n\nArman: Hello\nMaya: Hi",
        "fake-tts",
        [SpeakerVoice("Arman", "Charon"), SpeakerVoice("Maya", "Puck")],
    )
    assert audio.sample_rate == 24000
    assert len(audio.pcm_data) > 0
