"""
QA Agent — core logic.

Receives a CrashReport, creates or updates a GitHub Issue, clones the target
repository to read relevant source files, then uses the LLM to generate a
minimal failing pytest test case that asserts the correct behaviour of the
affected function (not that the crash occurs).

The LLM call is retried up to _MAX_TEST_RETRIES times when the generated test
is detected to assert the crash rather than the fix (e.g. pytest.raises with
the same exception type as the crash report).

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

# Maximum number of times to retry LLM generation when the test fails validation.
_MAX_TEST_RETRIES = 2


async def handle(report: CrashReport, redis_client: redis.Redis) -> QAResult:
    """
    Generate a failing test case for the given crash report.

    Steps:
      1. Create or update a GitHub Issue.
      2. Clone the target repo and read relevant source files.
      3. Call the LLM to generate a failing pytest test case.
      4. Post the generated test case as a comment on the GitHub Issue.
      5. Persist the QAResult to Redis.
      6. Publish the test_case_generated event to trigger the Dev Agent.

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

        # Step 3 — LLM generates the test case (retried if validation fails).
        base_prompt = prompts.user(
            error_type=report.error_type,
            error_message=report.error_message,
            stack_trace=report.stack_trace,
            affected_component=report.affected_component,
            affected_endpoint=report.affected_endpoint,
            summary=report.summary,
            source_files=source_files,
        )

        raw_response = None
        rejection_note = ""
        for attempt in range(1, _MAX_TEST_RETRIES + 2):  # attempts: 1, 2, 3
            prompt = base_prompt if not rejection_note else base_prompt + rejection_note
            raw_response = await complete(
                agent="qa",
                prompt=prompt,
                system=prompts.SYSTEM,
            )
            data = extract_json(raw_response)
            problem = _check_test(data.get("content", ""), report.error_type)
            if not problem:
                break
            logger.warning(
                "qa agent test failed validation — retrying",
                extra={
                    "incident_id": report.incident_id,
                    "attempt": attempt,
                    "problem": problem,
                },
            )
            rejection_note = prompts.rejection_note(problem)

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

    # Post the generated test case as a comment on the GitHub Issue before
    # handing off to the Dev Agent, so reviewers can see what will be run.
    test_comment = (
        f"**Generated test case** (`{test_case.file_path}::{test_case.test_name}`):\n\n"
        f"```python\n{test_case.content}\n```\n\n"
        f"Helix is now running this test and attempting a fix (incident `{report.incident_id}`)."
    )
    logger.debug(
        "posting test case to github issue",
        extra={"incident_id": report.incident_id, "issue_number": ticket_id},
    )
    await github.add_issue_comment(
        repo=gh_config.target_repo,
        issue_number=ticket_id,
        comment=test_comment,
    )
    logger.debug("test case posted to github issue", extra={"incident_id": report.incident_id})

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


def _check_test(test_content: str, error_type: str) -> str:
    """
    Return a problem description if the test content looks wrong, or "" if it is fine.

    Catches the most common mistake: asserting the crash occurs (pytest.raises
    with the same exception type as the crash report) instead of asserting the
    correct return value.

    Args:
        test_content: Full content of the generated test file.
        error_type:   Exception class from the crash report, e.g. "AttributeError".

    Returns:
        A plain-English description of the problem, or "" if the test looks valid.
    """
    # Detect: pytest.raises(<CrashErrorType>) — asserting the crash, not the fix.
    pattern = re.compile(
        r"pytest\.raises\s*\(\s*" + re.escape(error_type) + r"\s*\)",
        re.IGNORECASE,
    )
    if pattern.search(test_content):
        return (
            f"The test uses `pytest.raises({error_type})`, which asserts the crash "
            f"occurs rather than asserting the correct behaviour. A test like this "
            f"will pass on the buggy code, so the Dev Agent will never apply a fix."
        )
    return ""
