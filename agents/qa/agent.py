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
from core.models import CrashReport, QAResult, TestCase, TestFormat, TicketAction, language_to_test_format
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

    # If this is a duplicate issue, skip the full pipeline and notify via Slack.
    # The Dev Agent should not re-run for a bug it has already attempted to fix.
    if ticket_action == TicketAction.updated:
        logger.info(
            "duplicate issue detected — skipping test generation and dev agent",
            extra={"incident_id": report.incident_id, "issue_url": ticket_url},
        )
        await write_status(redis_client, report.incident_id, "duplicate_detected")
        await publish(
            redis_client,
            "duplicate_detected",
            report.incident_id,
            {
                "issue_url": ticket_url,
                "issue_number": ticket_id,
                "error_type": report.error_type,
                "error_message": report.error_message,
            },
        )
        return QAResult(
            incident_id=report.incident_id,
            ticket_id=ticket_id,
            ticket_url=ticket_url,
            ticket_action=ticket_action,
            test_case=TestCase(file_path="", test_name="", content="", format=language_to_test_format(report.language)),
            relevant_files=[],
        )

    # Step 2 — Clone repo and read relevant source files.
    repo_dir = tempfile.mkdtemp(prefix="helix-qa-")
    try:
        clone_url = f"https://github.com/{gh_config.target_repo}.git"
        await github.clone_repo(clone_url, repo_dir)
        source_files = _read_relevant_files(repo_dir, report.stack_trace, report.language)

        # Step 3 — LLM generates the test case (retried if validation fails).
        test_format = language_to_test_format(report.language)

        base_prompt = prompts.user(
            error_type=report.error_type,
            error_message=report.error_message,
            stack_trace=report.stack_trace,
            affected_component=report.affected_component,
            affected_endpoint=report.affected_endpoint,
            summary=report.summary,
            source_files=source_files,
            language=report.language,
            test_format=test_format.value,
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
            problem = _check_test(data.get("content", ""), report.error_type, report.language)
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
            rejection_note = prompts.rejection_note(problem, test_format.value)

    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)

    data = extract_json(raw_response)

    test_case = TestCase(
        file_path=data["file_path"],
        test_name=data["test_name"],
        content=data["content"],
        format=test_format,
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
            comment=f"⚠️ Helix re-detected this crash (incident `{report.incident_id}`). A Slack notification has been sent — if a fix PR is already open, please review and approve it.",
        )
        return issue_number, issue_url, TicketAction.updated

    issue_number, issue_url = await github.create_issue(
        repo=repo,
        title=title,
        body=body,
        labels=["bug", "helix"],
    )
    return issue_number, issue_url, TicketAction.created


def _read_relevant_files(repo_dir: str, stack_trace: str, language: str = "python") -> dict[str, str]:
    """
    Identify and read the source files most likely involved in the crash.

    Extracts file paths from the stack trace, filters to paths that exist
    in the local clone, and reads up to _MAX_SOURCE_FILES of them.

    Args:
        repo_dir:    Path to the cloned repository root.
        stack_trace: Formatted stack trace string.
        language:    Application language, e.g. "python", "javascript".

    Returns:
        Mapping of relative file path → file content (truncated if large).
    """
    candidate_paths = _extract_paths_from_stack_trace(stack_trace, language)
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


