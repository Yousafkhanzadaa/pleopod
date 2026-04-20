import json
import re
from typing import Any


def extract_json(text: str) -> Any:
    """Parse model output that should be JSON, tolerating fenced code blocks."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start_obj = cleaned.find("{")
        start_arr = cleaned.find("[")
        starts = [idx for idx in (start_obj, start_arr) if idx >= 0]
        if not starts:
            raise
        start = min(starts)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def to_pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
