"""
Dev Agent — subscriber entry point.

Subscribes to the test_case_generated Redis channel. For each event it
calls the LLM to suggest a fix, posts it as a GitHub Issue comment, and
notifies the team via Slack and email.

Run with:
    python -m agents.dev.main
"""

import asyncio
import logging
import os

import redis.asyncio as aioredis

from agents.dev.agent import handle
from core.config import get_redis_url
from core.db import get_db, get_project
from core.events import subscribe
from core.github_app import get_installation_token
from core.models import CrashReport, Project, ProjectSettings, QAResult
from core.state import read_crash_report, read_qa_result

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def main() -> None:
    """Subscribe to test_case_generated events and run the Dev Agent for each one."""
    logger.info("=== Dev Agent starting ===")
    redis_url = get_redis_url()
    logger.info("dev agent connecting to redis", extra={"redis_url": redis_url})
    redis_client = aioredis.from_url(redis_url, decode_responses=False)
    logger.info("dev agent subscriber started — listening on helix:events:test_case_generated")

    async for incident_id, payload in subscribe(redis_client, "test_case_generated", agent_name="dev"):
        logger.info("dev agent received test_case_generated event", extra={"incident_id": incident_id})
        try:
            logger.debug("reading qa_result from redis", extra={"incident_id": incident_id})
            qa_result = await read_qa_result(redis_client, incident_id)
            if qa_result is None:
                logger.warning(
                    "qa_result not in redis — falling back to event payload",
                    extra={"incident_id": incident_id},
                )
                qa_result = QAResult.model_validate(payload)
            else:
                logger.debug("qa_result loaded from redis", extra={"incident_id": incident_id})

            logger.debug("reading crash_report from redis", extra={"incident_id": incident_id})
            crash_report = await read_crash_report(redis_client, incident_id)
            if crash_report is None:
                logger.error(
                    "crash_report missing for incident — skipping",
                    extra={"incident_id": incident_id},
                )
                continue
            logger.debug(
                "crash_report loaded from redis",
                extra={"incident_id": incident_id, "severity": crash_report.severity.value},
            )

            # Load per-project config from Postgres when available.
            project: Project | None = None
            installation_token: str | None = None
            if crash_report.project_id and os.environ.get("DATABASE_URL"):
                try:
                    async with get_db() as db:
                        row = await get_project(db, crash_report.project_id)
                    if row:
                        settings = ProjectSettings(
                            anthropic_api_key=row.get("anthropic_api_key"),
                            sentry_webhook_secret=row.get("sentry_webhook_secret"),
                            rollbar_access_token=row.get("rollbar_access_token"),
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
                            github_installation_id=row.get("github_installation_id"),
                            settings=settings,
                        )
                        if project.github_installation_id:
                            async with get_db() as db:
                                installation_token = await get_installation_token(
                                    project.github_installation_id, db
                                )
                except Exception as proj_exc:
                    logger.warning(
                        "failed to load project config — using env var fallback",
                        extra={"incident_id": incident_id, "project_id": crash_report.project_id, "error": str(proj_exc)},
                    )

            await handle(qa_result, crash_report, redis_client, project=project, installation_token=installation_token)
            logger.info("dev agent finished handling test_case_generated", extra={"incident_id": incident_id})
        except Exception as exc:
            logger.error(
                "dev agent failed on test_case_generated",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