def _extract_paths_from_stack_trace(stack_trace: str, language: str = "python") -> list[str]:
    """
    Parse a stack trace and return unique relative application file paths.

    Supports Python, JavaScript/TypeScript, Ruby, Java/Kotlin, and Go.
    Filters out standard library and dependency paths — only application code
    is returned.

    Args:
        stack_trace: Formatted stack trace string.
        language:    Application language, e.g. "python", "javascript".

    Returns:
        List of unique relative file paths, most recent frame first.
    """
    lang = language.lower()
    seen: set[str] = set()
    paths: list[str] = []

    if lang in ("javascript", "typescript"):
        # at functionName (/app/src/file.ts:10:5)
        # at /app/src/file.js:10:5
        pattern = re.compile(r"at (?:\S+ \()?([^\s()]+\.[jt]sx?):(\d+)")
        for match in pattern.finditer(stack_trace):
            path = match.group(1)
            if "node_modules" in path:
                continue
            path = _normalise_path(path)
            if path and path not in seen:
                seen.add(path)
                paths.append(path)

    elif lang == "ruby":
        # /app/lib/checkout.rb:42:in `process'
        pattern = re.compile(r"([^\s:]+\.rb):(\d+):in")
        for match in pattern.finditer(stack_trace):
            path = match.group(1)
            if "/gems/" in path or "/usr/lib/ruby" in path or "/usr/local/lib/ruby" in path:
                continue
            path = _normalise_path(path)
            if path and path not in seen:
                seen.add(path)
                paths.append(path)

    elif lang in ("java", "kotlin"):
        # at com.example.checkout.Processor.process(Processor.java:42)
        pattern = re.compile(r"at [\w.$]+\((\w+\.(?:java|kt)):(\d+)\)")
        for match in pattern.finditer(stack_trace):
            path = match.group(1)
            # Skip JDK and common framework classes — we only have a filename,
            # not a full path, so filter by the frame's package prefix instead.
            frame = match.group(0)
            if re.match(r"at (?:java|javax|sun|com\.sun|kotlin|kotlinx)\.", frame):
                continue
            if path not in seen:
                seen.add(path)
                paths.append(path)

    elif lang == "go":
        # /home/user/app/checkout/processor.go:42 +0x1234
        pattern = re.compile(r"(/[^\s:]+\.go):(\d+)")
        for match in pattern.finditer(stack_trace):
            path = match.group(1)
            if "/usr/local/go/" in path or "/go/pkg/" in path:
                continue
            path = _normalise_path(path)
            if path and path not in seen:
                seen.add(path)
                paths.append(path)

    else:
        # Python (default): File "path/to/file.py", line 42, in function_name
        pattern = re.compile(r'File "([^"]+)", line \d+')
        for match in pattern.finditer(stack_trace):
            path = match.group(1)
            if path.startswith("/") and ("site-packages" in path or "/lib/python" in path):
                continue
            path = _normalise_path(path)
            if path and path not in seen:
                seen.add(path)
                paths.append(path)

    # Return most recent frame first (closest to the error).
    return list(reversed(paths))


def _normalise_path(path: str) -> str:
    """Strip leading ./ or / from a path to make it relative."""
    path = path.lstrip("./")
    # Strip a leading absolute path component that looks like a container root
    # (e.g. "/app/src/file.js" → "src/file.js" won't work, keep as-is for matching)
    return path


def _check_test(test_content: str, error_type: str, language: str = "python") -> str:
    """
    Return a problem description if the test asserts the crash occurs rather
    than asserting the correct behaviour, or "" if the test looks valid.

    Checks the framework-specific anti-pattern for each supported language.

    Args:
        test_content: Full content of the generated test file.
        error_type:   Exception class from the crash report, e.g. "AttributeError".
        language:     Application language, e.g. "python", "javascript".

    Returns:
        A plain-English description of the problem, or "" if the test looks valid.
    """
    lang = language.lower()

    if lang in ("javascript", "typescript"):
        # Jest: expect(...).toThrow(ErrorType) or .rejects.toThrow(ErrorType)
        pattern = re.compile(
            r"\.toThrow\s*\(\s*" + re.escape(error_type) + r"\s*\)",
            re.IGNORECASE,
        )
        if pattern.search(test_content):
            return (
                f"The test uses `.toThrow({error_type})`, which asserts the crash "
                f"occurs rather than asserting the correct behaviour. Assert the "
                f"expected return value instead."
            )

    elif lang == "ruby":
        # RSpec: expect { }.to raise_error(ErrorType)
        pattern = re.compile(
            r"raise_error\s*\(\s*" + re.escape(error_type) + r"\s*\)",
            re.IGNORECASE,
        )
        if pattern.search(test_content):
            return (
                f"The test uses `raise_error({error_type})`, which asserts the crash "
                f"occurs rather than asserting the correct behaviour. Assert the "
                f"expected return value instead."
            )

    elif lang in ("java", "kotlin"):
        # JUnit: assertThrows(ErrorType.class, ...) or @Test(expected = ErrorType.class)
        pattern = re.compile(
            r"assertThrows\s*\(\s*" + re.escape(error_type) + r"(?:\.class)?\s*,",
            re.IGNORECASE,
        )
        expected_pattern = re.compile(
            r"expected\s*=\s*" + re.escape(error_type) + r"(?:\.class)?",
            re.IGNORECASE,
        )
        if pattern.search(test_content) or expected_pattern.search(test_content):
            return (
                f"The test asserts that `{error_type}` is thrown, which asserts the "
                f"crash occurs rather than asserting the correct behaviour. Assert the "
                f"expected return value instead."
            )

    else:
        # Python (default): pytest.raises(ErrorType)
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
