"""Tests for agents/crash_handler/agent.py and agents/crash_handler/main.py"""
import hashlib
import hmac
import json
import time
import urllib.parse
import pytest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from core.models import CrashReport, PRResult, RollbarEvent, Severity


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ROLLBAR_TOKEN = "test-rollbar-access-token"

SAMPLE_YAML = {
    "rollbar": {"access_token_env": "ROLLBAR_ACCESS_TOKEN"},
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
    monkeypatch.setenv("ROLLBAR_ACCESS_TOKEN", ROLLBAR_TOKEN)
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
    r.xadd = AsyncMock(return_value=b"1234567890-0")
    return r


LLM_RESPONSE = json.dumps({
    "severity": "high",
    "error_type": "KeyError",
    "error_message": "'item_id'",
    "stack_trace": "...",
    "affected_component": "checkout",
    "affected_endpoint": "/api/v1/checkout",
    "summary": "A KeyError occurred in the checkout process.",
    "language": "python",
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
    assert report.language == "python"


async def test_handle_uses_rollbar_language_over_llm(mock_redis):
    """Rollbar-provided language takes precedence over the LLM-detected one."""
    event = RollbarEvent(
        item_id="12345",
        occurrence_id="occ-uuid-002",
        title="TypeError: Cannot read property",
        level="error",
        language="javascript",
        stack_trace="at process (/app/checkout.js:10:5)",
        raw={},
    )
    llm_response = json.dumps({
        "severity": "high",
        "error_type": "TypeError",
        "error_message": "Cannot read property",
        "stack_trace": "...",
        "affected_component": "checkout",
        "affected_endpoint": "/api/checkout",
        "summary": "A TypeError in checkout.",
        "language": "python",  # LLM incorrectly detects python
    })
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.agent.complete", new=AsyncMock(return_value=llm_response)):
        from agents.crash_handler.agent import handle
        report = await handle(event, mock_redis)

    # Rollbar said "javascript" — that wins
    assert report.language == "javascript"


async def test_handle_falls_back_to_llm_language_when_rollbar_omits_it(mock_redis):
    """When Rollbar sends no language, the LLM-detected value is used."""
    event = RollbarEvent(
        item_id="12345",
        occurrence_id="occ-uuid-003",
        title="RuntimeError: boom",
        level="error",
        language=None,
        stack_trace="/app/main.go:42 +0x1234",
        raw={},
    )
    llm_response = json.dumps({
        "severity": "medium",
        "error_type": "RuntimeError",
        "error_message": "boom",
        "stack_trace": "...",
        "affected_component": "main",
        "affected_endpoint": "main()",
        "summary": "A runtime error in main.",
        "language": "go",
    })
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.agent.complete", new=AsyncMock(return_value=llm_response)):
        from agents.crash_handler.agent import handle
        report = await handle(event, mock_redis)

    assert report.language == "go"


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

    mock_redis.xadd.assert_called_once()
    stream = mock_redis.xadd.call_args[0][0]
    assert "crash_analysed" in stream


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
                "metadata": {"access_token": ROLLBAR_TOKEN},
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


def test_webhook_rollbar_test_ping_returns_202():
    client = _make_client()
    mock_project = {"project_id": "proj-001", "rollbar_access_token": ROLLBAR_TOKEN}
    payload = {"event_name": "test", "data": {"message": "This is a test payload from Rollbar."}}
    with patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)):
        resp = client.post(
            "/webhook/rollbar/proj-001",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 202
    assert resp.json() == {"status": "ok"}


def test_webhook_wrong_token_returns_401():
    import copy
    client = _make_client()
    mock_project = {"project_id": "proj-001", "rollbar_access_token": ROLLBAR_TOKEN}
    payload = copy.deepcopy(RAW_ROLLBAR_PAYLOAD)
    payload["data"]["item"]["last_occurrence"]["metadata"]["access_token"] = "wrong"
    body = json.dumps(payload).encode()
    with patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)):
        resp = client.post("/webhook/rollbar/proj-001", content=body, headers={"content-type": "application/json"})
    assert resp.status_code == 401


