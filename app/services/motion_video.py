"""ffmpeg-based motion-caption video renderer.

This module builds an engaging short-form video from an episode's audio, a
background image, and word-level caption timings using only ffmpeg filters. It
is intentionally free of any headless browser so it runs cheaply anywhere,
including a Railway hobby instance.

Design:
- Ken Burns (slow zoom/pan) on the background image via ``zoompan``.
- Big animated word-group captions burned in from a generated ASS subtitle
  file (captions, an intro title card, a brand wordmark, and a closing source
  card all live in that single ASS document).
- An audio-reactive ``showwaves`` strip near the bottom.
- A time-driven progress bar via ``drawbox``.

Text rendering (the ASS filter) needs an ffmpeg built with libass, which the
production Debian image ships but some minimal local builds do not. Everything
here is capability-detected so the richest supported video is produced, and the
caller can fall back to a plain static render if even the motion background is
unavailable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

WHITE_HEX = "#FFFFFF"
BLACK_HEX = "#000000"
DEFAULT_ACCENT_HEX = "#22D3EE"

# Deterministic font search order. The production Dockerfile installs
# fonts-dejavu-core; macOS ships Arial. libass resolves the family name via
# fontconfig, but drawtext-free rendering still benefits from a known fontsdir.
_FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
)


# --------------------------------------------------------------------------- #
# ffmpeg capability detection
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def available_ffmpeg_filters() -> frozenset[str]:
    if not shutil.which("ffmpeg"):
        return frozenset()
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return frozenset()

    names: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        # Lines look like: " T.. drawtext V->V  Draw text on top of video."
        if len(parts) >= 3 and re.fullmatch(r"[A-Za-z0-9_]+", parts[1]):
            names.add(parts[1])
    return frozenset(names)


def ffmpeg_supports(*filters: str) -> bool:
    available = available_ffmpeg_filters()
    return bool(available) and all(name in available for name in filters)


def captions_supported() -> bool:
    """True when ffmpeg can burn ASS subtitles (needs a libass build)."""
    return ffmpeg_supports("ass")


def motion_background_supported() -> bool:
    """True when ffmpeg can build the Ken Burns background and audio waveform."""
    return ffmpeg_supports("zoompan", "scale", "crop")


# --------------------------------------------------------------------------- #
# Colour helpers
# --------------------------------------------------------------------------- #


def _normalize_hex(value: str | None, fallback: str) -> str:
    text = (value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", text):
        return fallback.lstrip("#").upper()
    return text.upper()


def hex_to_ass_color(value: str | None, fallback: str = WHITE_HEX) -> str:
    """Convert ``#RRGGBB`` to an opaque ASS ``&HAABBGGRR`` colour."""
    h = _normalize_hex(value, fallback)
    rr, gg, bb = h[0:2], h[2:4], h[4:6]
    return f"&H00{bb}{gg}{rr}"


def hex_to_ffmpeg_color(value: str | None, fallback: str = WHITE_HEX) -> str:
    """Convert ``#RRGGBB`` to an ffmpeg ``0xRRGGBB`` colour."""
    return f"0x{_normalize_hex(value, fallback)}"


# --------------------------------------------------------------------------- #
# Caption cues
# --------------------------------------------------------------------------- #


@dataclass
class CaptionCue:
    start: float
    end: float
    words: list[str]
    emphasis_index: int = -1


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _emphasis_index(words: Sequence[str]) -> int:
    best_index, best_len = -1, 0
    for index, word in enumerate(words):
        core = re.sub(r"[^A-Za-z0-9]", "", word)
        if len(core) >= 5 and len(core) > best_len:
            best_index, best_len = index, len(core)
    return best_index


