"""Tests for agents/crash_handler/agent.py and agents/crash_handler/main.py"""
import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from core.models import CrashReport, Severity, SentryEvent


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SENTRY_SECRET = "test-sentry-secret"

SAMPLE_YAML = {
    "sentry": {"webhook_secret_env": "SENTRY_WEBHOOK_SECRET"},
    "redis": {"url_env": "REDIS_URL", "ttl_seconds": 604800},
    "agents": {
        "crash_handler": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    },
    "github": {
        "token_env": "GITHUB_TOKEN",
        "target_repo": "acme/repo",
        "base_branch": "main",
    },
    "jira": {
        "url_env": "JIRA_URL",
        "email_env": "JIRA_EMAIL",
        "token_env": "JIRA_TOKEN",
        "project_key_env": "JIRA_PROJECT_KEY",
    },
    "slack": {
        "token_env": "SLACK_BOT_TOKEN",
        "approval_channel_env": "SLACK_APPROVAL_CHANNEL",
        "signing_secret_env": "SLACK_SIGNING_SECRET",
        "approval_port": 8001,
    },
    "email": {
        "from_env": "EMAIL_FROM",
        "to_env": "EMAIL_TO",
        "sendgrid_api_key_env": "SENDGRID_API_KEY",
        "smtp_host_env": "SMTP_HOST",
        "smtp_port_env": "SMTP_PORT",
        "smtp_user_env": "SMTP_USER",
        "smtp_password_env": "SMTP_PASSWORD",
    },
}


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("SENTRY_WEBHOOK_SECRET", SENTRY_SECRET)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("EMAIL_FROM", "helix@acme.com")
    monkeypatch.setenv("EMAIL_TO", "oncall@acme.com")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)


@pytest.fixture
def sentry_event():
    return SentryEvent(
        event_id="evt-001",
        title="KeyError: 'item_id'",
        message="A key error occurred",
        culprit="checkout.process",
        level="error",
        platform="python",
        stack_trace='File "checkout.py", line 42, in process\n    item = cart[item_id]',
        raw={"id": "evt-001"},
    )


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.publish = AsyncMock(return_value=1)
    return r


LLM_RESPONSE = json.dumps({
    "severity": "high",
    "error_type": "KeyError",
    "error_message": "'item_id'",
    "stack_trace": "...",
    "affected_component": "checkout",
    "affected_endpoint": "/api/v1/checkout",
    "summary": "A KeyError occurred in the checkout process.",
})


# ---------------------------------------------------------------------------
# agent.handle()
# ---------------------------------------------------------------------------

async def test_handle_returns_crash_report(sentry_event, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.agent.complete", new=AsyncMock(return_value=LLM_RESPONSE)):
        from agents.crash_handler.agent import handle
        report = await handle(sentry_event, mock_redis)

    assert isinstance(report, CrashReport)
    assert report.error_type == "KeyError"
    assert report.severity == Severity.high
    assert report.affected_component == "checkout"


async def test_handle_persists_to_redis(sentry_event, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.agent.complete", new=AsyncMock(return_value=LLM_RESPONSE)):
        from agents.crash_handler.agent import handle
        await handle(sentry_event, mock_redis)

    # write_crash_report and write_status each call redis.set
    assert mock_redis.set.call_count >= 2


async def test_handle_publishes_event(sentry_event, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.agent.complete", new=AsyncMock(return_value=LLM_RESPONSE)):
        from agents.crash_handler.agent import handle
        await handle(sentry_event, mock_redis)

    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[0][0]
    assert "crash_analysed" in channel


async def test_handle_uses_event_stack_trace_as_fallback(sentry_event, mock_redis):
    response_no_trace = json.dumps({
        "severity": "high",
        "error_type": "KeyError",
        "error_message": "'item_id'",
        "affected_component": "checkout",
        "affected_endpoint": "/api/v1/checkout",
        "summary": "A bug.",
    })
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.agent.complete", new=AsyncMock(return_value=response_no_trace)):
        from agents.crash_handler.agent import handle
        report = await handle(sentry_event, mock_redis)

    assert report.stack_trace == sentry_event.stack_trace


# ---------------------------------------------------------------------------
# FastAPI webhook endpoint
# ---------------------------------------------------------------------------

def _make_sentry_sig(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


RAW_SENTRY_PAYLOAD = {
    "id": "evt-001",
    "message": "KeyError: 'item_id'",
    "event": {
        "event_id": "evt-001",
        "level": "error",
        "culprit": "checkout.process",
        "platform": "python",
        "exception": {
            "values": [{
                "type": "KeyError",
                "value": "'item_id'",
                "stacktrace": {"frames": [{"filename": "checkout.py", "lineno": 42, "function": "process", "context_line": "item = cart[item_id]"}]},
            }]
        },
    },
}


def _make_client():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import app
        return TestClient(app, raise_server_exceptions=False)


def test_healthz():
    client = _make_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_webhook_missing_signature_returns_401():
    client = _make_client()
    body = json.dumps(RAW_SENTRY_PAYLOAD).encode()
    resp = client.post("/webhook/sentry", content=body, headers={"content-type": "application/json"})
    assert resp.status_code == 401


def test_webhook_invalid_json_returns_400():
    client = _make_client()
    body = b"not-json"
    sig = _make_sentry_sig(SENTRY_SECRET, body)
    resp = client.post(
        "/webhook/sentry",
        content=body,
        headers={"sentry-hook-signature": sig, "content-type": "application/json"},
    )
    assert resp.status_code == 400


def test_webhook_valid_request_returns_202():
    body = json.dumps(RAW_SENTRY_PAYLOAD).encode()
    sig = _make_sentry_sig(SENTRY_SECRET, body)

    mock_report = CrashReport(
        incident_id="inc-001",
        sentry_event_id="evt-001",
        severity=Severity.high,
        error_type="KeyError",
        error_message="'item_id'",
        stack_trace="...",
        affected_component="checkout",
        affected_endpoint="/api/checkout",
        summary="A bug.",
    )

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.handle", new=AsyncMock(return_value=mock_report)):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/webhook/sentry",
                content=body,
                headers={"sentry-hook-signature": sig, "content-type": "application/json"},
            )

    assert resp.status_code == 202
    assert resp.json()["incident_id"] == "inc-001"
