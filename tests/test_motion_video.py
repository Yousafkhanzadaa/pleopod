from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import motion_video
from app.services.motion_video import (
    MotionVideoSpec,
    build_ass_document,
    build_ffmpeg_command,
    caption_cues_from_line_timings,
    hex_to_ass_color,
    hex_to_ffmpeg_color,
    motion_background_supported,
    motion_caption_plan,
)


def _line(text: str, start: float, end: float, speaker: str = "Arman") -> dict:
    return {"id": "l", "speaker": speaker, "text": text, "startSeconds": start, "endSeconds": end}


def test_hex_to_ass_color_reorders_to_bgr() -> None:
    # #22d3ee -> BB=ee GG=d3 RR=22
    assert hex_to_ass_color("#22d3ee") == "&H00EED322"
    assert hex_to_ass_color("#FFFFFF") == "&H00FFFFFF"
    # shorthand and invalid values fall back to white.
    assert hex_to_ass_color("#fff") == "&H00FFFFFF"
    assert hex_to_ass_color("not-a-color") == "&H00FFFFFF"


def test_hex_to_ffmpeg_color() -> None:
    assert hex_to_ffmpeg_color("#22d3ee") == "0x22D3EE"
    assert hex_to_ffmpeg_color(None) == "0xFFFFFF"


def test_caption_cues_group_words_and_stay_ordered() -> None:
    cues = caption_cues_from_line_timings(
        [_line("Nvidia just shipped a new inference chip today", 0.0, 4.0)],
        max_words=3,
    )
    assert cues, "expected caption cues"
    # No cue exceeds the word budget.
    assert all(len(cue.words) <= 3 for cue in cues)
    # Cues are ordered and non-overlapping and within the line window.
    for earlier, later in zip(cues, cues[1:], strict=False):
        assert earlier.end <= later.start + 1e-6
    assert cues[0].start >= 0.0
    assert cues[-1].end <= 4.0 + 1e-6
    # Words are preserved in order.
    flattened = [word for cue in cues for word in cue.words]
    assert flattened == ["Nvidia", "just", "shipped", "a", "new", "inference", "chip", "today"]


def test_caption_cues_emphasize_a_long_word() -> None:
    (cue,) = caption_cues_from_line_timings([_line("the inference chip", 0.0, 1.5)], max_words=3)
    assert cue.words[cue.emphasis_index] == "inference"


def test_caption_cues_skip_invalid_lines() -> None:
    cues = caption_cues_from_line_timings(
        [
            _line("", 0.0, 2.0),
            _line("valid line here", 2.0, 1.0),  # end <= start
            {"text": "no timing"},
        ]
    )
    assert cues == []


def test_build_ass_document_has_styles_events_and_accent() -> None:
    cues = caption_cues_from_line_timings(
        [_line("the inference chip matters", 0.0, 2.0)], max_words=3
    )
    doc = build_ass_document(
        cues,
        video_width=1920,
        video_height=1080,
        accent_color="#22d3ee",
        title="Nvidia chip",
        brand="Pleopod",
        source_label="Sources: nvidia.com",
        duration=4,
    )
    assert "[V4+ Styles]" in doc
    assert "Style: Caption,DejaVu Sans," in doc
    assert "[Events]" in doc
    # Intro title, brand and source events are present.
    assert ",Title,," in doc
    assert ",Brand,," in doc
    assert ",Source,," in doc
    # Caption events use the ASS timestamp format H:MM:SS.cc.
    assert "Dialogue: 0,0:00:00.00," in doc
    # Emphasized word is wrapped in the accent colour.
    assert hex_to_ass_color("#22d3ee") in doc
    # Text is upper-cased for punchy captions.
    assert "INFERENCE" in doc