def caption_cues_from_line_timings(
    line_timings: Sequence[dict[str, Any]] | None,
    *,
    max_words: int = 3,
    min_cue_seconds: float = 0.32,
    gap_seconds: float = 0.02,
) -> list[CaptionCue]:
    """Turn per-line timings into short word-group caption cues.

    Each line is split into groups of at most ``max_words`` words and the
    line's time window is distributed across the groups weighted by character
    length. This reuses the same char-weighting the pipeline already applies to
    build line timings, so no forced aligner or Whisper pass is required.
    """
    max_words = max(1, int(max_words))
    cues: list[CaptionCue] = []
    for line in line_timings or []:
        start = _to_float(line.get("startSeconds"))
        end = _to_float(line.get("endSeconds"))
        text = str(line.get("text") or "").strip()
        if start is None or end is None or end <= start or not text:
            continue

        words = [word for word in text.split() if word.strip()]
        if not words:
            continue

        groups = [words[i : i + max_words] for i in range(0, len(words), max_words)]
        total_chars = sum(len(word) for group in groups for word in group) or 1
        span = end - start
        cursor = start
        chars_before = 0
        for group in groups:
            group_chars = sum(len(word) for word in group)
            group_start = max(start + span * (chars_before / total_chars), cursor)
            chars_before += group_chars
            group_end = start + span * (chars_before / total_chars)
            if group_end - group_start < min_cue_seconds:
                group_end = group_start + min_cue_seconds
            cues.append(
                CaptionCue(
                    start=group_start,
                    end=group_end,
                    words=list(group),
                    emphasis_index=_emphasis_index(group),
                )
            )
            cursor = group_end + gap_seconds

    cues.sort(key=lambda cue: cue.start)
    for current, following in zip(cues, cues[1:], strict=False):
        if current.end > following.start:
            current.end = max(current.start + 0.05, following.start - 0.01)
    return [cue for cue in cues if cue.end > cue.start]


# --------------------------------------------------------------------------- #
# ASS document
# --------------------------------------------------------------------------- #


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remainder = seconds % 60
    return f"{hours}:{minutes:02d}:{remainder:05.2f}"


def _clean_ass_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("\\", " ").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", text).strip()


def _style_line(
    name: str,
    *,
    font_name: str,
    font_size: int,
    primary: str,
    outline_color: str,
    bold: bool,
    alignment: int,
    margin_l: int,
    margin_r: int,
    margin_v: int,
    outline: float,
    shadow: float,
) -> str:
    bold_flag = -1 if bold else 0
    return (
        f"Style: {name},{font_name},{font_size},{primary},{primary},"
        f"{outline_color},&H64000000,{bold_flag},0,0,0,100,100,0,0,1,"
        f"{outline:g},{shadow:g},{alignment},{margin_l},{margin_r},{margin_v},1"
    )


def _caption_event_text(cue: CaptionCue, primary_ass: str, accent_ass: str) -> str:
    words = [_clean_ass_text(word).upper() for word in cue.words]
    words = [word for word in words if word]
    if not words:
        return ""
    if 0 <= cue.emphasis_index < len(words):
        index = cue.emphasis_index
        words[index] = f"{{\\c{accent_ass}}}{words[index]}{{\\c{primary_ass}}}"
    body = " ".join(words)
    # Fade in/out plus a subtle scale pop as each cue appears.
    return f"{{\\fad(70,70)\\fscx84\\fscy84\\t(0,110,\\fscx100\\fscy100)}}{body}"


