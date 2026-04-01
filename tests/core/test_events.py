"""Tests for core/events.py"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.events import publish, subscribe


@pytest.fixture
def redis():
    return AsyncMock()


# ---------------------------------------------------------------------------
# publish — redis backend
# ---------------------------------------------------------------------------

async def test_publish_redis(redis, monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "redis")
    await publish(redis, "crash_analysed", "inc-001", {"key": "value"})
    redis.publish.assert_awaited_once()
    channel, message = redis.publish.call_args[0]
    assert channel == "helix:events:crash_analysed"
    data = json.loads(message)
    assert data["incident_id"] == "inc-001"
    assert data["payload"] == {"key": "value"}


# ---------------------------------------------------------------------------
# publish — eventbridge backend
# ---------------------------------------------------------------------------

async def test_publish_eventbridge(redis, monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "eventbridge")
    mock_eb = MagicMock()
    mock_eb.put_events.return_value = {"FailedEntryCount": 0, "Entries": []}

    with patch("boto3.client", return_value=mock_eb):
        await publish(redis, "crash_analysed", "inc-001", {"key": "value"})

    mock_eb.put_events.assert_called_once()
    entry = mock_eb.put_events.call_args[1]["Entries"][0]
    assert entry["DetailType"] == "crash_analysed"
    assert entry["EventBusName"] == "helix-mvp"


async def test_publish_eventbridge_failure_raises(redis, monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "eventbridge")
    mock_eb = MagicMock()
    mock_eb.put_events.return_value = {
        "FailedEntryCount": 1,
        "Entries": [{"ErrorCode": "InternalFailure"}],
    }
    with patch("boto3.client", return_value=mock_eb):
        with pytest.raises(RuntimeError, match="EventBridge put_events failed"):
            await publish(redis, "crash_analysed", "inc-001", {})


# ---------------------------------------------------------------------------
# publish — invalid backend
# ---------------------------------------------------------------------------

async def test_publish_invalid_backend_raises(redis, monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "kafka")
    with pytest.raises(ValueError, match="Unknown HELIX_EVENT_BACKEND"):
        await publish(redis, "crash_analysed", "inc-001", {})


# ---------------------------------------------------------------------------
# subscribe — redis backend
# ---------------------------------------------------------------------------

async def test_subscribe_redis_yields_events(monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "redis")

    message = {
        "type": "message",
        "data": json.dumps({"incident_id": "inc-001", "payload": {"key": "val"}}),
    }
    control_message = {"type": "subscribe", "data": 1}

    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen.return_value = _async_iter([control_message, message])

    redis_client = AsyncMock()
    redis_client.pubsub = MagicMock(return_value=pubsub)

    results = []
    async for incident_id, payload in subscribe(redis_client, "crash_analysed"):
        results.append((incident_id, payload))
        break  # only consume one event

    assert results[0] == ("inc-001", {"key": "val"})


async def test_subscribe_redis_skips_malformed_messages(monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "redis")

    bad_message = {"type": "message", "data": "not-json"}
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen.return_value = _async_iter([bad_message])

    redis_client = AsyncMock()
    redis_client.pubsub = MagicMock(return_value=pubsub)

    results = []
    async for incident_id, payload in subscribe(redis_client, "crash_analysed"):
        results.append((incident_id, payload))

    assert results == []


# ---------------------------------------------------------------------------
# subscribe — eventbridge backend (no-op)
# ---------------------------------------------------------------------------

async def test_subscribe_eventbridge_is_noop(monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "eventbridge")
    redis_client = AsyncMock()
    results = []
    async for item in subscribe(redis_client, "crash_analysed"):
        results.append(item)
    assert results == []


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _async_iter(items):
    for item in items:
        yield item
