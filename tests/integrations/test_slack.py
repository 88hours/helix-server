"""Tests for integrations/slack.py"""
import hashlib
import hmac
import json
import time
import pytest
import respx
import httpx

from integrations import slack


SLACK_TOKEN = "xoxb-test-token"
CHANNEL = "C123456"
SIGNING_SECRET = "test-signing-secret"


@pytest.fixture(autouse=True)
def slack_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", SLACK_TOKEN)
    monkeypatch.setenv("SLACK_APPROVAL_CHANNEL", CHANNEL)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)


def _make_signature(secret: str, timestamp: str, body: str) -> str:
    base = f"v0:{timestamp}:{body}"
    return "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# verify_signature
# ---------------------------------------------------------------------------

def test_verify_signature_valid():
    body = b"payload=test"
    ts = str(int(time.time()))
    sig = _make_signature(SIGNING_SECRET, ts, body.decode())
    assert slack.verify_signature(body, ts, sig, SIGNING_SECRET) is True


def test_verify_signature_invalid_sig():
    body = b"payload=test"
    ts = str(int(time.time()))
    assert slack.verify_signature(body, ts, "v0=badhex", SIGNING_SECRET) is False


def test_verify_signature_stale_timestamp():
    body = b"payload=test"
    old_ts = str(int(time.time()) - 400)  # older than 300s limit
    sig = _make_signature(SIGNING_SECRET, old_ts, body.decode())
    assert slack.verify_signature(body, old_ts, sig, SIGNING_SECRET) is False


def test_verify_signature_bad_timestamp():
    assert slack.verify_signature(b"body", "not-a-number", "v0=sig", SIGNING_SECRET) is False


# ---------------------------------------------------------------------------
# _auth_header
# ---------------------------------------------------------------------------

def test_auth_header_missing_token_raises(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with pytest.raises(EnvironmentError, match="SLACK_BOT_TOKEN"):
        slack._auth_header()


# ---------------------------------------------------------------------------
# post_message
# ---------------------------------------------------------------------------

@respx.mock
async def test_post_message():
    respx.post("https://slack.com/api/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    await slack.post_message("Hello world!")


@respx.mock
async def test_post_message_slack_error_raises():
    respx.post("https://slack.com/api/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
    )
    with pytest.raises(RuntimeError, match="channel_not_found"):
        await slack.post_message("Hello")


async def test_post_message_missing_channel_skips(monkeypatch, caplog):
    monkeypatch.delenv("SLACK_APPROVAL_CHANNEL", raising=False)
    import logging
    with caplog.at_level(logging.WARNING, logger="integrations.slack"):
        await slack.post_message("Hello", channel=None)
    assert "SLACK_APPROVAL_CHANNEL" in caplog.text


# ---------------------------------------------------------------------------
# post_escalation
# ---------------------------------------------------------------------------

@respx.mock
async def test_post_escalation():
    respx.post("https://slack.com/api/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    await slack.post_escalation(
        incident_id="inc-001",
        crash_summary="A KeyError occurred.",
        attempts=3,
        context="Tried A, B, and C.",
    )
