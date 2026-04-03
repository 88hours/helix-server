"""
QA Agent — core logic.

Receives a CrashReport, creates or updates a GitHub Issue, clones the target
repository to read relevant source files, then uses the LLM to generate a
minimal failing pytest test case that reproduces the bug.

Entry point: handle()
"""

import logging
import re
import shutil
import tempfile
from pathlib import Path

import redis.asyncio as redis

from agents.qa import prompts
from core.config import get_github_config
from core.events import publish
from core.llm import complete
from core.models import CrashReport, QAResult, TestCase, TestFormat, TicketAction
from core.state import write_qa_result, write_status
from core.utils import extract_json
from integrations import github

logger = logging.getLogger(__name__)

# Maximum number of source files to read and pass to the LLM.
_MAX_SOURCE_FILES = 8

# Maximum characters to read per source file (keeps prompt size manageable).
_MAX_FILE_CHARS = 4_000


async def handle(report: CrashReport, redis_client: redis.Redis) -> QAResult:
    """
    Generate a failing test case for the given crash report.

    Steps:
      1. Create or update a GitHub Issue.
      2. Clone the target repo and read relevant source files.
      3. Call the LLM to generate a failing pytest test case.
      4. Persist the QAResult to Redis.
      5. Publish the test_case_generated event to trigger the Dev Agent.

    Args:
        report:       CrashReport produced by the Crash Handler Agent.
        redis_client: Async Redis client.

    Returns:
        The persisted QAResult.
    """
    logger.info("qa agent started", extra={"incident_id": report.incident_id})

    gh_config = get_github_config()

    # Step 1 — GitHub Issue.
    ticket_id, ticket_url, ticket_action = await _create_or_update_issue(
        report, gh_config.target_repo
    )

    # Step 2 — Clone repo and read relevant source files.
    repo_dir = tempfile.mkdtemp(prefix="helix-qa-")
    try:
        clone_url = f"https://github.com/{gh_config.target_repo}.git"
        await github.clone_repo(clone_url, repo_dir)
        source_files = _read_relevant_files(repo_dir, report.stack_trace)

        # Step 3 — LLM generates the test case.
        prompt = prompts.user(
            error_type=report.error_type,
            error_message=report.error_message,
            stack_trace=report.stack_trace,
            affected_component=report.affected_component,
            affected_endpoint=report.affected_endpoint,
            summary=report.summary,
            source_files=source_files,
        )

        raw_response = await complete(
            agent="qa",
            prompt=prompt,
            system=prompts.SYSTEM,
        )

    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)

    data = extract_json(raw_response)

    test_case = TestCase(
        file_path=data["file_path"],
        test_name=data["test_name"],
        content=data["content"],
        format=TestFormat.pytest,
    )

    result = QAResult(
        incident_id=report.incident_id,
        ticket_id=ticket_id,
        ticket_url=ticket_url,
        ticket_action=ticket_action,
        test_case=test_case,
        relevant_files=list(source_files.keys()),
    )

    await write_qa_result(redis_client, result)
    await write_status(redis_client, report.incident_id, "test_case_generated")
    await publish(
        redis_client,
        "test_case_generated",
        report.incident_id,
        result.model_dump(mode="json"),
    )

    logger.info(
        "qa agent complete",
        extra={
            "incident_id": report.incident_id,
            "ticket_id": ticket_id,
            "test_file": test_case.file_path,
        },
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _create_or_update_issue(
    report: CrashReport,
    repo: str,
) -> tuple[str, str, TicketAction]:
    """
    Find an existing GitHub Issue for this bug or create a new one.

    Returns:
        (issue_number, issue_url, ticket_action)
    """
    title = f"[Helix] {report.error_type}: {report.error_message[:120]}"
    body = (
        f"**Incident ID:** {report.incident_id}\n"
        f"**Severity:** {report.severity.value}\n"
        f"**Affected component:** {report.affected_component}\n"
        f"**Affected endpoint:** {report.affected_endpoint}\n\n"
        f"**Summary:**\n{report.summary}\n\n"
        f"**Stack trace:**\n```\n{report.stack_trace}\n```"
    )

    existing = await github.find_existing_issue(repo=repo, title=title)

    if existing:
        issue_number, issue_url = existing
        await github.add_issue_comment(
            repo=repo,
            issue_number=issue_number,
            comment=f"Helix re-detected this crash (incident `{report.incident_id}`). Generating a new test case.",
        )
        return issue_number, issue_url, TicketAction.updated

    issue_number, issue_url = await github.create_issue(
        repo=repo,
        title=title,
        body=body,
        labels=["bug", "helix"],
    )
    return issue_number, issue_url, TicketAction.created


def _read_relevant_files(repo_dir: str, stack_trace: str) -> dict[str, str]:
    """
    Identify and read the source files most likely involved in the crash.

    Extracts file paths from the stack trace, filters to paths that exist
    in the local clone, and reads up to _MAX_SOURCE_FILES of them.

    Args:
        repo_dir:    Path to the cloned repository root.
        stack_trace: Formatted stack trace string.

    Returns:
        Mapping of relative file path → file content (truncated if large).
    """
    candidate_paths = _extract_paths_from_stack_trace(stack_trace)
    result: dict[str, str] = {}

    for relative_path in candidate_paths:
        if len(result) >= _MAX_SOURCE_FILES:
            break
        full_path = Path(repo_dir) / relative_path
        if not full_path.is_file():
            continue
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            if len(content) > _MAX_FILE_CHARS:
                content = content[:_MAX_FILE_CHARS] + "\n... [truncated]"
            result[relative_path] = content
        except OSError as exc:
            logger.warning(
                "could not read source file",
                extra={"path": relative_path, "error": str(exc)},
            )

    return result


def _extract_paths_from_stack_trace(stack_trace: str) -> list[str]:
    """
    Parse a Python stack trace and return unique relative file paths.

    Filters out stdlib and site-packages paths — we only want application code.

    Args:
        stack_trace: Formatted Python stack trace string.

    Returns:
        List of unique relative file paths, in order of appearance (deepest first).
    """
    pattern = re.compile(r'File "([^"]+)", line \d+')
    seen: set[str] = set()
    paths: list[str] = []

    for match in pattern.finditer(stack_trace):
        path = match.group(1)
        # Skip absolute paths pointing to stdlib or installed packages.
        if path.startswith("/") and ("site-packages" in path or "/lib/python" in path):
            continue
        # Normalise: strip leading "./" if present.
        path = path.lstrip("./")
        if path and path not in seen:
            seen.add(path)
            paths.append(path)

    # Return most recent frame first (closest to the error).
    return list(reversed(paths))
