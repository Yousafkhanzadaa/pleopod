from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from youtube_uploader.client import (
    authorization_url,
    create_pkce_pair,
    exchange_code_for_tokens,
    refresh_access_token,
    upload_from_manifest,
)
from youtube_uploader.manifest import YouTubeUploadManifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="youtube-uploader")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser("auth")
    auth_parser.add_argument("--client-id", default=os.getenv("YOUTUBE_CLIENT_ID"))
    auth_parser.add_argument("--client-secret", default=os.getenv("YOUTUBE_CLIENT_SECRET"))
    auth_parser.add_argument("--host", default="localhost")
    auth_parser.add_argument("--port", type=int, default=8080)
    auth_parser.add_argument("--redirect-path", default="/oauth2/callback")
    auth_parser.add_argument("--timeout-seconds", type=int, default=300)
    auth_parser.add_argument("--out")
    auth_parser.add_argument("--no-browser", action="store_true")

    auth_parser = subparsers.add_parser("auth-url")
    auth_parser.add_argument("--client-id", default=os.getenv("YOUTUBE_CLIENT_ID"))
    auth_parser.add_argument("--redirect-uri", required=True)
    auth_parser.add_argument("--state")
    auth_parser.add_argument("--code-challenge")

    exchange_parser = subparsers.add_parser("exchange-code")
    exchange_parser.add_argument("--code", required=True)
    exchange_parser.add_argument("--redirect-uri", required=True)
    exchange_parser.add_argument("--client-id", default=os.getenv("YOUTUBE_CLIENT_ID"))
    exchange_parser.add_argument("--client-secret", default=os.getenv("YOUTUBE_CLIENT_SECRET"))
    exchange_parser.add_argument("--code-verifier")
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
            print(
                authorization_url(
                    args.client_id,
                    args.redirect_uri,
                    args.state,
                    code_challenge=args.code_challenge,
                )
            )
            return 0

        if args.command == "auth":
            tokens = run_auth_flow(args)
            write_json(tokens, args.out, secure=bool(args.out))
            if args.out:
                print(f"Saved YouTube OAuth tokens to {args.out}")
                print("Use the refresh_token value as YOUTUBE_REFRESH_TOKEN.")
            return 0

        if args.command == "exchange-code":
            require(args.client_id, "YOUTUBE_CLIENT_ID or --client-id is required")
            tokens = exchange_code_for_tokens(
                code=args.code,
                client_id=args.client_id,
                client_secret=args.client_secret,
                redirect_uri=args.redirect_uri,
                code_verifier=args.code_verifier,
            )
            write_json(tokens, args.out, secure=bool(args.out))
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


class OAuthCallbackServer(HTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        expected_state: str,
        callback_path: str,
    ):
        super().__init__(server_address, OAuthCallbackHandler)
        self.expected_state = expected_state
        self.callback_path = callback_path
        self.code: str | None = None
        self.error: str | None = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        server = cast(OAuthCallbackServer, self.server)
        parsed = urlparse(self.path)
        if parsed.path != server.callback_path:
            self._respond(404, "Not Found", "Unexpected OAuth callback path.")
            return

        params = parse_qs(parsed.query)
        returned_state = first(params.get("state"))
        if returned_state != server.expected_state:
            server.error = "OAuth state mismatch"
        elif error := first(params.get("error")):
            server.error = error
        elif code := first(params.get("code")):
            server.code = code
        else:
            server.error = "OAuth callback did not include an authorization code"

        if server.code:
            self._respond(
                200,
                "YouTube authentication complete",
                "Authentication complete. You can close this tab and return to the terminal.",
            )
        else:
            self._respond(
                400,
                "YouTube authentication failed",
                server.error or "Authentication failed.",
            )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _respond(self, status: int, title: str, message: str) -> None:
        escaped_title = html.escape(title)
        escaped_message = html.escape(message)
        body = f"""
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>{escaped_title}</title></head>
  <body>
    <h1>{escaped_title}</h1>
    <p>{escaped_message}</p>
  </body>
</html>
""".strip().encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_auth_flow(args: argparse.Namespace) -> dict[str, Any]:
    require(args.client_id, "YOUTUBE_CLIENT_ID or --client-id is required")
    callback_path = normalize_redirect_path(args.redirect_path)
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = create_pkce_pair()

    with OAuthCallbackServer((args.host, args.port), state, callback_path) as server:
        server.timeout = args.timeout_seconds
        redirect_uri = f"http://{args.host}:{server.server_port}{callback_path}"
        url = authorization_url(
            args.client_id,
            redirect_uri,
            state=state,
            code_challenge=code_challenge,
        )

        if args.no_browser or not webbrowser.open(url):
            print("Open this URL to authenticate YouTube:")
            print(url)
        else:
            print("Opened browser for YouTube authentication.")
        print(f"Waiting for OAuth callback on {redirect_uri}")

        server.handle_request()
        if server.error:
            raise RuntimeError(server.error)
        if not server.code:
            raise TimeoutError("Timed out waiting for YouTube OAuth callback")
        code = server.code

    tokens = exchange_code_for_tokens(
        code=code,
        client_id=args.client_id,
        client_secret=args.client_secret,
        redirect_uri=redirect_uri,
        timeout_seconds=args.timeout_seconds,
        code_verifier=code_verifier,
    )
    return {
        **tokens,
        "client_id": args.client_id,
        "redirect_uri": redirect_uri,
    }


def first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def normalize_redirect_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def require(value: str | None, message: str) -> None:
    if not value:
        raise ValueError(message)


def write_json(data: object, out_path: str | None, secure: bool = False) -> None:
    text = f"{json.dumps(data, indent=2, sort_keys=True)}\n"
    if out_path:
        path = Path(out_path)
        path.write_text(text, encoding="utf-8")
        if secure:
            path.chmod(0o600)
    else:
        print(text, end="")


if __name__ == "__main__":
    raise SystemExit(main())
