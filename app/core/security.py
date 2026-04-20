import json
import time
from typing import Any

import httpx
from fastapi import HTTPException, Request, status

from app.core.config import Settings

JWKS_CACHE_SECONDS = 300
SUPPORTED_JWT_ALGORITHMS = {"ES256", "RS256", "HS256"}
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_expires_at = 0.0


async def require_admin_request(request: Request, settings: Settings) -> dict[str, Any]:
    api_key = request.headers.get("x-admin-api-key")
    if settings.admin_api_key and api_key == settings.admin_api_key:
        return {"auth_type": "admin_api_key"}

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        claims = await verify_supabase_jwt(token, settings)

        app_metadata = claims.get("app_metadata") or {}
        if app_metadata.get("role") == "admin" or "admin" in app_metadata.get("roles", []):
            return {"auth_type": "supabase_jwt", "claims": claims}

    if settings.is_local and not settings.admin_api_key:
        return {"auth_type": "local_dev"}

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin access required")


async def verify_supabase_jwt(token: str, settings: Settings) -> dict[str, Any]:
    try:
        from jose import JWTError, jwt
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT verification dependency is not installed",
        ) from exc

    header = jwt.get_unverified_header(token)
    algorithm = header.get("alg")
    if algorithm not in SUPPORTED_JWT_ALGORITHMS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported JWT signing algorithm",
        )

    jwks = await _load_supabase_jwks(settings)
    if jwks:
        key = _select_jwk(jwks, header)
        if key:
            try:
                return jwt.decode(
                    token,
                    key,
                    algorithms=[algorithm],
                    options={"verify_aud": False},
                )
            except JWTError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid bearer token",
                ) from exc

    if settings.supabase_legacy_jwt_secret:
        try:
            return jwt.decode(
                token,
                settings.supabase_legacy_jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid legacy bearer token",
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No matching Supabase JWT signing key found",
    )


async def _load_supabase_jwks(settings: Settings) -> dict[str, Any] | None:
    global _jwks_cache, _jwks_cache_expires_at

    if settings.supabase_jwks_json:
        return json.loads(settings.supabase_jwks_json)

    jwks_url = settings.resolved_supabase_jwks_url
    if not jwks_url:
        return None

    now = time.monotonic()
    if _jwks_cache is not None and now < _jwks_cache_expires_at:
        return _jwks_cache

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_expires_at = now + JWKS_CACHE_SECONDS
        return _jwks_cache


def _select_jwk(jwks: dict[str, Any], header: dict[str, Any]) -> dict[str, Any] | None:
    keys = jwks.get("keys") or []
    kid = header.get("kid")
    algorithm = header.get("alg")
    for key in keys:
        if kid and key.get("kid") != kid:
            continue
        if key.get("alg") and key.get("alg") != algorithm:
            continue
        return key
    return None
