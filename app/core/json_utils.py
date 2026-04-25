import json
import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_JSON_START_RE = re.compile(r"[{\[]")


def extract_json(text: str) -> Any:
    """Parse model output that should be JSON, tolerating fenced code blocks."""
    cleaned = text.strip()
    parse_errors: list[json.JSONDecodeError] = []
    for candidate in _json_candidates(cleaned):
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError as exc:
            parse_errors.append(exc)
        extracted = _extract_first_json_value(candidate)
        if extracted is not None:
            return extracted
    if parse_errors:
        raise parse_errors[-1]
    raise json.JSONDecodeError("No JSON object found", cleaned, 0)


def parse_model_json(text: str, model_type: type[BaseModel]) -> dict[str, Any]:
    """Extract JSON from model text and validate it against a Pydantic schema."""
    return model_type.model_validate(extract_json(text)).model_dump(mode="json")


def to_pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _json_candidates(cleaned: str) -> list[str]:
    candidates = [cleaned]
    if cleaned.startswith("```"):
        candidates.append(re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE))
    candidates.extend(match.group(1).strip() for match in _JSON_FENCE_RE.finditer(cleaned))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        deduped.append(candidate)
        seen.add(candidate)
    return deduped


def _extract_first_json_value(text: str) -> Any | None:
    decoder = json.JSONDecoder(strict=False)
    for match in _JSON_START_RE.finditer(text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        return value
    return None
