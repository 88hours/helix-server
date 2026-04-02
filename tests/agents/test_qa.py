"""Tests for agents/qa/agent.py"""
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.models import (
    CrashReport,
    QAResult,
    Severity,
    TicketAction,
)


SAMPLE_YAML = {
    "rollbar": {"webhook_secret_env": "ROLLBAR_WEBHOOK_SECRET"},
    "redis": {"url_env": "REDIS_URL", "ttl_seconds": 604800},
    "agents": {
        "qa": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
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
    monkeypatch.setenv("JIRA_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "dev@acme.com")
    monkeypatch.setenv("JIRA_TOKEN", "jira-token")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "PROJ")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
def crash_report():
    return CrashReport(
        incident_id="inc-001",
        rollbar_item_id="12345",
        severity=Severity.high,
        error_type="KeyError",
        error_message="'item_id'",
        stack_trace='File "checkout.py", line 42, in process\n    item = cart[item_id]',
        affected_component="checkout",
        affected_endpoint="/api/v1/checkout",
        summary="A KeyError in the checkout process.",
    )


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.publish = AsyncMock(return_value=1)
    return r


LLM_RESPONSE = json.dumps({
    "file_path": "tests/test_checkout.py",
    "test_name": "test_checkout_raises_on_missing_item",
    "content": "def test_checkout_raises_on_missing_item():\n    assert False",
})


# ---------------------------------------------------------------------------
# handle()
# ---------------------------------------------------------------------------

async def test_handle_returns_qa_result(crash_report, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.clone_repo", new=AsyncMock()), \
         patch("integrations.jira.find_existing_issue", new=AsyncMock(return_value=None)), \
         patch("integrations.jira.create_issue", new=AsyncMock(return_value=("PROJ-1", "https://jira/PROJ-1"))), \
         patch("agents.qa.agent.complete", new=AsyncMock(return_value=LLM_RESPONSE)):
        from agents.qa.agent import handle
        result = await handle(crash_report, mock_redis)

    assert isinstance(result, QAResult)
    assert result.incident_id == "inc-001"
    assert result.test_case.file_path == "tests/test_checkout.py"
    assert result.ticket_action == TicketAction.created


async def test_handle_updates_existing_ticket(crash_report, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.clone_repo", new=AsyncMock()), \
         patch("integrations.jira.find_existing_issue", new=AsyncMock(return_value=("PROJ-42", "https://jira/PROJ-42"))), \
         patch("integrations.jira.add_comment", new=AsyncMock()), \
         patch("agents.qa.agent.complete", new=AsyncMock(return_value=LLM_RESPONSE)):
        from agents.qa.agent import handle
        result = await handle(crash_report, mock_redis)

    assert result.ticket_id == "PROJ-42"
    assert result.ticket_action == TicketAction.updated


async def test_handle_publishes_event(crash_report, mock_redis):
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML), \
         patch("integrations.github.clone_repo", new=AsyncMock()), \
         patch("integrations.jira.find_existing_issue", new=AsyncMock(return_value=None)), \
         patch("integrations.jira.create_issue", new=AsyncMock(return_value=("PROJ-1", "https://jira/PROJ-1"))), \
         patch("agents.qa.agent.complete", new=AsyncMock(return_value=LLM_RESPONSE)):
        from agents.qa.agent import handle
        await handle(crash_report, mock_redis)

    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[0][0]
    assert "test_case_generated" in channel


# ---------------------------------------------------------------------------
# _extract_paths_from_stack_trace
# ---------------------------------------------------------------------------

def test_extract_paths_basic():
    from agents.qa.agent import _extract_paths_from_stack_trace
    trace = 'File "checkout.py", line 42, in process'
    paths = _extract_paths_from_stack_trace(trace)
    assert "checkout.py" in paths


def test_extract_paths_filters_stdlib():
    from agents.qa.agent import _extract_paths_from_stack_trace
    trace = 'File "/usr/lib/python3.12/json/decoder.py", line 10, in decode'
    paths = _extract_paths_from_stack_trace(trace)
    assert paths == []


def test_extract_paths_filters_site_packages():
    from agents.qa.agent import _extract_paths_from_stack_trace
    trace = 'File "/usr/local/lib/python3.12/site-packages/pydantic/main.py", line 1, in foo'
    paths = _extract_paths_from_stack_trace(trace)
    assert paths == []


def test_extract_paths_deduplicates():
    from agents.qa.agent import _extract_paths_from_stack_trace
    trace = (
        'File "checkout.py", line 1, in a\n'
        'File "checkout.py", line 2, in b'
    )
    paths = _extract_paths_from_stack_trace(trace)
    assert paths.count("checkout.py") == 1


def test_extract_paths_most_recent_first():
    from agents.qa.agent import _extract_paths_from_stack_trace
    trace = (
        'File "module_a.py", line 1, in a\n'
        'File "module_b.py", line 2, in b'
    )
    paths = _extract_paths_from_stack_trace(trace)
    assert paths[0] == "module_b.py"


# ---------------------------------------------------------------------------
# _read_relevant_files
# ---------------------------------------------------------------------------

def test_read_relevant_files_reads_existing_file(tmp_path):
    from agents.qa.agent import _read_relevant_files
    (tmp_path / "checkout.py").write_text("def process(): pass")
    trace = 'File "checkout.py", line 1, in process'
    files = _read_relevant_files(str(tmp_path), trace)
    assert "checkout.py" in files
    assert "process" in files["checkout.py"]


def test_read_relevant_files_skips_missing_file(tmp_path):
    from agents.qa.agent import _read_relevant_files
    trace = 'File "nonexistent.py", line 1, in fn'
    files = _read_relevant_files(str(tmp_path), trace)
    assert files == {}


def test_read_relevant_files_truncates_large_file(tmp_path):
    from agents.qa.agent import _read_relevant_files, _MAX_FILE_CHARS
    big_content = "x" * (_MAX_FILE_CHARS + 1000)
    (tmp_path / "big.py").write_text(big_content)
    trace = 'File "big.py", line 1, in fn'
    files = _read_relevant_files(str(tmp_path), trace)
    assert "[truncated]" in files["big.py"]


def test_read_relevant_files_respects_max_count(tmp_path):
    from agents.qa.agent import _read_relevant_files, _MAX_SOURCE_FILES
    # Create more files than the limit
    trace_lines = []
    for i in range(_MAX_SOURCE_FILES + 3):
        fname = f"module_{i}.py"
        (tmp_path / fname).write_text("pass")
        trace_lines.append(f'File "{fname}", line 1, in fn')
    trace = "\n".join(trace_lines)
    files = _read_relevant_files(str(tmp_path), trace)
    assert len(files) <= _MAX_SOURCE_FILES
