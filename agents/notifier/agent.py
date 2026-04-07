"""
Notifier Agent — core logic.

Handles all outbound Slack and email notifications for the pipeline.

Entry points:
  handle()             — called on fix_suggested events; sends the team a
                         link to the GitHub Issue where the fix was posted.
  handle_escalation()  — called on fix_failed events; sends an escalation
                         message when the Dev Agent exhausts all retries.
  handle_pr_created()  — called on pr_created events; posts a Slack approval
                         request with Approve / Reject buttons. No-op when
                         Slack is not configured.
  handle_duplicate()   — called on duplicate_detected events; notifies the
                         team that the same bug has recurred and prompts them
                         to review any pending fix PR.
"""

import logging

import redis.asyncio as redis

import os

from core.config import ProjectConfig, get_email_config, get_slack_config
from core.db import get_db, get_project
from core.models import Project, ProjectSettings
from core.permissions import load_permissions, require
from core.state import read_crash_report, read_pr_result
from integrations import email, slack

logger = logging.getLogger(__name__)


async def _load_project_config(project_id: str) -> tuple:
    """
    Load SlackConfig and EmailConfig for a project from Postgres.

    Falls back to env-var-based global config if DATABASE_URL is not set,
    the project is not found, or any error occurs.

    Args:
        project_id: Helix project UUID.

    Returns:
        Tuple of (SlackConfig, EmailConfig).
    """
    if not project_id or not os.environ.get("DATABASE_URL"):
        return get_slack_config(), get_email_config()
    try:
        async with get_db() as db:
            row = await get_project(db, project_id)
        if not row:
            return get_slack_config(), get_email_config()
        settings = ProjectSettings(
            slack_bot_token=row.get("slack_bot_token"),
            slack_signing_secret=row.get("slack_signing_secret"),
            slack_approval_channel=row.get("slack_approval_channel"),
            sendgrid_api_key=row.get("sendgrid_api_key"),
            smtp_host=row.get("smtp_host"),
            email_from=row.get("email_from"),
            email_to=row.get("email_to"),
        )
        project = Project(
            project_id=row["project_id"],
            name=row["name"],
            repo=row["repo"],
            base_branch=row["base_branch"],
            language=row["language"],
            settings=settings,
        )
        pc = ProjectConfig(project)
        return pc.slack(), pc.email()
    except Exception as exc:
        logger.warning("failed to load project config for notifier — using env vars: %s", exc)
        return get_slack_config(), get_email_config()


async def handle(
    incident_id: str,
    issue_url: str,
    redis_client: redis.Redis,
) -> None:
    """
    Send Slack and email notifications for a suggested fix.

    Reads the CrashReport from Redis to populate error context in the
    notification messages. If the crash report is not found (expired or not
    yet written), sends the notification with placeholder context rather than
    failing silently.

    Args:
        incident_id:  Helix incident ID.
        issue_url:    URL of the GitHub Issue where the fix was posted.
        redis_client: Async Redis client.
    """
    logger.info("notifier agent started", extra={"incident_id": incident_id})

    permissions = load_permissions("notifier")

    logger.debug("reading crash report from redis", extra={"incident_id": incident_id})
    require(permissions, "redis", "read_crash_report")
    crash_report = await read_crash_report(redis_client, incident_id)

    project_id = crash_report.project_id if crash_report else ""
    slack_config, email_config = await _load_project_config(project_id)
    if crash_report is None:
        logger.warning(
            "crash report not found in redis — sending notification without error context",
            extra={"incident_id": incident_id},
        )
        error_type = "unknown"
        error_message = "unknown"
        affected_component = "unknown"
    else:
        error_type = crash_report.error_type
        error_message = crash_report.error_message
        affected_component = crash_report.affected_component

    slack_text = (
        f":wrench: *Helix suggested a fix* for incident `{incident_id}`\n"
        f"*Error:* `{error_type}: {error_message}`\n"
        f"*Component:* {affected_component}\n"
        f"*Review the fix:* {issue_url}"
    )
    require(permissions, "slack", "post_message")
    await slack.post_message(
        text=slack_text,
        channel=slack_config.approval_channel,
        token=slack_config.token,
    )
    logger.debug("slack notification sent", extra={"incident_id": incident_id})

    require(permissions, "email", "send_fix_suggested")
    await email.send_fix_suggested(
        incident_id=incident_id,
        error_type=error_type,
        error_message=error_message,
        issue_url=issue_url,
        from_addr=email_config.from_addr,
        to_addr=email_config.to_addrs,
        sendgrid_api_key=email_config.sendgrid_api_key,
        smtp_host=email_config.smtp_host,
        smtp_port=email_config.smtp_port,
        smtp_user=email_config.smtp_user,
        smtp_password=email_config.smtp_password,
    )

    logger.info(
        "slack and email notifications sent",
        extra={"incident_id": incident_id},
    )


