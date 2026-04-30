"""
Postgres database layer for Helix persistent storage.

Manages user profiles, projects, project settings, and GitHub App installation
tokens.  Uses SQLAlchemy async core (not ORM) with asyncpg.

Tables
------
users                — Auth0 user profiles (sub as PK)
projects             — per-user projects (UUID project_id as PK)
project_settings     — credentials and config for each project (1:1 with projects)
github_installations — GitHub App installation tokens, cached with expiry

Connection
----------
Reads DATABASE_URL from the environment.  Call init_db() once on startup to
create all tables if they do not exist.

Usage
-----
    from core.db import get_db, init_db

    await init_db()

    async with get_db() as db:
        await db.execute(...)
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    text,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    """Return the module-level engine, creating it on first call."""
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            raise RuntimeError("DATABASE_URL environment variable is not set")
        # asyncpg requires postgresql+asyncpg:// scheme
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        _engine = create_async_engine(url, poolclass=NullPool, echo=False)
    return _engine


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncConnection, None]:
    """
    Async context manager that yields an open database connection.

    Commits on clean exit, rolls back on exception.

    Usage::

        async with get_db() as db:
            await db.execute(text("SELECT 1"))
    """
    engine = _get_engine()
    async with engine.begin() as conn:
        yield conn


# ---------------------------------------------------------------------------
# DDL — create tables on startup
# ---------------------------------------------------------------------------

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    sub         TEXT PRIMARY KEY,
    name        TEXT,
    email       TEXT,
    picture     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    project_id          TEXT PRIMARY KEY,
    owner_sub           TEXT NOT NULL REFERENCES users(sub) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    repo                TEXT NOT NULL,
    base_branch         TEXT NOT NULL DEFAULT 'main',
    language            TEXT NOT NULL DEFAULT 'python',
    github_installation_id TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_settings (
    project_id              TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    anthropic_api_key       TEXT,
    sentry_webhook_secret   TEXT,
    rollbar_access_token    TEXT,
    slack_bot_token         TEXT,
    slack_signing_secret    TEXT,
    slack_approval_channel  TEXT,
    sendgrid_api_key        TEXT,
    smtp_host               TEXT,
    email_from              TEXT,
    email_to                TEXT,
    alert_sources           TEXT NOT NULL DEFAULT '["sentry","rollbar"]',
    agent_overrides         TEXT NOT NULL DEFAULT '{}',
    pipeline                TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS github_installations (
    installation_id     TEXT PRIMARY KEY,
    owner_sub           TEXT NOT NULL REFERENCES users(sub) ON DELETE CASCADE,
    access_token        TEXT,
    token_expires_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_settings (
    sub                 TEXT PRIMARY KEY REFERENCES users(sub) ON DELETE CASCADE,
    anthropic_api_key   TEXT,
    openrouter_api_key  TEXT,
    ollama_base_url     TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_events (
    id          BIGSERIAL PRIMARY KEY,
    incident_id TEXT,
    project_id  TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL,
    action      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ok',
    details     JSONB,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_incident   ON audit_events (incident_id);
CREATE INDEX IF NOT EXISTS idx_audit_project_ts ON audit_events (project_id, ts DESC);
"""


async def init_db() -> None:
    """
    Create all Helix tables if they do not exist.

    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS.
    """
    engine = _get_engine()
    async with engine.begin() as conn:
        for statement in _CREATE_TABLES_SQL.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                await conn.execute(text(stmt))
    logger.info("database tables verified / created")


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

async def upsert_user(db: AsyncConnection, sub: str, name: str, email: str, picture: str) -> None:
    """
    Insert or update a user record from Auth0 token claims.

    Args:
        db:      Open database connection.
        sub:     Auth0 subject claim (e.g. "github|12345678").
        name:    Display name from the token.
        email:   Email address from the token.
        picture: Avatar URL from the token.
    """
    await db.execute(
        text("""
            INSERT INTO users (sub, name, email, picture)
            VALUES (:sub, :name, :email, :picture)
            ON CONFLICT (sub) DO UPDATE
                SET name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    picture = EXCLUDED.picture
        """),
        {"sub": sub, "name": name, "email": email, "picture": picture},
    )


# ---------------------------------------------------------------------------
# Project helpers
# ---------------------------------------------------------------------------

