"""
Event publishing and subscribing for the Helix agent pipeline.

Supports two backends, selected via the HELIX_EVENT_BACKEND environment variable:

    redis        — Redis Pub/Sub (default; recommended for Railway / local dev)
    eventbridge  — AWS EventBridge (recommended for AWS-hosted deployments)

Publishing is the same call regardless of backend:

    await publish(client, "crash_analysed", report.incident_id, report.model_dump())

Subscribing is only needed for the Redis backend — on EventBridge, AWS routes
events to agents via Lambda triggers configured in the AWS console.

    async for incident_id, payload in subscribe(client, "crash_analysed"):
        ...  # handle event

Event channel / detail-type names map 1-to-1:

    crash_analysed          helix:events:crash_analysed
    test_case_generated     helix:events:test_case_generated
    fix_suggested           helix:events:fix_suggested
    pr_created              helix:events:pr_created
    quality_approved        helix:events:quality_approved
    quality_rejected        helix:events:quality_rejected
"""

import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# EventBridge bus name — all Helix events go to this bus.
_EVENTBRIDGE_BUS = "helix-mvp"

# Source prefix used in EventBridge event envelopes.
_EVENTBRIDGE_SOURCE_PREFIX = "helix"

# Redis Pub/Sub channel prefix.
_REDIS_CHANNEL_PREFIX = "helix:events"


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def _get_backend() -> str:
    """
    Return the configured event backend.

    Reads HELIX_EVENT_BACKEND from the environment. Defaults to "redis".
    Valid values: "redis", "eventbridge".
    """
    backend = os.environ.get("HELIX_EVENT_BACKEND", "redis").lower()
    if backend not in ("redis", "eventbridge"):
        raise ValueError(
            f"Unknown HELIX_EVENT_BACKEND '{backend}'. Must be 'redis' or 'eventbridge'."
        )
    return backend


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

def _redis_channel(event_name: str) -> str:
    """Build the Redis Pub/Sub channel name for an event."""
    return f"{_REDIS_CHANNEL_PREFIX}:{event_name}"


async def _publish_redis(client: redis.Redis, event_name: str, incident_id: str, payload: dict) -> None:
    """Publish an event to a Redis Pub/Sub channel."""
    channel = _redis_channel(event_name)
    message = json.dumps({"incident_id": incident_id, "payload": payload})
    await client.publish(channel, message)
    logger.info(
        "event published via redis",
        extra={"event": event_name, "incident_id": incident_id, "channel": channel},
    )


# ---------------------------------------------------------------------------
# EventBridge helpers
# ---------------------------------------------------------------------------

async def _publish_eventbridge(event_name: str, incident_id: str, payload: dict) -> None:
    """
    Publish an event to the AWS EventBridge helix-mvp bus.

    Uses boto3 (imported lazily so Redis-only deployments don't need AWS SDK).
    Requires AWS credentials available in the environment (IAM role or env vars).
    """
    import boto3  # lazy import — not required for Redis backend

    detail = {"incident_id": incident_id, "payload": payload}
    entry = {
        "Source": f"{_EVENTBRIDGE_SOURCE_PREFIX}.{event_name}",
        "DetailType": event_name,
        "Detail": json.dumps(detail),
        "EventBusName": _EVENTBRIDGE_BUS,
    }

    # boto3 is synchronous — run in a thread to avoid blocking the event loop.
    import asyncio
    eb = boto3.client("events")
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(None, lambda: eb.put_events(Entries=[entry]))

    failed = response.get("FailedEntryCount", 0)
    if failed:
        raise RuntimeError(
            f"EventBridge put_events failed for event '{event_name}': {response['Entries']}"
        )

    logger.info(
        "event published via eventbridge",
        extra={"event": event_name, "incident_id": incident_id, "bus": _EVENTBRIDGE_BUS},
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def publish(
    client: redis.Redis,
    event_name: str,
    incident_id: str,
    payload: dict,
) -> None:
    """
    Publish a Helix pipeline event using the configured backend.

    Args:
        client:      Async Redis client (used for the Redis backend;
                     ignored for EventBridge but still required so call
                     sites are backend-agnostic).
        event_name:  Short event name, e.g. "crash_analysed".
                     Must match a key in CLAUDE.md's event channel list.
        incident_id: The incident this event belongs to.
        payload:     Event data — typically model.model_dump() for the
                     output model of the publishing agent.
    """
    backend = _get_backend()
    if backend == "redis":
        await _publish_redis(client, event_name, incident_id, payload)
    else:
        await _publish_eventbridge(event_name, incident_id, payload)


async def subscribe(
    client: redis.Redis,
    event_name: str,
) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
    """
    Subscribe to a Helix pipeline event channel (Redis backend only).

    Yields (incident_id, payload) tuples as events arrive. Runs indefinitely
    until the caller breaks or the connection drops.

    This function is a no-op on the EventBridge backend — agents hosted on
    AWS are triggered by EventBridge rules, not by polling a channel.

    Args:
        client:     Async Redis client.
        event_name: Short event name to subscribe to, e.g. "crash_analysed".

    Yields:
        (incident_id, payload) for each received event.

    Example:
        async for incident_id, payload in subscribe(client, "crash_analysed"):
            report = CrashReport.model_validate(payload)
            await handle(report)
    """
    backend = _get_backend()
    if backend == "eventbridge":
        logger.warning(
            "subscribe() called with EventBridge backend — no-op; "
            "agents should be triggered via EventBridge rules instead"
        )
        return

    channel = _redis_channel(event_name)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    logger.info("subscribed to channel", extra={"event": event_name, "channel": channel})

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue  # skip subscribe confirmation and other control messages

        try:
            data = json.loads(message["data"])
            incident_id = data["incident_id"]
            payload = data["payload"]
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(
                "malformed event message — skipping",
                extra={"channel": channel, "error": str(exc), "raw": message["data"]},
            )
            continue

        logger.info(
            "event received",
            extra={"event": event_name, "incident_id": incident_id, "channel": channel},
        )
        yield incident_id, payload
