"""
Crash Handler Agent — FastAPI entry point.

Exposes per-project webhook endpoints plus the streaming dashboard API:

  Webhooks (no auth — verified via payload signature / access token):
    POST /webhook/rollbar/{project_id}  — per-project Rollbar webhook.
    POST /webhook/sentry/{project_id}   — per-project Sentry webhook.
    POST /webhook/rollbar               — legacy; returns 410 Gone with upgrade message.
    POST /webhook/sentry                — legacy; returns 410 Gone with upgrade message.
    POST /slack/actions                 — Slack button interactions (Approve / Reject PR).

  GitHub App:
    GET  /api/github/callback           — GitHub App installation callback; stores installation_id.
    GET  /api/github/repos              — list repos accessible via the user's GitHub App installation.

  Dashboard API (requires Auth0 JWT when AUTH0_DOMAIN is set):
    GET  /api/incidents              — list all known incidents (reads Redis state).
    GET  /api/incidents/{id}         — full state for one incident (crash report, QA result, PR).
    GET  /api/stream/{id}            — Server-Sent Events stream of live agent progress.
    GET  /api/repos                  — list the calling user's configured repos.
    POST /api/repos                  — add a repo to the calling user's config.
    DELETE /api/repos/{owner}/{name} — remove a repo from the calling user's config.
    GET  /api/projects               — list projects from Postgres.
    POST /api/projects               — create a project (wizard final step).
    PUT  /api/projects/{project_id}/settings  — update project settings.
    DELETE /api/projects/{project_id}         — delete a project.
    GET  /api/projects/{project_id}/webhook-urls — return webhook URLs for copy.

  Dashboard SPA:
    GET /app  and  GET /app/*       — serve the built React frontend from dashboard/dist/.

Run with:
    uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port 8000
"""

import json
import logging
import os
import uuid
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agents.crash_handler.agent import handle
from core.auth import get_current_user
from core.config import get_github_config, get_redis_url, get_rollbar_config, get_sentry_config, get_slack_config, is_demo_mode
from core.db import (
    delete_project as db_delete_project,
    get_db,
    get_installation_for_user,
    get_project,
    init_db,
    insert_project,
    list_projects as db_list_projects,
    upsert_github_installation,
    upsert_project_settings,
    upsert_user,
)
from core.github_app import build_install_url, get_app_slug, list_installation_repos
from core.models import Project, ProjectSettings, RepoConfig
from core.state import (
    read_crash_report,
    read_pr_result,
    read_qa_result,
    read_status,
    read_user_repos,
    write_status,
    write_user_repos,
)
from core.ui_events import subscribe_ui_events
from integrations import rollbar as rollbar_integration
from integrations import sentry as sentry_integration
from integrations import slack as slack_integration
from integrations.github import merge_pull_request

# Path to the built React dashboard (populated by: cd dashboard && npm run build).
_DASHBOARD_DIST = Path(__file__).parent.parent.parent / "dashboard" / "dist"

# Landing page — static HTML served at /.
_LANDING_PAGE = Path(__file__).parent.parent.parent / "index.html"

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the Redis client and initialise Postgres tables on startup."""
    redis_url = get_redis_url()
    logger.info("=== Crash Handler starting ===")
    logger.info("demo mode: %s", os.environ.get("HELIX_DEMO", "not set"))
    logger.info("crash handler connecting to redis", extra={"redis_url": redis_url})
    app.state.redis = aioredis.from_url(redis_url, decode_responses=False)

    # Initialise Postgres tables (safe to call every startup — IF NOT EXISTS).
    if os.environ.get("DATABASE_URL"):
        try:
            await init_db()
        except Exception as exc:
            logger.warning("Postgres init failed — continuing without DB: %s", exc)
    else:
        logger.warning("DATABASE_URL not set — project Postgres storage disabled")

    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("PUBLIC_DOMAIN") or "localhost:8000"
    logger.info("crash handler started — listening on %s", domain)
    yield
    await app.state.redis.aclose()
    logger.info("crash handler shut down")


app = FastAPI(
    title="Helix — Crash Handler",
    description="Receives Rollbar webhooks and triggers the incident response pipeline.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz():
    """Liveness probe — always returns 200 if the server is running."""
    return {"status": "ok"}


@app.post("/webhook/rollbar", status_code=status.HTTP_410_GONE)
async def rollbar_webhook_legacy():
    """Legacy Rollbar webhook endpoint — replaced by /webhook/rollbar/{project_id}."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "This webhook URL is no longer active. "
            "Create a project in the Helix dashboard to get a per-project webhook URL: "
            "POST /webhook/rollbar/{project_id}"
        ),
    )


