from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PrivacyStatus = Literal["private", "unlisted", "public"]


@dataclass(frozen=True)
class YouTubeUploadManifest:
    title: str
    description: str
    video_path: str | None = None
    video_url: str | None = None
    thumbnail_path: str | None = None
    thumbnail_url: str | None = None
    tags: list[str] = field(default_factory=list)
    category_id: str = "28"
    privacy_status: PrivacyStatus = "private"
    self_declared_made_for_kids: bool = False
    embeddable: bool = True
    license: str = "youtube"
    public_stats_viewable: bool = True
    notify_subscribers: bool = False
    thumbnail_required: bool = False
    language: str | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> YouTubeUploadManifest:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> YouTubeUploadManifest:
        title = clean_text(str(data.get("title") or ""), max_chars=100)
        description = clean_text(str(data.get("description") or ""), max_bytes=5000)
        if not title:
            raise ValueError("YouTube manifest requires title")
        if not description:
            raise ValueError("YouTube manifest requires description")

        video_path = optional_str(data.get("videoPath") or data.get("video_path"))
        video_url = optional_str(data.get("videoUrl") or data.get("video_url"))
        if not video_path and not video_url:
            raise ValueError("YouTube manifest requires videoPath or videoUrl")

        privacy_status = str(data.get("privacyStatus") or data.get("privacy_status") or "private")
        if privacy_status not in {"private", "unlisted", "public"}:
            raise ValueError("privacyStatus must be private, unlisted, or public")

        return cls(
            title=title,
            description=description,
            video_path=video_path,
            video_url=video_url,
            thumbnail_path=optional_str(data.get("thumbnailPath") or data.get("thumbnail_path")),
            thumbnail_url=optional_str(data.get("thumbnailUrl") or data.get("thumbnail_url")),
            tags=clean_tags(data.get("tags") or []),
            category_id=str(data.get("categoryId") or data.get("category_id") or "28"),
            privacy_status=privacy_status,  # type: ignore[arg-type]
            self_declared_made_for_kids=bool(
                data.get("selfDeclaredMadeForKids")
                or data.get("self_declared_made_for_kids")
                or False
            ),
            embeddable=bool(data.get("embeddable", True)),
            license=str(data.get("license") or "youtube"),
            public_stats_viewable=bool(
                data.get("publicStatsViewable")
                if "publicStatsViewable" in data
                else data.get("public_stats_viewable", True)
            ),
            notify_subscribers=bool(
                data.get("notifySubscribers") or data.get("notify_subscribers") or False
            ),
            thumbnail_required=bool(
                data.get("thumbnailRequired") or data.get("thumbnail_required") or False
            ),
            language=optional_str(data.get("language")),
        )

    def to_insert_body(self) -> dict[str, Any]:
        snippet: dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "categoryId": self.category_id,
        }
        if self.language:
            snippet["defaultLanguage"] = self.language

        return {
            "snippet": snippet,
            "status": {
                "privacyStatus": self.privacy_status,
                "selfDeclaredMadeForKids": self.self_declared_made_for_kids,
                "embeddable": self.embeddable,
                "license": self.license,
                "publicStatsViewable": self.public_stats_viewable,
            },
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "videoPath": self.video_path,
            "videoUrl": self.video_url,
            "thumbnailPath": self.thumbnail_path,
            "thumbnailUrl": self.thumbnail_url,
            "tags": self.tags,
            "categoryId": self.category_id,
            "privacyStatus": self.privacy_status,
            "selfDeclaredMadeForKids": self.self_declared_made_for_kids,
            "embeddable": self.embeddable,
            "license": self.license,
            "publicStatsViewable": self.public_stats_viewable,
            "notifySubscribers": self.notify_subscribers,
            "thumbnailRequired": self.thumbnail_required,
            "language": self.language,
        }


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_text(value: str, max_chars: int | None = None, max_bytes: int | None = None) -> str:
    cleaned = value.replace("<", "").replace(">", "").strip()
    if max_chars is not None:
        cleaned = cleaned[:max_chars].rstrip()
    if max_bytes is not None:
        encoded = cleaned.encode("utf-8")
        if len(encoded) > max_bytes:
            encoded = encoded[:max_bytes]
            cleaned = encoded.decode("utf-8", errors="ignore").rstrip()
    return cleaned


def clean_tags(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    tags: list[str] = []
    for value in values:
        tag = clean_text(str(value), max_chars=50)
        if tag and tag.lower() not in {item.lower() for item in tags}:
            tags.append(tag)
    return tags[:20]
