"""
Notifier Agent — core logic.

Subscribes to fix_suggested events and sends Slack and email notifications
with a link to the GitHub Issue where the suggested fix was posted.

Entry points:
  handle()  — called on fix_suggested events
"""

import logging

import redis.asyncio as redis

from core.config import get_email_config, get_slack_config
from core.state import read_crash_report
from integrations import email, slack

logger = logging.getLogger(__name__)


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

    slack_config = get_slack_config()
    email_config = get_email_config()

    logger.debug("reading crash report from redis", extra={"incident_id": incident_id})
    crash_report = await read_crash_report(redis_client, incident_id)
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
    await slack.post_message(
        text=slack_text,
        channel=slack_config.approval_channel,
        token=slack_config.token,
    )
    logger.debug("slack notification sent", extra={"incident_id": incident_id})

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
