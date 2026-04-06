"""
UI event publishing for the Helix dashboard.

Publishes fine-grained agent progress updates to a per-incident Redis Pub/Sub
channel so the dashboard can stream live agent activity to the browser.

These events are ephemeral — Pub/Sub (not Streams) is intentional here.  If
the browser is not connected when an event fires, that event is lost; the
dashboard recovers by reading the persistent incident state from Redis when it
(re)connects.

Channel:  helix:ui:{incident_id}

Event schema (JSON-serialised):

    {
        "type":        "agent_start" | "agent_step" | "agent_done" | "status_changed",
        "agent":       "crash_handler" | "qa" | "dev" | "notifier",
        "message":     "Human-readable progress message",
        "incident_id": "uuid",
        "timestamp":   "ISO-8601 UTC",
    }
"""

import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "helix:ui"


def _channel(incident_id: str) -> str:
    """Build the Pub/Sub channel name for an incident's UI events."""
    return f"{_CHANNEL_PREFIX}:{incident_id}"


async def publish_ui_event(
    client: redis.Redis,
    incident_id: str,
    event_type: str,
    agent: str,
    message: str,
) -> None:
    """
    Publish a UI progress event for an incident.

    Called by agents at key moments (start, each major step, done) to feed
    the live dashboard stream.  Fire-and-forget — a failure here must never
    block the agent pipeline.

    Args:
        client:      Async Redis client.
        incident_id: The incident this event belongs to.
        event_type:  "agent_start", "agent_step", "agent_done", or "status_changed".
        agent:       Agent name, e.g. "crash_handler", "qa", "dev".
        message:     Human-readable progress message shown in the dashboard.
    """
    channel = _channel(incident_id)
    payload = json.dumps(
        {
            "type": event_type,
            "agent": agent,
            "message": message,
            "incident_id": incident_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    try:
        await client.publish(channel, payload)
        logger.debug(
            "ui event published",
            extra={
                "incident_id": incident_id,
                "event_type": event_type,
                "agent": agent,
            },
        )
    except Exception as exc:  # noqa: BLE001
        # Never let a UI event failure crash the agent.
        logger.warning(
            "ui event publish failed — continuing",
            extra={"incident_id": incident_id, "error": str(exc)},
        )


async def subscribe_ui_events(
    client: redis.Redis,
    incident_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Subscribe to UI events for an incident and yield parsed event dicts.

    Used by the SSE endpoint in the crash handler to stream agent progress to
    the browser.  Runs indefinitely until the caller breaks the loop or the
    client disconnects.

    Args:
        client:      Async Redis client (dedicated connection — do not share
                     a Pub/Sub client with other commands).
        incident_id: The incident to subscribe to.

    Yields:
        Parsed event dicts with keys: type, agent, message, incident_id, timestamp.
    """
    channel = _channel(incident_id)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    logger.info(
        "ui event stream opened",
        extra={"incident_id": incident_id, "channel": channel},
    )

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                yield json.loads(message["data"])
            except (json.JSONDecodeError, KeyError) as exc:
                logger.error(
                    "malformed ui event — skipping",
                    extra={"channel": channel, "error": str(exc)},
                )
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        logger.info(
            "ui event stream closed",
            extra={"incident_id": incident_id},
        )