async def insert_project(
    db: AsyncConnection,
    project_id: str,
    owner_sub: str,
    name: str,
    repo: str,
    base_branch: str,
    language: str,
    github_installation_id: str | None,
) -> None:
    """
    Insert a new project row.

    Args:
        db:                      Open database connection.
        project_id:              UUID string for the project.
        owner_sub:               Auth0 sub of the creating user.
        name:                    Human-readable project name.
        repo:                    Repository in "owner/name" format.
        base_branch:             Branch PRs are opened against.
        language:                Primary language of the repo.
        github_installation_id:  GitHub App installation ID, if connected.
    """
    await db.execute(
        text("""
            INSERT INTO projects
                (project_id, owner_sub, name, repo, base_branch, language, github_installation_id)
            VALUES
                (:project_id, :owner_sub, :name, :repo, :base_branch, :language, :installation_id)
        """),
        {
            "project_id": project_id,
            "owner_sub": owner_sub,
            "name": name,
            "repo": repo,
            "base_branch": base_branch,
            "language": language,
            "installation_id": github_installation_id,
        },
    )


async def get_project(db: AsyncConnection, project_id: str) -> dict | None:
    """
    Fetch a project row by project_id, joined with its settings.

    Returns a dict with all project + settings columns, or None if not found.

    Args:
        db:         Open database connection.
        project_id: UUID string of the project.
    """
    result = await db.execute(
        text("""
            SELECT p.*, s.anthropic_api_key, s.sentry_webhook_secret,
                   s.rollbar_access_token, s.slack_bot_token, s.slack_signing_secret,
                   s.slack_approval_channel, s.sendgrid_api_key, s.smtp_host,
                   s.email_from, s.email_to, s.alert_sources, s.agent_overrides, s.pipeline
            FROM projects p
            LEFT JOIN project_settings s ON s.project_id = p.project_id
            WHERE p.project_id = :project_id
        """),
        {"project_id": project_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_projects(db: AsyncConnection, owner_sub: str) -> list[dict]:
    """
    List all projects owned by a user, joined with their settings.

    Args:
        db:        Open database connection.
        owner_sub: Auth0 sub of the user.
    """
    result = await db.execute(
        text("""
            SELECT p.*, s.anthropic_api_key, s.sentry_webhook_secret,
                   s.rollbar_access_token, s.slack_bot_token, s.slack_signing_secret,
                   s.slack_approval_channel, s.sendgrid_api_key, s.smtp_host,
                   s.email_from, s.email_to, s.alert_sources, s.agent_overrides, s.pipeline
            FROM projects p
            LEFT JOIN project_settings s ON s.project_id = p.project_id
            WHERE p.owner_sub = :sub
            ORDER BY p.created_at ASC
        """),
        {"sub": owner_sub},
    )
    return [dict(r) for r in result.mappings()]



async def list_all_projects(db: AsyncConnection) -> list[dict]:
    """List all projects across all users (used in demo mode when auth is disabled)."""
    result = await db.execute(
        text("""
            SELECT p.*, s.anthropic_api_key, s.sentry_webhook_secret,
                   s.rollbar_access_token, s.slack_bot_token, s.slack_signing_secret,
                   s.slack_approval_channel, s.sendgrid_api_key, s.smtp_host,
                   s.email_from, s.email_to, s.alert_sources, s.agent_overrides, s.pipeline
            FROM projects p
            LEFT JOIN project_settings s ON s.project_id = p.project_id
            ORDER BY p.created_at ASC
        """)
    )
    return [dict(r) for r in result.mappings()]


async def delete_project(db: AsyncConnection, project_id: str, owner_sub: str) -> bool:
    """
    Delete a project and its settings (CASCADE).  Returns True if a row was deleted.

    The owner_sub check ensures users can only delete their own projects.

    Args:
        db:         Open database connection.
        project_id: UUID string of the project.
        owner_sub:  Auth0 sub of the requesting user.
    """
    result = await db.execute(
        text("DELETE FROM projects WHERE project_id = :pid AND owner_sub = :sub"),
        {"pid": project_id, "sub": owner_sub},
    )
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Project settings helpers
# ---------------------------------------------------------------------------

async def upsert_project_settings(db: AsyncConnection, project_id: str, settings: dict) -> None:
    """
    Insert or update project settings.

    The settings dict should contain only the fields being set — missing keys
    are left unchanged on update (via COALESCE).

    Args:
        db:         Open database connection.
        project_id: UUID of the project.
        settings:   Dict of setting key → value (plain strings, already unmasked).
    """
    await db.execute(
        text("""
            INSERT INTO project_settings (
                project_id, anthropic_api_key, sentry_webhook_secret,
                rollbar_access_token, slack_bot_token, slack_signing_secret,
                slack_approval_channel, sendgrid_api_key, smtp_host,
                email_from, email_to, alert_sources, agent_overrides, pipeline
            ) VALUES (
                :project_id, :anthropic_api_key, :sentry_webhook_secret,
                :rollbar_access_token, :slack_bot_token, :slack_signing_secret,
                :slack_approval_channel, :sendgrid_api_key, :smtp_host,
                :email_from, :email_to, :alert_sources, :agent_overrides, :pipeline
            )
            ON CONFLICT (project_id) DO UPDATE SET
                anthropic_api_key      = COALESCE(EXCLUDED.anthropic_api_key,      project_settings.anthropic_api_key),
                sentry_webhook_secret  = COALESCE(EXCLUDED.sentry_webhook_secret,  project_settings.sentry_webhook_secret),
                rollbar_access_token   = COALESCE(EXCLUDED.rollbar_access_token,   project_settings.rollbar_access_token),
                slack_bot_token        = COALESCE(EXCLUDED.slack_bot_token,        project_settings.slack_bot_token),
                slack_signing_secret   = COALESCE(EXCLUDED.slack_signing_secret,   project_settings.slack_signing_secret),
                slack_approval_channel = COALESCE(EXCLUDED.slack_approval_channel, project_settings.slack_approval_channel),
                sendgrid_api_key       = COALESCE(EXCLUDED.sendgrid_api_key,       project_settings.sendgrid_api_key),
                smtp_host              = COALESCE(EXCLUDED.smtp_host,              project_settings.smtp_host),
                email_from             = COALESCE(EXCLUDED.email_from,             project_settings.email_from),
                email_to               = COALESCE(EXCLUDED.email_to,               project_settings.email_to),
                alert_sources          = COALESCE(EXCLUDED.alert_sources,          project_settings.alert_sources),
                agent_overrides        = COALESCE(EXCLUDED.agent_overrides,        project_settings.agent_overrides),
                pipeline               = COALESCE(EXCLUDED.pipeline,               project_settings.pipeline)
        """),
        {
            "project_id": project_id,
            "anthropic_api_key": settings.get("anthropic_api_key"),
            "sentry_webhook_secret": settings.get("sentry_webhook_secret"),
            "rollbar_access_token": settings.get("rollbar_access_token"),
            "slack_bot_token": settings.get("slack_bot_token"),
            "slack_signing_secret": settings.get("slack_signing_secret"),
            "slack_approval_channel": settings.get("slack_approval_channel"),
            "sendgrid_api_key": settings.get("sendgrid_api_key"),
            "smtp_host": settings.get("smtp_host"),
            "email_from": settings.get("email_from"),
            "email_to": settings.get("email_to"),
            "alert_sources": settings.get("alert_sources", '["sentry","rollbar"]'),
            "agent_overrides": settings.get("agent_overrides", "{}"),
            "pipeline": settings.get("pipeline", "{}"),
        },
    )


# ---------------------------------------------------------------------------
# GitHub installation helpers
# ---------------------------------------------------------------------------

async def upsert_github_installation(
    db: AsyncConnection,
    installation_id: str,
    owner_sub: str,
    access_token: str | None = None,
    token_expires_at: datetime | None = None,
) -> None:
    """
    Insert or update a GitHub App installation record.

    Args:
        db:               Open database connection.
        installation_id:  GitHub App installation ID (numeric string).
        owner_sub:        Auth0 sub of the user who installed the app.
        access_token:     Cached installation access token (may be None initially).
        token_expires_at: Expiry time of the cached token.
    """
    await db.execute(
        text("""
            INSERT INTO github_installations (installation_id, owner_sub, access_token, token_expires_at)
            VALUES (:installation_id, :owner_sub, :access_token, :token_expires_at)
            ON CONFLICT (installation_id) DO UPDATE SET
                owner_sub        = EXCLUDED.owner_sub,
                access_token     = COALESCE(EXCLUDED.access_token,     github_installations.access_token),
                token_expires_at = COALESCE(EXCLUDED.token_expires_at, github_installations.token_expires_at)
        """),
        {
            "installation_id": installation_id,
            "owner_sub": owner_sub,
            "access_token": access_token,
            "token_expires_at": token_expires_at,
        },
    )


async def get_github_installation(db: AsyncConnection, installation_id: str) -> dict | None:
    """
    Fetch a cached GitHub installation token record.

    Args:
        db:               Open database connection.
        installation_id:  GitHub App installation ID.
    """
    result = await db.execute(
        text("SELECT * FROM github_installations WHERE installation_id = :iid"),
        {"iid": installation_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def get_installation_for_user(db: AsyncConnection, owner_sub: str) -> dict | None:
    """
    Fetch the most recent GitHub installation record for a user.

    Args:
        db:        Open database connection.
        owner_sub: Auth0 sub of the user.
    """
    result = await db.execute(
        text("""
            SELECT * FROM github_installations
            WHERE owner_sub = :sub
            ORDER BY installation_id DESC
            LIMIT 1
        """),
        {"sub": owner_sub},
    )
    row = result.mappings().first()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# User settings helpers
# ---------------------------------------------------------------------------

async def get_user_settings(db: AsyncConnection, sub: str) -> dict:
    """
    Fetch the user-level LLM key settings for a user.

    Returns a dict with anthropic_api_key, openrouter_api_key, ollama_base_url.
    All values are None if not set. Returns an empty dict structure if the row
    does not exist yet.

    Args:
        db:  Open database connection.
        sub: Auth0 subject claim of the user.
    """
    result = await db.execute(
        text("SELECT * FROM user_settings WHERE sub = :sub"),
        {"sub": sub},
    )
    row = result.mappings().first()
    if row:
        return dict(row)
    return {"sub": sub, "anthropic_api_key": None, "openrouter_api_key": None, "ollama_base_url": None}


async def upsert_user_settings(db: AsyncConnection, sub: str, settings: dict) -> dict:
    """
    Insert or update user-level LLM key settings.

    Only non-None values in the settings dict are written; existing values are
    preserved for keys not present in the dict (via COALESCE). Pass an explicit
    None value to clear a field.

    Args:
        db:       Open database connection.
        sub:      Auth0 subject claim of the user.
        settings: Dict with any of: anthropic_api_key, openrouter_api_key, ollama_base_url.

    Returns:
        The updated settings row as a dict.
    """
    await db.execute(
        text("""
            INSERT INTO user_settings (sub, anthropic_api_key, openrouter_api_key, ollama_base_url, updated_at)
            VALUES (:sub, :anthropic_api_key, :openrouter_api_key, :ollama_base_url, now())
            ON CONFLICT (sub) DO UPDATE SET
                anthropic_api_key  = CASE WHEN :anthropic_api_key  IS NOT NULL THEN :anthropic_api_key  ELSE user_settings.anthropic_api_key  END,
                openrouter_api_key = CASE WHEN :openrouter_api_key IS NOT NULL THEN :openrouter_api_key ELSE user_settings.openrouter_api_key END,
                ollama_base_url    = CASE WHEN :ollama_base_url    IS NOT NULL THEN :ollama_base_url    ELSE user_settings.ollama_base_url    END,
                updated_at         = now()
        """),
        {
            "sub": sub,
            "anthropic_api_key": settings.get("anthropic_api_key"),
            "openrouter_api_key": settings.get("openrouter_api_key"),
            "ollama_base_url": settings.get("ollama_base_url"),
        },
    )
    return await get_user_settings(db, sub)


# ---------------------------------------------------------------------------
# Audit trail helpers
# ---------------------------------------------------------------------------

async def list_audit_events(
    db: AsyncConnection,
    *,
    incident_id: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return audit events filtered by incident or project, newest first."""
    conditions = []
    params: dict = {"limit": limit}
    if incident_id:
        conditions.append("incident_id = :incident_id")
        params["incident_id"] = incident_id
    if project_id:
        conditions.append("project_id = :project_id")
        params["project_id"] = project_id
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = await db.execute(
        text(f"SELECT * FROM audit_events {where} ORDER BY ts DESC LIMIT :limit"),
        params,
    )
    return [dict(r._mapping) for r in rows]
