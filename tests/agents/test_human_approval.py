"""Tests for agents/human_approval/agent.py and agents/human_approval/main.py"""
import hashlib
import hmac
import json
import time
import urllib.parse
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from core.models import PRResult


SIGNING_SECRET = "test-signing-secret"

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
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APPROVAL_CHANNEL", "C123")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("EMAIL_FROM", "helix@acme.com")
    monkeypatch.setenv("EMAIL_TO", "oncall@acme.com")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")


@pytest.fixture
def pr_result():
    return PRResult(
        incident_id="inc-001",
        pr_url="https://github.com/acme/repo/pull/42",
        pr_number=42,
        branch_name="helix/fix/inc-001-1",
        iterations_taken=1,
        fix_summary="Fixed.",
    )


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=None)
    return r


# ---------------------------------------------------------------------------
# handle_approve — success path
# ---------------------------------------------------------------------------

async def test_handle_approve_merges_pr_and_notifies(pr_result, mock_redis):
    mock_redis.get = AsyncMock(return_value=pr_result.model_dump_json().encode())

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.merge_pull_request", new=AsyncMock()) as mock_merge, \
         patch("integrations.slack.post_message", new=AsyncMock()) as mock_slack, \
         patch("integrations.email.send_pr_merged", new=AsyncMock()) as mock_email:
        from agents.human_approval.agent import handle_approve
        await handle_approve("inc-001", "alice", mock_redis)

    mock_merge.assert_awaited_once()
    mock_slack.assert_awaited_once()
    mock_email.assert_awaited_once()

    merge_kwargs = mock_merge.call_args.kwargs
    assert merge_kwargs["pr_number"] == 42
    assert "alice" in merge_kwargs.get("commit_title", "")


async def test_handle_approve_updates_status(pr_result, mock_redis):
    mock_redis.get = AsyncMock(return_value=pr_result.model_dump_json().encode())

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.merge_pull_request", new=AsyncMock()), \
         patch("integrations.slack.post_message", new=AsyncMock()), \
         patch("integrations.email.send_pr_merged", new=AsyncMock()):
        from agents.human_approval.agent import handle_approve
        await handle_approve("inc-001", "alice", mock_redis)

    # write_status calls redis.set
    mock_redis.set.assert_called()
    last_call = mock_redis.set.call_args_list[-1]
    assert "merged" in str(last_call)


# ---------------------------------------------------------------------------
# handle_approve — missing pr_result
# ---------------------------------------------------------------------------

async def test_handle_approve_missing_pr_result_posts_warning(mock_redis):
    mock_redis.get = AsyncMock(return_value=None)

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.slack.post_message", new=AsyncMock()) as mock_slack, \
         patch("integrations.github.merge_pull_request", new=AsyncMock()) as mock_merge:
        from agents.human_approval.agent import handle_approve
        await handle_approve("inc-999", "alice", mock_redis)

    mock_merge.assert_not_awaited()
    mock_slack.assert_awaited_once()
    text = mock_slack.call_args.kwargs.get("text", "")
    assert "cannot merge" in text.lower() or "state not found" in text.lower()


# ---------------------------------------------------------------------------
# handle_reject
# ---------------------------------------------------------------------------

async def test_handle_reject_posts_slack_and_updates_status(pr_result, mock_redis):
    mock_redis.get = AsyncMock(return_value=pr_result.model_dump_json().encode())

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.slack.post_message", new=AsyncMock()) as mock_slack:
        from agents.human_approval.agent import handle_reject
        await handle_reject("inc-001", "bob", mock_redis)

    mock_slack.assert_awaited_once()
    text = mock_slack.call_args.kwargs.get("text", "")
    assert "bob" in text
    assert "rejected" in text.lower()
    mock_redis.set.assert_called()


