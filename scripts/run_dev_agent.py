"""
Manual dev agent runner — bypasses the full pipeline.

Usage:
    uv run python -m scripts.run_dev_agent

Provider override examples:
    HELIX_DEV_PROVIDER=opencode uv run python -m scripts.run_dev_agent
    HELIX_DEV_PROVIDER=claude-code uv run python -m scripts.run_dev_agent
    HELIX_DEV_OPENCODE_MODEL=ollama/qwen2.514b HELIX_DEV_PROVIDER=opencode uv run python -m scripts.run_dev_agent
    HELIX_DEV_PROVIDER=goose uv run python -m scripts.run_dev_agent
    HELIX_DEV_GOOSE_MODEL=ollama/qwen3.6:latest HELIX_DEV_PROVIDER=goose uv run python -m scripts.run_dev_agent

Clones 88hours/helix-test. Push and PR creation are stubbed out.
Repo left at /tmp/helix-dev-debug after the run — inspect with git status / git diff.
"""

import asyncio
import logging
import os
import shutil

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


os.environ.setdefault("HELIX_DEV_MAX_ITERATIONS", "3")

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

_LOG_FILE = "/tmp/helix-dev-agent.log"
_log_handler = logging.FileHandler(_LOG_FILE, mode="w")
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "DEBUG"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(), _log_handler],
)
print(f"Logging to {_LOG_FILE}")


async def main() -> None:
    os.environ.setdefault("HELIX_GITHUB_REPO", "88hours/helix-test")
    os.environ.setdefault("HELIX_DEV_PROVIDER", "goose")
    os.environ.setdefault("HELIX_DEV_GOOSE_MODEL", "ollama/qwen3.6:latest")
    os.environ.setdefault(
        "HELIX_DEV_GOOSE_SYSTEM",
        "You are a coding agent. Use your shell tool to run commands immediately. "
        "Do not introduce yourself. Do not ask questions. Do not search the web. "
        "Read files and run tests using your tools. "
        "The repository is already cloned in the current working directory.",
    )
    os.environ.setdefault("GITHUB_TOKEN", "dummy")
    os.environ.setdefault("LOG_LEVEL", "DEBUG")
    redis_client = _make_fake_redis()

    crash_report = CrashReport(
        incident_id="debug-001",
        project_id="helix-test",
        source_item_id="sentry-123",
        source="sentry",
        severity=Severity.high,
        error_type="KeyError",
        error_message="'amount'",
        stack_trace=(
            "File fastapi_error.py in trigger_key_error\n"
            "  process_payment({\"card_last4\": \"4242\"})\n"
            "File fastapi_error.py in process_payment\n"
            "  return f\"Charging ${payload['amount']} to card {payload.get('card_last4', 'xxxx')}\""
        ),
        affected_component="payment",
        affected_endpoint="/error/key",
        summary="KeyError raised because process_payment is called without the required 'amount' key in the payload.",
        language="python",
    )

    qa_result = QAResult(
        incident_id="debug-001",
        ticket_id=None,
        ticket_url=None,
        ticket_action=TicketAction.created,
        test_case=TestCase(
            file_path="tests/test_payment.py",
            test_name="test_process_payment_missing_amount",
            content=(
                "def test_process_payment_missing_amount():\n"
                "    from fastapi_error import trigger_key_error\n"
                "    trigger_key_error()  # must not raise KeyError\n"
            ),
            format=TestFormat.pytest,
        ),
        relevant_files=[],
    )

    result = await handle(qa_result, crash_report, redis_client)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
