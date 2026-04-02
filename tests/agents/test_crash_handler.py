"""Tests for agents/crash_handler/agent.py and agents/crash_handler/main.py"""
import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from core.models import CrashReport, RollbarEvent, Severity


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ROLLBAR_SECRET = "test-rollbar-secret"

SAMPLE_YAML = {
    "rollbar": {"webhook_secret_env": "ROLLBAR_WEBHOOK_SECRET"},
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
    monkeypatch.setenv("ROLLBAR_WEBHOOK_SECRET", ROLLBAR_SECRET)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("EMAIL_FROM", "helix@acme.com")
    monkeypatch.setenv("EMAIL_TO", "oncall@acme.com")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)


@pytest.fixture
def rollbar_event():
    return RollbarEvent(
        item_id="12345",
        occurrence_id="occ-uuid-001",
        title="KeyError: 'item_id'",
        level="error",
        environment="production",
        language="python",
        culprit="checkout.process",
        stack_trace='File "checkout.py", line 42, in process\n    item = cart[item_id]',
        raw={"data": {"item": {"id": 12345}}},
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

async def test_handle_returns_crash_report(rollbar_event, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.agent.complete", new=AsyncMock(return_value=LLM_RESPONSE)):
        from agents.crash_handler.agent import handle
        report = await handle(rollbar_event, mock_redis)

    assert isinstance(report, CrashReport)
    assert report.error_type == "KeyError"
    assert report.severity == Severity.high
    assert report.affected_component == "checkout"


async def test_handle_persists_to_redis(rollbar_event, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.agent.complete", new=AsyncMock(return_value=LLM_RESPONSE)):
        from agents.crash_handler.agent import handle
        await handle(rollbar_event, mock_redis)

    # write_crash_report and write_status each call redis.set
    assert mock_redis.set.call_count >= 2


async def test_handle_publishes_event(rollbar_event, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.agent.complete", new=AsyncMock(return_value=LLM_RESPONSE)):
        from agents.crash_handler.agent import handle
        await handle(rollbar_event, mock_redis)

    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[0][0]
    assert "crash_analysed" in channel


async def test_handle_uses_event_stack_trace_as_fallback(rollbar_event, mock_redis):
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
        report = await handle(rollbar_event, mock_redis)

    assert report.stack_trace == rollbar_event.stack_trace


# ---------------------------------------------------------------------------
# FastAPI webhook endpoint
# ---------------------------------------------------------------------------

def _make_rollbar_sig(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


RAW_ROLLBAR_PAYLOAD = {
    "event_name": "new_item",
    "data": {
        "item": {
            "id": 12345,
            "title": "KeyError: 'item_id'",
            "level": "error",
            "environment": "production",
            "project_id": 654321,
            "last_occurrence": {
                "id": "occ-uuid-001",
                "language": "python",
                "context": "checkout.process",
                "body": {
                    "trace": {
                        "frames": [
                            {
                                "filename": "checkout.py",
                                "lineno": 42,
                                "method": "process",
                                "code": "item = cart[item_id]",
                            }
                        ],
                        "exception": {"class": "KeyError", "message": "'item_id'"},
                    }
                },
            },
        }
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
    body = json.dumps(RAW_ROLLBAR_PAYLOAD).encode()
    resp = client.post("/webhook/rollbar", content=body, headers={"content-type": "application/json"})
    assert resp.status_code == 401


def test_webhook_invalid_json_returns_400():
    client = _make_client()
    body = b"not-json"
    sig = _make_rollbar_sig(ROLLBAR_SECRET, body)
    resp = client.post(
        "/webhook/rollbar",
        content=body,
        headers={"x-rollbar-signature": sig, "content-type": "application/json"},
    )
    assert resp.status_code == 400


def test_webhook_valid_request_returns_202():
    body = json.dumps(RAW_ROLLBAR_PAYLOAD).encode()
    sig = _make_rollbar_sig(ROLLBAR_SECRET, body)

    mock_report = CrashReport(
        incident_id="inc-001",
        rollbar_item_id="12345",
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
                "/webhook/rollbar",
                content=body,
                headers={"x-rollbar-signature": sig, "content-type": "application/json"},
            )

    assert resp.status_code == 202
    assert resp.json()["incident_id"] == "inc-001"
