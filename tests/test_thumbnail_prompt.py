from app.agents.prompts import thumbnail_hook_text, thumbnail_prompt


def test_thumbnail_prompt_uses_mobile_readable_hook_and_bans_clutter() -> None:
    prompt = thumbnail_prompt(
        {
            "title": "AI's Catastrophic Risks: A Stark Warning from Experts",
            "summary": (
                "A recent study surveyed 272 AI experts, revealing a significant "
                "probability of catastrophic AI outcomes within five years."
            ),
        }
    )

    assert "Exact large text hook: AI WARNING" in prompt
    assert "1280x720" in prompt
    assert "Do not render any other readable text" in prompt
    assert "stats panels" in prompt
    assert "Leave the bottom-right corner visually clean" in prompt


def test_thumbnail_hook_prefers_short_product_phrase() -> None:
    hook = thumbnail_hook_text(
        {
            "title": "DGX Station for Windows: AI Power on Your Desktop",
            "summary": "NVIDIA and Microsoft unveiled the DGX Station for Windows.",
        }
    )

    assert hook == "DGX STATION WINDOWS"


def test_thumbnail_hook_has_generic_fallback() -> None:
    assert thumbnail_hook_text({"title": "", "summary": ""}) == "TECH SHIFT"


def test_thumbnail_hook_expands_single_word_title() -> None:
    assert thumbnail_hook_text({"title": "OpenAI", "summary": ""}) == "OPENAI UPDATE"
