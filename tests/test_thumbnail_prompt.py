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
    "description": "A factual short video about the findings and their limitations.",
    "transcript": "Arman explains the survey, its findings, and how viewers should read them.",
}

JOB = {
    "topic": "Expert views on long-term AI risk",
    "category": "Technology news",
    "audience": "curious technology professionals",
    "language": "en",
    "tone": "clear and evidence-led",
}


def test_thumbnail_prompt_uses_dynamic_art_direction_and_production_constraints() -> None:
    image_direction = (
        "Build a handmade paper-cut scene in which a tiny research team studies an "
        "enormous uncertain shadow, with warm desk light against a cool archive room."
    )
    prompt = thumbnail_prompt(
        SCRIPT,
        {
            "hook": "HOW CERTAIN?",
            "accent_word": "CERTAIN",
            "layout": "subject_left_text_right",
            "accent_color": "#8EE3EF",
            "image_prompt": image_direction,
        },
        JOB,
    )

    assert SCRIPT["title"] in prompt
    assert SCRIPT["summary"] in prompt
    assert JOB["audience"] in prompt
    assert JOB["category"] in prompt
    assert SCRIPT["transcript"] not in prompt
    assert image_direction in prompt
    assert "The subject belongs on the left" in prompt
    assert "space on the\nright for a large text overlay" in prompt
    assert "Do not render the hook" in prompt
    assert "16:9 composition" in prompt


def test_thumbnail_director_receives_full_content_and_leaves_style_open() -> None:
    prompt = thumbnail_director_prompt(SCRIPT, JOB)

    assert SCRIPT["title"] in prompt
    assert SCRIPT["summary"] in prompt
    assert SCRIPT["description"] in prompt
    assert SCRIPT["transcript"] in prompt
    assert JOB["topic"] in prompt
    assert JOB["audience"] in prompt
    assert "full creative freedom" in prompt
    assert "do not reuse a default style" in prompt
    assert '"image_prompt"' in prompt
    assert '"accent_color"' in prompt
    assert '"image_style"' not in prompt
    assert "signal_yellow" not in prompt


def test_thumbnail_hook_fallback_extracts_content_without_topic_templates() -> None:
    hook = thumbnail_hook_text(
        {
            "title": "DGX Station for Windows: AI Power on Your Desktop",
            "summary": "NVIDIA and Microsoft unveiled the DGX Station for Windows.",
        }
    )

    assert hook == "DGX STATION WINDOWS"


def test_thumbnail_hook_has_generic_fallback() -> None:
    assert thumbnail_hook_text({"title": "", "summary": ""}) == "WHAT CHANGED?"


def test_thumbnail_hook_expands_single_word_title() -> None:
    assert thumbnail_hook_text({"title": "OpenAI", "summary": ""}) == "WHY OPENAI?"


def test_thumbnail_hook_does_not_hardcode_topic_specific_copy() -> None:
    hook = thumbnail_hook_text(
        {
            "title": "AI Designs World-First Vaccine for Human Trials",
            "summary": "An AI-designed vaccine has entered a human clinical trial.",
        }
    )

    assert hook == "AI DESIGNS WORLD"


def test_normalized_brief_preserves_dynamic_prompt_and_repairs_control_fields() -> None:
    image_direction = (
        "Use an unexpected but coherent visual treatment selected specifically for this story."
    )
    brief = normalized_thumbnail_brief(
        SCRIPT,
        {
            "hook": "THIS IS A VERY LONG GENERIC THUMBNAIL SENTENCE",
            "accent_word": "MISSING",
            "layout": "center_everything",
            "accent_color": "yellow",
            "image_prompt": image_direction,
        },
        JOB,
    )

    assert brief["hook"] == "AI CATASTROPHIC RISKS"
    assert brief["accent_word"] == "RISKS"
    assert brief["layout"] == "subject_right_text_left"
    assert brief["accent_color"] == "#FFD43B"
    assert brief["image_prompt"] == image_direction