@app.post("/webhook/sentry", status_code=status.HTTP_410_GONE)
async def sentry_webhook_legacy():
    """Legacy Sentry webhook endpoint — replaced by /webhook/sentry/{project_id}."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "This webhook URL is no longer active. "
            "Create a project in the Helix dashboard to get a per-project webhook URL: "
            "POST /webhook/sentry/{project_id}"
        ),
    )


async def _load_project_or_404(project_id: str) -> dict:
    """
    Load a project from Postgres by project_id.

    Raises 404 if the project does not exist or DATABASE_URL is not configured.
    """
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Database not configured")
    async with get_db() as db:
        row = await get_project(db, project_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return row


@app.post("/webhook/rollbar/{project_id}", status_code=status.HTTP_202_ACCEPTED)
async def rollbar_webhook(project_id: str, request: Request):
    """
    Receive a Rollbar item-alert webhook for a specific project.

    Loads the project from Postgres to verify the access token embedded in
    the payload, then delegates to the Crash Handler Agent.
    Returns 202 immediately — processing is async.
    """
    row = await _load_project_or_404(project_id)
    body = await request.body()

    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON: {exc}")

    if raw.get("event_name") == "test":
        logger.info("rollbar connectivity test received — acknowledged", extra={"project_id": project_id})
        return {"status": "ok"}

    if is_demo_mode():
        logger.warning("demo mode enabled — skipping rollbar token verification", extra={"project_id": project_id})
    else:
        access_token = row.get("rollbar_access_token") or ""
        if not access_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Rollbar access token not configured for this project")
        if not rollbar_integration.verify_token(raw, access_token):
            logger.warning("rollbar token mismatch", extra={"project_id": project_id})
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")

    crash_event = rollbar_integration.parse_event(raw)
    report = await handle(crash_event, request.app.state.redis, project_id=project_id)
    logger.info("rollbar webhook accepted", extra={"incident_id": report.incident_id, "project_id": project_id})
    return {"incident_id": report.incident_id, "status": "accepted"}


@app.post("/webhook/sentry/{project_id}", status_code=status.HTTP_202_ACCEPTED)
async def sentry_webhook(project_id: str, request: Request):
    """
    Receive a Sentry issue-alert webhook for a specific project.

    Loads the project from Postgres to verify the HMAC-SHA256 signature,
    then delegates to the Crash Handler Agent.
    Returns 202 immediately — processing is async.
    """
    row = await _load_project_or_404(project_id)
    body = await request.body()
    signature = request.headers.get("sentry-hook-signature", "")

    logger.info(
        "sentry webhook received",
        extra={"project_id": project_id, "signature": signature[:20] if signature else "none"},
    )

    if is_demo_mode():
        logger.warning("demo mode — skipping sentry signature verification", extra={"project_id": project_id})
    else:
        webhook_secret = row.get("sentry_webhook_secret") or ""
        if webhook_secret:
            if not sentry_integration.verify_signature(body, signature, webhook_secret):
                logger.warning("sentry signature mismatch", extra={"project_id": project_id})
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
        else:
            logger.warning("sentry_webhook_secret not set for project — skipping check", extra={"project_id": project_id})

    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON: {exc}")

    if raw.get("action") == "ping" or raw.get("type") == "ping":
        logger.info("sentry ping received — acknowledged", extra={"project_id": project_id})
        return {"status": "ok"}

    crash_event = sentry_integration.parse_event(raw)
    report = await handle(crash_event, request.app.state.redis, project_id=project_id)
    logger.info("sentry webhook accepted", extra={"incident_id": report.incident_id, "project_id": project_id})
    return {"incident_id": report.incident_id, "status": "accepted"}


@app.post("/slack/actions", status_code=status.HTTP_200_OK)
async def slack_actions(request: Request):
    """
    Receive a Slack interactive component payload (button click).

    Handles Approve / Reject button clicks from the PR approval message
    posted by the Notifier Agent.

    On Approve: merges the PR via GitHub API and sets status to pr_merged.
    On Reject:  sets status to approval_rejected and posts a confirmation
                message back to Slack.

    Returns a plain-text response that Slack displays in place of the
    original message.

    Requires SLACK_SIGNING_SECRET to be configured — returns 403 if absent
    or if the signature is invalid.
    """
    body = await request.body()

    slack_config = get_slack_config()
    if not slack_config.signing_secret:
        logger.warning("slack actions endpoint called but SLACK_SIGNING_SECRET is not configured")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slack signing secret not configured",
        )

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not slack_integration.verify_signature(body, timestamp, signature, slack_config.signing_secret):
        logger.warning("slack actions signature verification failed")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Slack signature",
        )

    # Slack sends interactions as URL-encoded form data with a "payload" field.
    try:
        form = urllib.parse.parse_qs(body.decode("utf-8"))
        payload = json.loads(form["payload"][0])
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse Slack payload: {exc}",
        )

    actions = payload.get("actions", [])
    if not actions:
        return {"text": "No action found in payload."}

    action = actions[0]
    action_id = action.get("action_id", "")
    incident_id = action.get("value", "")

    logger.info(
        "slack action received",
        extra={"action_id": action_id, "incident_id": incident_id},
    )

    if action_id == "approve_pr":
        pr_result = await read_pr_result(request.app.state.redis, incident_id)
        if pr_result is None:
            logger.error(
                "pr_result not found for approval",
                extra={"incident_id": incident_id},
            )
            return {"text": f"Could not find PR for incident `{incident_id}`. It may have expired."}

        try:
            github_config = get_github_config()
            await merge_pull_request(
                repo=github_config.target_repo,
                pr_number=pr_result.pr_number,
            )
        except Exception as exc:
            logger.error(
                "pr merge failed",
                extra={"incident_id": incident_id, "pr_number": pr_result.pr_number, "error": str(exc)},
                exc_info=True,
            )
            return {"text": f":x: Merge failed for PR #{pr_result.pr_number}: {exc}"}

        await write_status(request.app.state.redis, incident_id, "pr_merged")
        logger.info(
            "pr approved and merged",
            extra={"incident_id": incident_id, "pr_number": pr_result.pr_number},
        )
        return {"text": f":white_check_mark: PR #{pr_result.pr_number} merged. Incident `{incident_id}` resolved."}

    if action_id == "reject_pr":
        await write_status(request.app.state.redis, incident_id, "approval_rejected")
        logger.info(
            "pr rejected by reviewer",
            extra={"incident_id": incident_id},
        )
        return {"text": f":x: PR rejected for incident `{incident_id}`. The branch remains open for manual review."}

    logger.warning("unknown slack action_id", extra={"action_id": action_id, "incident_id": incident_id})
    return {"text": f"Unknown action: {action_id}"}


# ---------------------------------------------------------------------------
# Dashboard API
# ---------------------------------------------------------------------------

@app.get("/api/incidents", tags=["dashboard"])
async def list_incidents(request: Request, _user: dict = Depends(get_current_user)):
    """
    List all known incidents.

    Scans Redis for helix:incident:*:status keys to enumerate incident IDs,
    then reads the status and crash report summary for each.  Returns newest
    incidents first (sorted by crash report timestamp).
    """
    redis_client = request.app.state.redis
    incidents = []

    async for raw_key in redis_client.scan_iter("helix:incident:*:status"):
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        # key format: helix:incident:{id}:status
        parts = key.split(":")
        if len(parts) != 4:
            continue
        incident_id = parts[2]

        status_val = await read_status(redis_client, incident_id)
        report = await read_crash_report(redis_client, incident_id)

        incidents.append(
            {
                "incident_id": incident_id,
                "status": status_val or "unknown",
                "error_type": report.error_type if report else None,
                "error_message": report.error_message if report else None,
                "severity": report.severity.value if report else None,
                "affected_component": report.affected_component if report else None,
                "summary": report.summary if report else None,
                "timestamp": report.timestamp.isoformat() if report and report.timestamp else None,
            }
        )

    incidents.sort(key=lambda i: i["timestamp"] or "", reverse=True)
    return {"incidents": incidents}


@app.get("/api/incidents/{incident_id}", tags=["dashboard"])
async def get_incident(incident_id: str, request: Request, _user: dict = Depends(get_current_user)):
    """
    Return the full state for a single incident.

    Reads crash_report, qa_result, pr_result, and status from Redis.
    Returns 404 if the incident does not exist.
    """
    redis_client = request.app.state.redis

    status_val = await read_status(redis_client, incident_id)
    if status_val is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    report = await read_crash_report(redis_client, incident_id)
    qa_result = await read_qa_result(redis_client, incident_id)
    pr_result = await read_pr_result(redis_client, incident_id)

    return {
        "incident_id": incident_id,
        "status": status_val,
        "crash_report": report.model_dump(mode="json") if report else None,
        "qa_result": qa_result.model_dump(mode="json") if qa_result else None,
        "pr_result": pr_result.model_dump(mode="json") if pr_result else None,
    }


@app.get("/api/stream/{incident_id}", tags=["dashboard"])
async def stream_incident(incident_id: str, request: Request, _user: dict = Depends(get_current_user)):
    """
    Server-Sent Events stream of live agent progress for an incident.

    On connect: immediately sends a "snapshot" event with the current full
    incident state so the browser renders something before any new events fire.

    Then: subscribes to helix:ui:{incident_id} Pub/Sub and forwards each
    "progress" event as it is published by an agent.

    Uses a dedicated Redis client for Pub/Sub (pub/sub is stateful — cannot
    share the application-wide client).
    """
    redis_client = request.app.state.redis
    redis_url = get_redis_url()

    async def event_generator():
        # Snapshot — send current state so the UI is immediately populated.
        status_val = await read_status(redis_client, incident_id)
        report = await read_crash_report(redis_client, incident_id)
        qa_result = await read_qa_result(redis_client, incident_id)
        pr_result = await read_pr_result(redis_client, incident_id)

        yield {
            "event": "snapshot",
            "data": json.dumps(
                {
                    "incident_id": incident_id,
                    "status": status_val,
                    "crash_report": report.model_dump(mode="json") if report else None,
                    "qa_result": qa_result.model_dump(mode="json") if qa_result else None,
                    "pr_result": pr_result.model_dump(mode="json") if pr_result else None,
                }
            ),
        }

        # Live stream — forward agent progress events.
        pubsub_client = aioredis.from_url(redis_url, decode_responses=True)
        try:
            async for event in subscribe_ui_events(pubsub_client, incident_id):
                if await request.is_disconnected():
                    break
                yield {"event": "progress", "data": json.dumps(event)}
        finally:
            await pubsub_client.aclose()

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Repo configuration API
# ---------------------------------------------------------------------------

class AddRepoBody(BaseModel):
    """Request body for POST /api/repos."""
    repo: str           # "owner/name"
    base_branch: str = "main"
    language: str = "python"


@app.get("/api/repos", tags=["repos"])
async def list_repos(request: Request, current_user: dict = Depends(get_current_user)):
    """
    List all repos the calling user has configured.

    Returns repos in the order they were added.
    """
    repos = await read_user_repos(request.app.state.redis, current_user["sub"])
    return {"repos": [r.model_dump(mode="json") for r in repos]}


@app.post("/api/repos", tags=["repos"], status_code=201)
async def add_repo(body: AddRepoBody, request: Request, current_user: dict = Depends(get_current_user)):
    """
    Add a repo to the calling user's Helix configuration.

    Returns 409 if the repo is already configured.
    The repo string must be in "owner/name" format, e.g. "acme/backend".
    """
    if "/" not in body.repo or body.repo.count("/") != 1:
        raise HTTPException(status_code=400, detail="repo must be in 'owner/name' format")

    user_id = current_user["sub"]
    repos = await read_user_repos(request.app.state.redis, user_id)

    if any(r.repo == body.repo for r in repos):
        raise HTTPException(status_code=409, detail=f"'{body.repo}' is already configured")

    new_repo = RepoConfig(repo=body.repo, base_branch=body.base_branch, language=body.language)
    repos.append(new_repo)
    await write_user_repos(request.app.state.redis, user_id, repos)
    return new_repo.model_dump(mode="json")


@app.delete("/api/repos/{owner}/{name}", tags=["repos"])
async def remove_repo(owner: str, name: str, request: Request, current_user: dict = Depends(get_current_user)):
    """
    Remove a repo from the calling user's Helix configuration.

    Returns 404 if the repo is not configured.
    """
    repo_slug = f"{owner}/{name}"
    user_id = current_user["sub"]
    repos = await read_user_repos(request.app.state.redis, user_id)
    updated = [r for r in repos if r.repo != repo_slug]

    if len(updated) == len(repos):
        raise HTTPException(status_code=404, detail=f"'{repo_slug}' is not configured")

    await write_user_repos(request.app.state.redis, user_id, updated)
    return {"removed": repo_slug}


# ---------------------------------------------------------------------------
# GitHub App — installation callback and repo listing
# ---------------------------------------------------------------------------

@app.get("/api/github/callback", tags=["github"])
async def github_app_callback(
    request: Request,
    installation_id: Optional[str] = None,
    setup_action: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """
    GitHub App installation callback.

    GitHub redirects here after a user installs or updates the Helix GitHub App.
    Stores the installation_id linked to the user's Auth0 sub in Postgres, then
    redirects back to the project wizard in the dashboard.

    Query parameters (set by GitHub):
        installation_id  — numeric installation ID
        setup_action     — "install" or "update"
    """
    if not installation_id:
        raise HTTPException(status_code=400, detail="Missing installation_id")

    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Database not configured")

    user = current_user
    async with get_db() as db:
        await upsert_user(
            db,
            sub=user.get("sub", ""),
            name=user.get("name", ""),
            email=user.get("email", "") or "",
            picture=user.get("picture", "") or "",
        )
        await upsert_github_installation(db, installation_id=installation_id, owner_sub=user["sub"])

    logger.info(
        "github app installation stored",
        extra={"installation_id": installation_id, "sub": user.get("sub"), "setup_action": setup_action},
    )
    # Redirect back to the wizard with the installation_id so React can pick it up.
    return RedirectResponse(url=f"/app/projects/new?installation_id={installation_id}")


@app.post("/api/github/installations", tags=["github"])
async def register_github_installation(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    Manually register a GitHub App installation for the current user.

    Used when the user has already installed the GitHub App but the automatic
    callback was not reached (e.g. Setup URL not configured at install time).
    The frontend sends the installation_id and this endpoint stores it.

    Body:
        installation_id  — numeric GitHub App installation ID
    """
    installation_id = str(body.get("installation_id", "")).strip()
    if not installation_id:
        raise HTTPException(status_code=400, detail="installation_id is required")

    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Database not configured")

    user = current_user
    async with get_db() as db:
        await upsert_user(
            db,
            sub=user.get("sub", ""),
            name=user.get("name", ""),
            email=user.get("email", "") or "",
            picture=user.get("picture", "") or "",
        )
        await upsert_github_installation(db, installation_id=installation_id, owner_sub=user["sub"])

    logger.info(
        "github app installation registered manually",
        extra={"installation_id": installation_id, "sub": user.get("sub")},
    )
    return {"installation_id": installation_id, "status": "registered"}