async def test_handle_reject_without_pr_result(mock_redis):
    mock_redis.get = AsyncMock(return_value=None)

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.slack.post_message", new=AsyncMock()) as mock_slack:
        from agents.human_approval.agent import handle_reject
        # Should not raise — pr_link falls back to "the PR"
        await handle_reject("inc-999", "bob", mock_redis)

    mock_slack.assert_awaited_once()


# ---------------------------------------------------------------------------
# FastAPI endpoint — /slack/interactions
# ---------------------------------------------------------------------------

def _make_sig(secret: str, timestamp: str, body: str) -> str:
    base = f"v0:{timestamp}:{body}"
    return "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()


def _make_interaction_body(action_id: str, incident_id: str, username: str = "alice") -> bytes:
    payload = {
        "type": "block_actions",
        "user": {"username": username},
        "actions": [{"action_id": action_id, "value": incident_id}],
    }
    return urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()


def _make_client():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.human_approval.main import app
        return TestClient(app, raise_server_exceptions=False)


def test_healthz():
    client = _make_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_interactions_missing_signature_returns_401():
    client = _make_client()
    body = _make_interaction_body("helix_approve_pr", "inc-001")
    resp = client.post(
        "/slack/interactions",
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


def test_interactions_invalid_payload_returns_400():
    ts = str(int(time.time()))
    body = b"payload=not-valid-json"
    sig = _make_sig(SIGNING_SECRET, ts, body.decode())
    client = _make_client()
    resp = client.post(
        "/slack/interactions",
        content=body,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
        },
    )
    assert resp.status_code == 400


def test_interactions_approve_queues_background_task():
    body = _make_interaction_body("helix_approve_pr", "inc-001")
    ts = str(int(time.time()))
    sig = _make_sig(SIGNING_SECRET, ts, body.decode())

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.human_approval.main.handle_approve", new=AsyncMock()):
        from agents.human_approval.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/slack/interactions",
                content=body,
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": sig,
                },
            )

    assert resp.status_code == 200
    assert "inc-001" in resp.json().get("text", "")


def test_interactions_reject_queues_background_task():
    body = _make_interaction_body("helix_reject_pr", "inc-001", username="bob")
    ts = str(int(time.time()))
    sig = _make_sig(SIGNING_SECRET, ts, body.decode())

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.human_approval.main.handle_reject", new=AsyncMock()):
        from agents.human_approval.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/slack/interactions",
                content=body,
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": sig,
                },
            )

    assert resp.status_code == 200
    assert "inc-001" in resp.json().get("text", "")


def test_interactions_unknown_type_returns_empty():
    payload = {"type": "shortcut", "callback_id": "foo"}
    body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(time.time()))
    sig = _make_sig(SIGNING_SECRET, ts, body.decode())

    client = _make_client()
    resp = client.post(
        "/slack/interactions",
        content=body,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {}


def test_interactions_no_actions_returns_empty():
    payload = {"type": "block_actions", "user": {"username": "alice"}, "actions": []}
    body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(time.time()))
    sig = _make_sig(SIGNING_SECRET, ts, body.decode())

    client = _make_client()
    resp = client.post(
        "/slack/interactions",
        content=body,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {}


def test_interactions_missing_incident_id_returns_warning():
    payload = {
        "type": "block_actions",
        "user": {"username": "alice"},
        "actions": [{"action_id": "helix_approve_pr", "value": ""}],
    }
    body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(time.time()))
    sig = _make_sig(SIGNING_SECRET, ts, body.decode())

    client = _make_client()
    resp = client.post(
        "/slack/interactions",
        content=body,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
        },
    )
    assert resp.status_code == 200
    assert "Missing" in resp.json().get("text", "")


def test_interactions_unknown_action_id_returns_empty():
    payload = {
        "type": "block_actions",
        "user": {"username": "alice"},
        "actions": [{"action_id": "some_other_action", "value": "inc-001"}],
    }
    body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(time.time()))
    sig = _make_sig(SIGNING_SECRET, ts, body.decode())

    client = _make_client()
    resp = client.post(
        "/slack/interactions",
        content=body,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {}
