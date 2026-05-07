"""Tests for agents/dev/agent.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
        "dev": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    },
    "github": {
        "token_env": "GITHUB_TOKEN",
        "target_repo": "acme/repo",
        "base_branch": "main",
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
        project_id="proj-001",
        source_item_id="12345", source="rollbar",
        severity=Severity.high,
        error_type="AttributeError",
        error_message="'NoneType' object has no attribute 'get'",
        stack_trace="File send_error.py line 25 in greet_user",
        affected_component="greet_user",
        affected_endpoint="/api/greet",
        summary="greet_user crashes when user is None.",
    )


@pytest.fixture
def qa_result():
    return QAResult(
        incident_id="inc-001",
        ticket_id="42",
        ticket_url="https://github.com/acme/repo/issues/42",
        ticket_action=TicketAction.created,
        test_case=TestCase(
            file_path="tests/test_greet.py",
            test_name="test_greet_user_missing",
            content="def test_greet_user_missing():\n    assert greet_user('bob') is not None",
            format=TestFormat.pytest,
        ),
        relevant_files=["send_error.py"],
    )


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.publish = AsyncMock(return_value=1)
    r.xadd = AsyncMock(return_value=b"1234567890-0")
    return r


@pytest.fixture
def pr_result():
    return PRResult(
        incident_id="inc-001",
        pr_url="https://github.com/acme/repo/pull/7",
        pr_number=7,
        branch_name="helix/fix/inc-001-1",
        iterations_taken=1,
        files_changed=["send_error.py"],
        fix_summary="Added None guard in greet_user.",
    )


LLM_FIX = (
    "**Root cause:** `get_user` returns None for unknown users.\n\n"
    "```python\n# Before\nreturn f\"Hello, {user.get('name')}!\"\n"
    "# After\nif user is None:\n    return 'Unknown user'\n"
    "return f\"Hello, {user.get('name')}!\"\n```"
)


# ---------------------------------------------------------------------------
# handle() — pre-TDD steps (comment + event); TDD loop is mocked out
# ---------------------------------------------------------------------------

async def test_handle_posts_fix_comment(crash_report, qa_result, mock_redis, pr_result):
    """handle() must post a Helix comment to the GitHub Issue."""
    add_comment = AsyncMock()
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.dev.agent._fetch_source_files", new=AsyncMock(return_value={})), \
         patch("agents.dev.agent.complete", new=AsyncMock(return_value=LLM_FIX)), \
         patch("integrations.github.add_issue_comment", new=add_comment), \
         patch("agents.dev.agent._tdd_loop", new=AsyncMock(return_value=pr_result)):
        from agents.dev.agent import handle
        await handle(qa_result, crash_report, mock_redis)

    add_comment.assert_awaited_once()
    _, kwargs = add_comment.call_args
    assert "[Helix]" in kwargs["comment"]


async def test_handle_publishes_fix_suggested_event(crash_report, qa_result, mock_redis, pr_result):
    """handle() must publish fix_suggested after posting the GitHub comment."""
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.dev.agent._fetch_source_files", new=AsyncMock(return_value={})), \
         patch("agents.dev.agent.complete", new=AsyncMock(return_value=LLM_FIX)), \
         patch("integrations.github.add_issue_comment", new=AsyncMock()), \
         patch("agents.dev.agent._tdd_loop", new=AsyncMock(return_value=pr_result)):
        from agents.dev.agent import handle
        await handle(qa_result, crash_report, mock_redis)

    mock_redis.xadd.assert_called_once()
    stream = mock_redis.xadd.call_args[0][0]
    assert "fix_suggested" in stream


async def test_handle_calls_tdd_loop(crash_report, qa_result, mock_redis, pr_result):
    """handle() must invoke _tdd_loop after posting the comment and the event."""
    tdd_loop = AsyncMock(return_value=pr_result)
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.dev.agent._fetch_source_files", new=AsyncMock(return_value={})), \
         patch("agents.dev.agent.complete", new=AsyncMock(return_value=LLM_FIX)), \
         patch("integrations.github.add_issue_comment", new=AsyncMock()), \
         patch("agents.dev.agent._tdd_loop", new=tdd_loop):
        from agents.dev.agent import handle
        result = await handle(qa_result, crash_report, mock_redis)

    tdd_loop.assert_awaited_once()
    assert result == pr_result


async def test_handle_passes_diagnosis_to_tdd_loop(crash_report, qa_result, mock_redis, pr_result):
    """handle() must pass a diagnosis (or None) to _tdd_loop."""
    tdd_loop = AsyncMock(return_value=pr_result)
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.dev.agent._fetch_source_files", new=AsyncMock(return_value={})), \
         patch("agents.dev.agent.complete", new=AsyncMock(return_value=LLM_FIX)), \
         patch("integrations.github.add_issue_comment", new=AsyncMock()), \
         patch("agents.dev.agent._tdd_loop", new=tdd_loop):
        from agents.dev.agent import handle
        await handle(qa_result, crash_report, mock_redis)

    _, kwargs = tdd_loop.call_args
    assert "diagnosis" in kwargs


# ---------------------------------------------------------------------------
# _fetch_source_files
# ---------------------------------------------------------------------------

async def test_fetch_source_files_returns_content():
    import base64
    fake_content = base64.b64encode(b"def get_user(): pass").decode()

    mock_response = MagicMock()
    mock_response.json.return_value = {"content": fake_content + "\n"}
    mock_response.raise_for_status.return_value = None

    with patch("agents.dev.agent.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_response)

        from agents.dev.agent import _fetch_source_files
        result = await _fetch_source_files("acme/repo", ["send_error.py"])

    assert "send_error.py" in result
    assert "get_user" in result["send_error.py"]


# ---------------------------------------------------------------------------
# Pure helpers — _tests_passed, _extract_explanation, _build_pr_body
# ---------------------------------------------------------------------------

def test_tests_passed_returns_true_when_sentinel_present():
    from agents.dev.agent import _tests_passed
    assert _tests_passed("running suite...\nTESTS_PASSED\nFixed null check") is True


def test_tests_passed_returns_false_when_sentinel_absent():
    from agents.dev.agent import _tests_passed
    assert _tests_passed("TESTS_FAILED\nCould not locate root cause") is False


def test_extract_explanation_after_tests_passed():
    from agents.dev.agent import _extract_explanation
    assert _extract_explanation("TESTS_PASSED\nAdded None guard") == "Added None guard"


def test_extract_explanation_after_tests_failed():
    from agents.dev.agent import _extract_explanation
    assert _extract_explanation("TESTS_FAILED\nCould not reproduce") == "Could not reproduce"


def test_extract_explanation_no_sentinel_returns_stripped_response():
    from agents.dev.agent import _extract_explanation
    assert _extract_explanation("  some raw output  ") == "some raw output"


def test_build_pr_body_contains_all_key_fields(crash_report, qa_result):
    from agents.dev.agent import _build_pr_body
    body = _build_pr_body(crash_report, qa_result, "Added None guard in greet_user", 2)
    assert "AttributeError" in body
    assert crash_report.incident_id in body
    assert qa_result.test_case.file_path in body
    assert "2 iteration" in body
    assert qa_result.ticket_url in body


# ---------------------------------------------------------------------------
# _get_changed_files
# ---------------------------------------------------------------------------

async def test_get_changed_files_returns_list():
    from agents.dev.agent import _get_changed_files
    with patch("integrations.github._git", new=AsyncMock(return_value="fix.py\ntest_fix.py\n")):
        result = await _get_changed_files("/tmp/repo")
    assert result == ["fix.py", "test_fix.py"]


async def test_get_changed_files_returns_empty_list_on_error():
    from agents.dev.agent import _get_changed_files
    with patch("integrations.github._git", side_effect=RuntimeError("git error")):
        result = await _get_changed_files("/tmp/repo")
    assert result == []


# ---------------------------------------------------------------------------
# _post_failure_comment
# ---------------------------------------------------------------------------

async def test_post_failure_comment_includes_attempt_summaries(qa_result):
    from core.permissions import load_permissions
    permissions = load_permissions("dev")
    add_comment = AsyncMock()
    with patch("integrations.github.add_issue_comment", new=add_comment):
        from agents.dev.agent import _post_failure_comment
        await _post_failure_comment(qa_result, "acme/repo", ["Tried guard", "Tried refactor"], permissions)
    comment = add_comment.call_args.kwargs["comment"]
    assert "Attempt 1" in comment
    assert "Tried guard" in comment
    assert "Attempt 2" in comment
    assert "Tried refactor" in comment


async def test_post_failure_comment_no_attempts_shows_placeholder(qa_result):
    from core.permissions import load_permissions
    permissions = load_permissions("dev")
    add_comment = AsyncMock()
    with patch("integrations.github.add_issue_comment", new=add_comment):
        from agents.dev.agent import _post_failure_comment
        await _post_failure_comment(qa_result, "acme/repo", [], permissions)
    comment = add_comment.call_args.kwargs["comment"]
    assert "No attempts were recorded" in comment


async def test_post_failure_comment_swallows_github_exception(qa_result):
    from core.permissions import load_permissions
    permissions = load_permissions("dev")
    with patch("integrations.github.add_issue_comment", side_effect=Exception("network error")):
        from agents.dev.agent import _post_failure_comment
        # must not raise
        await _post_failure_comment(qa_result, "acme/repo", [], permissions)


# ---------------------------------------------------------------------------
# _escalate
# ---------------------------------------------------------------------------

async def test_escalate_writes_status_and_publishes_fix_failed(crash_report, mock_redis):
    from core.permissions import load_permissions
    permissions = load_permissions("dev")
    mock_write_status = AsyncMock()
    mock_publish = AsyncMock()
    with patch("agents.dev.agent.write_status", new=mock_write_status), \
         patch("agents.dev.agent.publish", new=mock_publish):
        from agents.dev.agent import _escalate
        await _escalate(crash_report, ["Tried guard"], mock_redis, permissions)
    mock_write_status.assert_awaited_once_with(mock_redis, crash_report.incident_id, "fix_failed")
    mock_publish.assert_awaited_once()
    payload = mock_publish.call_args[0][3]
    assert payload["incident_id"] == crash_report.incident_id
    assert "Tried guard" in payload["context"]


async def test_escalate_with_no_attempts_sets_placeholder_context(crash_report, mock_redis):
    from core.permissions import load_permissions
    permissions = load_permissions("dev")
    mock_publish = AsyncMock()
    with patch("agents.dev.agent.write_status", new=AsyncMock()), \
         patch("agents.dev.agent.publish", new=mock_publish):
        from agents.dev.agent import _escalate
        await _escalate(crash_report, [], mock_redis, permissions)
    assert "No attempts recorded" in mock_publish.call_args[0][3]["context"]


# ---------------------------------------------------------------------------
# _tdd_loop — success on first iteration
# ---------------------------------------------------------------------------

async def test_tdd_loop_returns_pr_result_on_first_pass(qa_result, crash_report, mock_redis):
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()
    from core.permissions import load_permissions
    permissions = load_permissions("dev")

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.dev.agent.read_iterations", new=AsyncMock(return_value=0)), \
         patch("agents.dev.agent.increment_iterations", new=AsyncMock(return_value=1)), \
         patch("agents.dev.agent.write_pr_result", new=AsyncMock()), \
         patch("agents.dev.agent.write_status", new=AsyncMock()), \
         patch("agents.dev.agent.publish", new=AsyncMock()), \
         patch("agents.dev.agent.complete", new=AsyncMock(return_value="TESTS_PASSED\nAdded None guard")), \
         patch("integrations.github.clone_repo", new=AsyncMock()), \
         patch("integrations.github.checkout_branch", new=AsyncMock()), \
         patch("integrations.github.write_file", new=AsyncMock()), \
         patch("integrations.github.commit_and_push", new=AsyncMock()), \
         patch("integrations.github.create_pull_request", new=AsyncMock(return_value=(7, "https://github.com/acme/repo/pull/7"))), \
         patch("agents.dev.agent._get_changed_files", new=AsyncMock(return_value=["send_error.py"])):
        from agents.dev.agent import _tdd_loop
        result = await _tdd_loop(
            qa_result=qa_result,
            crash_report=crash_report,
            diagnosis=None,
            redis_client=mock_redis,
            permissions=permissions,
        )

    assert result.pr_number == 7
    assert result.iterations_taken == 1
    assert f"helix/fix/{crash_report.incident_id[:8]}-1" == result.branch_name


# ---------------------------------------------------------------------------
# _tdd_loop — iterations already exhausted before starting
# ---------------------------------------------------------------------------

async def test_tdd_loop_raises_when_max_iterations_already_reached(qa_result, crash_report, mock_redis):
    from core.permissions import load_permissions
    permissions = load_permissions("dev")

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.dev.agent.read_iterations", new=AsyncMock(return_value=3)), \
         patch("agents.dev.agent._post_failure_comment", new=AsyncMock()), \
         patch("agents.dev.agent._escalate", new=AsyncMock()):
        from agents.dev.agent import _tdd_loop
        with pytest.raises(RuntimeError, match="exhausted"):
            await _tdd_loop(
                qa_result=qa_result,
                crash_report=crash_report,
                diagnosis=None,
                redis_client=mock_redis,
                permissions=permissions,
            )


# ---------------------------------------------------------------------------
# _tdd_loop — all iterations fail
# ---------------------------------------------------------------------------

async def test_tdd_loop_raises_after_all_iterations_fail(qa_result, crash_report, mock_redis):
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()
    from core.permissions import load_permissions
    permissions = load_permissions("dev")

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.dev.agent.read_iterations", new=AsyncMock(return_value=0)), \
         patch("agents.dev.agent.increment_iterations", new=AsyncMock(side_effect=[1, 2, 3])), \
         patch("agents.dev.agent.write_status", new=AsyncMock()), \
         patch("agents.dev.agent.publish", new=AsyncMock()), \
         patch("agents.dev.agent.complete", new=AsyncMock(return_value="TESTS_FAILED\nCould not fix")), \
         patch("integrations.github.clone_repo", new=AsyncMock()), \
         patch("integrations.github.checkout_branch", new=AsyncMock()), \
         patch("integrations.github.write_file", new=AsyncMock()), \
         patch("agents.dev.agent._post_failure_comment", new=AsyncMock()), \
         patch("agents.dev.agent._escalate", new=AsyncMock()):
        from agents.dev.agent import _tdd_loop
        with pytest.raises(RuntimeError, match="exhausted"):
            await _tdd_loop(
                qa_result=qa_result,
                crash_report=crash_report,
                diagnosis=None,
                redis_client=mock_redis,
                permissions=permissions,
            )


# ---------------------------------------------------------------------------
# _tdd_loop — repo lock not acquired
# ---------------------------------------------------------------------------

async def test_tdd_loop_raises_when_repo_lock_not_acquired(qa_result, crash_report, mock_redis):
    mock_redis.set = AsyncMock(return_value=False)
    from core.permissions import load_permissions
    permissions = load_permissions("dev")

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.dev.agent.read_iterations", new=AsyncMock(return_value=0)), \
         patch("agents.dev.agent._REPO_LOCK_RETRIES", 1), \
         patch("agents.dev.agent._REPO_LOCK_RETRY_DELAY", 0):
        from agents.dev.agent import _tdd_loop
        with pytest.raises(RuntimeError, match="repo lock"):
            await _tdd_loop(
                qa_result=qa_result,
                crash_report=crash_report,
                diagnosis=None,
                redis_client=mock_redis,
                permissions=permissions,
            )


# ---------------------------------------------------------------------------
# handle — timeout escalation
# ---------------------------------------------------------------------------

async def test_handle_escalates_and_raises_on_timeout(crash_report, qa_result, mock_redis):
    import asyncio as _asyncio

    async def _hang(*args, **kwargs):
        await _asyncio.sleep(999)

    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("agents.dev.agent._fetch_source_files", new=AsyncMock(return_value={})), \
         patch("agents.dev.agent.complete", new=AsyncMock(return_value=LLM_FIX)), \
         patch("integrations.github.add_issue_comment", new=AsyncMock()), \
         patch("agents.dev.agent.write_status", new=AsyncMock()), \
         patch("agents.dev.agent.publish", new=AsyncMock()), \
         patch("agents.dev.agent._tdd_loop", new=_hang), \
         patch("agents.dev.agent._escalate", new=AsyncMock()) as mock_escalate, \
         patch("agents.dev.agent._TDD_TIMEOUT", 0.01):
        from agents.dev.agent import handle
        with pytest.raises(RuntimeError, match="timed out"):
            await handle(qa_result, crash_report, mock_redis)

    mock_escalate.assert_awaited_once()


async def test_fetch_source_files_skips_missing():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("404")

    with patch("agents.dev.agent.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_response)

        from agents.dev.agent import _fetch_source_files
        result = await _fetch_source_files("acme/repo", ["nonexistent.py"])

    assert result == {}
