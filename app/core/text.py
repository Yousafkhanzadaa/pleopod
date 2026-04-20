import re
import unicodedata

_SPEAKER_TURN_RE = re.compile(r"^([A-Za-z][\w .'-]{0,64}):\s*(.*)", re.DOTALL)


def slugify(value: str, max_length: int = 90) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_length].strip("-") or "episode"


def chunk_dialogue(script: str, max_chars: int) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in _dialogue_units(script, max_chars):
        unit = unit.strip()
        if not unit:
            continue
        separator_len = 2 if current else 0
        projected = current_len + separator_len + len(unit)
        if current and projected > max_chars:
            chunks.append("\n\n".join(current))
            current = [unit]
            current_len = len(unit)
        else:
            current.append(unit)
            current_len = projected
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _dialogue_units(script: str, max_chars: int) -> list[str]:
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", script.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            units.append(paragraph)
            continue
        units.extend(_split_oversized_dialogue_block(paragraph, max_chars))
    return units


def _split_oversized_dialogue_block(block: str, max_chars: int) -> list[str]:
    turns: list[str] = []
    current: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _SPEAKER_TURN_RE.match(line) and current:
            turns.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        turns.append("\n".join(current))

    units: list[str] = []
    for turn in turns:
        if len(turn) <= max_chars:
            units.append(turn)
        else:
            units.extend(_split_long_turn(turn, max_chars))
    return units


def _split_long_turn(turn: str, max_chars: int) -> list[str]:
    match = _SPEAKER_TURN_RE.match(turn)
    if not match:
        return _word_chunks(turn, max_chars)

    speaker = match.group(1).strip()
    body = match.group(2).strip()
    prefix = f"{speaker}: "
    body_limit = max_chars - len(prefix)
    if body_limit < 80:
        return _word_chunks(turn, max_chars)

    return [f"{prefix}{piece}" for piece in _sentence_chunks(body, body_limit)]


def _sentence_chunks(text: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            chunks.extend(_word_chunks(sentence, max_chars))
            continue

        projected = current_len + (1 if current else 0) + len(sentence)
        if current and projected > max_chars:
            chunks.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len = projected

    if current:
        chunks.append(" ".join(current))
    return chunks


def _word_chunks(text: str, max_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in text.split():
        if len(word) > max_chars:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            chunks.extend(word[i : i + max_chars] for i in range(0, len(word), max_chars))
            continue

        projected = current_len + (1 if current else 0) + len(word)
        if current and projected > max_chars:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len = projected

    if current:
        chunks.append(" ".join(current))
    return chunks
