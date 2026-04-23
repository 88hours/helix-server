"""Tests for core/db.py"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# _get_engine — URL conversion and caching
# ---------------------------------------------------------------------------

def test_get_engine_raises_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import core.db
    core.db._engine = None
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        core.db._get_engine()
    core.db._engine = None


def test_get_engine_converts_postgres_scheme(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost/db")
    import core.db
    core.db._engine = None
    with patch("core.db.create_async_engine") as mock_create:
        mock_create.return_value = MagicMock()
        core.db._get_engine()
    assert mock_create.call_args[0][0].startswith("postgresql+asyncpg://")
    core.db._engine = None


def test_get_engine_converts_postgresql_scheme(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    import core.db
    core.db._engine = None
    with patch("core.db.create_async_engine") as mock_create:
        mock_create.return_value = MagicMock()
        core.db._get_engine()
    assert "+asyncpg" in mock_create.call_args[0][0]
    core.db._engine = None


def test_get_engine_reuses_cached_engine():
    import core.db
    mock_engine = MagicMock()
    core.db._engine = mock_engine
    result = core.db._get_engine()
    assert result is mock_engine
    core.db._engine = None


# ---------------------------------------------------------------------------
# upsert_user
# ---------------------------------------------------------------------------

async def test_upsert_user_executes_insert():
    db = AsyncMock()
    from core.db import upsert_user
    await upsert_user(db, "github|123", "Alice", "alice@example.com", "https://pic.url/a.jpg")
    db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# insert_project
# ---------------------------------------------------------------------------

async def test_insert_project_executes_insert():
    db = AsyncMock()
    from core.db import insert_project
    await insert_project(db, "proj-001", "github|123", "Acme", "acme/repo", "main", "python", None)
    db.execute.assert_awaited_once()


async def test_insert_project_passes_installation_id():
    db = AsyncMock()
    from core.db import insert_project
    await insert_project(db, "proj-001", "github|123", "Acme", "acme/repo", "main", "python", "inst-42")
    params = db.execute.call_args[0][1]
    assert params["installation_id"] == "inst-42"


# ---------------------------------------------------------------------------
# get_project
# ---------------------------------------------------------------------------

async def test_get_project_returns_dict_when_found():
    db = AsyncMock()
    mock_row = {"project_id": "proj-001", "name": "Acme", "repo": "acme/repo"}
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = mock_row
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import get_project
    result = await get_project(db, "proj-001")
    assert result["project_id"] == "proj-001"
    assert result["repo"] == "acme/repo"


async def test_get_project_returns_none_when_not_found():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import get_project
    assert await get_project(db, "nonexistent") is None


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------

async def test_list_projects_returns_all_rows():
    db = AsyncMock()
    rows = [{"project_id": "p1"}, {"project_id": "p2"}]
    mock_result = MagicMock()
    mock_result.mappings.return_value = rows
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import list_projects
    result = await list_projects(db, "github|123")
    assert len(result) == 2
    assert result[0]["project_id"] == "p1"


async def test_list_projects_returns_empty_list():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import list_projects
    assert await list_projects(db, "github|123") == []


# ---------------------------------------------------------------------------
# delete_project
# ---------------------------------------------------------------------------

async def test_delete_project_returns_true_when_row_deleted():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 1
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import delete_project
    assert await delete_project(db, "proj-001", "github|123") is True


async def test_delete_project_returns_false_when_not_found():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 0
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import delete_project
    assert await delete_project(db, "nonexistent", "github|123") is False


# ---------------------------------------------------------------------------
# upsert_project_settings
# ---------------------------------------------------------------------------

async def test_upsert_project_settings_executes_upsert():
    db = AsyncMock()
    from core.db import upsert_project_settings
    await upsert_project_settings(db, "proj-001", {"slack_bot_token": "xoxb-test", "email_from": "h@x.com"})
    db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# upsert_github_installation
# ---------------------------------------------------------------------------

async def test_upsert_github_installation_without_token():
    db = AsyncMock()
    from core.db import upsert_github_installation
    await upsert_github_installation(db, "inst-123", "github|123")
    db.execute.assert_awaited_once()


async def test_upsert_github_installation_with_token():
    db = AsyncMock()
    expires = datetime.now(timezone.utc)
    from core.db import upsert_github_installation
    await upsert_github_installation(db, "inst-123", "github|123", "ghs_token", expires)
    params = db.execute.call_args[0][1]
    assert params["access_token"] == "ghs_token"
    assert params["token_expires_at"] == expires


# ---------------------------------------------------------------------------
# get_github_installation
# ---------------------------------------------------------------------------

async def test_get_github_installation_returns_row_when_found():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = {"installation_id": "inst-123", "owner_sub": "github|123"}
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import get_github_installation
    result = await get_github_installation(db, "inst-123")
    assert result["installation_id"] == "inst-123"


async def test_get_github_installation_returns_none_when_not_found():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import get_github_installation
    assert await get_github_installation(db, "nonexistent") is None


# ---------------------------------------------------------------------------
# get_installation_for_user
# ---------------------------------------------------------------------------

async def test_get_installation_for_user_returns_most_recent():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = {"installation_id": "inst-999", "owner_sub": "github|123"}
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import get_installation_for_user
    result = await get_installation_for_user(db, "github|123")
    assert result["installation_id"] == "inst-999"


async def test_get_installation_for_user_returns_none_when_not_found():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    from core.db import get_installation_for_user
    assert await get_installation_for_user(db, "github|no-install") is None


# ---------------------------------------------------------------------------
# get_db — context manager
# ---------------------------------------------------------------------------

async def test_get_db_yields_connection(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    import core.db
    core.db._engine = None

    mock_conn = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_ctx

    with patch("core.db.create_async_engine", return_value=mock_engine):
        core.db._engine = None
        from core.db import get_db
        async with get_db() as conn:
            assert conn is mock_conn
    core.db._engine = None


# ---------------------------------------------------------------------------
# init_db — creates tables
# ---------------------------------------------------------------------------

async def test_init_db_executes_statements(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    import core.db
    core.db._engine = None

    mock_conn = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_ctx

    with patch("core.db.create_async_engine", return_value=mock_engine):
        core.db._engine = None
        from core.db import init_db
        await init_db()

    assert mock_conn.execute.call_count >= 1
    core.db._engine = None
