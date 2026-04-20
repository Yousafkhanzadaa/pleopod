import re
import unicodedata


def slugify(value: str, max_length: int = 90) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_length].strip("-") or "episode"


def chunk_dialogue(script: str, max_chars: int) -> list[str]:
    if len(script) <= max_chars:
        return [script.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in re.split(r"\n\s*\n", script.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        projected = current_len + len(paragraph) + 2
        if current and projected > max_chars:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len = projected
    if current:
        chunks.append("\n\n".join(current))
    return chunks
