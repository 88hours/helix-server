"""Tests for agents/dev/agent.py"""
import pytest
from unittest.mock import AsyncMock, patch

from core.models import (
    CrashReport,
    PRResult,
    QAResult,
    Severity,
    TestCase,
    TestFormat,
    TicketAction,
)


SAMPLE_YAML = {
    "rollbar": {"access_token_env": "ROLLBAR_ACCESS_TOKEN"},
    "redis": {"url_env": "REDIS_URL", "ttl_seconds": 604800},
    "agents": {
        "dev": {"provider": "claude-code", "model": "claude-code"},
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
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "signing-secret")
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
        stack_trace="File checkout.py line 42",
        affected_component="checkout",
        affected_endpoint="/api/checkout",
        summary="A KeyError in checkout.",
    )


@pytest.fixture
def qa_result():
    return QAResult(
        incident_id="inc-001",
        ticket_id="PROJ-1",
        ticket_url="https://jira/PROJ-1",
        ticket_action=TicketAction.created,
        test_case=TestCase(
            file_path="tests/test_checkout.py",
            test_name="test_checkout_raises",
            content="def test_checkout_raises(): assert False",
            format=TestFormat.pytest,
        ),
    )


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=b"0")
    r.publish = AsyncMock(return_value=1)
    # Simulate increment: first call returns 1
    r.incr = AsyncMock(side_effect=[1, 2, 3])
    return r


def _pr_result():
    return PRResult(
        incident_id="inc-001",
        pr_url="https://github.com/acme/repo/pull/1",
        pr_number=1,
        branch_name="helix/fix/inc-001-1",
        iterations_taken=1,
        fix_summary="Fixed the KeyError.",
    )


# ---------------------------------------------------------------------------
# _tests_passed / _extract_explanation
# ---------------------------------------------------------------------------

def test_tests_passed_true():
    from agents.dev.agent import _tests_passed
    assert _tests_passed("blah TESTS_PASSED explanation") is True


def test_tests_passed_false():
    from agents.dev.agent import _tests_passed
    assert _tests_passed("TESTS_FAILED explanation") is False


def test_extract_explanation_after_tests_passed():
    from agents.dev.agent import _extract_explanation
    result = _extract_explanation("TESTS_PASSED\nFixed the bug.")
    assert result == "Fixed the bug."


def test_extract_explanation_after_tests_failed():
    from agents.dev.agent import _extract_explanation
    result = _extract_explanation("TESTS_FAILED\nStill broken.")
    assert result == "Still broken."


def test_extract_explanation_no_sentinel():
    from agents.dev.agent import _extract_explanation
    result = _extract_explanation("No sentinel here.")
    assert result == "No sentinel here."


# ---------------------------------------------------------------------------
# _build_pr_body
# ---------------------------------------------------------------------------

def test_build_pr_body_contains_key_fields(crash_report, qa_result):
    from agents.dev.agent import _build_pr_body
    body = _build_pr_body(crash_report, qa_result, "Fixed by adding a guard.", 1)
    assert "inc-001" in body
    assert "KeyError" in body
    assert "checkout" in body
    assert "Fixed by adding a guard." in body
    assert "PROJ-1" in body


# ---------------------------------------------------------------------------
# _get_changed_files
# ---------------------------------------------------------------------------

async def test_get_changed_files_returns_list():
    from agents.dev.agent import _get_changed_files
    with patch("integrations.github._git", new=AsyncMock(return_value="checkout.py\nfoo.py")):
        files = await _get_changed_files("/tmp/repo")
    assert files == ["checkout.py", "foo.py"]


async def test_get_changed_files_returns_empty_on_error():
    from agents.dev.agent import _get_changed_files
    with patch("integrations.github._git", side_effect=RuntimeError("git failed")):
        files = await _get_changed_files("/tmp/repo")
    assert files == []


# ---------------------------------------------------------------------------
# _escalate
# ---------------------------------------------------------------------------

