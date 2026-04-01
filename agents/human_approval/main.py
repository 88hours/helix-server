"""
Human Approval Agent — FastAPI entry point.

Receives Slack interaction payloads (button clicks from the approval message)
and dispatches to handle_approve() or handle_reject().

Slack requires a response within 3 seconds. The actual work (merging the PR,
sending email) is handed off to a FastAPI BackgroundTask so the endpoint
returns 200 immediately.

Interactivity Request URL to configure in your Slack app settings:
    http://<host>:8001/slack/interactions

Run with:
    uvicorn agents.human_approval.main:app --host 0.0.0.0 --port 8001
"""

import json
import logging
import os
import urllib.parse
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from agents.human_approval.agent import handle_approve, handle_reject
from core.config import get_redis_url, get_slack_config
from integrations.slack import verify_signature

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Slack action IDs — must match the values set in integrations/slack.py.
_ACTION_APPROVE = "helix_approve_pr"
_ACTION_REJECT = "helix_reject_pr"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the Redis client on startup and close it on shutdown."""
    app.state.redis = aioredis.from_url(get_redis_url(), decode_responses=False)
    logger.info("human approval agent started — redis connected")
    yield
    await app.state.redis.aclose()
    logger.info("human approval agent shut down")


app = FastAPI(
    title="Helix — Human Approval",
    description="Receives Slack button interactions and merges or rejects Helix PRs.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz():
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/slack/interactions", status_code=status.HTTP_200_OK)
async def slack_interactions(request: Request, background_tasks: BackgroundTasks):
    """
    Receive a Slack block_actions interaction payload.

    Slack sends a POST with Content-Type: application/x-www-form-urlencoded.
    The body contains a single field named "payload" whose value is a
    URL-encoded JSON string.

    Verification:
        The X-Slack-Signature and X-Slack-Request-Timestamp headers are
        checked against the app's Signing Secret before any processing.

    Response:
        Returns 200 immediately with a brief status message.
        The actual work (merging PR, notifications) runs in the background.
    """
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    slack_config = get_slack_config()
    if not verify_signature(body, timestamp, signature, slack_config.signing_secret):
        logger.warning("slack interaction signature verification failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Slack signature",
        )

    # Slack sends application/x-www-form-urlencoded with a "payload" field.
    try:
        form = urllib.parse.parse_qs(body.decode("utf-8"))
        raw_payload = form.get("payload", [None])[0]
        if not raw_payload:
            raise ValueError("missing payload field")
        payload = json.loads(raw_payload)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse Slack payload: {exc}",
        )

    if payload.get("type") != "block_actions":
        # Ignore non-action payloads (e.g. shortcut, view_submission).
        return JSONResponse(content={})

    actions = payload.get("actions", [])
    if not actions:
        return JSONResponse(content={})

    action = actions[0]
    action_id = action.get("action_id", "")
    incident_id = action.get("value", "")
    user = payload.get("user", {})
    username = user.get("username") or user.get("name") or user.get("id", "unknown")

    if not incident_id:
        logger.warning("slack interaction missing incident_id in action value")
        return JSONResponse(content={"text": "Missing incident ID."})

    redis_client = request.app.state.redis

    if action_id == _ACTION_APPROVE:
        background_tasks.add_task(handle_approve, incident_id, username, redis_client)
        logger.info(
            "approval action queued",
            extra={"incident_id": incident_id, "approved_by": username},
        )
        return JSONResponse(content={"text": f"Merging PR for incident `{incident_id}`..."})

    if action_id == _ACTION_REJECT:
        background_tasks.add_task(handle_reject, incident_id, username, redis_client)
        logger.info(
            "rejection action queued",
            extra={"incident_id": incident_id, "rejected_by": username},
        )
        return JSONResponse(content={"text": f"PR for incident `{incident_id}` rejected."})

    logger.warning("unknown action_id received", extra={"action_id": action_id})
    return JSONResponse(content={})
