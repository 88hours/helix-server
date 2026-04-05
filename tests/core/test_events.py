"""Tests for core/events.py"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from redis.exceptions import ResponseError

from core.events import publish, subscribe


@pytest.fixture
def redis_mock():
    return AsyncMock()


# ---------------------------------------------------------------------------
# publish — redis backend
# ---------------------------------------------------------------------------

async def test_publish_redis(redis_mock, monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "redis")
    await publish(redis_mock, "crash_analysed", "inc-001", {"key": "value"})
    redis_mock.xadd.assert_awaited_once()
    stream, fields = redis_mock.xadd.call_args[0]
    assert stream == "helix:stream:crash_analysed"
    data = json.loads(fields["data"])
    assert data["incident_id"] == "inc-001"
    assert data["payload"] == {"key": "value"}


# ---------------------------------------------------------------------------
# publish — eventbridge backend
# ---------------------------------------------------------------------------

async def test_publish_eventbridge(redis_mock, monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "eventbridge")
    mock_eb = MagicMock()
    mock_eb.put_events.return_value = {"FailedEntryCount": 0, "Entries": []}

    with patch("boto3.client", return_value=mock_eb):
        await publish(redis_mock, "crash_analysed", "inc-001", {"key": "value"})

    mock_eb.put_events.assert_called_once()
    entry = mock_eb.put_events.call_args[1]["Entries"][0]
    assert entry["DetailType"] == "crash_analysed"
    assert entry["EventBusName"] == "helix-mvp"


async def test_publish_eventbridge_failure_raises(redis_mock, monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "eventbridge")
    mock_eb = MagicMock()
    mock_eb.put_events.return_value = {
        "FailedEntryCount": 1,
        "Entries": [{"ErrorCode": "InternalFailure"}],
    }
    with patch("boto3.client", return_value=mock_eb):
        with pytest.raises(RuntimeError, match="EventBridge put_events failed"):
            await publish(redis_mock, "crash_analysed", "inc-001", {})


# ---------------------------------------------------------------------------
# publish — invalid backend
# ---------------------------------------------------------------------------

async def test_publish_invalid_backend_raises(redis_mock, monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "kafka")
    with pytest.raises(ValueError, match="Unknown HELIX_EVENT_BACKEND"):
        await publish(redis_mock, "crash_analysed", "inc-001", {})


# ---------------------------------------------------------------------------
# subscribe — redis backend (streams)
# ---------------------------------------------------------------------------

async def test_subscribe_redis_yields_events(monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "redis")

    entry_id = b"1234567890-0"
    fields = {b"data": json.dumps({"incident_id": "inc-001", "payload": {"key": "val"}}).encode()}

    redis_client = AsyncMock()
    redis_client.xgroup_create = AsyncMock(side_effect=ResponseError("BUSYGROUP Consumer Group name already exists"))
    redis_client.xreadgroup = AsyncMock(return_value=[
        (b"helix:stream:crash_analysed", [(entry_id, fields)])
    ])
    redis_client.xack = AsyncMock()

    results = []
    async for incident_id, payload in subscribe(redis_client, "crash_analysed", agent_name="qa"):
        results.append((incident_id, payload))
        break

    assert results[0] == ("inc-001", {"key": "val"})


async def test_subscribe_redis_skips_malformed_entries(monkeypatch):
    import asyncio
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "redis")

    entry_id = b"1234567890-0"
    bad_fields = {b"data": b"not-json"}

    redis_client = AsyncMock()
    redis_client.xgroup_create = AsyncMock(side_effect=ResponseError("BUSYGROUP Consumer Group name already exists"))
    # Return the bad entry once, then cancel so the infinite loop exits cleanly.
    redis_client.xreadgroup = AsyncMock(side_effect=[
        [(b"helix:stream:crash_analysed", [(entry_id, bad_fields)])],
        asyncio.CancelledError(),
    ])
    redis_client.xack = AsyncMock()

    results = []
    with pytest.raises(asyncio.CancelledError):
        async for incident_id, payload in subscribe(redis_client, "crash_analysed", agent_name="qa"):
            results.append((incident_id, payload))

    # The malformed entry must never have been yielded.
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
