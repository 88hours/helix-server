"""Tests for agents/code_quality/agent.py"""
import json
import pytest
from unittest.mock import AsyncMock, patch

from core.models import (
    CrashReport,
    PRResult,
    QualityResult,
    QualityVerdict,
    Severity,
)


SAMPLE_YAML = {
    "rollbar": {"access_token_env": "ROLLBAR_ACCESS_TOKEN"},
    "redis": {"url_env": "REDIS_URL", "ttl_seconds": 604800},
    "agents": {
        "code_quality": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
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
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("EMAIL_FROM", "helix@acme.com")
    monkeypatch.setenv("EMAIL_TO", "oncall@acme.com")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")


@pytest.fixture
def crash_report():
    return CrashReport(
        incident_id="inc-001",
        rollbar_item_id="12345",
        severity=Severity.high,
        error_type="KeyError",
        error_message="'item_id'",
        stack_trace="...",
        affected_component="checkout",
        affected_endpoint="/api/checkout",
        summary="A KeyError in checkout.",
    )


@pytest.fixture
def pr_result():
    return PRResult(
        incident_id="inc-001",
        pr_url="https://github.com/acme/repo/pull/42",
        pr_number=42,
        branch_name="helix/fix/inc-001-1",
        iterations_taken=1,
        fix_summary="Fixed the KeyError.",
    )


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.publish = AsyncMock(return_value=1)
    return r


PASSED_LLM_RESPONSE = json.dumps({
    "verdict": "passed",
    "test_coverage": "90% — covers the crash path",
    "standards_check": "passed",
    "security_check": "passed",
    "notes": "Looks good.",
    "feedback": "",
})

FAILED_LLM_RESPONSE = json.dumps({
    "verdict": "failed",
    "test_coverage": "60% — missing edge cases",
    "standards_check": "failed",
    "security_check": "passed",
    "notes": "Missing error handling.",
    "feedback": "Add error handling for the edge case.",
})


# ---------------------------------------------------------------------------
# handle() — passed verdict
# ---------------------------------------------------------------------------

async def test_handle_passed_publishes_quality_approved(crash_report, pr_result, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.get_pr_diff", new=AsyncMock(return_value="diff --git a/checkout.py")), \
         patch("agents.code_quality.agent.complete", new=AsyncMock(return_value=PASSED_LLM_RESPONSE)), \
         patch("integrations.slack.post_approval_request", new=AsyncMock()), \
         patch("integrations.email.send_approval_request", new=AsyncMock()):
        from agents.code_quality.agent import handle
        result = await handle(pr_result, crash_report, mock_redis)

    assert isinstance(result, QualityResult)
    assert result.verdict == QualityVerdict.passed

    channel = mock_redis.publish.call_args[0][0]
    assert "quality_approved" in channel


async def test_handle_passed_sends_slack_and_email(crash_report, pr_result, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.get_pr_diff", new=AsyncMock(return_value="diff")), \
         patch("agents.code_quality.agent.complete", new=AsyncMock(return_value=PASSED_LLM_RESPONSE)), \
         patch("integrations.slack.post_approval_request", new=AsyncMock()) as mock_slack, \
         patch("integrations.email.send_approval_request", new=AsyncMock()) as mock_email:
        from agents.code_quality.agent import handle
        await handle(pr_result, crash_report, mock_redis)

    mock_slack.assert_awaited_once()
    mock_email.assert_awaited_once()


# ---------------------------------------------------------------------------
# handle() — failed verdict
# ---------------------------------------------------------------------------

async def test_handle_failed_publishes_quality_rejected(crash_report, pr_result, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.get_pr_diff", new=AsyncMock(return_value="diff")), \
         patch("agents.code_quality.agent.complete", new=AsyncMock(return_value=FAILED_LLM_RESPONSE)):
        from agents.code_quality.agent import handle
        result = await handle(pr_result, crash_report, mock_redis)

    assert result.verdict == QualityVerdict.failed
    assert result.feedback == "Add error handling for the edge case."

    channel = mock_redis.publish.call_args[0][0]
    assert "quality_rejected" in channel


async def test_handle_failed_does_not_send_notifications(crash_report, pr_result, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.get_pr_diff", new=AsyncMock(return_value="diff")), \
         patch("agents.code_quality.agent.complete", new=AsyncMock(return_value=FAILED_LLM_RESPONSE)), \
         patch("integrations.slack.post_approval_request", new=AsyncMock()) as mock_slack, \
         patch("integrations.email.send_approval_request", new=AsyncMock()) as mock_email:
        from agents.code_quality.agent import handle
        await handle(pr_result, crash_report, mock_redis)

    mock_slack.assert_not_awaited()
    mock_email.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle() — result fields
# ---------------------------------------------------------------------------

async def test_handle_result_includes_iteration(crash_report, pr_result, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.get_pr_diff", new=AsyncMock(return_value="diff")), \
         patch("agents.code_quality.agent.complete", new=AsyncMock(return_value=PASSED_LLM_RESPONSE)), \
         patch("integrations.slack.post_approval_request", new=AsyncMock()), \
         patch("integrations.email.send_approval_request", new=AsyncMock()):
        from agents.code_quality.agent import handle
        result = await handle(pr_result, crash_report, mock_redis)

    assert result.iteration == 1
    assert result.pr_url == pr_result.pr_url
