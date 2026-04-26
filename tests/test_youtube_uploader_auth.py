import importlib
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
UPLOADER_PATH = ROOT / "youtube-uploader"
if str(UPLOADER_PATH) not in sys.path:
    sys.path.insert(0, str(UPLOADER_PATH))

client = importlib.import_module("youtube_uploader.client")
cli = importlib.import_module("youtube_uploader.__main__")


def test_create_pkce_pair_returns_google_safe_values() -> None:
    verifier, challenge = client.create_pkce_pair()

    assert 43 <= len(verifier) <= 128
    assert re.fullmatch(r"[A-Za-z0-9_-]+", verifier)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", challenge)
    assert "=" not in challenge


def test_authorization_url_can_include_pkce_challenge() -> None:
    url = client.authorization_url(
        "client-id",
        "http://localhost:8080/oauth2/callback",
        state="state-value",
        code_challenge="challenge-value",
    )

    query = parse_qs(urlparse(url).query)

    assert query["client_id"] == ["client-id"]
    assert query["scope"] == [client.UPLOAD_SCOPE]
    assert query["state"] == ["state-value"]
    assert query["code_challenge"] == ["challenge-value"]
    assert query["code_challenge_method"] == ["S256"]


def test_normalize_redirect_path_adds_leading_slash() -> None:
    assert cli.normalize_redirect_path("oauth2/callback") == "/oauth2/callback"
    assert cli.normalize_redirect_path("/oauth2/callback") == "/oauth2/callback"
