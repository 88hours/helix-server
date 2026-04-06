"""
Crash Handler Agent — FastAPI entry point.

Exposes three webhook endpoints plus the streaming dashboard API:

  Webhooks (no auth — verified via payload signature / access token):
    POST /webhook/rollbar  — verifies the Rollbar access token, parses the payload, delegates to agent.py.
    POST /webhook/sentry   — verifies HMAC-SHA256 signature, parses the payload, delegates to agent.py.
    POST /slack/actions    — receives Slack button interactions (Approve / Reject PR).
                             Verifies the Slack signing secret, then merges or rejects the PR.
                             Only active when SLACK_SIGNING_SECRET is configured.

  Dashboard API (requires Auth0 JWT when AUTH0_DOMAIN is set):
    GET  /api/incidents              — list all known incidents (reads Redis state).
    GET  /api/incidents/{id}         — full state for one incident (crash report, QA result, PR).
    GET  /api/stream/{id}            — Server-Sent Events stream of live agent progress.
    GET  /api/repos                  — list the calling user's configured repos.
    POST /api/repos                  — add a repo to the calling user's config.
    DELETE /api/repos/{owner}/{name} — remove a repo from the calling user's config.

  Dashboard SPA:
    GET /app  and  GET /app/*       — serve the built React frontend from dashboard/dist/.

Run with:
    uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port 8000
"""

import json
import logging
import os
import urllib.parse
from pathlib import Path

import redis.asyncio as aioredis
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agents.crash_handler.agent import handle
from core.auth import get_current_user
from core.config import get_github_config, get_redis_url, get_rollbar_config, get_sentry_config, get_slack_config, is_demo_mode
from core.models import RepoConfig
from core.state import read_crash_report, read_pr_result, read_qa_result, read_status, read_user_repos, write_status, write_user_repos
from core.ui_events import subscribe_ui_events
from integrations import rollbar as rollbar_integration
from integrations import sentry as sentry_integration
from integrations import slack as slack_integration
from integrations.github import merge_pull_request

# Path to the built React dashboard (populated by: cd dashboard && npm run build).
_DASHBOARD_DIST = Path(__file__).parent.parent.parent / "dashboard" / "dist"

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the Redis client on startup and close it on shutdown."""
    redis_url = get_redis_url()
    logger.info("=== Crash Handler starting ===")
    logger.info("demo mode: %s", os.environ.get("HELIX_DEMO", "not set"))
    logger.info("crash handler connecting to redis", extra={"redis_url": redis_url})
    app.state.redis = aioredis.from_url(redis_url, decode_responses=False)
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("PUBLIC_DOMAIN") or "localhost:8000"
    logger.info(
        "crash handler started — redis connected, listening on %s/webhook/rollbar and %s/webhook/sentry",
        domain,
        domain,
    )
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


@app.post("/webhook/rollbar", status_code=status.HTTP_202_ACCEPTED)
async def rollbar_webhook(request: Request):
    """
    Receive a Rollbar item-alert webhook.

    Verifies the access token embedded in the payload, parses it, and
    delegates to the Crash Handler Agent.  Returns 202 immediately —
    processing is async (the agent publishes a Redis event; the QA Agent
    picks it up).

    Rollbar embeds the project read token at data.access_token in every
    webhook payload. This is compared against ROLLBAR_ACCESS_TOKEN.
    """
    body = await request.body()

    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {exc}",
        )

    # Rollbar sends a tokenless ping payload to verify the URL is reachable.
    # Acknowledge it immediately — there is nothing to process.
    if raw.get("event_name") == "test":
        logger.info("rollbar connectivity test received — acknowledged")
        return {"status": "ok"}

    if is_demo_mode():
        logger.warning("demo mode enabled — skipping rollbar access token verification")
    else:
        rollbar_cfg = get_rollbar_config()
        if not rollbar_integration.verify_token(raw, rollbar_cfg.access_token):
            logger.warning("rollbar webhook access token mismatch")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token",
            )

    crash_event = rollbar_integration.parse_event(raw)
    logger.debug(
        "rollbar webhook parsed",
        extra={"item_id": crash_event.item_id, "level": crash_event.level, "title": crash_event.title},
    )

    report = await handle(crash_event, request.app.state.redis)

    logger.info(
        "webhook accepted",
        extra={"incident_id": report.incident_id, "severity": report.severity.value},
    )
    return {"incident_id": report.incident_id, "status": "accepted"}


@app.post("/webhook/sentry", status_code=status.HTTP_202_ACCEPTED)
async def sentry_webhook(request: Request):
    """
    Receive a Sentry issue-alert webhook.

    Verifies the HMAC-SHA256 signature in the `sentry-hook-signature` header,
    parses the payload, and delegates to the Crash Handler Agent.

    Returns 202 immediately — the agent pipeline is fully async.
    """
    body = await request.body()
    signature = request.headers.get("sentry-hook-signature", "")

    logger.debug(
        "sentry webhook received — headers: %s",
        dict(request.headers),
    )
    logger.info(
        "sentry webhook received — signature=%r demo=%s body_preview=%r",
        signature,
        is_demo_mode(),
        body[:200],
    )

    if is_demo_mode():
        logger.warning("demo mode enabled — skipping sentry signature verification")
    else:
        sentry_cfg = get_sentry_config()
        if sentry_cfg.webhook_secret:
            if not sentry_integration.verify_signature(body, signature, sentry_cfg.webhook_secret):
                import hashlib
                import hmac as _hmac
                expected = _hmac.new(
                    sentry_cfg.webhook_secret.encode("utf-8"), body, hashlib.sha256
                ).hexdigest()
                logger.warning(
                    "sentry webhook signature verification failed — "
                    "received=%r expected=%r body_len=%d",
                    signature,
                    expected,
                    len(body),
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature",
                )
        else:
            logger.warning("SENTRY_WEBHOOK_SECRET not configured — skipping signature check")

    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {exc}",
        )

    # Sentry sends a ping on first save of the webhook URL.
    if raw.get("action") == "ping" or raw.get("type") == "ping":
        logger.info("sentry connectivity ping received — acknowledged")
        return {"status": "ok"}

    crash_event = sentry_integration.parse_event(raw)
    logger.debug(
        "sentry webhook parsed",
        extra={"item_id": crash_event.item_id, "level": crash_event.level, "title": crash_event.title},
    )

    report = await handle(crash_event, request.app.state.redis)

    logger.info(
        "sentry webhook accepted",
        extra={"incident_id": report.incident_id, "severity": report.severity.value},
    )
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
