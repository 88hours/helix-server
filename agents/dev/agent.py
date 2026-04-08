"""
Dev Agent — core logic.

Receives the QA Agent's failing test case, calls the LLM to generate a
minimal fix suggestion, posts it as a GitHub Issue comment, then performs
a full TDD loop: clones the repo, writes the failing test, uses the
claude-code CLI to implement the fix, verifies the full test suite, and
opens a GitHub PR on success.  Retries up to MAX_ITERATIONS times.

All Slack and email notifications are delegated to the Notifier Agent via
events:
  fix_suggested — published after the GitHub comment; Notifier sends the
                  team a link to the issue.
  fix_failed    — published when all retries are exhausted; Notifier sends
                  an escalation message with full context.

Entry points:
  handle()  — called on test_case_generated events
"""

import asyncio
import base64
import logging
import shutil
import tempfile

import httpx
import redis.asyncio as redis

from agents.dev import prompts
from typing import Optional

from core.config import ProjectConfig, get_github_config
from core.events import publish
from core.llm import complete
from core.models import CrashReport, PRResult, Project, QAResult
from core.permissions import AgentPermissions, load_permissions, require
from core.state import (
    increment_iterations,
    read_iterations,
    write_pr_result,
    write_status,
)
from core.ui_events import publish_tool_event, publish_ui_event
from integrations import github

logger = logging.getLogger(__name__)

# Maximum total fix attempts across all retries.
MAX_ITERATIONS = 3

# Maximum characters to read per source file passed to the LLM.
_MAX_FILE_CHARS = 4_000

# Per-repo lock: prevents two Dev Agent workers from cloning the same repo
# simultaneously, which would produce conflicting branches and duplicate PRs.
_REPO_LOCK_TTL = 600      # seconds — covers the longest expected TDD run
_REPO_LOCK_RETRIES = 12   # 12 × 30 s = up to 6 minutes of waiting
_REPO_LOCK_RETRY_DELAY = 30  # seconds between lock-check retries