async def test_escalate_calls_slack_and_email(crash_report):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.slack.post_escalation", new=AsyncMock()) as mock_slack, \
         patch("integrations.email.send_escalation", new=AsyncMock()) as mock_email:
        from agents.dev.agent import _escalate
        from core.config import get_slack_config, get_email_config
        with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
            sc = get_slack_config()
            ec = get_email_config()
        await _escalate(crash_report, ["attempt 1"], sc, ec)

    mock_slack.assert_awaited_once()
    mock_email.assert_awaited_once()


async def test_escalate_no_context_uses_placeholder(crash_report):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.slack.post_escalation", new=AsyncMock()) as mock_slack, \
         patch("integrations.email.send_escalation", new=AsyncMock()):
        from agents.dev.agent import _escalate
        from core.config import get_slack_config, get_email_config
        with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
            sc = get_slack_config()
            ec = get_email_config()
        await _escalate(crash_report, [], sc, ec)

    call_kwargs = mock_slack.call_args.kwargs
    assert "No attempts recorded." in call_kwargs.get("context", "")


# ---------------------------------------------------------------------------
# handle() — success path
# ---------------------------------------------------------------------------

async def test_handle_success(crash_report, qa_result, mock_redis):
    # Simulate: iterations=0, then increment to 1, TESTS_PASSED on first try
    mock_redis.get = AsyncMock(return_value=b"0")
    mock_redis.incr = AsyncMock(return_value=1)

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.clone_repo", new=AsyncMock()), \
         patch("integrations.github.checkout_branch", new=AsyncMock()), \
         patch("integrations.github.write_file", new=AsyncMock()), \
         patch("integrations.github.commit_and_push", new=AsyncMock()), \
         patch("integrations.github.create_pull_request", new=AsyncMock(return_value=(42, "https://github.com/pr/42"))), \
         patch("integrations.github._git", new=AsyncMock(return_value="checkout.py")), \
         patch("agents.dev.agent.complete", new=AsyncMock(return_value="TESTS_PASSED\nFixed the bug.")):
        from agents.dev.agent import handle
        result = await handle(qa_result, crash_report, mock_redis)

    assert isinstance(result, PRResult)
    assert result.pr_number == 42
    assert result.iterations_taken == 1


# ---------------------------------------------------------------------------
# handle() — exhausted iterations
# ---------------------------------------------------------------------------

async def test_handle_raises_when_iterations_exhausted(crash_report, qa_result, mock_redis):
    # Simulate already at MAX_ITERATIONS
    mock_redis.get = AsyncMock(return_value=b"3")

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.slack.post_escalation", new=AsyncMock()), \
         patch("integrations.email.send_escalation", new=AsyncMock()):
        from agents.dev.agent import handle
        with pytest.raises(RuntimeError, match="exhausted"):
            await handle(qa_result, crash_report, mock_redis)


# ---------------------------------------------------------------------------
# handle_retry() — passes quality_feedback through
# ---------------------------------------------------------------------------

async def test_handle_retry_passes_feedback(crash_report, qa_result, mock_redis):
    mock_redis.get = AsyncMock(return_value=b"0")
    mock_redis.incr = AsyncMock(return_value=1)

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.clone_repo", new=AsyncMock()), \
         patch("integrations.github.checkout_branch", new=AsyncMock()), \
         patch("integrations.github.write_file", new=AsyncMock()), \
         patch("integrations.github.commit_and_push", new=AsyncMock()), \
         patch("integrations.github.create_pull_request", new=AsyncMock(return_value=(1, "https://github.com/pr/1"))), \
         patch("integrations.github._git", new=AsyncMock(return_value="")), \
         patch("agents.dev.agent.complete", new=AsyncMock(return_value="TESTS_PASSED\nRetried fix.")) as mock_complete:
        from agents.dev.agent import handle_retry
        result = await handle_retry(qa_result, crash_report, "needs better test", mock_redis)

    assert result.pr_number == 1
    # quality_feedback only used on iteration==1; verify complete was called
    mock_complete.assert_awaited_once()
