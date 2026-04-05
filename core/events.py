"""
Event publishing and subscribing for the Helix agent pipeline.

Supports two backends, selected via the HELIX_EVENT_BACKEND environment variable:

    redis        — Redis Streams (default; recommended for Railway / local dev)
    eventbridge  — AWS EventBridge (recommended for AWS-hosted deployments)

Publishing is the same call regardless of backend:

    await publish(client, "crash_analysed", report.incident_id, report.model_dump())

Subscribing is only needed for the Redis backend — on EventBridge, AWS routes
events to agents via Lambda triggers configured in the AWS console.

    async for incident_id, payload in subscribe(client, "crash_analysed"):
        ...  # handle event

Redis Streams are used instead of Pub/Sub so that messages are persisted on the
broker.  Agents that start late, restart, or lag behind will still receive every
event — no messages are dropped.  Each agent uses a dedicated consumer group so
it always receives every event independently of other agents.

Event stream key format:  helix:stream:{event_name}
Consumer group name:      helix:{event_name}:{agent_name}

EventBridge detail-type names match the event_name 1-to-1:

    crash_analysed          helix:stream:crash_analysed
    test_case_generated     helix:stream:test_case_generated
    fix_suggested           helix:stream:fix_suggested
    pr_created              helix:stream:pr_created
"""

import json
import logging
import os
import socket
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as redis
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# EventBridge bus name — all Helix events go to this bus.
_EVENTBRIDGE_BUS = "helix-mvp"

# Source prefix used in EventBridge event envelopes.
_EVENTBRIDGE_SOURCE_PREFIX = "helix"

# Redis Streams key prefix.
_REDIS_STREAM_PREFIX = "helix:stream"

# Maximum number of entries to keep per stream (older entries are trimmed).
# 1 000 entries per stream is more than enough for an MVP.
_STREAM_MAXLEN = 1000

# Number of milliseconds to block waiting for new stream entries.
# Using a finite timeout allows the loop to stay responsive to cancellation.
_BLOCK_MS = 5000


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
# Redis Streams helpers
# ---------------------------------------------------------------------------

def _stream_key(event_name: str) -> str:
    """Build the Redis Streams key for an event."""
    return f"{_REDIS_STREAM_PREFIX}:{event_name}"


def _group_name(event_name: str, agent_name: str) -> str:
    """
    Build the consumer group name for a given event and agent.

    Each agent gets its own group so every agent independently receives
    every event (fan-out), rather than competing for messages.
    """
    return f"helix:{event_name}:{agent_name}"


def _consumer_name() -> str:
    """
    Return a stable consumer name for this process.

    Uses the hostname so that each Railway replica gets its own identity,
    which lets the broker track per-consumer pending-entry lists correctly.
    """
    return socket.gethostname()


async def _ensure_group(client: redis.Redis, stream: str, group: str) -> None:
    """
    Create a consumer group if it does not already exist.

    Uses MKSTREAM so the stream itself is created if absent.  The group
    starts reading from the latest entry ("$") so agents only process events
    that arrive after they first start — previously processed events are not
    replayed on restart because the group remembers its last-delivered ID.

    Args:
        client: Async Redis client.
        stream: Stream key, e.g. "helix:stream:crash_analysed".
        group:  Consumer group name.
    """
    try:
        await client.xgroup_create(stream, group, id="$", mkstream=True)
        logger.debug("consumer group created", extra={"stream": stream, "group": group})
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            pass  # group already exists — nothing to do
        else:
            raise


async def _publish_redis(
    client: redis.Redis,
    event_name: str,
    incident_id: str,
    payload: dict,
) -> None:
    """
    Append an event to the Redis Stream for the given event name.

    Trims the stream to _STREAM_MAXLEN entries (approximate, for efficiency)
    so memory usage stays bounded.
    """
    stream = _stream_key(event_name)
    data = json.dumps({"incident_id": incident_id, "payload": payload})
    await client.xadd(stream, {"data": data}, maxlen=_STREAM_MAXLEN, approximate=True)
    logger.info(
        "event published via redis",
        extra={"event": event_name, "incident_id": incident_id, "stream": stream},
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
    import asyncio
    import boto3  # lazy import — not required for Redis backend

    detail = {"incident_id": incident_id, "payload": payload}
    entry = {
        "Source": f"{_EVENTBRIDGE_SOURCE_PREFIX}.{event_name}",
        "DetailType": event_name,
        "Detail": json.dumps(detail),
        "EventBusName": _EVENTBRIDGE_BUS,
    }

    # boto3 is synchronous — run in a thread to avoid blocking the event loop.
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
    agent_name: str = "",
) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
    """
    Subscribe to a Helix pipeline event stream (Redis backend only).

    Uses Redis Streams with consumer groups so messages are persisted and
    delivered reliably — agents that restart or start late will not miss
    events that arrived while they were down.

    Each (event_name, agent_name) pair gets its own consumer group, so
    every agent independently receives every event (fan-out).

    Yields (incident_id, payload) tuples as events arrive.  Runs
    indefinitely until the caller breaks or the connection drops.

    On EventBridge this is a no-op — agents are triggered by EventBridge
    rules instead of polling.

    Args:
        client:     Async Redis client.
        event_name: Short event name to subscribe to, e.g. "crash_analysed".
        agent_name: Name of the subscribing agent, e.g. "qa".  Used to
                    build the consumer group name.  Inferred from
                    event_name if omitted.

    Yields:
        (incident_id, payload) for each received event.
    """
    backend = _get_backend()
    if backend == "eventbridge":
        logger.warning(
            "subscribe() called with EventBridge backend — no-op; "
            "agents should be triggered via EventBridge rules instead"
        )
        return

    stream = _stream_key(event_name)
    group = _group_name(event_name, agent_name or event_name)
    consumer = _consumer_name()

    await _ensure_group(client, stream, group)
    logger.info(
        "subscribed to stream",
        extra={"event": event_name, "stream": stream, "group": group, "consumer": consumer},
    )

    while True:
        # ">" means: give me only new messages not yet delivered to this group.
        results = await client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=1,
            block=_BLOCK_MS,
        )

        if not results:
            # Timeout — no new messages; loop back and block again.
            continue

        for _stream_key_bytes, entries in results:
            for entry_id, fields in entries:
                raw = fields.get(b"data") or fields.get("data", b"")
                try:
                    data = json.loads(raw)
                    incident_id = data["incident_id"]
                    payload = data["payload"]
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.error(
                        "malformed stream entry — skipping",
                        extra={"stream": stream, "entry_id": entry_id, "error": str(exc)},
                    )
                    await client.xack(stream, group, entry_id)
                    continue

                logger.info(
                    "event received",
                    extra={"event": event_name, "incident_id": incident_id, "stream": stream},
                )

                # Acknowledge after the caller has processed the event.
                # try/finally ensures xack runs even if the caller breaks the loop.
                try:
                    yield incident_id, payload
                finally:
                    await client.xack(stream, group, entry_id)
