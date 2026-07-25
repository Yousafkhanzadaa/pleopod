from io import BytesIO

from PIL import Image

from app.services.thumbnail import render_thumbnail_artwork


def test_render_thumbnail_adds_exact_hook_at_youtube_dimensions() -> None:
    source = BytesIO()
    Image.new("RGB", (1024, 1024), "#121820").save(source, format="PNG")

    result = render_thumbnail_artwork(
        source.getvalue(),
        {
            "hook": "AI-MADE VACCINE",
            "accent_word": "VACCINE",
            "layout": "subject_right_text_left",
            "palette": "mint_green",
        },
    )

    with Image.open(BytesIO(result.data)) as rendered:
        assert rendered.size == (1280, 720)
        assert rendered.format == "PNG"
        assert rendered.getbbox() == (0, 0, 1280, 720)

    assert result.metadata["typography_composited"] is True
    assert result.metadata["hook"] == "AI-MADE VACCINE"
    assert result.metadata["accent_word"] == "VACCINE"
    assert 1 <= result.metadata["line_count"] <= 3
    assert result.metadata["font_size"] >= 70


def test_render_thumbnail_right_aligns_text_when_subject_is_left() -> None:
    source = BytesIO()
    Image.new("RGB", (1280, 720), "#F4F1E8").save(source, format="PNG")

    result = render_thumbnail_artwork(
        source.getvalue(),
        {
            "hook": "$50B AI BET",
            "accent_word": "BET",
            "layout": "subject_left_text_right",
            "palette": "coral_red",
        },
    )

    assert result.metadata["layout"] == "subject_left_text_right"
    assert result.metadata["text_zone_luminance"] > 145
