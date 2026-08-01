from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from itertools import combinations
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

THUMBNAIL_SIZE = (1280, 720)

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/Library/Fonts/Arial Black.ttf",
)

@dataclass(frozen=True)
class ThumbnailRenderResult:
    data: bytes
    metadata: dict[str, Any]


def render_thumbnail_artwork(
    image_data: bytes,
    brief: dict[str, Any],
    *,
    font_path: str | Path | None = None,
) -> ThumbnailRenderResult:
    """Fit generated artwork and add exact, mobile-readable typography.

    The image model creates only the visual story. Rendering text locally prevents
    misspellings, invented labels, and inconsistent type hierarchy while keeping the
    image-generation request count at one.
    """

    with Image.open(BytesIO(image_data)) as source:
        image = ImageOps.fit(
            source.convert("RGB"),
            THUMBNAIL_SIZE,
            method=Image.Resampling.LANCZOS,
        )

    layout = str(brief.get("layout") or "subject_right_text_left")
    text_on_left = layout == "subject_right_text_left"
    zone = (64, 104, 616, 574) if text_on_left else (664, 82, 1216, 536)
    hook = str(brief.get("hook") or "WHAT CHANGED?").strip().upper()
    words = hook.split()
    if not words:
        words = ["WHAT", "CHANGED?"]

    resolved_font = resolve_thumbnail_font(font_path)
    draw = ImageDraw.Draw(image)
    font, lines = _fit_hook(
        draw,
        words,
        resolved_font,
        max_width=zone[2] - zone[0],
        max_height=zone[3] - zone[1],
    )
    line_height = _line_height(draw, font)
    line_gap = max(4, int(font.size * 0.02))
    total_height = len(lines) * line_height + max(0, len(lines) - 1) * line_gap
    y = zone[1] + max(0, (zone[3] - zone[1] - total_height) // 2)

    luminance = _zone_luminance(image, zone)
    base_fill = "#FFFFFF" if luminance < 145 else "#101217"
    stroke_fill = "#080A0E" if base_fill == "#FFFFFF" else "#FFFFFF"
    accent_fill = _accent_color(brief.get("accent_color"))
    accent_word = _normalized_word(str(brief.get("accent_word") or words[-1]))
    stroke_width = max(4, font.size // 24)
    shadow_offset = max(3, font.size // 32)

    for line in lines:
        line_width = _line_width(draw, line, font)
        x = zone[0] if text_on_left else zone[2] - line_width
        for index, word in enumerate(line):
            word_width = _text_width(draw, word, font)
            fill = accent_fill if _normalized_word(word) == accent_word else base_fill
            draw.text(
                (x + shadow_offset, y + shadow_offset),
                word,
                font=font,
                fill="#000000",
                stroke_width=stroke_width + 2,
                stroke_fill="#000000",
            )
            draw.text(
                (x, y),
                word,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            x += word_width
            if index < len(line) - 1:
                x += _space_width(draw, font)
        y += line_height + line_gap

    output = BytesIO()
    image.save(output, format="PNG", optimize=True, compress_level=8)
    return ThumbnailRenderResult(
        data=output.getvalue(),
        metadata={
            "typography_composited": True,
            "hook": hook,
            "accent_word": accent_word,
            "accent_color": accent_fill,
            "layout": layout,
            "font": Path(resolved_font).name if resolved_font else "Pillow default",
            "font_size": font.size,
            "line_count": len(lines),
            "text_zone_luminance": round(luminance, 2),
            "width": THUMBNAIL_SIZE[0],
            "height": THUMBNAIL_SIZE[1],
        },
    )


def resolve_thumbnail_font(explicit: str | Path | None = None) -> str | None:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate)
    for value in _FONT_CANDIDATES:
        if Path(value).is_file():
            return value
    return None


def _fit_hook(
    draw: ImageDraw.ImageDraw,
    words: list[str],
    font_path: str | None,
    *,
    max_width: int,
    max_height: int,
) -> tuple[Any, list[list[str]]]:
    for font_size in range(174, 69, -4):
        font = _load_font(font_path, font_size)
        line_height = _line_height(draw, font)
        for lines in _ranked_line_partitions(draw, words, font, max_lines=2):
            line_gap = max(4, int(font_size * 0.02))
            height = len(lines) * line_height + max(0, len(lines) - 1) * line_gap
            if height > max_height:
                continue
            if max(_line_width(draw, line, font) for line in lines) <= max_width:
                return font, lines

    font = _load_font(font_path, 70)
    return font, _ranked_line_partitions(draw, words, font, max_lines=3)[0]


def _ranked_line_partitions(
    draw: ImageDraw.ImageDraw,
    words: list[str],
    font: Any,
    *,
    max_lines: int,
) -> list[list[list[str]]]:
    if len(words) == 1:
        return [[words]]

    partitions: list[list[list[str]]] = []
    line_limit = min(max_lines, len(words))
    for line_count in range(1, line_limit + 1):
        for breaks in combinations(range(1, len(words)), line_count - 1):
            starts = (0, *breaks)
            ends = (*breaks, len(words))
            partitions.append([words[start:end] for start, end in zip(starts, ends, strict=True)])

    def score(lines: list[list[str]]) -> tuple[float, int]:
        widths = [_line_width(draw, line, font) for line in lines]
        imbalance = max(widths) - min(widths)
        return (max(widths) + imbalance * 0.2, len(lines))

    return sorted(partitions, key=score)


def _load_font(font_path: str | None, size: int) -> Any:
    if font_path:
        return ImageFont.truetype(font_path, size=size)
    return ImageFont.load_default(size=size)


def _line_width(draw: ImageDraw.ImageDraw, words: list[str], font: Any) -> int:
    return sum(_text_width(draw, word, font) for word in words) + max(
        0, len(words) - 1
    ) * _space_width(draw, font)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: Any) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font, stroke_width=0)
    return right - left


def _space_width(draw: ImageDraw.ImageDraw, font: Any) -> int:
    return max(12, _text_width(draw, " ", font))


def _line_height(draw: ImageDraw.ImageDraw, font: Any) -> int:
    _, top, _, bottom = draw.textbbox((0, 0), "Ag", font=font, stroke_width=0)
    return int((bottom - top) * 1.08)


def _zone_luminance(image: Image.Image, zone: tuple[int, int, int, int]) -> float:
    red, green, blue = image.crop(zone).resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _normalized_word(value: str) -> str:
    return "".join(
        character for character in value.upper() if character.isalnum() or character == "$"
    )


def _accent_color(value: Any) -> str:
    color = str(value or "").strip().upper()
    if len(color) == 7 and color.startswith("#") and all(
        character in "0123456789ABCDEF" for character in color[1:]
    ):
        return color
    return "#FFD43B"