async def handle(
    qa_result: QAResult,
    crash_report: CrashReport,
    redis_client: redis.Redis,
    project: Optional[Project] = None,
    installation_token: Optional[str] = None,
) -> PRResult:
    """
    Generate a fix suggestion, post it to GitHub, notify the team, then
    implement the fix via TDD and open a PR.

    Steps:
      1. Fetch relevant source files from GitHub (no clone).
      2. Call the LLM to suggest a minimal code fix.
      3. Post the fix suggestion as a comment on the GitHub Issue.
      4. Publish fix_suggested event → Notifier Agent sends Slack/email.
      5. TDD loop: clone repo → write test → claude-code iterate → PR.
         On success: persist PRResult, update status, publish pr_created.
         On exhaustion: post failure comment, publish fix_failed event
         → Notifier Agent sends escalation via Slack/email.

    Args:
        qa_result:    QAResult from the QA Agent (contains the failing test case).
        crash_report: CrashReport from the Crash Handler Agent.
        redis_client: Async Redis client.

    Returns:
        PRResult with the created pull request details.

    Raises:
        RuntimeError: All iterations exhausted; escalation sent to Slack/email.
    """
    permissions = load_permissions("dev")
    if project is not None:
        gh_config = ProjectConfig(project).github(installation_token=installation_token)
    else:
        gh_config = get_github_config()
    incident_id = crash_report.incident_id

    logger.info("dev agent started", extra={"incident_id": incident_id})
    await publish_ui_event(redis_client, incident_id, "agent_start", "dev", "Dev Agent started — fetching source files…")

    # Step 1 — Fetch source files from GitHub API.
    require(permissions, "github", "fetch_source_files")
    source_files = await _fetch_source_files(
        repo=gh_config.target_repo,
        paths=qa_result.relevant_files,
        token=gh_config.token,
    )
    logger.debug(
        "source files fetched",
        extra={"incident_id": incident_id, "files": list(source_files.keys())},
    )
    await publish_tool_event(redis_client, incident_id, "dev", "github", "fetch_files", "success", f"{len(source_files)} files")

    await publish_ui_event(redis_client, incident_id, "agent_step", "dev", f"Fetched {len(source_files)} source file(s) — generating fix suggestion…")

    # Step 2 — LLM generates a fix suggestion.
    suggestion_prompt = prompts.build_suggestion(
        error_type=crash_report.error_type,
        error_message=crash_report.error_message,
        summary=crash_report.summary,
        test_file_path=qa_result.test_case.file_path,
        test_name=qa_result.test_case.test_name,
        test_content=qa_result.test_case.content,
        source_files=source_files,
    )
    logger.info("dev agent calling llm for fix suggestion", extra={"incident_id": incident_id})
    fix_suggestion = await complete(agent="dev", prompt=suggestion_prompt)
    await publish_tool_event(redis_client, incident_id, "dev", "llm", "complete", "success", "fix suggestion")
    logger.debug(
        "llm fix suggestion received",
        extra={"incident_id": incident_id, "response_length": len(fix_suggestion)},
    )

    # Step 3 — Post the fix suggestion as a GitHub Issue comment.
    issue_comment = (
        f"**Suggested fix** for `{crash_report.error_type}: {crash_report.error_message}`\n\n"
        f"{fix_suggestion}\n\n"
        f"---\n"
        f"*Generated by Helix for incident `{incident_id}`. "
        f"Implementing via TDD — a PR will follow.*"
    )
    logger.debug(
        "posting fix suggestion to github issue",
        extra={"incident_id": incident_id, "issue_number": qa_result.ticket_id},
    )
    require(permissions, "github", "add_issue_comment")
    await github.add_issue_comment(
        repo=gh_config.target_repo,
        issue_number=qa_result.ticket_id,
        comment=issue_comment,
        token=gh_config.token,
    )
    await publish_tool_event(redis_client, incident_id, "dev", "github", "add_comment", "success", f"#{qa_result.ticket_id} fix suggestion")
    logger.info(
        "fix suggestion posted to github issue",
        extra={"incident_id": incident_id, "issue_number": qa_result.ticket_id},
    )

    await publish_ui_event(redis_client, incident_id, "agent_step", "dev", "Fix suggestion posted to GitHub issue — starting TDD loop…")

    # Step 4 — Publish fix_suggested; Notifier Agent handles Slack/email.
    require(permissions, "redis", "write_status")
    await write_status(redis_client, incident_id, "fix_suggested")
    require(permissions, "events", "publish:fix_suggested")
    await publish(
        redis_client,
        "fix_suggested",
        incident_id,
        {
            "incident_id": incident_id,
            "issue_url": qa_result.ticket_url,
            "ticket_id": qa_result.ticket_id,
        },
    )

    # Step 5 — TDD loop: implement the fix and open a PR.
    return await _tdd_loop(
        qa_result=qa_result,
        crash_report=crash_report,
        fix_suggestion=fix_suggestion,
        redis_client=redis_client,
        permissions=permissions,
        project=project,
        installation_token=installation_token,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _tdd_loop(
    qa_result: QAResult,
    crash_report: CrashReport,
    fix_suggestion: str,
    redis_client: redis.Redis,
    permissions: AgentPermissions,
    project: Optional[Project] = None,
    installation_token: Optional[str] = None,
) -> PRResult:
    """
    Clone the repo, write the failing test, and iterate with claude-code until
    the test suite passes or all iterations are exhausted.

    Args:
        qa_result:      QAResult containing the failing test case.
        crash_report:   CrashReport for the incident.
        fix_suggestion: Fix suggestion text from the LLM (already posted to GitHub).
        redis_client:   Async Redis client.
        permissions:    Dev Agent's loaded permissions — enforced before each operation.

    Returns:
        PRResult with the created pull request details.

    Raises:
        RuntimeError: All iterations exhausted; escalation sent to Slack/email.
    """
    if project is not None:
        gh_config = ProjectConfig(project).github(installation_token=installation_token)
    else:
        gh_config = get_github_config()
    incident_id = crash_report.incident_id

    require(permissions, "redis", "read_iterations")
    current_iterations = await read_iterations(redis_client, incident_id)
    if current_iterations >= MAX_ITERATIONS:
        await _post_failure_comment(qa_result, gh_config.target_repo, [], permissions, token=gh_config.token)
        await _escalate(crash_report, [], redis_client, permissions)
        raise RuntimeError(
            f"Dev Agent for incident {incident_id} has exhausted all {MAX_ITERATIONS} iterations."
        )

    # Acquire a per-repo lock so concurrent incidents on the same repo do not
    # clone simultaneously, create conflicting branches, or open duplicate PRs.
    # The lock value is the incident_id so it is traceable in Redis.
    repo_lock_key = f"helix:repo_lock:{gh_config.target_repo}"
    lock_acquired = False
    for _attempt in range(_REPO_LOCK_RETRIES):
        lock_acquired = await redis_client.set(
            repo_lock_key, incident_id, nx=True, ex=_REPO_LOCK_TTL
        )
        if lock_acquired:
            break
        logger.info(
            "repo lock held — waiting before retry",
            extra={
                "incident_id": incident_id,
                "repo": gh_config.target_repo,
                "attempt": _attempt + 1,
            },
        )
        await asyncio.sleep(_REPO_LOCK_RETRY_DELAY)

    if not lock_acquired:
        raise RuntimeError(
            f"Could not acquire repo lock for {gh_config.target_repo} after "
            f"{_REPO_LOCK_RETRIES} retries — another incident is already in progress."
        )

    repo_dir = tempfile.mkdtemp(prefix="helix-dev-")
    prior_attempts: list[str] = []
    try:
        clone_url = f"https://github.com/{gh_config.target_repo}.git"
        require(permissions, "github", "clone_repo")
        await github.clone_repo(clone_url, repo_dir, token=gh_config.token)
        await publish_tool_event(redis_client, incident_id, "dev", "git", "clone", "success", gh_config.target_repo)

        require(permissions, "redis", "increment_iterations")
        iteration = await increment_iterations(redis_client, incident_id)
        branch_name = f"helix/fix/{incident_id[:8]}-{iteration}"
        require(permissions, "github", "checkout_branch")
        await github.checkout_branch(repo_dir, branch_name)

        require(permissions, "github", "write_file")
        await github.write_file(
            repo_dir,
            qa_result.test_case.file_path,
            qa_result.test_case.content,
        )

        while iteration <= MAX_ITERATIONS:
            await publish_ui_event(
                redis_client, incident_id, "agent_step", "dev",
                f"TDD iteration {iteration}/{MAX_ITERATIONS} — running Claude Code…",
            )
            prompt = prompts.build_tdd(
                incident_id=incident_id,
                error_type=crash_report.error_type,
                error_message=crash_report.error_message,
                summary=crash_report.summary,
                test_file_path=qa_result.test_case.file_path,
                test_name=qa_result.test_case.test_name,
                iteration=iteration,
                prior_attempts=prior_attempts,
                fix_suggestion=fix_suggestion if iteration == 1 else "",
                language=crash_report.language,
            )

            logger.info(
                "dev agent tdd iteration",
                extra={"incident_id": incident_id, "iteration": iteration},
            )

            response = await complete(agent="dev", prompt=prompt, cwd=repo_dir)
            logger.debug(
                "claude-code response",
                extra={"incident_id": incident_id, "iteration": iteration, "response": response},
            )
            tdd_status = "success" if _tests_passed(response) else "failed"
            await publish_tool_event(redis_client, incident_id, "dev", "claude_code", "tdd_iterate", tdd_status, f"iteration {iteration}/{MAX_ITERATIONS}")

            if _tests_passed(response):
                fix_summary = _extract_explanation(response)
                files_changed = await _get_changed_files(repo_dir)

                commit_message = (
                    f"fix: resolve {crash_report.error_type} in "
                    f"{crash_report.affected_component} (helix/{incident_id[:8]})\n\n"
                    f"{fix_summary}"
                )
                require(permissions, "github", "commit_and_push")
                await github.commit_and_push(repo_dir, branch_name, commit_message)
                await publish_tool_event(redis_client, incident_id, "dev", "github", "commit_push", "success", branch_name)

                pr_title = (
                    f"[Helix] Fix {crash_report.error_type} in "
                    f"{crash_report.affected_component}"
                )
                pr_body = _build_pr_body(crash_report, qa_result, fix_summary, iteration)
                require(permissions, "github", "create_pull_request")
                pr_number, pr_url = await github.create_pull_request(
                    repo=gh_config.target_repo,
                    title=pr_title,
                    body=pr_body,
                    head=branch_name,
                    base=gh_config.base_branch,
                    token=gh_config.token,
                )
                await publish_tool_event(redis_client, incident_id, "dev", "github", "create_pr", "success", f"#{pr_number}")

                pr_result = PRResult(
                    incident_id=incident_id,
                    pr_url=pr_url,
                    pr_number=pr_number,
                    branch_name=branch_name,
                    iterations_taken=iteration,
                    files_changed=files_changed,
                    fix_summary=fix_summary,
                )

                require(permissions, "redis", "write_pr_result")
                await write_pr_result(redis_client, pr_result)
                require(permissions, "redis", "write_status")
                await write_status(redis_client, incident_id, "pr_created")
                await publish_ui_event(
                    redis_client, incident_id, "agent_step", "dev",
                    f"Tests passed on iteration {iteration} — PR #{pr_number} created",
                )
                await publish_ui_event(redis_client, incident_id, "status_changed", "dev", "pr_created")
                require(permissions, "events", "publish:pr_created")
                await publish(
                    redis_client,
                    "pr_created",
                    incident_id,
                    pr_result.model_dump(mode="json"),
                )
                await publish_ui_event(redis_client, incident_id, "agent_done", "dev", f"Fix complete — awaiting human approval for PR #{pr_number}")

                logger.info(
                    "dev agent complete",
                    extra={
                        "incident_id": incident_id,
                        "pr_number": pr_number,
                        "iterations": iteration,
                    },
                )
                return pr_result

            # Tests failed — record attempt and retry if budget remains.
            explanation = _extract_explanation(response)
            prior_attempts.append(explanation)
            await publish_ui_event(
                redis_client, incident_id, "agent_step", "dev",
                f"Iteration {iteration} failed — {'retrying' if iteration < MAX_ITERATIONS else 'escalating'}",
            )
            logger.warning(
                "dev agent tdd iteration failed",
                extra={"incident_id": incident_id, "iteration": iteration},
            )

            if iteration >= MAX_ITERATIONS:
                break

            require(permissions, "redis", "increment_iterations")
            iteration = await increment_iterations(redis_client, incident_id)
            branch_name = f"helix/fix/{incident_id[:8]}-{iteration}"
            require(permissions, "github", "checkout_branch")
            await github.checkout_branch(repo_dir, branch_name)

    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)
        if lock_acquired:
            await redis_client.delete(repo_lock_key)

    # All iterations exhausted.
    await publish_ui_event(redis_client, incident_id, "agent_done", "dev", f"All {MAX_ITERATIONS} iterations exhausted — escalating to human")
    await _post_failure_comment(qa_result, gh_config.target_repo, prior_attempts, permissions, token=gh_config.token)
    await _escalate(crash_report, prior_attempts, redis_client, permissions)
    raise RuntimeError(
        f"Dev Agent for incident {incident_id} exhausted all {MAX_ITERATIONS} iterations."
    )


