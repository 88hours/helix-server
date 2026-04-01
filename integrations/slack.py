"""
Slack integration for the Helix agent pipeline.

Provides async helpers for posting messages and interactive approval requests
to Slack using the Web API (chat.postMessage).

Required environment variables:
    SLACK_BOT_TOKEN        — Bot token with chat:write scope (xoxb-...)
    SLACK_APPROVAL_CHANNEL — Channel ID or name for human approval messages

The approval message uses Slack Block Kit with Approve / Reject buttons.
When a reviewer clicks a button, Slack sends an interaction payload to the
configured Interactivity Request URL — that handler is in agents/human_approval/.
"""

import logging
import os
from typing import Optional

import httpx

from core.models import QualityReport

logger = logging.getLogger(__name__)

_SLACK_API = "https://slack.com/api"


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _auth_header(token: Optional[str] = None) -> dict[str, str]:
    """
    Return the Authorization header for Slack API calls.

    Args:
        token: Slack bot token. Falls back to SLACK_BOT_TOKEN env var.

    Raises:
        EnvironmentError: If no token can be resolved.
    """
    resolved = token or os.environ.get("SLACK_BOT_TOKEN")
    if not resolved:
        raise EnvironmentError("SLACK_BOT_TOKEN is not set")
    return {"Authorization": f"Bearer {resolved}"}


async def _post(payload: dict, token: Optional[str] = None) -> None:
    """
    Call chat.postMessage with the given Block Kit payload.

    Args:
        payload: Full Slack API payload dict (must include "channel").
        token:   Slack bot token. Falls back to SLACK_BOT_TOKEN env var.

    Raises:
        RuntimeError: If Slack returns ok=false.
        httpx.HTTPStatusError: On HTTP-level failures.
    """
    headers = {**_auth_header(token), "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{_SLACK_API}/chat.postMessage",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        error = data.get("error", "unknown_error")
        raise RuntimeError(f"Slack API error: {error}")

    logger.info(
        "slack message posted",
        extra={"channel": payload.get("channel"), "error": None},
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def post_message(
    text: str,
    channel: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """
    Post a plain-text message to a Slack channel.

    Args:
        text:    Message body. Supports Slack mrkdwn formatting.
        channel: Channel ID or name. Defaults to SLACK_APPROVAL_CHANNEL env var.
        token:   Slack bot token. Defaults to SLACK_BOT_TOKEN env var.
    """
    resolved_channel = channel or os.environ.get("SLACK_APPROVAL_CHANNEL")
    if not resolved_channel:
        raise EnvironmentError("SLACK_APPROVAL_CHANNEL is not set")

    await _post({"channel": resolved_channel, "text": text}, token)


async def post_approval_request(
    incident_id: str,
    pr_url: str,
    report: QualityReport,
    channel: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """
    Post an interactive approval request to Slack.

    Sends a Block Kit message with an Approve and a Reject button.  When the
    reviewer clicks either, Slack delivers an interaction payload to the
    configured Interactivity Request URL (the Human Approval agent).

    Args:
        incident_id: Helix incident ID — embedded in button values so the
                     approval handler knows which incident to act on.
        pr_url:      URL of the GitHub PR to review.
        report:      QualityReport from the Code Quality Agent.
        channel:     Channel ID or name. Defaults to SLACK_APPROVAL_CHANNEL.
        token:       Slack bot token. Defaults to SLACK_BOT_TOKEN.
    """
    resolved_channel = channel or os.environ.get("SLACK_APPROVAL_CHANNEL")
    if not resolved_channel:
        raise EnvironmentError("SLACK_APPROVAL_CHANNEL is not set")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":rotating_light: Helix — PR ready for review"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Incident:*\n`{incident_id}`"},
                {"type": "mrkdwn", "text": f"*Pull Request:*\n<{pr_url}|View PR>"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Test coverage:*\n{report.test_coverage}"},
                {"type": "mrkdwn", "text": f"*Standards:*\n{report.standards_check.value}"},
                {"type": "mrkdwn", "text": f"*Security:*\n{report.security_check.value}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Notes:*\n{report.notes}"},
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve & Merge"},
                    "style": "primary",
                    "action_id": "helix_approve_pr",
                    "value": incident_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": "helix_reject_pr",
                    "value": incident_id,
                },
            ],
        },
    ]

    await _post({"channel": resolved_channel, "blocks": blocks}, token)
    logger.info("approval request posted", extra={"incident_id": incident_id, "pr_url": pr_url})


async def post_escalation(
    incident_id: str,
    crash_summary: str,
    attempts: int,
    context: str,
    channel: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """
    Post a human-escalation message when the Dev Agent exhausts all retries.

    Includes the full context (crash report, what was tried) so the on-call
    engineer has everything they need without digging through logs.

    Args:
        incident_id:   Helix incident ID.
        crash_summary: Plain-English summary from the CrashReport.
        attempts:      Number of fix attempts made by the Dev Agent.
        context:       Full Dev Agent reasoning and what was tried.
        channel:       Channel ID or name. Defaults to SLACK_APPROVAL_CHANNEL.
        token:         Slack bot token. Defaults to SLACK_BOT_TOKEN.
    """
    resolved_channel = channel or os.environ.get("SLACK_APPROVAL_CHANNEL")
    if not resolved_channel:
        raise EnvironmentError("SLACK_APPROVAL_CHANNEL is not set")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":sos: Helix — Dev Agent needs human help"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Incident:*\n`{incident_id}`"},
                {"type": "mrkdwn", "text": f"*Attempts exhausted:*\n{attempts}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Crash summary:*\n{crash_summary}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*What the agent tried:*\n```{context[:2800]}```"},
        },
    ]

    await _post({"channel": resolved_channel, "blocks": blocks}, token)
    logger.info("escalation posted", extra={"incident_id": incident_id, "attempts": attempts})
