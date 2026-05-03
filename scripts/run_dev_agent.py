"""
Manual dev agent runner — bypasses the full pipeline.

Usage:
    uv run python -m scripts.run_dev_agent

Provider override examples:
    HELIX_DEV_PROVIDER=opencode uv run python -m scripts.run_dev_agent
    HELIX_DEV_PROVIDER=claude-code uv run python -m scripts.run_dev_agent
    HELIX_DEV_OPENCODE_MODEL=ollama/qwen2.514b HELIX_DEV_PROVIDER=opencode uv run python -m scripts.run_dev_agent

Clones 88hours/helix-test. Push and PR creation are stubbed out.
Repo left at /tmp/helix-dev-debug after the run — inspect with git status / git diff.
"""

import asyncio
import logging
import os
import shutil

from dotenv import load_dotenv
load_dotenv()

from unittest.mock import AsyncMock


def _make_fake_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.publish = AsyncMock(return_value=0)
    r.expire = AsyncMock(return_value=True)
    _counter = 0

    def _incr(*_, **__):
        nonlocal _counter
        _counter += 1
        return _counter

    r.incr = AsyncMock(side_effect=_incr)
    return r


import agents.dev.agent as _dev_agent
import integrations.github as _github

_DEV_REPO_DIR = "/tmp/helix-dev-debug"
shutil.rmtree(_DEV_REPO_DIR, ignore_errors=True)

_dev_agent.tempfile = type("_tmpfile", (), {"mkdtemp": staticmethod(lambda **_: _DEV_REPO_DIR)})()
_dev_agent.shutil = type("_shutil", (), {"rmtree": staticmethod(lambda *_, **__: None)})()
_github.commit_and_push = AsyncMock()
_github.create_pull_request = AsyncMock(return_value=(0, "https://github.com/88hours/helix-test/pull/0"))

from agents.dev.agent import handle
from core.models import (
    CrashReport,
    QAResult,
    TestCase,
    TestFormat,
    TicketAction,
    Severity,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "DEBUG"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def main() -> None:
    os.environ.setdefault("HELIX_GITHUB_REPO", "88hours/helix-test")
    os.environ.setdefault("HELIX_DEV_PROVIDER", "claude-code")
    os.environ.setdefault("HELIX_DEV_OPENCODE_MODEL", "ollama/qwen2.514b")
    os.environ.setdefault("GITHUB_TOKEN", "dummy")

    redis_client = _make_fake_redis()

    crash_report = CrashReport(
        incident_id="debug-001",
        project_id="test-project",
        source_item_id="sentry-123",
        source="sentry",
        severity=Severity.high,
        error_type="KeyError",
        error_message="'user_id'",
        stack_trace="File auth/login.py line 42 in login\n  return session['user_id']",
        affected_component="auth",
        affected_endpoint="/login",
        summary="KeyError raised when user_id is missing from session dict in login handler.",
        language="python",
    )

    qa_result = QAResult(
        incident_id="debug-001",
        ticket_id=None,
        ticket_url=None,
        ticket_action=TicketAction.created,
        test_case=TestCase(
            file_path="tests/test_auth.py",
            test_name="test_login_missing_user_id",
            content=(
                "def test_login_missing_user_id():\n"
                "    from auth.login import login\n"
                "    assert login({}) is not None\n"
            ),
            format=TestFormat.pytest,
        ),
        relevant_files=[],
    )

    result = await handle(qa_result, crash_report, redis_client)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
