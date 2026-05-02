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
from typing import Optional

from core.config import ProjectConfig, get_github_config
from core.models import Project
from core.events import publish
from core.llm import complete
from core.models import CrashReport, QAResult, TestCase, TestFormat, TicketAction, language_to_test_format
from core.permissions import AgentPermissions, load_permissions, require
from core.state import write_llm_response, write_qa_result, write_status
from core.ui_events import publish_tool_event, publish_ui_event
from core.utils import extract_json
from integrations import github

logger = logging.getLogger(__name__)

# Maximum number of source files to read and pass to the LLM.
_MAX_SOURCE_FILES = 8

# Maximum characters to read per source file (keeps prompt size manageable).
_MAX_FILE_CHARS = 4_000

# Maximum number of times to retry LLM generation when the test fails validation.
_MAX_TEST_RETRIES = 2


async def handle(
    report: CrashReport,
    redis_client: redis.Redis,
    project: Optional[Project] = None,
    installation_token: Optional[str] = None,
) -> QAResult:
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
        report:             CrashReport produced by the Crash Handler Agent.
        redis_client:       Async Redis client.
        project:            Project model for per-project config (Phase 3+).
                            When None, falls back to global env var config.
        installation_token: GitHub App installation token for the project.
                            Used when project is set; falls back to GITHUB_TOKEN.

    Returns:
        The persisted QAResult.
    """
    logger.info("qa agent started", extra={"incident_id": report.incident_id})
    await publish_ui_event(redis_client, report.incident_id, "agent_start", "qa", "QA Agent started — creating GitHub issue…")

    permissions = load_permissions("qa")
    if project is not None:
        gh_config = ProjectConfig(project).github(installation_token=installation_token)
    else:
        gh_config = get_github_config()

    # Step 1 — GitHub Issue (optional — failure does not block the pipeline).
    ticket_id, ticket_url, ticket_action = None, None, TicketAction.created
    try:
        ticket_id, ticket_url, ticket_action = await _create_or_update_issue(
            report, gh_config.target_repo, permissions, redis_client, gh_config.token
        )
        await publish_ui_event(redis_client, report.incident_id, "agent_step", "qa", f"GitHub issue #{ticket_id} {'updated (duplicate)' if ticket_action == TicketAction.updated else 'created'}")
    except Exception as gh_exc:
        logger.warning(
            "github issue step skipped — continuing pipeline",
            extra={"incident_id": report.incident_id, "error": str(gh_exc)},
        )
        await publish_ui_event(redis_client, report.incident_id, "agent_step", "qa", "GitHub issue skipped — continuing pipeline")

    # If this is a duplicate issue, skip the full pipeline and notify via Slack.
    # The Dev Agent should not re-run for a bug it has already attempted to fix.
    if ticket_action == TicketAction.updated:
        logger.info(
            "duplicate issue detected — skipping test generation and dev agent",
            extra={"incident_id": report.incident_id, "issue_url": ticket_url},
        )
        require(permissions, "redis", "write_status")
        await write_status(redis_client, report.incident_id, "duplicate_detected")
        require(permissions, "events", "publish:duplicate_detected")
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
    await publish_ui_event(redis_client, report.incident_id, "agent_step", "qa", "Cloning repository to read source files…")
    repo_dir = tempfile.mkdtemp(prefix="helix-qa-")
    try:
        clone_url = f"https://github.com/{gh_config.target_repo}.git"
        require(permissions, "github", "clone_repo")
        await github.clone_repo(clone_url, repo_dir, token=gh_config.token)
        await publish_tool_event(redis_client, report.incident_id, "qa", "git", "clone", "success", gh_config.target_repo)
        source_files = _read_relevant_files(repo_dir, report.stack_trace, report.language)
        await publish_ui_event(redis_client, report.incident_id, "agent_step", "qa", f"Read {len(source_files)} relevant source file(s)")

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
        data: dict = {}
        rejection_note = ""
        for attempt in range(1, _MAX_TEST_RETRIES + 2):  # attempts: 1, 2, 3
            await publish_ui_event(
                redis_client, report.incident_id, "agent_step", "qa",
                f"Generating test case (attempt {attempt})…",
            )
            prompt = base_prompt if not rejection_note else base_prompt + rejection_note
            raw_response = await complete(
                agent="qa",
                prompt=prompt,
                system=prompts.SYSTEM,
                json_mode=True,
            )
            await write_llm_response(redis_client, report.incident_id, "qa", attempt, raw_response)
            await publish_tool_event(redis_client, report.incident_id, "qa", "llm", "complete", "success", f"attempt {attempt}")
            try:
                data = extract_json(raw_response)
            except ValueError:
                logger.warning(
                    "qa agent llm returned invalid JSON — retrying",
                    extra={"incident_id": report.incident_id, "attempt": attempt},
                )
                rejection_note = "\n\nIMPORTANT: Your previous response was not valid JSON. Return ONLY a JSON object — no prose, no markdown, no extra text."
                continue

            # Normalise field aliases that models commonly use instead of our schema.
            if "content" not in data and "test_code" in data:
                data["content"] = data.pop("test_code")
            if "file_path" not in data:
                data["file_path"] = f"tests/test_{report.affected_component.lower().replace(' ', '_')}.py"

            content = (data.get("content") or "").strip()
            if not content:
                logger.warning(
                    "qa agent llm returned empty content — retrying",
                    extra={"incident_id": report.incident_id, "attempt": attempt},
                )
                rejection_note = "\n\nIMPORTANT: The 'content' field in your previous response was empty or null. You MUST include the full test file content as a non-empty string."
                continue
            problem = _check_test(content, report.error_type, report.language)
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

    missing = [k for k in ("file_path", "test_name", "content") if not (data.get(k) or "").strip()]
    if missing:
        raise ValueError(f"LLM response missing required fields after all retries: {missing}. Last response: {raw_response!r:.200}")

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

    require(permissions, "redis", "write_qa_result")
    await write_qa_result(redis_client, result)
    require(permissions, "redis", "write_status")
    await write_status(redis_client, report.incident_id, "test_case_generated")
    await publish_ui_event(redis_client, report.incident_id, "status_changed", "qa", "test_case_generated")

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
    if ticket_id is not None:
        require(permissions, "github", "add_issue_comment")
        await github.add_issue_comment(
            repo=gh_config.target_repo,
            issue_number=ticket_id,
            comment=test_comment,
            token=gh_config.token,
        )
        await publish_tool_event(redis_client, report.incident_id, "qa", "github", "add_comment", "success", f"#{ticket_id} test case")
        logger.debug("test case posted to github issue", extra={"incident_id": report.incident_id})

    await publish_ui_event(
        redis_client, report.incident_id, "agent_step", "qa",
        f"Test case written: {test_case.file_path}::{test_case.test_name}",
    )
    require(permissions, "events", "publish:test_case_generated")
    await publish(
        redis_client,
        "test_case_generated",
        report.incident_id,
        result.model_dump(mode="json"),
    )
    await publish_ui_event(redis_client, report.incident_id, "agent_done", "qa", "Test case complete — handing off to Dev Agent")

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
    permissions: AgentPermissions,
    redis_client: redis.Redis,
    token: str | None = None,
) -> tuple[str, str, TicketAction]:
    """
    Find an existing GitHub Issue for this bug or create a new one.

    Args:
        report:      CrashReport from the Crash Handler Agent.
        repo:        GitHub repository in "owner/name" format.
        permissions: QA Agent's loaded permissions — enforced before each GitHub call.
        token:       GitHub token (installation token or GITHUB_TOKEN fallback).

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

    require(permissions, "github", "find_existing_issue")
    existing = await github.find_existing_issue(repo=repo, title=title, token=token)
    await publish_tool_event(redis_client, report.incident_id, "qa", "github", "find_issue", "success", "duplicate" if existing else "no match")

    if existing:
        issue_number, issue_url = existing
        require(permissions, "github", "add_issue_comment")
        await github.add_issue_comment(
            repo=repo,
            issue_number=issue_number,
            comment=f"⚠️ Helix re-detected this crash (incident `{report.incident_id}`). A Slack notification has been sent — if a fix PR is already open, please review and approve it.",
            token=token,
        )
        await publish_tool_event(redis_client, report.incident_id, "qa", "github", "add_comment", "success", f"#{issue_number}")
        return issue_number, issue_url, TicketAction.updated

    require(permissions, "github", "create_issue")
    issue_number, issue_url = await github.create_issue(
        repo=repo,
        title=title,
        body=body,
        labels=["bug", "helix"],
        token=token,
    )
    await publish_tool_event(redis_client, report.incident_id, "qa", "github", "create_issue", "success", f"#{issue_number}")
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

    # Build a filename → repo-relative-path index for fallback searches.
    # Stack traces from developer machines contain absolute local paths that
    # won't match the repo directory structure, so we search by basename.
    filename_index: dict[str, str] = {}
    repo_root = Path(repo_dir)
    for p in repo_root.rglob("*"):
        if p.is_file() and not any(part.startswith(".") for part in p.parts):
            rel = str(p.relative_to(repo_root))
            filename_index.setdefault(p.name, rel)

    for relative_path in candidate_paths:
        if len(result) >= _MAX_SOURCE_FILES:
            break
        full_path = repo_root / relative_path
        if not full_path.is_file():
            # Fall back: search by filename only
            basename = Path(relative_path).name
            fallback = filename_index.get(basename)
            if fallback:
                relative_path = fallback
                full_path = repo_root / relative_path
            else:
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
    """Return a normalised relative path, stripping leading ./ or /."""
    return path.lstrip("./") if not path.startswith("/") else path.split("/")[-1]


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