def _tests_passed(response: str) -> bool:
    """Return True if the claude-code response contains the TESTS_PASSED sentinel."""
    return "TESTS_PASSED" in response


def _extract_explanation(response: str) -> str:
    """
    Extract the explanation paragraph that follows the sentinel line.

    Returns the text after TESTS_PASSED / TESTS_FAILED, or the full response
    if neither sentinel is found.
    """
    for sentinel in ("TESTS_PASSED", "TESTS_FAILED"):
        if sentinel in response:
            parts = response.split(sentinel, maxsplit=1)
            return parts[1].strip() if len(parts) > 1 else response.strip()
    return response.strip()


async def _get_changed_files(repo_dir: str) -> list[str]:
    """
    Return the list of files changed in the working tree relative to HEAD.

    Uses `git diff --name-only HEAD` to catch both staged and unstaged changes.
    Falls back to an empty list on any error.
    """
    try:
        output = await github._git(["diff", "--name-only", "HEAD"], cwd=repo_dir)
        return [line for line in output.splitlines() if line.strip()]
    except RuntimeError:
        return []


def _build_pr_body(
    crash_report: CrashReport,
    qa_result: QAResult,
    fix_summary: str,
    iterations: int,
) -> str:
    """Build a plain-English PR description for the GitHub pull request."""
    return (
        f"## Summary\n\n"
        f"{fix_summary}\n\n"
        f"## Incident\n\n"
        f"- **Incident ID:** `{crash_report.incident_id}`\n"
        f"- **Error:** `{crash_report.error_type}: {crash_report.error_message}`\n"
        f"- **Component:** {crash_report.affected_component}\n"
        f"- **Endpoint:** {crash_report.affected_endpoint}\n"
        f"- **Issue:** [{qa_result.ticket_id}]({qa_result.ticket_url})\n\n"
        f"## What Changed\n\n"
        f"{crash_report.summary}\n\n"
        f"## Testing\n\n"
        f"- Failing test added: `{qa_result.test_case.file_path}::"
        f"{qa_result.test_case.test_name}`\n"
        f"- Full test suite passed after fix\n"
        f"- Fix took {iterations} iteration(s)\n\n"
        f"---\n"
        f"*Generated by [Helix](https://github.com/88hours/helix) — "
        f"autonomous incident response*"
    )


