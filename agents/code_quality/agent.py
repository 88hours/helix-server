"""
Code Quality Agent — core logic.

Fetches the PR diff, reviews it using the LLM, then either posts a Slack
approval request (on pass) or publishes a quality_rejected event with
structured feedback for the Dev Agent to retry (on fail).

Entry point: handle()
"""

import logging

import redis.asyncio as redis

from agents.code_quality import prompts
from core.config import get_email_config, get_github_config, get_slack_config
from core.events import publish
from core.llm import complete
from core.models import (
    CrashReport,
    PRResult,
    QualityReport,
    QualityResult,
    QualityVerdict,
)
from core.state import write_status
from core.utils import extract_json
from integrations import email, github, slack

logger = logging.getLogger(__name__)


async def handle(
    pr_result: PRResult,
    crash_report: CrashReport,
    redis_client: redis.Redis,
) -> QualityResult:
    """
    Review the pull request and route based on the verdict.

    Steps:
      1. Fetch the PR diff from GitHub.
      2. Call the LLM to review for coverage, standards, and security.
      3. If passed: post a Slack approval request and publish quality_approved.
      4. If failed: publish quality_rejected with feedback for the Dev Agent.

    Args:
        pr_result:    PRResult from the Dev Agent (contains PR number and URL).
        crash_report: CrashReport from the Crash Handler (provides context).
        redis_client: Async Redis client.

    Returns:
        The QualityResult produced by this review.
    """
    incident_id = crash_report.incident_id
    logger.info("code quality agent started", extra={"incident_id": incident_id})

    gh_config = get_github_config()
    slack_config = get_slack_config()
    email_config = get_email_config()

    # Step 1 — Fetch the PR diff.
    pr_diff = await github.get_pr_diff(
        repo=gh_config.target_repo,
        pr_number=pr_result.pr_number,
    )

    # Step 2 — LLM review.
    prompt = prompts.user(
        crash_summary=crash_report.summary,
        pr_diff=pr_diff,
    )
    raw_response = await complete(
        agent="code_quality",
        prompt=prompt,
        system=prompts.SYSTEM,
    )

    data = extract_json(raw_response)

    report = QualityReport(
        test_coverage=data["test_coverage"],
        standards_check=QualityVerdict(data["standards_check"]),
        security_check=QualityVerdict(data["security_check"]),
        notes=data["notes"],
    )

    verdict = QualityVerdict(data["verdict"])
    feedback: str = data.get("feedback", "")

    result = QualityResult(
        incident_id=incident_id,
        pr_url=pr_result.pr_url,
        verdict=verdict,
        report=report,
        feedback=feedback or None,
        iteration=pr_result.iterations_taken,
    )

    # Step 3/4 — Route based on verdict.
    if verdict == QualityVerdict.passed:
        await write_status(redis_client, incident_id, "quality_approved")
        await publish(
            redis_client,
            "quality_approved",
            incident_id,
            result.model_dump(mode="json"),
        )
        await slack.post_approval_request(
            incident_id=incident_id,
            pr_url=pr_result.pr_url,
            report=report,
            channel=slack_config.approval_channel,
            token=slack_config.token,
        )
        await email.send_approval_request(
            incident_id=incident_id,
            pr_url=pr_result.pr_url,
            report=report,
            from_addr=email_config.from_addr,
            to_addr=email_config.to_addrs,
            sendgrid_api_key=email_config.sendgrid_api_key,
            smtp_host=email_config.smtp_host,
            smtp_port=email_config.smtp_port,
            smtp_user=email_config.smtp_user,
            smtp_password=email_config.smtp_password,
        )
        logger.info(
            "code quality approved — slack and email notifications sent",
            extra={"incident_id": incident_id, "pr_url": pr_result.pr_url},
        )
    else:
        await write_status(redis_client, incident_id, "quality_rejected")
        await publish(
            redis_client,
            "quality_rejected",
            incident_id,
            result.model_dump(mode="json"),
        )
        logger.warning(
            "code quality rejected — feedback sent to dev agent",
            extra={"incident_id": incident_id, "feedback": feedback},
        )

    return result
