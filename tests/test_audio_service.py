from app.providers.ai import AudioGeneration
from app.services.audio import audio_from_wav_bytes, wav_bytes


def test_audio_from_wav_bytes_round_trips_pcm() -> None:
    original = AudioGeneration(
        pcm_data=b"\x01\x00\x02\x00\x03\x00\x04\x00",
        sample_rate=24000,
        channels=1,
        sample_width=2,
    )

    decoded = audio_from_wav_bytes(wav_bytes(original))

    assert decoded.pcm_data == original.pcm_data
    assert decoded.sample_rate == original.sample_rate
    assert decoded.channels == original.channels
    assert decoded.sample_width == original.sample_width