def test_webhook_invalid_json_returns_400():
    client = _make_client()
    mock_project = {"project_id": "proj-001", "rollbar_access_token": ROLLBAR_TOKEN}
    with patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)):
        resp = client.post(
            "/webhook/rollbar/proj-001",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 400


def test_sentry_webhook_demo_mode_skips_verification():
    """In demo mode, Sentry signature verification must not run even when
    SENTRY_WEBHOOK_SECRET is set and the signature header is wrong."""
    payload = {"action": "ping"}
    body = json.dumps(payload).encode()
    mock_project = {"project_id": "proj-001", "sentry_webhook_secret": None}

    sample_yaml = {**SAMPLE_YAML, "demo": True, "sentry": {"webhook_secret_env": "SENTRY_WEBHOOK_SECRET"}}

    with patch("core.config._load_yaml", return_value=sample_yaml), \
         patch.dict("os.environ", {"SENTRY_WEBHOOK_SECRET": "real-secret", "HELIX_DEMO": "true"}), \
         patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/webhook/sentry/proj-001",
                content=body,
                headers={
                    "content-type": "application/json",
                    "sentry-hook-signature": "invalid-signature",
                },
            )

    # ping must be acknowledged; if verification ran it would be 401
    assert resp.status_code == 202
    assert resp.json() == {"status": "ok"}


def test_webhook_valid_request_returns_202():
    body = json.dumps(RAW_ROLLBAR_PAYLOAD).encode()
    mock_project = {"project_id": "proj-001", "rollbar_access_token": ROLLBAR_TOKEN}

    mock_report = CrashReport(
        incident_id="inc-001",
        project_id="proj-001",
        source_item_id="12345", source="rollbar",
        severity=Severity.high,
        error_type="KeyError",
        error_message="'item_id'",
        stack_trace="...",
        affected_component="checkout",
        affected_endpoint="/api/checkout",
        summary="A bug.",
    )

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)), \
         patch("agents.crash_handler.main.is_duplicate_occurrence", new=AsyncMock(return_value=False)), \
         patch("agents.crash_handler.main.handle", new=AsyncMock(return_value=mock_report)):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/webhook/rollbar/proj-001",
                content=body,
                headers={"content-type": "application/json"},
            )

    assert resp.status_code == 202
    assert resp.json()["incident_id"] == "inc-001"


# ---------------------------------------------------------------------------
# /slack/actions endpoint
# ---------------------------------------------------------------------------

SIGNING_SECRET = "test-slack-signing-secret"

SAMPLE_PR_RESULT = PRResult(
    incident_id="inc-001",
    pr_url="https://github.com/acme/repo/pull/42",
    pr_number=42,
    branch_name="helix/fix-inc-001",
    iterations_taken=1,
    files_changed=["checkout.py"],
    fix_summary="Fixed the KeyError in checkout.",
)


def _slack_action_body(action_id: str, incident_id: str) -> bytes:
    """Build a URL-encoded Slack interaction payload."""
    payload = {
        "type": "block_actions",
        "actions": [{"action_id": action_id, "value": incident_id}],
    }
    return urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()


def _slack_headers(body: bytes, secret: str) -> dict:
    ts = str(int(time.time()))
    base = f"v0:{ts}:{body.decode()}"
    sig = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return {
        "content-type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
    }


def _make_slack_yaml():
    return {
        **SAMPLE_YAML,
        "slack": {
            "token_env": "SLACK_BOT_TOKEN",
            "approval_channel_env": "SLACK_APPROVAL_CHANNEL",
            "signing_secret_env": "SLACK_SIGNING_SECRET",
        },
    }


def test_slack_actions_missing_signing_secret_returns_403(monkeypatch):
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    body = _slack_action_body("approve_pr", "inc-001")
    ts = str(int(time.time()))
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": "v0=invalid",
    }
    with patch("core.config._load_yaml", return_value=_make_slack_yaml()):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/slack/actions", content=body, headers=headers)
    assert resp.status_code == 403


def test_slack_actions_invalid_signature_returns_403(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    body = _slack_action_body("approve_pr", "inc-001")
    ts = str(int(time.time()))
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": "v0=badsignature",
    }
    with patch("core.config._load_yaml", return_value=_make_slack_yaml()):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/slack/actions", content=body, headers=headers)
    assert resp.status_code == 403


