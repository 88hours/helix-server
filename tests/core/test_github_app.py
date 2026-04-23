"""Tests for core/github_app.py"""
import base64
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# _get_app_id
# ---------------------------------------------------------------------------

def test_get_app_id_returns_env_var(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "123456")
    from core.github_app import _get_app_id
    assert _get_app_id() == "123456"


def test_get_app_id_raises_when_not_set(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    from core.github_app import _get_app_id
    with pytest.raises(RuntimeError, match="GITHUB_APP_ID"):
        _get_app_id()


# ---------------------------------------------------------------------------
# _get_private_key
# ---------------------------------------------------------------------------

def test_get_private_key_decodes_base64(monkeypatch):
    pem = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
    encoded = base64.b64encode(pem.encode()).decode()
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", encoded)
    from core.github_app import _get_private_key
    assert _get_private_key() == pem


def test_get_private_key_raises_when_not_set(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    from core.github_app import _get_private_key
    with pytest.raises(RuntimeError, match="GITHUB_APP_PRIVATE_KEY"):
        _get_private_key()


def test_get_private_key_raises_on_invalid_base64(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "not-valid-base64!!!")
    from core.github_app import _get_private_key
    with pytest.raises(RuntimeError, match="Failed to decode"):
        _get_private_key()


# ---------------------------------------------------------------------------
# get_app_slug
# ---------------------------------------------------------------------------

def test_get_app_slug_returns_env_var(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_SLUG", "helix-bot")
    from core.github_app import get_app_slug
    assert get_app_slug() == "helix-bot"


def test_get_app_slug_raises_when_not_set(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_SLUG", raising=False)
    from core.github_app import get_app_slug
    with pytest.raises(RuntimeError, match="GITHUB_APP_SLUG"):
        get_app_slug()


# ---------------------------------------------------------------------------
# build_install_url
# ---------------------------------------------------------------------------

def test_build_install_url_uses_slug(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_SLUG", "helix-bot")
    from core.github_app import build_install_url
    url = build_install_url()
    assert url == "https://github.com/apps/helix-bot/installations/new"


# ---------------------------------------------------------------------------
# _make_jwt
# ---------------------------------------------------------------------------

def test_make_jwt_returns_encoded_token(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "123456")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", base64.b64encode(b"fake-pem").decode())
    with patch("core.github_app.jwt.encode", return_value="fake-jwt") as mock_encode:
        from core.github_app import _make_jwt
        result = _make_jwt()
    assert result == "fake-jwt"
    mock_encode.assert_called_once()
    # algorithm may be positional or keyword depending on PyJWT version
    args, kwargs = mock_encode.call_args
    algorithm = kwargs.get("algorithm") or (args[2] if len(args) > 2 else None)
    assert algorithm == "RS256"


# ---------------------------------------------------------------------------
# _fetch_installation_token
# ---------------------------------------------------------------------------

async def test_fetch_installation_token_returns_token_and_expiry(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "123456")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", base64.b64encode(b"fake-pem").decode())
    expires = "2030-01-01T12:00:00Z"
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"token": "ghs_token123", "expires_at": expires}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("core.github_app._make_jwt", return_value="fake-jwt"), \
         patch("core.github_app.httpx.AsyncClient", return_value=mock_client):
        from core.github_app import _fetch_installation_token
        token, exp = await _fetch_installation_token("inst-001")

    assert token == "ghs_token123"
    assert exp.year == 2030


# ---------------------------------------------------------------------------
# get_installation_token
# ---------------------------------------------------------------------------

async def test_get_installation_token_returns_cached_when_fresh():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    cached = {"installation_id": "inst-001", "owner_sub": "github|123",
              "access_token": "cached-token", "token_expires_at": future}
    db = AsyncMock()
    with patch("core.github_app.get_github_installation", new=AsyncMock(return_value=cached)):
        from core.github_app import get_installation_token
        token = await get_installation_token("inst-001", db)
    assert token == "cached-token"


async def test_get_installation_token_fetches_when_expired():
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cached = {"installation_id": "inst-001", "owner_sub": "github|123",
              "access_token": "old-token", "token_expires_at": past}
    db = AsyncMock()
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    with patch("core.github_app.get_github_installation", new=AsyncMock(return_value=cached)), \
         patch("core.github_app._fetch_installation_token", new=AsyncMock(return_value=("new-token", future))), \
         patch("core.github_app.upsert_github_installation", new=AsyncMock()):
        from core.github_app import get_installation_token
        token = await get_installation_token("inst-001", db)
    assert token == "new-token"


async def test_get_installation_token_fetches_when_no_cache():
    db = AsyncMock()
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    with patch("core.github_app.get_github_installation", new=AsyncMock(return_value=None)), \
         patch("core.github_app._fetch_installation_token", new=AsyncMock(return_value=("fresh-token", future))), \
         patch("core.github_app.upsert_github_installation", new=AsyncMock()):
        from core.github_app import get_installation_token
        token = await get_installation_token("inst-001", db)
    assert token == "fresh-token"


async def test_get_installation_token_makes_naive_datetime_aware():
    """Cached token with a naive (no tzinfo) datetime is still used if not expired."""
    naive_future = datetime.now() + timedelta(hours=1)  # no tzinfo
    cached = {"installation_id": "inst-001", "owner_sub": "github|123",
              "access_token": "cached-token", "token_expires_at": naive_future}
    db = AsyncMock()
    with patch("core.github_app.get_github_installation", new=AsyncMock(return_value=cached)):
        from core.github_app import get_installation_token
        token = await get_installation_token("inst-001", db)
    assert token == "cached-token"


# ---------------------------------------------------------------------------
# list_installation_repos
# ---------------------------------------------------------------------------

async def test_list_installation_repos_returns_all_repos():
    db = AsyncMock()
    batch = [
        {"full_name": "acme/backend", "private": False, "default_branch": "main", "description": ""},
        {"full_name": "acme/frontend", "private": True, "default_branch": "main", "description": None},
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"repositories": batch}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("core.github_app.get_installation_token", new=AsyncMock(return_value="ghs_token")), \
         patch("core.github_app.httpx.AsyncClient", return_value=mock_client):
        from core.github_app import list_installation_repos
        repos = await list_installation_repos("inst-001", db)

    assert len(repos) == 2
    assert repos[0]["full_name"] == "acme/backend"
    assert repos[1]["description"] == ""  # None becomes ""


async def test_list_installation_repos_returns_empty_list():
    db = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"repositories": []}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("core.github_app.get_installation_token", new=AsyncMock(return_value="ghs_token")), \
         patch("core.github_app.httpx.AsyncClient", return_value=mock_client):
        from core.github_app import list_installation_repos
        repos = await list_installation_repos("inst-001", db)

    assert repos == []
