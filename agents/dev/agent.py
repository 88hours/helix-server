"""
Dev Agent — core logic.

Clones the target repository, writes the QA Agent's failing test, then uses
the claude-code CLI to iteratively run the test, write a fix, and verify the
full suite.  Retries up to MAX_ITERATIONS times.  On exhaustion, escalates
to Slack and email.  On success, opens a GitHub PR and publishes the pr_created event.

Entry points:
  handle()         — called on test_case_generated events (initial fix)
  handle_retry()   — called on quality_rejected events (fix after review)
"""

import logging
import shutil
import tempfile

import redis.asyncio as redis

from agents.dev import prompts
from core.config import get_email_config, get_github_config, get_slack_config
from core.events import publish
from core.llm import complete
from core.models import CrashReport, PRResult, QAResult
from core.state import (
    increment_iterations,
    read_iterations,
    write_pr_result,
    write_status,
)
from integrations import email, github, slack

logger = logging.getLogger(__name__)

# Maximum total fix attempts across all retries (including quality rejections).
MAX_ITERATIONS = 3


async def handle(
    qa_result: QAResult,
    crash_report: CrashReport,
    redis_client: redis.Redis,
) -> PRResult:
    """
    Attempt to fix the bug described by qa_result and crash_report.

    Called on test_case_generated events — the initial fix attempt.

    Args:
        qa_result:    QAResult from the QA Agent (contains the failing test case).
        crash_report: CrashReport from the Crash Handler Agent.
        redis_client: Async Redis client.

    Returns:
        PRResult with the created pull request details.

    Raises:
        RuntimeError: All iterations exhausted; escalation posted to Slack.
    """
    return await _run(
        qa_result=qa_result,
        crash_report=crash_report,
        redis_client=redis_client,
        quality_feedback="",
    )


