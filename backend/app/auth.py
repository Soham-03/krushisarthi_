"""Clerk login check. If Clerk is not configured, everyone is the same demo user."""
import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from .config import settings

_client = None


def _jwks():
    global _client
    if _client is None:
        _client = PyJWKClient(settings.clerk_jwks_url, cache_keys=True)
    return _client


def current_user(authorization: str = Header(default="")) -> str:
    if not settings.clerk_enabled:
        return "demo-user"
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Please sign in")
    token = authorization[7:].strip()
    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256"], leeway=15,
            issuer=settings.clerk_issuer or None, options={"verify_aud": False},
        )
    except Exception:
        raise HTTPException(401, "Your session has expired. Please sign in again")
    return claims["sub"]
