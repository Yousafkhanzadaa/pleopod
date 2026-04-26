from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from youtube_uploader.manifest import YouTubeUploadManifest

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
VIDEO_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


class YouTubeUploadError(RuntimeError):
    pass


def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str | None = None,
    code_challenge: str | None = None,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": UPLOAD_SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }
    if state:
        params["state"] = state
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(
    code: str,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    timeout_seconds: int = 60,
    code_verifier: str | None = None,
) -> dict[str, Any]:
    payload = {
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if client_secret:
        payload["client_secret"] = client_secret
    if code_verifier:
        payload["code_verifier"] = code_verifier
    return post_form(TOKEN_URL, payload, timeout_seconds)


def refresh_access_token(
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
    timeout_seconds: int = 60,
) -> str:
    payload = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client_secret:
        payload["client_secret"] = client_secret
    response = post_form(TOKEN_URL, payload, timeout_seconds)
    token = response.get("access_token")
    if not token:
        raise YouTubeUploadError("Google token response did not include access_token")
    return str(token)


def upload_from_manifest(
    manifest: YouTubeUploadManifest,
    access_token: str,
    chunk_size: int = 8 * 1024 * 1024,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    with materialized_media(manifest.video_path, manifest.video_url) as video_path:
        video_id, raw_response = upload_video(
            manifest=manifest,
            video_path=video_path,
            access_token=access_token,
            chunk_size=chunk_size,
            timeout_seconds=timeout_seconds,
        )

    thumbnail_uploaded = False
    thumbnail_error: str | None = None
    thumbnail_source = manifest.thumbnail_path or manifest.thumbnail_url
    if thumbnail_source:
        try:
            with materialized_media(manifest.thumbnail_path, manifest.thumbnail_url) as thumb_path:
                upload_thumbnail(
                    video_id=video_id,
                    thumbnail_path=thumb_path,
                    access_token=access_token,
                    timeout_seconds=timeout_seconds,
                )
                thumbnail_uploaded = True
        except Exception as exc:  # noqa: BLE001
            thumbnail_error = str(exc)
            if manifest.thumbnail_required:
                raise

    return {
        "videoId": video_id,
        "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}",
        "privacyStatus": manifest.privacy_status,
        "thumbnailUploaded": thumbnail_uploaded,
        "thumbnailError": thumbnail_error,
        "rawVideoResponse": raw_response,
    }


def upload_video(
    manifest: YouTubeUploadManifest,
    video_path: Path,
    access_token: str,
    chunk_size: int,
    timeout_seconds: int,
) -> tuple[str, dict[str, Any]]:
    size = video_path.stat().st_size
    if size <= 0:
        raise YouTubeUploadError(f"Video file is empty: {video_path}")

    mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
    metadata = json.dumps(manifest.to_insert_body()).encode("utf-8")
    params = urlencode(
        {
            "uploadType": "resumable",
            "part": "snippet,status",
            "notifySubscribers": str(manifest.notify_subscribers).lower(),
        }
    )
    session = request(
        "POST",
        f"{VIDEO_UPLOAD_URL}?{params}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": mime_type,
        },
        body=metadata,
        timeout_seconds=timeout_seconds,
        expected={200, 201},
    )
    upload_url = session["headers"].get("location")
    if not upload_url:
        raise YouTubeUploadError("YouTube resumable upload did not return a Location header")

    response = upload_file_chunks(
        upload_url=upload_url,
        file_path=video_path,
        mime_type=mime_type,
        access_token=access_token,
        chunk_size=chunk_size,
        timeout_seconds=timeout_seconds,
    )
    video_id = response.get("id")
    if not video_id:
        raise YouTubeUploadError("YouTube upload response did not include video id")
    return str(video_id), response


def upload_file_chunks(
    upload_url: str,
    file_path: Path,
    mime_type: str,
    access_token: str,
    chunk_size: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    total = file_path.stat().st_size
    size = max(256 * 1024, chunk_size)
    offset = 0
    with file_path.open("rb") as handle:
        while offset < total:
            handle.seek(offset)
            chunk = handle.read(min(size, total - offset))
            end = offset + len(chunk) - 1
            try:
                response = request(
                    "PUT",
                    upload_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Length": str(len(chunk)),
                        "Content-Type": mime_type,
                        "Content-Range": f"bytes {offset}-{end}/{total}",
                    },
                    body=chunk,
                    timeout_seconds=timeout_seconds,
                    expected={200, 201, 308, 500, 502, 503, 504},
                )
            except HTTPError as exc:
                if exc.code == 308:
                    offset = next_offset_from_range(exc.headers.get("Range"), end)
                    continue
                if exc.code >= 500:
                    time.sleep(2)
                    continue
                raise

            if response["status"] in {200, 201}:
                return response["json"]
            if response["status"] in {500, 502, 503, 504}:
                time.sleep(2)
                continue
            if response["status"] == 308:
                offset = next_offset_from_range(response["headers"].get("range"), end)
                continue
            offset = end + 1

    raise YouTubeUploadError("YouTube upload ended without a final response")


def upload_thumbnail(
    video_id: str,
    thumbnail_path: Path,
    access_token: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    size = thumbnail_path.stat().st_size
    if size > 2 * 1024 * 1024:
        raise YouTubeUploadError("YouTube custom thumbnails must be 2MB or smaller")
    mime_type = mimetypes.guess_type(thumbnail_path.name)[0] or "image/png"
    body = thumbnail_path.read_bytes()
    response = request(
        "POST",
        f"{THUMBNAIL_UPLOAD_URL}?{urlencode({'videoId': video_id})}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": mime_type,
            "Content-Length": str(len(body)),
        },
        body=body,
        timeout_seconds=timeout_seconds,
        expected={200, 201},
    )
    return response["json"]


def post_form(url: str, payload: dict[str, str], timeout_seconds: int) -> dict[str, Any]:
    body = urlencode(payload).encode("utf-8")
    response = request(
        "POST",
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
        timeout_seconds=timeout_seconds,
        expected={200},
    )
    return response["json"]


def request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout_seconds: int,
    expected: set[int],
) -> dict[str, Any]:
    try:
        with urlopen(
            Request(url, data=body, headers=headers, method=method),
            timeout=timeout_seconds,
        ) as response:
            status = response.status
            data = response.read()
            if status not in expected:
                raise YouTubeUploadError(f"Unexpected HTTP {status}: {data.decode('utf-8')}")
            return {
                "status": status,
                "headers": {key.lower(): value for key, value in response.headers.items()},
                "body": data,
                "json": json.loads(data.decode("utf-8")) if data else {},
            }
    except HTTPError as exc:
        if exc.code in expected:
            data = exc.read()
            return {
                "status": exc.code,
                "headers": {key.lower(): value for key, value in exc.headers.items()},
                "body": data,
                "json": json.loads(data.decode("utf-8")) if data else {},
            }
        detail = exc.read().decode("utf-8", errors="replace")
        raise YouTubeUploadError(f"HTTP {exc.code} from YouTube API: {detail}") from exc
    except URLError as exc:
        raise YouTubeUploadError(f"YouTube API request failed: {exc}") from exc


def next_offset_from_range(range_header: str | None, fallback_end: int) -> int:
    if not range_header:
        return fallback_end + 1
    _, _, end = range_header.partition("-")
    try:
        return int(end) + 1
    except ValueError:
        return fallback_end + 1


class materialized_media:
    def __init__(self, path: str | None, url: str | None):
        self.path = Path(path).expanduser().resolve() if path else None
        self.url = url
        self.temp_path: Path | None = None

    def __enter__(self) -> Path:
        if self.path:
            if not self.path.exists():
                raise YouTubeUploadError(f"Media file does not exist: {self.path}")
            return self.path
        if not self.url:
            raise YouTubeUploadError("Missing media path or URL")
        suffix = Path(self.url.split("?", 1)[0]).suffix or ".bin"
        fd, temp_name = tempfile.mkstemp(prefix="pleopod-youtube-", suffix=suffix)
        os.close(fd)
        self.temp_path = Path(temp_name)
        with urlopen(self.url, timeout=120) as response:
            self.temp_path.write_bytes(response.read())
        return self.temp_path

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.temp_path:
            self.temp_path.unlink(missing_ok=True)
