"""
GitHub App integration for Helix.

Handles JWT generation, installation access token fetch/cache, and repo listing.
Used by the onboarding wizard and agents to obtain short-lived tokens scoped to
a specific GitHub App installation.

Flow
----
1. User installs the GitHub App → GitHub redirects to /api/github/callback with
   installation_id in the query string.
2. Backend stores the installation_id linked to the user's Auth0 sub.
3. When an agent needs to access a repo, it calls get_installation_token() which:
   a. Checks the cached token in Postgres (github_installations table).
   b. If missing or expired, generates a JWT from the App private key, calls the
      GitHub API to exchange it for a fresh installation token, and caches it.
4. list_installation_repos() returns all repos the installation has access to —
   used to populate the repo picker in the onboarding wizard.

Environment variables
---------------------
GITHUB_APP_ID           Numeric GitHub App ID (e.g. "123456")
GITHUB_APP_PRIVATE_KEY  PEM private key, base64-encoded
GITHUB_APP_SLUG         App slug used to build the install URL (e.g. "helix-bot")
"""

import base64
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
import jwt

from core.db import AsyncConnection, get_github_installation, upsert_github_installation

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_TOKEN_BUFFER_SECONDS = 60  # refresh token this many seconds before expiry


def _get_app_id() -> str:
    """Return the GitHub App ID from the environment."""
    app_id = os.environ.get("GITHUB_APP_ID", "")
    if not app_id:
        raise RuntimeError("GITHUB_APP_ID environment variable is not set")
    return app_id


def _get_private_key() -> str:
    """
    Return the GitHub App RSA private key as a PEM string.

    The key is stored base64-encoded in GITHUB_APP_PRIVATE_KEY to avoid
    newline handling issues in .env files and container environment variables.
    """
    raw = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")
    if not raw:
        raise RuntimeError("GITHUB_APP_PRIVATE_KEY environment variable is not set")
    try:
        return base64.b64decode(raw).decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to decode GITHUB_APP_PRIVATE_KEY: {exc}") from exc


def get_app_slug() -> str:
    """Return the GitHub App slug for building the installation URL."""
    slug = os.environ.get("GITHUB_APP_SLUG", "")
    if not slug:
        raise RuntimeError("GITHUB_APP_SLUG environment variable is not set")
    return slug


def build_install_url() -> str:
    """
    Return the GitHub App installation page URL.

    Redirecting the user here lets them choose which repos to grant access to.
    After installation, GitHub redirects to the configured callback URL with
    installation_id in the query string.
    """
    return f"https://github.com/apps/{get_app_slug()}/installations/new"


def _make_jwt() -> str:
    """
    Generate a short-lived JWT signed with the App private key.

    GitHub requires this JWT to authenticate as the App itself (not as an
    installation) when exchanging for an installation access token.

    The JWT is valid for 60 seconds — enough for one API call.
    """
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iat": now - 10,        # issued-at with 10s clock skew buffer
        "exp": now + 60,        # expiry: 60 seconds
        "iss": _get_app_id(),   # issuer: the App ID
    }
    return jwt.encode(payload, _get_private_key(), algorithm="RS256")


async def _fetch_installation_token(installation_id: str) -> tuple[str, datetime]:
    """
    Call the GitHub API to obtain a fresh installation access token.

    Args:
        installation_id: GitHub App installation ID.

    Returns:
        Tuple of (access_token, expires_at).

    Raises:
        httpx.HTTPStatusError: If the GitHub API returns a non-2xx response.
    """
    app_jwt = _make_jwt()
    url = f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    token = data["token"]
    # GitHub returns expiry as ISO 8601 string, e.g. "2024-01-01T12:00:00Z"
    expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    logger.debug("fetched fresh installation token", extra={"installation_id": installation_id})
    return token, expires_at


async def get_installation_token(installation_id: str, db: AsyncConnection) -> str:
    """
    Return a valid installation access token, using the Postgres cache.

    Checks the cached token first. If it is missing or within
    _TOKEN_BUFFER_SECONDS of expiry, fetches a fresh one from the GitHub API
    and updates the cache.

    Args:
        installation_id: GitHub App installation ID.
        db:              Open database connection for cache read/write.

    Returns:
        A valid GitHub installation access token string.
    """
    now = datetime.now(timezone.utc)
    cached = await get_github_installation(db, installation_id)

    if cached and cached.get("access_token") and cached.get("token_expires_at"):
        expires_at = cached["token_expires_at"]
        # Make timezone-aware if the DB returns a naive datetime
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at - now > timedelta(seconds=_TOKEN_BUFFER_SECONDS):
            return cached["access_token"]

    # Cache miss or near-expiry — fetch a fresh token
    token, expires_at = await _fetch_installation_token(installation_id)
    await upsert_github_installation(
        db,
        installation_id=installation_id,
        owner_sub=cached["owner_sub"] if cached else "",
        access_token=token,
        token_expires_at=expires_at,
    )
    return token


async def list_installation_repos(installation_id: str, db: AsyncConnection) -> list[dict]:
    """
    Return all repositories the installation has access to.

    Used by the onboarding wizard to populate the repo picker dropdown.

    Args:
        installation_id: GitHub App installation ID.
        db:              Open database connection (for token cache).

    Returns:
        List of dicts with keys: full_name, private, default_branch, description.
    """
    token = await get_installation_token(installation_id, db)
    repos: list[dict] = []
    page = 1

    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                f"{_GITHUB_API}/installation/repositories",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("repositories", [])
            if not batch:
                break
            for r in batch:
                repos.append({
                    "full_name": r["full_name"],
                    "private": r["private"],
                    "default_branch": r.get("default_branch", "main"),
                    "description": r.get("description") or "",
                })
            if len(batch) < 100:
                break
            page += 1

    logger.debug(
        "listed installation repos",
        extra={"installation_id": installation_id, "count": len(repos)},
    )
    return repos
