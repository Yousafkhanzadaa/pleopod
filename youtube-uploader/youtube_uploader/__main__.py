from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from youtube_uploader.client import (
    authorization_url,
    exchange_code_for_tokens,
    refresh_access_token,
    upload_from_manifest,
)
from youtube_uploader.manifest import YouTubeUploadManifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="youtube-uploader")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser("auth-url")
    auth_parser.add_argument("--client-id", default=os.getenv("YOUTUBE_CLIENT_ID"))
    auth_parser.add_argument("--redirect-uri", required=True)
    auth_parser.add_argument("--state")

    exchange_parser = subparsers.add_parser("exchange-code")
    exchange_parser.add_argument("--code", required=True)
    exchange_parser.add_argument("--redirect-uri", required=True)
    exchange_parser.add_argument("--client-id", default=os.getenv("YOUTUBE_CLIENT_ID"))
    exchange_parser.add_argument("--client-secret", default=os.getenv("YOUTUBE_CLIENT_SECRET"))
    exchange_parser.add_argument("--out")

    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--manifest", required=True)
    upload_parser.add_argument("--out")
    upload_parser.add_argument("--dry-run", action="store_true")
    upload_parser.add_argument("--chunk-size", type=int, default=8 * 1024 * 1024)
    upload_parser.add_argument("--timeout-seconds", type=int, default=120)
    upload_parser.add_argument("--access-token", default=os.getenv("YOUTUBE_ACCESS_TOKEN"))
    upload_parser.add_argument("--client-id", default=os.getenv("YOUTUBE_CLIENT_ID"))
    upload_parser.add_argument("--client-secret", default=os.getenv("YOUTUBE_CLIENT_SECRET"))
    upload_parser.add_argument("--refresh-token", default=os.getenv("YOUTUBE_REFRESH_TOKEN"))

    args = parser.parse_args(argv)
    try:
        if args.command == "auth-url":
            require(args.client_id, "YOUTUBE_CLIENT_ID or --client-id is required")
            print(authorization_url(args.client_id, args.redirect_uri, args.state))
            return 0

        if args.command == "exchange-code":
            require(args.client_id, "YOUTUBE_CLIENT_ID or --client-id is required")
            tokens = exchange_code_for_tokens(
                code=args.code,
                client_id=args.client_id,
                client_secret=args.client_secret,
                redirect_uri=args.redirect_uri,
            )
            write_json(tokens, args.out)
            return 0

        manifest = YouTubeUploadManifest.from_file(args.manifest)
        if args.dry_run:
            write_json({"ok": True, "manifest": manifest.public_dict()}, args.out)
            return 0

        access_token = args.access_token
        if not access_token:
            require(args.client_id, "YOUTUBE_CLIENT_ID or --client-id is required")
            require(args.refresh_token, "YOUTUBE_REFRESH_TOKEN or --refresh-token is required")
            access_token = refresh_access_token(
                client_id=args.client_id,
                client_secret=args.client_secret,
                refresh_token=args.refresh_token,
                timeout_seconds=args.timeout_seconds,
            )

        result = upload_from_manifest(
            manifest=manifest,
            access_token=access_token,
            chunk_size=args.chunk_size,
            timeout_seconds=args.timeout_seconds,
        )
        write_json(result, args.out)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"youtube-uploader: {exc}", file=sys.stderr)
        return 1


def require(value: str | None, message: str) -> None:
    if not value:
        raise ValueError(message)


def write_json(data: object, out_path: str | None) -> None:
    text = f"{json.dumps(data, indent=2, sort_keys=True)}\n"
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    raise SystemExit(main())
