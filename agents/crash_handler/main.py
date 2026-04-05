"""
Crash Handler Agent — FastAPI entry point.

Exposes a single POST /webhook/rollbar endpoint that:
  1. Verifies the Rollbar access token (data.access_token in the payload).
  2. Parses the raw payload into a RollbarEvent.
  3. Hands off to the Crash Handler Agent logic (agent.py).

Run with:
    uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port 8000
"""

import json
import logging
import os

import redis.asyncio as aioredis
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status

from agents.crash_handler.agent import handle
from core.config import get_redis_url, get_rollbar_config, get_sentry_config
from integrations import rollbar as rollbar_integration
from integrations import sentry as sentry_integration

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the Redis client on startup and close it on shutdown."""
    redis_url = get_redis_url()
    logger.info("crash handler connecting to redis", extra={"redis_url": redis_url})
    app.state.redis = aioredis.from_url(redis_url, decode_responses=False)
    logger.info("crash handler started — redis connected, listening on :8000/webhook/rollbar")
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

    sentry_cfg = get_sentry_config()
    if sentry_cfg.webhook_secret:
        if not sentry_integration.verify_signature(body, signature, sentry_cfg.webhook_secret):
            logger.warning("sentry webhook signature verification failed")
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
