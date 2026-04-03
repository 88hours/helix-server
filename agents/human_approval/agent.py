"""
Human Approval Agent — core logic.

Called when a reviewer clicks Approve or Reject on the Slack approval message.

  handle_approve — merges the GitHub PR, sends email confirmation, posts Slack update
  handle_reject  — posts a Slack message asking the reviewer to comment on the PR

Both functions are invoked from main.py as FastAPI background tasks so the
Slack interaction endpoint can return 200 immediately (Slack requires < 3s).
"""

import logging

import redis.asyncio as redis

from core.config import get_email_config, get_github_config, get_slack_config
from core.state import read_pr_result, write_status
from integrations import email, github, slack

logger = logging.getLogger(__name__)


async def handle_approve(
    incident_id: str,
    approved_by: str,
    redis_client: redis.Redis,
) -> None:
    """
    Merge the GitHub PR and notify via Slack and email.

    Steps:
      1. Read the PRResult from Redis to get the PR number.
      2. Merge the PR via the GitHub API (squash merge).
      3. Update the incident status in Redis.
      4. Post a Slack confirmation message.
      5. Send a pr_merged email.

    Args:
        incident_id:  Helix incident ID from the Slack button value.
        approved_by:  Slack username of the reviewer who clicked Approve.
        redis_client: Async Redis client.
    """
    logger.info(
        "approval received",
        extra={"incident_id": incident_id, "approved_by": approved_by},
    )

    gh_config = get_github_config()
    slack_config = get_slack_config()
    email_config = get_email_config()

    logger.debug("reading pr_result from redis", extra={"incident_id": incident_id})
    pr_result = await read_pr_result(redis_client, incident_id)
    if pr_result is None:
        logger.error(
            "pr_result not found for approval — cannot merge",
            extra={"incident_id": incident_id},
        )
        await slack.post_message(
            text=f":warning: Helix could not merge PR for incident `{incident_id}` — state not found. Please merge manually.",
            channel=slack_config.approval_channel,
            token=slack_config.token,
        )
        return

    # Merge the PR.
    commit_title = f"fix: Helix auto-fix for incident {incident_id[:8]} (approved by @{approved_by})"
    await github.merge_pull_request(
        repo=gh_config.target_repo,
        pr_number=pr_result.pr_number,
        commit_title=commit_title,
        merge_method="squash",
    )

    await write_status(redis_client, incident_id, "merged")

    # Slack confirmation.
    await slack.post_message(
        text=(
            f":white_check_mark: *PR #{pr_result.pr_number} merged* by @{approved_by}\n"
            f"Incident: `{incident_id}`\n"
            f"PR: {pr_result.pr_url}"
        ),
        channel=slack_config.approval_channel,
        token=slack_config.token,
    )

    # Email confirmation.
    await email.send_pr_merged(
        incident_id=incident_id,
        pr_url=pr_result.pr_url,
        pr_number=pr_result.pr_number,
        approved_by=approved_by,
        from_addr=email_config.from_addr,
        to_addr=email_config.to_addrs,
        sendgrid_api_key=email_config.sendgrid_api_key,
        smtp_host=email_config.smtp_host,
        smtp_port=email_config.smtp_port,
        smtp_user=email_config.smtp_user,
        smtp_password=email_config.smtp_password,
    )

    logger.info(
        "pr merged and notifications sent",
        extra={"incident_id": incident_id, "pr_number": pr_result.pr_number},
    )


async def handle_reject(
    incident_id: str,
    rejected_by: str,
    redis_client: redis.Redis,
) -> None:
    """
    Handle a PR rejection — notify via Slack and update Redis status.

    The PR is left open for the reviewer to close or for the Dev Agent to
    retry (if iterations remain). A message is posted to Slack asking the
    reviewer to leave a comment on the PR explaining the reason.

    Args:
        incident_id:  Helix incident ID from the Slack button value.
        rejected_by:  Slack username of the reviewer who clicked Reject.
        redis_client: Async Redis client.
    """
    logger.info(
        "rejection received",
        extra={"incident_id": incident_id, "rejected_by": rejected_by},
    )

    slack_config = get_slack_config()

    logger.debug("reading pr_result from redis", extra={"incident_id": incident_id})
    pr_result = await read_pr_result(redis_client, incident_id)
    pr_link = f"<{pr_result.pr_url}|PR #{pr_result.pr_number}>" if pr_result else "the PR"

    await write_status(redis_client, incident_id, "rejected")

    await slack.post_message(
        text=(
            f":x: *PR rejected* by @{rejected_by}\n"
            f"Incident: `{incident_id}`\n"
            f"Please leave a comment on {pr_link} explaining the reason "
            f"so the team can follow up."
        ),
        channel=slack_config.approval_channel,
        token=slack_config.token,
    )

    logger.info(
        "rejection noted",
        extra={"incident_id": incident_id, "rejected_by": rejected_by},
    )