async def _post_failure_comment(
    qa_result: QAResult,
    repo: str,
    prior_attempts: list[str],
    permissions: AgentPermissions,
    token: str | None = None,
) -> None:
    """
    Post a failure summary to the GitHub Issue when all fix attempts are exhausted.

    Args:
        qa_result:      QAResult containing the failing test case reference.
        repo:           GitHub repository in "owner/name" format.
        prior_attempts: Per-attempt explanation strings from the TDD loop.
        permissions:    Dev Agent's loaded permissions.
        token:          GitHub token. Falls back to GITHUB_TOKEN env var.
    """
    if prior_attempts:
        attempts_str = "\n\n".join(
            f"**Attempt {i + 1}:**\n{attempt}"
            for i, attempt in enumerate(prior_attempts)
        )
    else:
        attempts_str = "_No attempts were recorded (iterations already exhausted)._"

    comment = (
        f":x: **Helix could not automatically fix this bug** after {MAX_ITERATIONS} attempt(s).\n\n"
        f"**Failing test:** `{qa_result.test_case.file_path}::{qa_result.test_case.test_name}`\n\n"
        f"**What was tried:**\n\n{attempts_str}\n\n"
        f"Manual investigation is needed. The failing test above can be used to reproduce the bug."
    )
    logger.debug(
        "posting failure comment to github issue",
        extra={"issue_number": qa_result.ticket_id},
    )
    try:
        require(permissions, "github", "add_issue_comment")
        await github.add_issue_comment(
            repo=repo,
            issue_number=qa_result.ticket_id,
            comment=comment,
            token=token,
        )
    except Exception as exc:
        logger.warning(
            "could not post failure comment to github issue",
            extra={"issue_number": qa_result.ticket_id, "error": str(exc)},
        )


