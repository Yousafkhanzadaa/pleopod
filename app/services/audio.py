from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from app.providers.ai import AudioGeneration


def wav_bytes(audio: AudioGeneration) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(audio.channels)
            wf.setsampwidth(audio.sample_width)
            wf.setframerate(audio.sample_rate)
            wf.writeframes(audio.pcm_data)
        return Path(tmp.name).read_bytes()


def stitch_pcm_to_wav(segments: list[AudioGeneration]) -> bytes:
    if not segments:
        raise ValueError("No audio segments to stitch")
    first = segments[0]
    pcm = b"".join(segment.pcm_data for segment in segments)
    return wav_bytes(
        AudioGeneration(
            pcm_data=pcm,
            sample_rate=first.sample_rate,
            channels=first.channels,
            sample_width=first.sample_width,
        )
    )


def wav_to_mp3(wav_data: bytes) -> bytes:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required for MP3 export")
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = Path(tmpdir) / "input.wav"
        out_path = Path(tmpdir) / "output.mp3"
        in_path.write_bytes(wav_data)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(in_path),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "-ar",
                "44100",
                str(out_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return out_path.read_bytes()
