"""Tests for core/ui_events.py"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.ui_events import (
    publish_ui_event,
    publish_tool_event,
    read_ui_events,
    subscribe_ui_events,
    _channel,
    _event_log_key,
)


INCIDENT_ID = "inc-test-001"


# ---------------------------------------------------------------------------
# Channel and key helpers
# ---------------------------------------------------------------------------

def test_channel_format():
    assert _channel(INCIDENT_ID) == f"helix:ui:{INCIDENT_ID}"


def test_event_log_key_format():
    assert _event_log_key(INCIDENT_ID) == f"helix:ui:{INCIDENT_ID}:events"


# ---------------------------------------------------------------------------
# publish_ui_event
# ---------------------------------------------------------------------------

async def test_publish_ui_event_writes_to_list_and_pubsub():
    client = AsyncMock()
    await publish_ui_event(client, INCIDENT_ID, "agent_start", "qa", "QA agent starting")

    client.rpush.assert_called_once()
    log_key = _event_log_key(INCIDENT_ID)
    assert client.rpush.call_args[0][0] == log_key

    client.expire.assert_called_once_with(log_key, 7 * 24 * 3600)
    client.publish.assert_called_once()
    assert client.publish.call_args[0][0] == _channel(INCIDENT_ID)


async def test_publish_ui_event_payload_fields():
    client = AsyncMock()
    await publish_ui_event(client, INCIDENT_ID, "agent_done", "dev", "Fix applied")

    raw_payload = client.rpush.call_args[0][1]
    payload = json.loads(raw_payload)

    assert payload["type"] == "agent_done"
    assert payload["agent"] == "dev"
    assert payload["message"] == "Fix applied"
    assert payload["incident_id"] == INCIDENT_ID
    assert "timestamp" in payload


async def test_publish_ui_event_does_not_raise_on_redis_error():
    client = AsyncMock()
    client.rpush.side_effect = Exception("Redis connection lost")

    # Must not raise — fire-and-forget.
    await publish_ui_event(client, INCIDENT_ID, "agent_step", "crash_handler", "Parsing crash")


# ---------------------------------------------------------------------------
# publish_tool_event
# ---------------------------------------------------------------------------

async def test_publish_tool_event_writes_correct_payload():
    client = AsyncMock()
    await publish_tool_event(
        client, INCIDENT_ID, "qa", "github", "create_issue", "success", "#42"
    )

    raw_payload = client.rpush.call_args[0][1]
    payload = json.loads(raw_payload)

    assert payload["type"] == "tool_call"
    assert payload["agent"] == "qa"
    assert payload["tool"] == "github"
    assert payload["action"] == "create_issue"
    assert payload["status"] == "success"
    assert payload["detail"] == "#42"
    assert payload["incident_id"] == INCIDENT_ID
    assert "timestamp" in payload


async def test_publish_tool_event_default_detail_is_empty():
    client = AsyncMock()
    await publish_tool_event(client, INCIDENT_ID, "dev", "git", "clone", "success")

    raw_payload = client.rpush.call_args[0][1]
    payload = json.loads(raw_payload)
    assert payload["detail"] == ""


async def test_publish_tool_event_does_not_raise_on_redis_error():
    client = AsyncMock()
    client.rpush.side_effect = ConnectionError("Redis down")

    await publish_tool_event(client, INCIDENT_ID, "dev", "llm", "complete", "failed")


async def test_publish_tool_event_publishes_to_correct_channel():
    client = AsyncMock()
    await publish_tool_event(client, INCIDENT_ID, "notifier", "slack", "post_message", "success")

    assert client.publish.call_args[0][0] == _channel(INCIDENT_ID)


# ---------------------------------------------------------------------------
# read_ui_events
# ---------------------------------------------------------------------------

async def test_read_ui_events_returns_parsed_events():
    event1 = {"type": "agent_start", "agent": "qa", "incident_id": INCIDENT_ID}
    event2 = {"type": "agent_done", "agent": "qa", "incident_id": INCIDENT_ID}

    client = AsyncMock()
    client.lrange.return_value = [json.dumps(event1), json.dumps(event2)]

    events = await read_ui_events(client, INCIDENT_ID)

    assert len(events) == 2
    assert events[0] == event1
    assert events[1] == event2
    client.lrange.assert_called_once_with(_event_log_key(INCIDENT_ID), 0, -1)


async def test_read_ui_events_returns_empty_list_when_none():
    client = AsyncMock()
    client.lrange.return_value = []

    events = await read_ui_events(client, INCIDENT_ID)
    assert events == []


async def test_read_ui_events_skips_malformed_entries():
    client = AsyncMock()
    client.lrange.return_value = [
        json.dumps({"type": "agent_start"}),
        b"not-valid-json{{",
        json.dumps({"type": "agent_done"}),
    ]

    events = await read_ui_events(client, INCIDENT_ID)
    assert len(events) == 2
    assert events[0]["type"] == "agent_start"
    assert events[1]["type"] == "agent_done"


# ---------------------------------------------------------------------------
# subscribe_ui_events
# ---------------------------------------------------------------------------

def _make_pubsub_client(fake_listen):
    """
    Build a mock Redis client whose .pubsub() returns a synchronous MagicMock
    with async subscribe/unsubscribe/aclose and the given async generator as listen.

    client.pubsub() is NOT awaited in the source — it's a regular method call —
    so we must use MagicMock (not AsyncMock) for pubsub() itself.
    """
    mock_pubsub = MagicMock()
    mock_pubsub.listen = fake_listen
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    client = MagicMock()
    client.pubsub.return_value = mock_pubsub
    return client, mock_pubsub


async def test_subscribe_ui_events_yields_parsed_events():
    event_payload = {"type": "agent_step", "agent": "dev", "incident_id": INCIDENT_ID}

    async def fake_listen():
        yield {"type": "subscribe", "data": None}   # ignored — not a "message"
        yield {"type": "message", "data": json.dumps(event_payload)}

    client, mock_pubsub = _make_pubsub_client(fake_listen)

    yielded = []
    async for event in subscribe_ui_events(client, INCIDENT_ID):
        yielded.append(event)
        break  # stop after first message

    assert len(yielded) == 1
    assert yielded[0] == event_payload
    mock_pubsub.subscribe.assert_called_once_with(_channel(INCIDENT_ID))


async def test_subscribe_ui_events_skips_malformed_messages():
    async def fake_listen():
        yield {"type": "message", "data": "not-valid-json{{"}
        yield {"type": "message", "data": json.dumps({"type": "agent_done"})}

    client, _ = _make_pubsub_client(fake_listen)

    yielded = []
    async for event in subscribe_ui_events(client, INCIDENT_ID):
        yielded.append(event)

    assert len(yielded) == 1
    assert yielded[0]["type"] == "agent_done"


async def test_subscribe_ui_events_unsubscribes_on_exit():
    async def fake_listen():
        yield {"type": "message", "data": json.dumps({"type": "agent_start"})}

    client, mock_pubsub = _make_pubsub_client(fake_listen)

    async for _ in subscribe_ui_events(client, INCIDENT_ID):
        pass

    mock_pubsub.unsubscribe.assert_called_once_with(_channel(INCIDENT_ID))
    mock_pubsub.aclose.assert_called_once()