def test_build_ffmpeg_command_core_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motion_video, "ffmpeg_supports", lambda *names: True)
    monkeypatch.setattr(motion_video, "captions_supported", lambda: False)
    spec = MotionVideoSpec(
        image_path="/tmp/bg.png",
        audio_path="/tmp/audio.mp3",
        output_path="/tmp/final.mp4",
        duration_seconds=59,
        width=1920,
        height=1080,
        fps=30,
        waveform=True,
    )
    cmd = build_ffmpeg_command(spec)
    assert cmd[0] == "ffmpeg"
    assert cmd[-1] == "/tmp/final.mp4"
    assert cmd.count("-i") == 2
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "zoompan" in graph
    assert "showwaves" in graph  # waveform enabled
    assert "drawbox" in graph  # progress bar
    assert "ass=f=" not in graph  # captions not supported here
    assert cmd[cmd.index("-map") + 1] == "[vout]"
    # With a waveform the audio is split and the split output is mapped.
    assert "[a_out]" in cmd
    assert cmd[cmd.index("-t") + 1] == "59.000"


def test_build_ffmpeg_command_burns_captions_when_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(motion_video, "ffmpeg_supports", lambda *names: True)
    monkeypatch.setattr(motion_video, "captions_supported", lambda: True)
    spec = MotionVideoSpec(
        image_path="/tmp/bg.png",
        audio_path="/tmp/audio.mp3",
        output_path="/tmp/final.mp4",
        duration_seconds=30,
        ass_path="/tmp/captions.ass",
        fonts_dir="/usr/share/fonts",
    )
    graph = build_ffmpeg_command(spec)[build_ffmpeg_command(spec).index("-filter_complex") + 1]
    assert "ass=f=/tmp/captions.ass" in graph
    assert "fontsdir=/usr/share/fonts" in graph


def test_build_ffmpeg_command_without_waveform_maps_audio_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(motion_video, "ffmpeg_supports", lambda *names: True)
    monkeypatch.setattr(motion_video, "captions_supported", lambda: False)
    spec = MotionVideoSpec(
        image_path="/tmp/bg.png",
        audio_path="/tmp/audio.mp3",
        output_path="/tmp/final.mp4",
        duration_seconds=30,
        waveform=False,
    )
    cmd = build_ffmpeg_command(spec)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "showwaves" not in graph
    assert "asplit" not in graph
    # Audio is mapped straight from the input.
    map_values = [cmd[i + 1] for i, token in enumerate(cmd) if token == "-map"]
    assert "1:a" in map_values


def test_motion_caption_plan_reports_features() -> None:
    plan = motion_caption_plan(
        {"durationSeconds": 88, "format": {"width": 1920, "height": 1080, "fps": 30}},
        captions=True,
        waveform=True,
    )
    assert plan["renderMode"] == "motion_caption"
    assert plan["features"] == {
        "kenBurns": True,
        "captions": True,
        "waveform": True,
        "progressBar": True,
    }
    assert plan["format"]["width"] == 1920


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe") and motion_background_supported()),
    reason="ffmpeg with zoompan/showwaves is required for the integration render",
)
def test_motion_caption_render_produces_valid_mp4(tmp_path: Path) -> None:
    image = tmp_path / "bg.png"
    audio = tmp_path / "audio.wav"
    output = tmp_path / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:duration=1",
         "-frames:v", "1", str(image)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=320:duration=3", str(audio)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    spec = MotionVideoSpec(
        image_path=str(image),
        audio_path=str(audio),
        output_path=str(output),
        duration_seconds=3,
        width=1280,
        height=720,
        fps=24,
        ass_path=None,  # captions need libass which may be absent locally
        waveform=True,
    )
    result = subprocess.run(build_ffmpeg_command(spec), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    assert output.exists() and output.stat().st_size > 0

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(output)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(probe.stdout)
    codecs = {stream["codec_type"]: stream["codec_name"] for stream in info["streams"]}
    assert codecs.get("video") == "h264"
    assert codecs.get("audio") == "aac"
    assert abs(float(info["format"]["duration"]) - 3.0) < 0.6