@app.get("/api/github/repos", tags=["github"])
async def list_github_repos(request: Request, current_user: dict = Depends(get_current_user)):
    """
    List all repositories accessible via the user's GitHub App installation.

    Used by the project wizard repo picker dropdown.
    Returns 404 if the user has not installed the GitHub App yet.
    """
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Database not configured")

    async with get_db() as db:
        installation = await get_installation_for_user(db, current_user["sub"])
        if not installation:
            raise HTTPException(
                status_code=404,
                detail="GitHub App not installed. Visit the install URL first.",
            )
        repos = await list_installation_repos(installation["installation_id"], db)

    return {
        "installation_id": installation["installation_id"],
        "install_url": build_install_url(),
        "repos": repos,
    }


@app.get("/api/github/install-url", tags=["github"])
async def get_github_install_url():
    """Return the GitHub App installation URL for the Connect GitHub button."""
    try:
        return {"install_url": build_install_url()}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Project API — Postgres-backed CRUD
# ---------------------------------------------------------------------------

# Sentinel value returned (and accepted) in place of real secret values.
_SETTINGS_MASK = "***"

_SECRET_FIELDS = {
    "anthropic_api_key",
    "sentry_webhook_secret",
    "rollbar_access_token",
    "slack_bot_token",
    "slack_signing_secret",
    "sendgrid_api_key",
}


