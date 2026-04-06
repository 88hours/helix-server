"""
Crash Handler Agent — FastAPI entry point.

Exposes three endpoints:
  - POST /webhook/rollbar  — verifies the Rollbar access token, parses the payload, delegates to agent.py.
  - POST /webhook/sentry   — verifies HMAC-SHA256 signature, parses the payload, delegates to agent.py.
  - POST /slack/actions    — receives Slack button interactions (Approve / Reject PR).
                             Verifies the Slack signing secret, then merges or rejects the PR.
                             Only active when SLACK_SIGNING_SECRET is configured.

Run with:
    uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port 8000
"""

import json
import logging
import os
import urllib.parse

import redis.asyncio as aioredis
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status

from agents.crash_handler.agent import handle
from core.config import get_github_config, get_redis_url, get_rollbar_config, get_sentry_config, get_slack_config, is_demo_mode
from core.state import read_pr_result, write_status
from integrations import rollbar as rollbar_integration
from integrations import sentry as sentry_integration
from integrations import slack as slack_integration
from integrations.github import merge_pull_request

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