async def handle_escalation(
    incident_id: str,
    crash_summary: str,
    attempts: int,
    context: str,
    redis_client: redis.Redis,
) -> None:
    """
    Send escalation notifications when the Dev Agent exhausts all retries.

    Called on fix_failed events.

    Args:
        incident_id:   Helix incident ID.
        crash_summary: Plain-English crash summary from the Crash Handler.
        attempts:      Number of fix attempts that were made.
        context:       Per-attempt summaries from the Dev Agent.
        redis_client:  Async Redis client (unused here; kept for consistency).
    """
    logger.info("notifier agent escalating", extra={"incident_id": incident_id})

    permissions = load_permissions("notifier")
    # Load project config from Postgres if available; fall back to env vars.
    crash_report = await read_crash_report(redis_client, incident_id)
    project_id = crash_report.project_id if crash_report else ""
    slack_config, email_config = await _load_project_config(project_id)

    require(permissions, "slack", "post_escalation")
    await slack.post_escalation(
        incident_id=incident_id,
        crash_summary=crash_summary,
        attempts=attempts,
        context=context,
        channel=slack_config.approval_channel,
        token=slack_config.token,
    )
    logger.debug("slack escalation sent", extra={"incident_id": incident_id})

    require(permissions, "email", "send_escalation")
    await email.send_escalation(
        incident_id=incident_id,
        crash_summary=crash_summary,
        attempts=attempts,
        context=context,
        from_addr=email_config.from_addr,
        to_addr=email_config.to_addrs,
        sendgrid_api_key=email_config.sendgrid_api_key,
        smtp_host=email_config.smtp_host,
        smtp_port=email_config.smtp_port,
        smtp_user=email_config.smtp_user,
        smtp_password=email_config.smtp_password,
    )

    logger.info(
        "escalation notifications sent",
        extra={"incident_id": incident_id},
    )


async def handle_pr_created(
    incident_id: str,
    redis_client: redis.Redis,
) -> None:
    """
    Post a Slack approval request when the Dev Agent has created a PR.

    Reads the PRResult from Redis and sends a Block Kit message with
    Approve / Reject buttons to the configured approval channel.

    This is entirely optional — if SLACK_BOT_TOKEN or SLACK_APPROVAL_CHANNEL
    is not set, the function logs a warning and returns without error. The PR
    remains open on GitHub and can be merged manually.

    Args:
        incident_id:  Helix incident ID.
        redis_client: Async Redis client.
    """
    logger.info("notifier handling pr_created", extra={"incident_id": incident_id})

    permissions = load_permissions("notifier")
    crash_report = await read_crash_report(redis_client, incident_id)
    project_id = crash_report.project_id if crash_report else ""
    slack_config, _ = await _load_project_config(project_id)
    if not slack_config.token or not slack_config.approval_channel:
        logger.warning(
            "slack approval skipped — SLACK_BOT_TOKEN or SLACK_APPROVAL_CHANNEL not configured",
            extra={"incident_id": incident_id},
        )
        return

    require(permissions, "redis", "read_pr_result")
    pr_result = await read_pr_result(redis_client, incident_id)
    if pr_result is None:
        logger.error(
            "pr_result not found in redis — cannot send approval request",
            extra={"incident_id": incident_id},
        )
        return

    require(permissions, "slack", "post_approval_request")
    await slack.post_approval_request(
        incident_id=incident_id,
        pr_url=pr_result.pr_url,
        pr_number=pr_result.pr_number,
        fix_summary=pr_result.fix_summary,
        channel=slack_config.approval_channel,
        token=slack_config.token,
    )

    logger.info(
        "approval request sent",
        extra={"incident_id": incident_id, "pr_number": pr_result.pr_number},
    )


async def handle_duplicate(
    incident_id: str,
    issue_url: str,
    error_type: str,
    error_message: str,
    redis_client: redis.Redis,
) -> None:
    """
    Notify the team when a crash recurs for a bug that already has an open issue.

    Sends a Slack message linking to the existing GitHub Issue and prompting
    the reviewer to approve any pending fix PR. The Dev Agent is not re-run.

    No-op if Slack is not configured.

    Args:
        incident_id:   Helix incident ID for the new occurrence.
        issue_url:     URL of the existing GitHub Issue.
        error_type:    Error class, e.g. "KeyError".
        error_message: Short error message.
        redis_client:  Async Redis client (unused; kept for consistency).
    """
    logger.info("notifier handling duplicate_detected", extra={"incident_id": incident_id})

    permissions = load_permissions("notifier")
    crash_report = await read_crash_report(redis_client, incident_id)
    project_id = crash_report.project_id if crash_report else ""
    slack_config, _ = await _load_project_config(project_id)
    if not slack_config.token or not slack_config.approval_channel:
        logger.warning(
            "duplicate notification skipped — Slack not configured",
            extra={"incident_id": incident_id},
        )
        return

    text = (
        f":warning: *Recurring crash* — incident `{incident_id}`\n"
        f"*Error:* `{error_type}: {error_message}`\n"
        f"*Existing issue:* {issue_url}\n"
        f"This bug has been seen before. If a fix PR is already open, please review and approve it."
    )
    require(permissions, "slack", "post_message")
    await slack.post_message(
        text=text,
        channel=slack_config.approval_channel,
        token=slack_config.token,
    )

    logger.info(
        "duplicate notification sent",
        extra={"incident_id": incident_id, "issue_url": issue_url},
    )