def _mask_row(row: dict) -> dict:
    """Return a project row dict with secret settings values replaced by '***'."""
    masked = dict(row)
    for field in _SECRET_FIELDS:
        if masked.get(field):
            masked[field] = _SETTINGS_MASK
    return masked


def _parse_repo_slug(repo_input: str) -> str:
    """
    Normalise a repo input to 'owner/name' format.

    Accepts HTTPS URLs, SSH URLs, and plain owner/name slugs.
    Raises ValueError if the result is not in 'owner/name' format.
    """
    s = repo_input.strip().rstrip("/")
    if s.startswith("git@"):
        s = s.split(":", 1)[-1]
    if "github.com" in s:
        idx = s.find("github.com")
        s = s[idx + len("github.com"):].lstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    if s.count("/") != 1:
        raise ValueError(f"Could not parse '{repo_input}' as owner/name")
    return s


def _public_base_url(request: Request) -> str:
    """Return the public base URL for this deployment."""
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("PUBLIC_DOMAIN")
    if domain:
        return f"https://{domain}"
    return str(request.base_url).rstrip("/")


class CreateProjectBody(BaseModel):
    """Request body for POST /api/projects (wizard final step)."""
    name: str
    repo: str                               # GitHub URL or owner/name
    base_branch: str = "main"
    language: str = "python"
    github_installation_id: Optional[str] = None
    # Settings submitted in the wizard
    anthropic_api_key: Optional[str] = None
    sentry_webhook_secret: Optional[str] = None
    rollbar_access_token: Optional[str] = None
    slack_bot_token: Optional[str] = None
    slack_signing_secret: Optional[str] = None
    slack_approval_channel: Optional[str] = None
    sendgrid_api_key: Optional[str] = None
    smtp_host: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[str] = None
    alert_sources: list[str] = ["sentry", "rollbar"]


