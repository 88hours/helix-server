"""
Auth0 JWT validation for the Helix dashboard API.

Validates RS256 bearer tokens issued by Auth0 using JWKS public key verification.
No client secret is required on the backend — only the Auth0 domain and audience.

Auth is optional: if AUTH0_DOMAIN is not set, all protected routes are accessible
without a token.  This preserves demo / local-dev behaviour without requiring an
Auth0 tenant.

Environment variables:
    AUTH0_DOMAIN    e.g. your-tenant.auth0.com
    AUTH0_AUDIENCE  e.g. https://api.helix.yourapp.com

Usage (FastAPI dependency injection):
    from core.auth import get_current_user

    @app.get("/api/protected")
    async def protected(user: dict = Depends(get_current_user)):
        return {"sub": user["sub"]}

The returned dict contains standard OIDC claims:
    sub    — Auth0 user ID, e.g. "github|12345678"
    email  — user email (requires openid + email scopes)
    name   — display name
"""

import logging
import os
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# Synthetic user returned when auth is disabled (demo / local-dev mode).
_DEMO_USER: dict = {
    "sub": "demo|00000000",
    "name": "Demo User",
    "email": "demo@helix.local",
}


def auth_enabled() -> bool:
    """Return True when AUTH0_DOMAIN is set and auth should be enforced."""
    return bool(os.environ.get("AUTH0_DOMAIN"))


def _domain() -> str:
    return os.environ["AUTH0_DOMAIN"]


def _audience() -> str:
    return os.environ.get("AUTH0_AUDIENCE", "")


@lru_cache(maxsize=1)
def _fetch_jwks(domain: str) -> dict:
    """
    Fetch and in-process-cache the JWKS from Auth0.

    The cache holds for the lifetime of the process — it is cleared only when
    a token presents an unknown kid (key rotation), at which point one fresh
    fetch is attempted.

    Args:
        domain: Auth0 tenant domain, e.g. "your-tenant.auth0.com".

    Returns:
        Parsed JWKS dict with a "keys" list.

    Raises:
        HTTPException 503: JWKS could not be fetched.
    """
    url = f"https://{domain}/.well-known/jwks.json"
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("failed to fetch Auth0 JWKS", extra={"url": url, "error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch authentication keys — try again shortly",
        ) from exc


def _rsa_key_for(jwks: dict, kid: str) -> dict | None:
    """Return the JWK entry matching kid, or None."""
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def _verify(token: str) -> dict:
    """
    Validate an Auth0 JWT and return its decoded claims.

    Validates: RS256 signature, expiry, audience, issuer.
    Handles key rotation by clearing the JWKS cache and retrying once.

    Args:
        token: Raw JWT string (the value after "Bearer ").

    Returns:
        Decoded payload dict.

    Raises:
        HTTPException 401: Token is missing, invalid, expired, or untrusted.
    """
    domain = _domain()
    audience = _audience()

    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token") from exc

    kid = header.get("kid", "")
    jwks = _fetch_jwks(domain)
    raw_key = _rsa_key_for(jwks, kid)

    if raw_key is None:
        # Key may have rotated — clear cache and retry once.
        _fetch_jwks.cache_clear()
        jwks = _fetch_jwks(domain)
        raw_key = _rsa_key_for(jwks, kid)

    if raw_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signing key not found",
        )

    try:
        from jwt.algorithms import RSAAlgorithm  # noqa: PLC0415

        public_key = RSAAlgorithm.from_jwk(raw_key)
        decode_kwargs: dict = dict(
            algorithms=["RS256"],
            issuer=f"https://{domain}/",
        )
        if audience:
            decode_kwargs["audience"] = audience

        return jwt.decode(token, public_key, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid issuer") from exc
    except jwt.DecodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token decode failed") from exc


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency — validate the bearer token and return JWT claims.

    When auth is disabled (AUTH0_DOMAIN not set), returns a synthetic demo user
    so all other code can treat the result uniformly.

    The SSE stream endpoint cannot send an Authorization header from the browser,
    so it passes the token as an ?access_token= query parameter instead.  This
    dependency checks that fallback automatically.

    Args:
        request:     FastAPI Request (used for the query-param fallback).
        credentials: HTTPBearer credentials (may be None when auto_error=False).

    Returns:
        JWT claims dict with at least {"sub": str, "name": str, "email": str}.

    Raises:
        HTTPException 401: Auth is enabled and no valid token was provided.
    """
    if not auth_enabled():
        return _DEMO_USER

    token: str | None = None

    if credentials:
        token = credentials.credentials
    else:
        # Fallback for EventSource which cannot set Authorization headers.
        token = request.query_params.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _verify(token)