async def _escalate(
    crash_report: CrashReport,
    prior_attempts: list[str],
    redis_client: redis.Redis,
    permissions: AgentPermissions,
) -> None:
    """
    Publish fix_failed event so the Notifier Agent escalates via Slack and email.

    Args:
        crash_report:   CrashReport for the incident.
        prior_attempts: Per-attempt explanation strings from the TDD loop.
        redis_client:   Async Redis client.
        permissions:    Dev Agent's loaded permissions.
    """
    context = "\n\n---\n\n".join(
        f"Attempt {i + 1}:\n{attempt}"
        for i, attempt in enumerate(prior_attempts)
    )
    if not context:
        context = "No attempts recorded."

    logger.warning(
        "dev agent escalating — all iterations exhausted",
        extra={"incident_id": crash_report.incident_id, "attempts": len(prior_attempts)},
    )

    require(permissions, "redis", "write_status")
    await write_status(redis_client, crash_report.incident_id, "fix_failed")
    require(permissions, "events", "publish:fix_failed")
    await publish(
        redis_client,
        "fix_failed",
        crash_report.incident_id,
        {
            "incident_id": crash_report.incident_id,
            "crash_summary": crash_report.summary,
            "attempts": MAX_ITERATIONS,
            "context": context,
        },
    )


async def _fetch_source_files(repo: str, paths: list[str], token: str | None = None) -> dict[str, str]:
    """
    Fetch the content of source files from the GitHub contents API.

    Args:
        repo:  Repository in "owner/name" format.
        paths: Relative file paths to fetch (from qa_result.relevant_files).
        token: GitHub token. Falls back to GITHUB_TOKEN env var.

    Returns:
        Mapping of relative path → file content (truncated if large).
        Files that cannot be fetched are silently skipped.
    """
    from integrations.github import _api_headers, _GITHUB_API

    result: dict[str, str] = {}
    async with httpx.AsyncClient() as client:
        for path in paths:
            url = f"{_GITHUB_API}/repos/{repo}/contents/{path}"
            try:
                response = await client.get(url, headers=_api_headers(token))
                response.raise_for_status()
                data = response.json()
                content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                if len(content) > _MAX_FILE_CHARS:
                    content = content[:_MAX_FILE_CHARS] + "\n... [truncated]"
                result[path] = content
                logger.debug("fetched source file", extra={"path": path})
            except Exception as exc:
                logger.warning(
                    "could not fetch source file",
                    extra={"path": path, "error": str(exc)},
                )
    return result