def test_slack_actions_approve_merges_pr(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-test-token")
    body = _slack_action_body("approve_pr", "inc-001")
    headers = _slack_headers(body, SIGNING_SECRET)

    with patch("core.config._load_yaml", return_value=_make_slack_yaml()), \
         patch("agents.crash_handler.main.read_pr_result", return_value=SAMPLE_PR_RESULT), \
         patch("agents.crash_handler.main.write_status", new=AsyncMock()) as mock_write_status, \
         patch("agents.crash_handler.main.merge_pull_request", new=AsyncMock()) as mock_merge:
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/slack/actions", content=body, headers=headers)

    assert resp.status_code == 200
    assert "merged" in resp.json()["text"].lower()
    mock_merge.assert_awaited_once_with(repo="acme/repo", pr_number=42)
    mock_write_status.assert_awaited_once_with(ANY, "inc-001", "pr_merged")


def test_slack_actions_reject_updates_status(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    body = _slack_action_body("reject_pr", "inc-001")
    headers = _slack_headers(body, SIGNING_SECRET)

    with patch("core.config._load_yaml", return_value=_make_slack_yaml()), \
         patch("agents.crash_handler.main.write_status", new=AsyncMock()) as mock_write_status:
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/slack/actions", content=body, headers=headers)

    assert resp.status_code == 200
    assert "rejected" in resp.json()["text"].lower()
    mock_write_status.assert_awaited_once_with(ANY, "inc-001", "approval_rejected")


# ---------------------------------------------------------------------------
# Legacy webhook endpoints — 410 Gone
# ---------------------------------------------------------------------------

def test_legacy_rollbar_webhook_returns_410():
    client = _make_client()
    resp = client.post("/webhook/rollbar", content=b"{}", headers={"content-type": "application/json"})
    assert resp.status_code == 410


def test_legacy_sentry_webhook_returns_410():
    client = _make_client()
    resp = client.post("/webhook/sentry", content=b"{}", headers={"content-type": "application/json"})
    assert resp.status_code == 410


# ---------------------------------------------------------------------------
# _load_project_or_404
# ---------------------------------------------------------------------------

def test_load_project_or_404_returns_503_when_no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main._load_project_or_404",
               side_effect=Exception("503")):
        pass  # tested indirectly via rollbar webhook below

    # Direct test: call the function without DATABASE_URL
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import _load_project_or_404
        import asyncio
        from fastapi import HTTPException as FHE
        with pytest.raises(FHE) as exc_info:
            asyncio.run(_load_project_or_404("proj-001"))
    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# Sentry webhook edge cases
# ---------------------------------------------------------------------------

def test_sentry_webhook_invalid_signature_returns_401(monkeypatch):
    mock_project = {"project_id": "proj-001", "sentry_webhook_secret": "real-secret"}
    body = json.dumps({"action": "created"}).encode()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/webhook/sentry/proj-001",
            content=body,
            headers={"content-type": "application/json", "sentry-hook-signature": "bad-sig"},
        )
    assert resp.status_code == 401


def test_sentry_webhook_no_secret_skips_verification(monkeypatch):
    mock_project = {"project_id": "proj-001", "sentry_webhook_secret": None}
    payload = {"action": "ping"}
    body = json.dumps(payload).encode()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/webhook/sentry/proj-001",
            content=body,
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 202


def test_sentry_webhook_invalid_json_returns_400():
    mock_project = {"project_id": "proj-001", "sentry_webhook_secret": None}
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/webhook/sentry/proj-001",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Rollbar webhook edge cases
# ---------------------------------------------------------------------------

def test_rollbar_webhook_returns_401_when_no_access_token_configured():
    mock_project = {"project_id": "proj-001", "rollbar_access_token": None}
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/webhook/rollbar/proj-001",
            content=json.dumps(RAW_ROLLBAR_PAYLOAD).encode(),
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Slack action edge cases
# ---------------------------------------------------------------------------

def test_slack_actions_returns_400_on_bad_payload(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    body = b"not-url-encoded-at-all!!!"
    ts = str(int(time.time()))
    import hmac as _hmac, hashlib as _hashlib
    base = f"v0:{ts}:{body.decode()}"
    sig = "v0=" + _hmac.new(SIGNING_SECRET.encode(), base.encode(), _hashlib.sha256).hexdigest()
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
    }
    with patch("core.config._load_yaml", return_value=_make_slack_yaml()):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/slack/actions", content=body, headers=headers)
    assert resp.status_code == 400


