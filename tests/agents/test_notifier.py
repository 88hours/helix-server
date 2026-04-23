"""Tests for agents/notifier/agent.py — handle_pr_created, handle, handle_escalation."""
import logging
import pytest
from unittest.mock import AsyncMock, patch

from core.models import CrashReport, PRResult, Severity
from core.config import get_email_config, get_slack_config


SAMPLE_YAML = {
    "redis": {"url_env": "REDIS_URL", "ttl_seconds": 604800},
    "slack": {
        "token_env": "SLACK_BOT_TOKEN",
        "approval_channel_env": "SLACK_APPROVAL_CHANNEL",
        "signing_secret_env": "SLACK_SIGNING_SECRET",
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

SAMPLE_PR_RESULT = PRResult(
    incident_id="inc-001",
    pr_url="https://github.com/acme/repo/pull/42",
    pr_number=42,
    branch_name="helix/fix-inc-001",
    iterations_taken=1,
    files_changed=["checkout.py"],
    fix_summary="Fixed the KeyError in checkout.",
)


SAMPLE_CRASH_REPORT = CrashReport(
    incident_id="inc-001",
    project_id="",
    source_item_id="12345",
    source="rollbar",
    severity=Severity.high,
    error_type="KeyError",
    error_message="'item_id'",
    stack_trace="...",
    affected_component="checkout",
    affected_endpoint="/api/v1/checkout",
    summary="A KeyError in checkout.",
)


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=None)
    r.xadd = AsyncMock(return_value=b"1234567890-0")
    return r


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APPROVAL_CHANNEL", "C123")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


# ---------------------------------------------------------------------------
# handle_pr_created
# ---------------------------------------------------------------------------

async def test_handle_pr_created_posts_approval(monkeypatch):
    """When Slack is configured and PRResult exists, posts the approval request."""
    mock_redis = AsyncMock()
    post_approval = AsyncMock()

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.notifier.agent.read_pr_result", return_value=SAMPLE_PR_RESULT), \
         patch("agents.notifier.agent.slack.post_approval_request", post_approval):
        from agents.notifier.agent import handle_pr_created
        await handle_pr_created("inc-001", mock_redis)

    post_approval.assert_awaited_once()
    call_kwargs = post_approval.call_args.kwargs
    assert call_kwargs["incident_id"] == "inc-001"
    assert call_kwargs["pr_number"] == 42
    assert "checkout" in call_kwargs["fix_summary"].lower()


async def test_handle_pr_created_no_op_when_token_missing(monkeypatch, caplog):
    """No approval message and no error when SLACK_BOT_TOKEN is absent."""
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    mock_redis = AsyncMock()
    post_approval = AsyncMock()

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.notifier.agent.slack.post_approval_request", post_approval), \
         caplog.at_level(logging.WARNING, logger="agents.notifier.agent"):
        from agents.notifier.agent import handle_pr_created
        await handle_pr_created("inc-001", mock_redis)

    post_approval.assert_not_awaited()
    assert "SLACK_BOT_TOKEN" in caplog.text


async def test_handle_pr_created_no_op_when_channel_missing(monkeypatch, caplog):
    """No approval message and no error when SLACK_APPROVAL_CHANNEL is absent."""
    monkeypatch.delenv("SLACK_APPROVAL_CHANNEL", raising=False)
    mock_redis = AsyncMock()
    post_approval = AsyncMock()

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.notifier.agent.slack.post_approval_request", post_approval), \
         caplog.at_level(logging.WARNING, logger="agents.notifier.agent"):
        from agents.notifier.agent import handle_pr_created
        await handle_pr_created("inc-001", mock_redis)

    post_approval.assert_not_awaited()
    assert "SLACK_APPROVAL_CHANNEL" in caplog.text


async def test_handle_pr_created_logs_error_when_pr_result_missing(caplog):
    """Logs an error and does not raise when PRResult is not found in Redis."""
    mock_redis = AsyncMock()
    post_approval = AsyncMock()

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.notifier.agent.read_pr_result", return_value=None), \
         patch("agents.notifier.agent.slack.post_approval_request", post_approval), \
         caplog.at_level(logging.ERROR, logger="agents.notifier.agent"):
        from agents.notifier.agent import handle_pr_created
        await handle_pr_created("inc-missing", mock_redis)

    post_approval.assert_not_awaited()
    assert "pr_result not found" in caplog.text


# ---------------------------------------------------------------------------
# _load_project_config
# ---------------------------------------------------------------------------

async def test_load_project_config_empty_project_id_returns_env_config():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.notifier.agent import _load_project_config
        slack_cfg, email_cfg = await _load_project_config("")
    assert slack_cfg is not None
    assert email_cfg is not None


async def test_load_project_config_no_database_url_returns_env_config(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.notifier.agent import _load_project_config
        slack_cfg, email_cfg = await _load_project_config("proj-001")
    assert slack_cfg is not None
    assert email_cfg is not None


async def test_load_project_config_project_found_returns_project_config(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    row = {
        "project_id": "proj-001",
        "name": "Acme",
        "repo": "acme/repo",
        "base_branch": "main",
        "language": "python",
        "slack_bot_token": "xoxb-proj",
        "slack_signing_secret": "signing-sec",
        "slack_approval_channel": "C999",
        "sendgrid_api_key": None,
        "smtp_host": "smtp.example.com",
        "email_from": "helix@acme.com",
        "email_to": "oncall@acme.com",
    }
    mock_db = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("agents.notifier.agent.get_db", return_value=mock_ctx), \
         patch("agents.notifier.agent.get_project", new=AsyncMock(return_value=row)):
        from agents.notifier.agent import _load_project_config
        slack_cfg, email_cfg = await _load_project_config("proj-001")
    assert slack_cfg.token == "xoxb-proj"
    assert slack_cfg.approval_channel == "C999"


async def test_load_project_config_project_not_found_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    mock_db = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("agents.notifier.agent.get_db", return_value=mock_ctx), \
         patch("agents.notifier.agent.get_project", new=AsyncMock(return_value=None)), \
         patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.notifier.agent import _load_project_config
        slack_cfg, _ = await _load_project_config("proj-missing")
    assert slack_cfg is not None


async def test_load_project_config_db_exception_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    with patch("agents.notifier.agent.get_db", side_effect=Exception("db down")), \
         patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        from agents.notifier.agent import _load_project_config
        slack_cfg, email_cfg = await _load_project_config("proj-001")
    assert slack_cfg is not None
    assert email_cfg is not None


# ---------------------------------------------------------------------------
# handle — fix_suggested notifications
# ---------------------------------------------------------------------------

async def test_handle_sends_slack_and_email_with_crash_context(mock_redis):
    post_message = AsyncMock()
    send_email = AsyncMock()

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.notifier.agent.read_crash_report", new=AsyncMock(return_value=SAMPLE_CRASH_REPORT)), \
         patch("agents.notifier.agent._load_project_config", new=AsyncMock(return_value=(get_slack_config(), get_email_config()))), \
         patch("agents.notifier.agent.slack.post_message", post_message), \
         patch("agents.notifier.agent.email.send_fix_suggested", send_email):
        from agents.notifier.agent import handle
        await handle("inc-001", "https://github.com/acme/repo/issues/42", mock_redis)

    post_message.assert_awaited_once()
    text = post_message.call_args.kwargs["text"]
    assert "KeyError" in text
    assert "checkout" in text
    assert "https://github.com/acme/repo/issues/42" in text
    send_email.assert_awaited_once()
    assert send_email.call_args.kwargs["incident_id"] == "inc-001"


async def test_handle_uses_placeholder_context_when_crash_report_missing(mock_redis):
    post_message = AsyncMock()
    send_email = AsyncMock()

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.notifier.agent.read_crash_report", new=AsyncMock(return_value=None)), \
         patch("agents.notifier.agent._load_project_config", new=AsyncMock(return_value=(get_slack_config(), get_email_config()))), \
         patch("agents.notifier.agent.slack.post_message", post_message), \
         patch("agents.notifier.agent.email.send_fix_suggested", send_email):
        from agents.notifier.agent import handle
        await handle("inc-001", "https://github.com/acme/repo/issues/42", mock_redis)

    text = post_message.call_args.kwargs["text"]
    assert "unknown" in text
    send_email.assert_awaited_once()
    assert send_email.call_args.kwargs["error_type"] == "unknown"


# ---------------------------------------------------------------------------
# handle_escalation
# ---------------------------------------------------------------------------

async def test_handle_escalation_sends_slack_and_email(mock_redis):
    post_escalation = AsyncMock()
    send_escalation = AsyncMock()

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.notifier.agent.read_crash_report", new=AsyncMock(return_value=SAMPLE_CRASH_REPORT)), \
         patch("agents.notifier.agent._load_project_config", new=AsyncMock(return_value=(get_slack_config(), get_email_config()))), \
         patch("agents.notifier.agent.slack.post_escalation", post_escalation), \
         patch("agents.notifier.agent.email.send_escalation", send_escalation):
        from agents.notifier.agent import handle_escalation
        await handle_escalation(
            incident_id="inc-001",
            crash_summary="A KeyError in checkout.",
            attempts=3,
            context="Attempt 1: tried X\nAttempt 2: tried Y",
            redis_client=mock_redis,
        )

    post_escalation.assert_awaited_once()
    kwargs = post_escalation.call_args.kwargs
    assert kwargs["incident_id"] == "inc-001"
    assert kwargs["attempts"] == 3
    assert "tried X" in kwargs["context"]
    send_escalation.assert_awaited_once()
    assert send_escalation.call_args.kwargs["attempts"] == 3