def build_ass_document(
    cues: Sequence[CaptionCue],
    *,
    video_width: int,
    video_height: int,
    font_name: str = "DejaVu Sans",
    primary_color: str = WHITE_HEX,
    outline_color: str = BLACK_HEX,
    accent_color: str = DEFAULT_ACCENT_HEX,
    title: str | None = None,
    brand: str | None = None,
    source_label: str | None = None,
    duration: float | None = None,
    title_seconds: float = 2.4,
    source_tail_seconds: float = 6.5,
) -> str:
    width = max(64, int(video_width))
    height = max(64, int(video_height))
    primary_ass = hex_to_ass_color(primary_color, WHITE_HEX)
    outline_ass = hex_to_ass_color(outline_color, BLACK_HEX)
    accent_ass = hex_to_ass_color(accent_color, DEFAULT_ACCENT_HEX)

    caption_size = max(28, round(height * 0.075))
    title_size = max(40, round(height * 0.10))
    brand_size = max(18, round(height * 0.026))
    source_size = max(16, round(height * 0.024))
    side_margin = round(width * 0.03)
    title_margin = round(width * 0.08)

    styles = [
        _style_line(
            "Caption",
            font_name=font_name,
            font_size=caption_size,
            primary=primary_ass,
            outline_color=outline_ass,
            bold=True,
            alignment=2,
            margin_l=side_margin,
            margin_r=side_margin,
            margin_v=round(height * 0.16),
            outline=max(2.0, height * 0.0055),
            shadow=max(1.0, height * 0.0028),
        ),
        _style_line(
            "Title",
            font_name=font_name,
            font_size=title_size,
            primary=primary_ass,
            outline_color=outline_ass,
            bold=True,
            alignment=5,
            margin_l=title_margin,
            margin_r=title_margin,
            margin_v=0,
            outline=max(2.0, height * 0.0065),
            shadow=max(1.0, height * 0.003),
        ),
        _style_line(
            "Brand",
            font_name=font_name,
            font_size=brand_size,
            primary=accent_ass,
            outline_color=outline_ass,
            bold=True,
            alignment=7,
            margin_l=side_margin,
            margin_r=side_margin,
            margin_v=round(height * 0.04),
            outline=max(1.0, height * 0.002),
            shadow=0,
        ),
        _style_line(
            "Source",
            font_name=font_name,
            font_size=source_size,
            primary=primary_ass,
            outline_color=outline_ass,
            bold=False,
            alignment=1,
            margin_l=side_margin,
            margin_r=side_margin,
            margin_v=round(height * 0.05),
            outline=max(1.0, height * 0.002),
            shadow=0,
        ),
    ]

    events: list[str] = []

    def add_event(start: float, end: float, style: str, text: str) -> None:
        cleaned = text.strip()
        if not cleaned or end <= start:
            return
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{cleaned}"
        )

    total = _to_float(duration)
    if brand:
        brand_text = _clean_ass_text(brand).upper()
        add_event(0.0, total if total else 3600.0, "Brand", brand_text)
    if title and total:
        title_text = _clean_ass_text(title).upper()[:70]
        add_event(
            0.0,
            min(title_seconds, total),
            "Title",
            f"{{\\fad(220,220)\\fscx90\\fscy90\\t(0,240,\\fscx100\\fscy100)}}{title_text}",
        )
    for cue in cues:
        add_event(cue.start, cue.end, "Caption", _caption_event_text(cue, primary_ass, accent_ass))
    if source_label and total:
        source_text = _clean_ass_text(source_label)[:90]
        add_event(
            max(0.0, total - source_tail_seconds),
            total,
            "Source",
            f"{{\\fad(220,220)}}{source_text}",
        )

    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            (
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding"
            ),
            *styles,
            "",
            "[Events]",
            (
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
                "MarginV, Effect, Text"
            ),
        ]
    )
    return header + "\n" + "\n".join(events) + "\n"


# --------------------------------------------------------------------------- #
# ffmpeg command construction
# --------------------------------------------------------------------------- #


@dataclass
class MotionVideoSpec:
    image_path: str
    audio_path: str
    output_path: str
    duration_seconds: float
    width: int = 1920
    height: int = 1080
    fps: int = 30
    accent_color: str = DEFAULT_ACCENT_HEX
    ass_path: str | None = None
    fonts_dir: str | None = None
    waveform: bool = True
    render_timeout_seconds: int = 1800
    extra_input_args: list[str] = field(default_factory=list)


