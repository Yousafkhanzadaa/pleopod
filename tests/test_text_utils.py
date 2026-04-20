from app.core.json_utils import extract_json
from app.core.text import chunk_dialogue, slugify


def test_extract_json_from_fenced_block() -> None:
    assert extract_json('```json\n{"ok": true}\n```') == {"ok": True}


def test_slugify() -> None:
    assert slugify("AI Agents: What changed in 2026?") == "ai-agents-what-changed-in-2026"


def test_chunk_dialogue() -> None:
    text = "A: hello\n\nB: " + ("world " * 50)
    chunks = chunk_dialogue(text, max_chars=60)
    assert len(chunks) >= 2
    assert chunks[0].startswith("A:")