async def handle_retry(
    qa_result: QAResult,
    crash_report: CrashReport,
    quality_feedback: str,
    redis_client: redis.Redis,
) -> PRResult:
    """
    Retry the fix after the Code Quality Agent rejected the previous PR.

    Called on quality_rejected events.

    Args:
        qa_result:        QAResult from the QA Agent.
        crash_report:     CrashReport from the Crash Handler Agent.
        quality_feedback: Structured feedback from the Code Quality Agent.
        redis_client:     Async Redis client.

    Returns:
        PRResult with the new pull request details.

    Raises:
        RuntimeError: All iterations exhausted; escalation posted to Slack.
    """
    return await _run(
        qa_result=qa_result,
        crash_report=crash_report,
        redis_client=redis_client,
        quality_feedback=quality_feedback,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _run(
    qa_result: QAResult,
    crash_report: CrashReport,
    redis_client: redis.Redis,
    quality_feedback: str,
) -> PRResult:
    """
    Core fix loop: clone → write test → iterate with claude-code → PR or escalate.
    """
    gh_config = get_github_config()
    incident_id = crash_report.incident_id

    current_iterations = await read_iterations(redis_client, incident_id)
    if current_iterations >= MAX_ITERATIONS:
        await _escalate(crash_report, [], get_slack_config(), get_email_config())
        raise RuntimeError(
            f"Dev Agent for incident {incident_id} has exhausted all {MAX_ITERATIONS} iterations."
        )

    repo_dir = tempfile.mkdtemp(prefix="helix-dev-")
    try:
        # Clone and prepare the branch.
        clone_url = f"https://github.com/{gh_config.target_repo}.git"
        await github.clone_repo(clone_url, repo_dir)

        iteration = await increment_iterations(redis_client, incident_id)
        branch_name = f"helix/fix/{incident_id[:8]}-{iteration}"
        await github.checkout_branch(repo_dir, branch_name)

        # Write the failing test file into the repo.
        await github.write_file(
            repo_dir,
            qa_result.test_case.file_path,
            qa_result.test_case.content,
        )

        # Attempt the fix — may take multiple claude-code calls within this clone.
        prior_attempts: list[str] = []
        while iteration <= MAX_ITERATIONS:
            prompt = prompts.build(
                incident_id=incident_id,
                error_type=crash_report.error_type,
                error_message=crash_report.error_message,
                summary=crash_report.summary,
                test_file_path=qa_result.test_case.file_path,
                test_name=qa_result.test_case.test_name,
                iteration=iteration,
                prior_attempts=prior_attempts,
                quality_feedback=quality_feedback if iteration == 1 else "",
            )

            logger.info(
                "dev agent iteration",
                extra={"incident_id": incident_id, "iteration": iteration},
            )

            response = await complete(agent="dev", prompt=prompt, cwd=repo_dir)

            if _tests_passed(response):
                fix_summary = _extract_explanation(response)
                files_changed = await _get_changed_files(repo_dir)

                commit_message = (
                    f"fix: resolve {crash_report.error_type} in "
                    f"{crash_report.affected_component} (helix/{incident_id[:8]})\n\n"
                    f"{fix_summary}"
                )
                await github.commit_and_push(repo_dir, branch_name, commit_message)

                pr_title = (
                    f"[Helix] Fix {crash_report.error_type} in "
                    f"{crash_report.affected_component}"
                )
                pr_body = _build_pr_body(crash_report, qa_result, fix_summary, iteration)
                pr_number, pr_url = await github.create_pull_request(
                    repo=gh_config.target_repo,
                    title=pr_title,
                    body=pr_body,
                    head=branch_name,
                    base=gh_config.base_branch,
                )

                pr_result = PRResult(
                    incident_id=incident_id,
                    pr_url=pr_url,
                    pr_number=pr_number,
                    branch_name=branch_name,
                    iterations_taken=iteration,
                    files_changed=files_changed,
                    fix_summary=fix_summary,
                )

                # Post the fix details as a comment on the GitHub Issue.
                files_str = "\n".join(f"- `{f}`" for f in files_changed) or "_(no files detected)_"
                issue_comment = (
                    f"**Fix implemented** — [PR #{pr_number}]({pr_url})\n\n"
                    f"{fix_summary}\n\n"
                    f"**Files changed:**\n{files_str}\n\n"
                    f"**Test passing:** `{qa_result.test_case.file_path}::{qa_result.test_case.test_name}`\n\n"
                    f"Fix took {iteration} iteration(s). Awaiting code review."
                )
                logger.debug(
                    "posting fix comment to github issue",
                    extra={"incident_id": incident_id, "issue_number": qa_result.ticket_id},
                )
                await github.add_issue_comment(
                    repo=gh_config.target_repo,
                    issue_number=qa_result.ticket_id,
                    comment=issue_comment,
                )

                await write_pr_result(redis_client, pr_result)
                await write_status(redis_client, incident_id, "pr_created")
                await publish(
                    redis_client,
                    "pr_created",
                    incident_id,
                    pr_result.model_dump(mode="json"),
                )

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
            logger.warning(
                "dev agent iteration failed",
                extra={"incident_id": incident_id, "iteration": iteration},
            )

            if iteration >= MAX_ITERATIONS:
                break

            iteration = await increment_iterations(redis_client, incident_id)
            # Checkout a fresh branch for the next attempt.
            branch_name = f"helix/fix/{incident_id[:8]}-{iteration}"
            await github.checkout_branch(repo_dir, branch_name)

    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)

    # All iterations exhausted.
    await _escalate(crash_report, prior_attempts, get_slack_config(), get_email_config())
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

    Uses `git diff --name-only HEAD` so it catches both staged and unstaged changes.
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


async def _escalate(
    crash_report: CrashReport,
    prior_attempts: list[str],
    slack_config,
    email_config,
) -> None:
    """Post an escalation message to Slack and email when all retries are exhausted."""
    context = "\n\n---\n\n".join(
        f"Attempt {i + 1}:\n{attempt}"
        for i, attempt in enumerate(prior_attempts)
    )
    if not context:
        context = "No attempts recorded."

    await slack.post_escalation(
        incident_id=crash_report.incident_id,
        crash_summary=crash_report.summary,
        attempts=MAX_ITERATIONS,
        context=context,
        channel=slack_config.approval_channel,
        token=slack_config.token,
    )
    await email.send_escalation(
        incident_id=crash_report.incident_id,
        crash_summary=crash_report.summary,
        attempts=MAX_ITERATIONS,
        context=context,
        from_addr=email_config.from_addr,
        to_addr=email_config.to_addrs,
        sendgrid_api_key=email_config.sendgrid_api_key,
        smtp_host=email_config.smtp_host,
        smtp_port=email_config.smtp_port,
        smtp_user=email_config.smtp_user,
        smtp_password=email_config.smtp_password,
    )
