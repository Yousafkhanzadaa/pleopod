from app.agents.prompts import (
    normalized_thumbnail_brief,
    thumbnail_director_prompt,
    thumbnail_hook_text,
    thumbnail_prompt,
)

SCRIPT = {
    "title": "AI's Catastrophic Risks: A Stark Warning from Experts",
    "summary": (
        "A recent study surveyed 272 AI experts, revealing a significant "
        "probability of catastrophic AI outcomes within five years."
    ),
}


def test_thumbnail_prompt_creates_textless_mobile_artwork_and_bans_clutter() -> None:
    prompt = thumbnail_prompt(SCRIPT)

    assert "1280x720" in prompt
    assert "Reserve the left 40-45% as genuinely clean negative space" in prompt
    assert "Generate absolutely no text" in prompt
    assert "No gradients" in prompt
    assert "No collage" in prompt
    assert "Avoid humanoid robots" in prompt
    assert "Leave the bottom-right corner visually clean" in prompt


def test_thumbnail_director_pairs_title_with_one_truthful_visual_story() -> None:
    prompt = thumbnail_director_prompt(SCRIPT)

    assert "Do not merely" in prompt
    assert "repeat or shorten the title" in prompt
    assert "Communicate exactly one idea" in prompt
    assert "one dominant subject" in prompt
    assert "Choose accent_word as one exact word from hook" in prompt


def test_thumbnail_hook_turns_product_story_into_a_benefit() -> None:
    hook = thumbnail_hook_text(
        {
            "title": "DGX Station for Windows: AI Power on Your Desktop",
            "summary": "NVIDIA and Microsoft unveiled the DGX Station for Windows.",
        }
    )

    assert hook == "DESKTOP SUPERCOMPUTER"


def test_thumbnail_hook_has_generic_fallback() -> None:
    assert thumbnail_hook_text({"title": "", "summary": ""}) == "WHAT CHANGED?"


def test_thumbnail_hook_expands_single_word_title() -> None:
    assert thumbnail_hook_text({"title": "OpenAI", "summary": ""}) == "WHY OPENAI?"


def test_thumbnail_hook_uses_specific_tension_instead_of_title_fragments() -> None:
    hook = thumbnail_hook_text(
        {
            "title": "AI Designs World-First Vaccine for Human Trials",
            "summary": "An AI-designed vaccine has entered a human clinical trial.",
        }
    )

    assert hook == "AI-MADE VACCINE"


def test_normalized_brief_rejects_invalid_hook_and_unknown_art_direction() -> None:
    brief = normalized_thumbnail_brief(
        SCRIPT,
        {
            "hook": "THIS IS A VERY LONG GENERIC THUMBNAIL SENTENCE",
            "accent_word": "MISSING",
            "layout": "center_everything",
            "palette": "rainbow",
        },
    )

    assert brief["hook"] == "HOW BAD?"
    assert brief["accent_word"] == "BAD"
    assert brief["layout"] == "subject_right_text_left"
    assert brief["palette"] == "signal_yellow"