def test_slack_actions_returns_200_when_no_actions_in_payload(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    import urllib.parse as _up, json as _json
    payload = {"type": "block_actions", "actions": []}
    body = _up.urlencode({"payload": _json.dumps(payload)}).encode()
    headers = _slack_headers(body, SIGNING_SECRET)
    with patch("core.config._load_yaml", return_value=_make_slack_yaml()):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/slack/actions", content=body, headers=headers)
    assert resp.status_code == 200
    assert "No action" in resp.json()["text"]


def test_slack_actions_approve_returns_200_when_pr_result_missing(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    body = _slack_action_body("approve_pr", "inc-missing")
    headers = _slack_headers(body, SIGNING_SECRET)
    with patch("core.config._load_yaml", return_value=_make_slack_yaml()), \
         patch("agents.crash_handler.main.read_pr_result", return_value=None):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/slack/actions", content=body, headers=headers)
    assert resp.status_code == 200
    assert "Could not find PR" in resp.json()["text"]


def test_slack_actions_approve_returns_200_when_merge_fails(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-test")
    body = _slack_action_body("approve_pr", "inc-001")
    headers = _slack_headers(body, SIGNING_SECRET)
    with patch("core.config._load_yaml", return_value=_make_slack_yaml()), \
         patch("agents.crash_handler.main.read_pr_result", return_value=SAMPLE_PR_RESULT), \
         patch("agents.crash_handler.main.merge_pull_request", side_effect=Exception("merge conflict")):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/slack/actions", content=body, headers=headers)
    assert resp.status_code == 200
    assert "Merge failed" in resp.json()["text"]


def test_slack_actions_unknown_action_returns_200(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    body = _slack_action_body("snooze_pr", "inc-001")
    headers = _slack_headers(body, SIGNING_SECRET)
    with patch("core.config._load_yaml", return_value=_make_slack_yaml()):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/slack/actions", content=body, headers=headers)
    assert resp.status_code == 200
    assert "Unknown action" in resp.json()["text"]


# ---------------------------------------------------------------------------
# Dashboard API — /api/incidents, /api/incidents/{id}
# ---------------------------------------------------------------------------

def test_list_incidents_returns_empty_list_when_no_incidents():
    async def empty_scan(pattern):
        return
        yield  # noqa: unreachable — makes this an async generator

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import app
    mock_redis = AsyncMock()
    mock_redis.scan_iter = empty_scan
    app.state.redis = mock_redis

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/incidents")
    assert resp.status_code == 200
    assert resp.json()["incidents"] == []


def test_get_incident_returns_404_when_not_found():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.read_status", new=AsyncMock(return_value=None)):
        from agents.crash_handler.main import app
        mock_redis = AsyncMock()
        app.state.redis = mock_redis
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/incidents/nonexistent")
    assert resp.status_code == 404


def test_get_incident_returns_incident_data():
    from core.models import CrashReport, Severity
    report = CrashReport(
        incident_id="inc-001", project_id="proj-001",
        source_item_id="12345", source="rollbar",
        severity=Severity.high, error_type="KeyError",
        error_message="'item_id'", stack_trace="...",
        affected_component="checkout", affected_endpoint="/api/v1/checkout",
        summary="A KeyError.",
    )
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.read_status", new=AsyncMock(return_value="pr_created")), \
         patch("agents.crash_handler.main.read_crash_report", new=AsyncMock(return_value=report)), \
         patch("agents.crash_handler.main.read_qa_result", new=AsyncMock(return_value=None)), \
         patch("agents.crash_handler.main.read_pr_result", new=AsyncMock(return_value=None)):
        from agents.crash_handler.main import app
        mock_redis = AsyncMock()
        app.state.redis = mock_redis
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/incidents/inc-001")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pr_created"
    assert resp.json()["crash_report"]["error_type"] == "KeyError"


# ---------------------------------------------------------------------------
# Repo API — /api/repos
# ---------------------------------------------------------------------------

def test_list_repos_returns_empty_list():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.read_user_repos", new=AsyncMock(return_value=[])):
        from agents.crash_handler.main import app
    mock_redis = AsyncMock()
    app.state.redis = mock_redis

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/repos")
    assert resp.status_code == 200
    assert resp.json()["repos"] == []


def test_add_repo_returns_201():
    from core.models import RepoConfig
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.read_user_repos", new=AsyncMock(return_value=[])), \
         patch("agents.crash_handler.main.write_user_repos", new=AsyncMock()):
        from agents.crash_handler.main import app
    mock_redis = AsyncMock()
    app.state.redis = mock_redis

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/repos", json={"repo": "acme/backend", "base_branch": "main", "language": "python"})
    assert resp.status_code == 201
    assert resp.json()["repo"] == "acme/backend"


def test_add_repo_returns_400_for_invalid_format():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.read_user_repos", new=AsyncMock(return_value=[])):
        from agents.crash_handler.main import app
    mock_redis = AsyncMock()
    app.state.redis = mock_redis

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/repos", json={"repo": "not-a-valid-repo"})
    assert resp.status_code == 400


def test_add_repo_returns_409_for_duplicate():
    from core.models import RepoConfig
    existing = [RepoConfig(repo="acme/backend", base_branch="main", language="python")]
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.read_user_repos", new=AsyncMock(return_value=existing)):
        from agents.crash_handler.main import app
        mock_redis = AsyncMock()
        app.state.redis = mock_redis
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/repos", json={"repo": "acme/backend"})
    assert resp.status_code == 409


def test_remove_repo_returns_200():
    from core.models import RepoConfig
    repos = [RepoConfig(repo="acme/backend", base_branch="main", language="python")]
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.read_user_repos", new=AsyncMock(return_value=repos)), \
         patch("agents.crash_handler.main.write_user_repos", new=AsyncMock()):
        from agents.crash_handler.main import app
        mock_redis = AsyncMock()
        app.state.redis = mock_redis
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/api/repos/acme/backend")
    assert resp.status_code == 200
    assert resp.json()["removed"] == "acme/backend"


def test_remove_repo_returns_404_when_not_configured():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.read_user_repos", new=AsyncMock(return_value=[])):
        from agents.crash_handler.main import app
    mock_redis = AsyncMock()
    app.state.redis = mock_redis

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.delete("/api/repos/acme/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Project API — /api/projects (Postgres-backed)
# ---------------------------------------------------------------------------

def _make_db_mock(mock_db):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def test_list_projects_returns_503_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = _make_client()
    resp = client.get("/api/projects")
    assert resp.status_code == 503


def test_list_projects_returns_project_list(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    rows = [{"project_id": "proj-001", "name": "Acme", "repo": "acme/repo",
             "rollbar_access_token": "secret", "sentry_webhook_secret": None,
             "slack_bot_token": None, "slack_signing_secret": None, "sendgrid_api_key": None}]
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.db_list_projects", new=AsyncMock(return_value=rows)), \
         patch("agents.crash_handler.main.db_list_all_projects", new=AsyncMock(return_value=rows)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()["projects"]
    assert len(projects) == 1
    assert projects[0]["rollbar_access_token"] == "***"


def test_create_project_returns_201(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    created_row = {
        "project_id": "new-uuid", "name": "My App", "repo": "acme/app",
        "base_branch": "main", "language": "python", "owner_sub": "demo|00000000",
        "rollbar_access_token": None, "sentry_webhook_secret": None,
        "slack_bot_token": None, "slack_signing_secret": None,
        "sendgrid_api_key": None, "github_installation_id": None,
    }
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.upsert_user", new=AsyncMock()), \
         patch("agents.crash_handler.main.insert_project", new=AsyncMock()), \
         patch("agents.crash_handler.main.upsert_project_settings", new=AsyncMock()), \
         patch("agents.crash_handler.main.get_installation_for_user", new=AsyncMock(return_value=None)), \
         patch("agents.crash_handler.main.get_project", new=AsyncMock(return_value=created_row)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/projects", json={
            "name": "My App", "repo": "acme/app", "base_branch": "main", "language": "python",
        })
    assert resp.status_code == 201
    assert "webhook_urls" in resp.json()


def test_create_project_returns_400_for_invalid_repo(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    client = _make_client()
    resp = client.post("/api/projects", json={"name": "Bad", "repo": "not-valid-format"})
    assert resp.status_code == 400


def test_delete_project_returns_200(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.db_delete_project", new=AsyncMock(return_value=True)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/api/projects/proj-001")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == "proj-001"


def test_delete_project_returns_404_when_not_found(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.db_delete_project", new=AsyncMock(return_value=False)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/api/projects/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Pure helpers — _mask_row, _parse_repo_slug, _require_db
# ---------------------------------------------------------------------------

def test_mask_row_replaces_secret_fields_with_stars():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import _mask_row
    row = {"rollbar_access_token": "secret123", "name": "Acme", "slack_bot_token": "xoxb"}
    masked = _mask_row(row)
    assert masked["rollbar_access_token"] == "***"
    assert masked["slack_bot_token"] == "***"
    assert masked["name"] == "Acme"


def test_mask_row_leaves_empty_secrets_unchanged():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import _mask_row
    row = {"rollbar_access_token": None, "name": "Acme"}
    masked = _mask_row(row)
    assert masked["rollbar_access_token"] is None


def test_parse_repo_slug_from_plain_slug():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import _parse_repo_slug
    assert _parse_repo_slug("acme/backend") == "acme/backend"


def test_parse_repo_slug_from_https_url():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import _parse_repo_slug
    assert _parse_repo_slug("https://github.com/acme/backend") == "acme/backend"


def test_parse_repo_slug_from_ssh_url():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import _parse_repo_slug
    assert _parse_repo_slug("git@github.com:acme/backend.git") == "acme/backend"


def test_parse_repo_slug_raises_for_invalid():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import _parse_repo_slug
    with pytest.raises(ValueError):
        _parse_repo_slug("not-a-valid-repo")


# ---------------------------------------------------------------------------
# Auth — /api/me
# ---------------------------------------------------------------------------

def test_get_me_returns_demo_user_when_auth_disabled(monkeypatch):
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    client = _make_client()
    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json()["sub"] == "demo|00000000"


# ---------------------------------------------------------------------------
# Static file routes — all return error dicts when files are absent
# ---------------------------------------------------------------------------

def test_serve_landing_returns_error_when_not_built():
    client = _make_client()
    resp = client.get("/")
    # Either FileResponse (if index.html exists) or error dict
    assert resp.status_code == 200


def test_serve_dashboard_root_responds():
    client = _make_client()
    resp = client.get("/app")
    assert resp.status_code in (200, 404)


def test_serve_dashboard_path_responds():
    client = _make_client()
    resp = client.get("/app/projects")
    assert resp.status_code in (200, 404)


def test_get_github_install_url_returns_503_when_not_configured():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.build_install_url",
               side_effect=RuntimeError("GITHUB_APP_ID not set")):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/github/install-url")
    assert resp.status_code == 503


def test_get_github_install_url_returns_url_when_configured(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_SLUG", "helix-bot")
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.build_install_url", return_value="https://github.com/apps/helix-bot/installations/new"):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/github/install-url")
    assert resp.status_code == 200
    assert "install_url" in resp.json()


# ---------------------------------------------------------------------------
# Update project settings — /api/projects/{project_id}/settings
# ---------------------------------------------------------------------------

def test_update_project_settings_returns_updated_row(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    row = {
        "project_id": "proj-001", "name": "Acme", "repo": "acme/repo",
        "owner_sub": "demo|00000000",
        "rollbar_access_token": None, "sentry_webhook_secret": None,
        "slack_bot_token": "xoxb-new", "slack_signing_secret": None,
        "sendgrid_api_key": None,
    }
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.get_project", new=AsyncMock(return_value=row)), \
         patch("agents.crash_handler.main.upsert_project_settings", new=AsyncMock()):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.put("/api/projects/proj-001/settings",
                          json={"slack_bot_token": "xoxb-new"})
    assert resp.status_code == 200
    assert resp.json()["slack_bot_token"] == "***"


def test_update_project_settings_returns_404_for_unknown_project(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.get_project", new=AsyncMock(return_value=None)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.put("/api/projects/nonexistent/settings", json={})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Get webhook URLs — /api/projects/{project_id}/webhook-urls
# ---------------------------------------------------------------------------

def test_get_webhook_urls_returns_urls(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    row = {"project_id": "proj-001", "owner_sub": "demo|00000000", "name": "Acme"}
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.get_project", new=AsyncMock(return_value=row)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/projects/proj-001/webhook-urls")
    assert resp.status_code == 200
    assert "sentry" in resp.json()
    assert "rollbar" in resp.json()


def test_get_webhook_urls_returns_404_when_not_found(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.get_project", new=AsyncMock(return_value=None)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/projects/nonexistent/webhook-urls")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List incidents — scan returns results
# ---------------------------------------------------------------------------

def test_list_incidents_returns_incidents_when_present():
    from core.models import CrashReport, Severity

    report = CrashReport(
        incident_id="inc-001", project_id="proj-001",
        source_item_id="12345", source="rollbar",
        severity=Severity.high, error_type="KeyError",
        error_message="'item_id'", stack_trace="...",
        affected_component="checkout", affected_endpoint="/api/v1/checkout",
        summary="A KeyError.",
    )

    async def mock_scan(pattern):
        yield b"helix:incident:inc-001:status"

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.read_status", new=AsyncMock(return_value="pr_created")), \
         patch("agents.crash_handler.main.read_crash_report", new=AsyncMock(return_value=report)):
        from agents.crash_handler.main import app
        mock_redis = AsyncMock()
        mock_redis.scan_iter = mock_scan
        app.state.redis = mock_redis
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/incidents")

    assert resp.status_code == 200
    assert len(resp.json()["incidents"]) == 1
    assert resp.json()["incidents"][0]["status"] == "pr_created"


# ---------------------------------------------------------------------------
# GitHub App callback — /api/github/callback
# ---------------------------------------------------------------------------

def test_github_app_callback_stores_installation(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.upsert_user", new=AsyncMock()), \
         patch("agents.crash_handler.main.upsert_github_installation", new=AsyncMock()):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        resp = client.get("/api/github/callback?installation_id=inst-001")
    assert resp.status_code in (200, 302, 307)


def test_github_app_callback_returns_400_when_no_installation_id(monkeypatch):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/github/callback")
    assert resp.status_code == 400


def test_github_app_callback_returns_503_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/github/callback?installation_id=inst-001")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Register GitHub installation — POST /api/github/installations
# ---------------------------------------------------------------------------

def test_register_github_installation_stores_and_returns_ok(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.upsert_user", new=AsyncMock()), \
         patch("agents.crash_handler.main.upsert_github_installation", new=AsyncMock()):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/github/installations", json={"installation_id": "inst-001"})
    assert resp.status_code == 200
    assert resp.json()["installation_id"] == "inst-001"


def test_register_github_installation_returns_400_when_missing_id(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/github/installations", json={})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# List GitHub repos — GET /api/github/repos
# ---------------------------------------------------------------------------

def test_list_github_repos_returns_repos(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    installation = {"installation_id": "inst-001", "owner_sub": "demo|00000000"}
    repos = [{"full_name": "acme/backend", "private": False, "default_branch": "main", "description": ""}]
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.get_installation_for_user", new=AsyncMock(return_value=installation)), \
         patch("agents.crash_handler.main.list_installation_repos", new=AsyncMock(return_value=repos)), \
         patch("agents.crash_handler.main.build_install_url", return_value="https://github.com/apps/helix-bot/installations/new"):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/github/repos")
    assert resp.status_code == 200
    assert len(resp.json()["repos"]) == 1


def test_list_github_repos_returns_404_when_not_installed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main.get_db", return_value=_make_db_mock(mock_db)), \
         patch("agents.crash_handler.main.get_installation_for_user", new=AsyncMock(return_value=None)):
        from agents.crash_handler.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/github/repos")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Sentry webhook — full happy path
# ---------------------------------------------------------------------------

def test_sentry_webhook_processes_event(monkeypatch):
    from core.models import CrashReport, Severity

    mock_project = {"project_id": "proj-001", "sentry_webhook_secret": None}
    mock_report = CrashReport(
        incident_id="inc-001", project_id="proj-001",
        source_item_id="12345", source="sentry",
        severity=Severity.high, error_type="KeyError",
        error_message="'item_id'", stack_trace="...",
        affected_component="checkout", affected_endpoint="/api/v1/checkout",
        summary="A bug.",
    )
    payload = {
        "action": "created",
        "data": {
            "issue": {
                "id": "12345",
                "title": "KeyError: 'item_id'",
                "level": "error",
                "culprit": "checkout.process",
                "platform": "python",
                "metadata": {"type": "KeyError", "value": "'item_id'"},
                "project": {"slug": "my-project"},
            }
        }
    }
    body = json.dumps(payload).encode()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.crash_handler.main._load_project_or_404", new=AsyncMock(return_value=mock_project)), \
         patch("agents.crash_handler.main.is_duplicate_occurrence", new=AsyncMock(return_value=False)), \
         patch("agents.crash_handler.main.handle", new=AsyncMock(return_value=mock_report)):
        from agents.crash_handler.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/webhook/sentry/proj-001",
                content=body,
                headers={"content-type": "application/json"},
            )
    assert resp.status_code == 202
    assert resp.json()["incident_id"] == "inc-001"
