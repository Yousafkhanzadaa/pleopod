import base64
import json

import pytest
from jose import jwt

from app.core.config import Settings
from app.core.security import verify_supabase_jwt


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@pytest.mark.asyncio
async def test_verify_supabase_jwt_with_inline_jwks() -> None:
    secret = "test-signing-secret"
    token = jwt.encode(
        {"sub": "user-1", "app_metadata": {"role": "admin"}},
        secret,
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        supabase_jwks_json=json.dumps(
            {
                "keys": [
                    {
                        "kty": "oct",
                        "kid": "test-key",
                        "alg": "HS256",
                        "k": _base64url(secret.encode("utf-8")),
                    }
                ]
            }
        )
    )

    claims = await verify_supabase_jwt(token, settings)

    assert claims["sub"] == "user-1"
    assert claims["app_metadata"]["role"] == "admin"


def test_supabase_jwks_url_defaults_from_project_url() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, supabase_url="https://example.supabase.co"
    )

    assert (
        settings.resolved_supabase_jwks_url
        == "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    )