class UpdateProjectSettingsBody(BaseModel):
    """Request body for PUT /api/projects/{project_id}/settings."""
    anthropic_api_key: Optional[str] = None
    sentry_webhook_secret: Optional[str] = None
    rollbar_access_token: Optional[str] = None
    slack_bot_token: Optional[str] = None
    slack_signing_secret: Optional[str] = None
    slack_approval_channel: Optional[str] = None
    sendgrid_api_key: Optional[str] = None
    smtp_host: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[str] = None


def _require_db() -> None:
    """Raise 503 if DATABASE_URL is not set."""
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Database not configured — set DATABASE_URL")


@app.get("/api/projects", tags=["projects"])
async def list_projects(request: Request, current_user: dict = Depends(get_current_user)):
    """
    List all projects for the calling user (from Postgres).

    Secret settings values are masked — each non-empty secret is returned as
    '***' so the UI can show "already set" state without exposing credentials.
    """
    _require_db()
    async with get_db() as db:
        rows = await db_list_projects(db, current_user["sub"])
    return {"projects": [_mask_row(r) for r in rows]}


@app.post("/api/projects", tags=["projects"], status_code=201)
async def create_project(
    body: CreateProjectBody,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new project (wizard final step).

    Accepts all project details and settings in one call — no orphaned records
    from abandoned wizards.  Returns the project with webhook URLs.
    """
    _require_db()
    try:
        repo_slug = _parse_repo_slug(body.repo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    project_id = str(uuid.uuid4())
    user = current_user

    async with get_db() as db:
        await upsert_user(
            db,
            sub=user.get("sub", ""),
            name=user.get("name", ""),
            email=user.get("email", "") or "",
            picture=user.get("picture", "") or "",
        )
        await insert_project(
            db,
            project_id=project_id,
            owner_sub=user["sub"],
            name=body.name,
            repo=repo_slug,
            base_branch=body.base_branch,
            language=body.language,
            github_installation_id=body.github_installation_id,
        )
        settings = {
            "anthropic_api_key": body.anthropic_api_key,
            "sentry_webhook_secret": body.sentry_webhook_secret,
            "rollbar_access_token": body.rollbar_access_token,
            "slack_bot_token": body.slack_bot_token,
            "slack_signing_secret": body.slack_signing_secret,
            "slack_approval_channel": body.slack_approval_channel,
            "sendgrid_api_key": body.sendgrid_api_key,
            "smtp_host": body.smtp_host,
            "email_from": body.email_from,
            "email_to": body.email_to,
            "alert_sources": json.dumps(body.alert_sources),
        }
        await upsert_project_settings(db, project_id, settings)
        row = await get_project(db, project_id)

    base = _public_base_url(request)
    result = _mask_row(dict(row))
    result["webhook_urls"] = {
        "sentry": f"{base}/webhook/sentry/{project_id}",
        "rollbar": f"{base}/webhook/rollbar/{project_id}",
    }
    logger.info("project created", extra={"project_id": project_id, "repo": repo_slug, "sub": user.get("sub")})
    return result


@app.put("/api/projects/{project_id}/settings", tags=["projects"])
async def update_project_settings(
    project_id: str,
    body: UpdateProjectSettingsBody,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Update credential settings for a project.

    Fields set to '***' are left unchanged. Empty string clears a field.
    Returns the updated project with masked secret values.
    """
    _require_db()
    async with get_db() as db:
        row = await get_project(db, project_id)
        if not row or row.get("owner_sub") != current_user["sub"]:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

        patch = body.model_dump(exclude_none=False)
        settings: dict = {}
        for key, value in patch.items():
            if value == _SETTINGS_MASK:
                continue
            settings[key] = value if value else None

        await upsert_project_settings(db, project_id, settings)
        updated_row = await get_project(db, project_id)

    return _mask_row(dict(updated_row))


@app.delete("/api/projects/{project_id}", tags=["projects"])
async def delete_project(
    project_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Delete a project and its settings.

    Returns 404 if the project does not exist or belongs to another user.
    """
    _require_db()
    async with get_db() as db:
        deleted = await db_delete_project(db, project_id, current_user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    logger.info("project deleted", extra={"project_id": project_id, "sub": current_user.get("sub")})
    return {"deleted": project_id}


@app.get("/api/projects/{project_id}/webhook-urls", tags=["projects"])
async def get_webhook_urls(
    project_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Return the webhook URLs for a project.

    Used by the wizard to display copy-paste URLs after project creation.
    """
    _require_db()
    async with get_db() as db:
        row = await get_project(db, project_id)
    if not row or row.get("owner_sub") != current_user["sub"]:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    base = _public_base_url(request)
    return {
        "project_id": project_id,
        "sentry": f"{base}/webhook/sentry/{project_id}",
        "rollbar": f"{base}/webhook/rollbar/{project_id}",
    }


@app.get("/api/me", tags=["auth"])
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    Return the calling user's identity from their Auth0 JWT.

    Used by the frontend to display the logged-in user's name and avatar.
    Returns a synthetic demo user when auth is disabled.
    """
    return {
        "sub": current_user.get("sub"),
        "name": current_user.get("name"),
        "email": current_user.get("email"),
        "picture": current_user.get("picture"),
    }


# ---------------------------------------------------------------------------
# Landing page — serve index.html at the root
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_landing():
    """
    Serve the static marketing/landing page at the root URL.

    The page contains a Sign In CTA that routes visitors to /app.
    """
    if _LANDING_PAGE.exists():
        return FileResponse(str(_LANDING_PAGE))
    return {"error": "Landing page not found"}


# ---------------------------------------------------------------------------
# Dashboard SPA — serve the built React app for all /app/* routes
# ---------------------------------------------------------------------------

@app.get("/app", include_in_schema=False)
async def serve_dashboard_root():
    """Redirect the bare /app path to the SPA index."""
    index = _DASHBOARD_DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"error": "Dashboard not built. Run: cd dashboard && npm run build"}


@app.get("/app/{path:path}", include_in_schema=False)
async def serve_dashboard(path: str):
    """
    Serve the React SPA for all /app/* routes.

    Asset requests (JS, CSS, images) are served directly from dashboard/dist/.
    All other paths return index.html so React Router handles client-side routing.
    """
    # Try to serve the file directly first (assets: JS, CSS, images, fonts).
    asset = _DASHBOARD_DIST / path
    if asset.is_file():
        return FileResponse(str(asset))

    # Fall back to SPA index for all other paths (React Router handles them).
    index = _DASHBOARD_DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))

    return {"error": "Dashboard not built. Run: cd dashboard && npm run build"}