def _escape_filter_path(path: str | None) -> str:
    if not path:
        return ""
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_ffmpeg_command(spec: MotionVideoSpec) -> list[str]:
    width = max(2, int(spec.width))
    height = max(2, int(spec.height))
    fps = max(1, int(spec.fps))
    duration = max(1.0, float(spec.duration_seconds))
    total_frames = max(1, int(round(duration * fps)))
    big_w, big_h = width * 2, height * 2
    accent = hex_to_ffmpeg_color(spec.accent_color, DEFAULT_ACCENT_HEX)

    parts: list[str] = [
        (
            f"[0:v]scale={big_w}:{big_h}:force_original_aspect_ratio=increase,"
            f"crop={big_w}:{big_h},"
            f"zoompan=z='min(zoom+0.0009,1.35)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s={width}x{height}:fps={fps},setsar=1[bg]"
        )
    ]

    current = "[bg]"
    map_audio = "1:a"

    if spec.waveform and ffmpeg_supports("showwaves"):
        wave_height = max(48, int(height * 0.12))
        wave_y = height - wave_height - int(height * 0.02)
        parts.append("[1:a]asplit=2[a_out][a_wave]")
        parts.append(
            f"[a_wave]showwaves=s={width}x{wave_height}:mode=cline:colors={accent}:"
            f"draw=full,format=rgba,colorchannelmixer=aa=0.45[wave]"
        )
        parts.append(f"{current}[wave]overlay=x=0:y={wave_y}:format=auto[vwave]")
        current = "[vwave]"
        map_audio = "[a_out]"

    if spec.ass_path and captions_supported():
        ass_arg = _escape_filter_path(spec.ass_path)
        fonts_arg = (
            f":fontsdir={_escape_filter_path(spec.fonts_dir)}" if spec.fonts_dir else ""
        )
        parts.append(f"{current}ass=f={ass_arg}{fonts_arg}[vtext]")
        current = "[vtext]"

    bar_height = max(6, int(height * 0.008))
    bar_y = height - bar_height
    parts.append(
        f"{current}"
        f"drawbox=x=0:y={bar_y}:w=iw:h={bar_height}:color=white@0.12:t=fill,"
        f"drawbox=x=0:y={bar_y}:w='iw*min(t/{duration:.3f},1)':h={bar_height}:"
        f"color={accent}@0.95:t=fill,"
        f"format=yuv420p[vout]"
    )

    filtergraph = ";".join(parts)
    return [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-t",
        f"{duration:.3f}",
        "-i",
        spec.image_path,
        *spec.extra_input_args,
        "-i",
        spec.audio_path,
        "-filter_complex",
        filtergraph,
        "-map",
        "[vout]",
        "-map",
        map_audio,
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{duration:.3f}",
        "-movflags",
        "+faststart",
        spec.output_path,
    ]


# --------------------------------------------------------------------------- #
# Fonts and plan metadata
# --------------------------------------------------------------------------- #


def resolve_caption_font_file(settings: object | None = None) -> str | None:
    explicit = getattr(settings, "video_caption_font_path", None)
    if explicit:
        candidate = Path(str(explicit)).expanduser()
        if candidate.exists():
            return str(candidate)
    for font_path in _FONT_CANDIDATES:
        if Path(font_path).exists():
            return font_path
    return None


def motion_caption_plan(
    payload: dict[str, Any], *, captions: bool, waveform: bool
) -> dict[str, Any]:
    fmt = payload.get("format") or {}
    return {
        "version": 1,
        "renderMode": "motion_caption",
        "durationSeconds": payload.get("durationSeconds"),
        "features": {
            "kenBurns": True,
            "captions": bool(captions),
            "waveform": bool(waveform),
            "progressBar": True,
        },
        "format": {
            "width": int(fmt.get("width") or 1920),
            "height": int(fmt.get("height") or 1080),
            "fps": int(fmt.get("fps") or 30),
            "videoCodec": "h264",
            "audioCodec": "aac",
        },
        "source": {
            "audioUrl": payload.get("audioUrl"),
            "thumbnailUrl": payload.get("thumbnailUrl"),
        },
    }
