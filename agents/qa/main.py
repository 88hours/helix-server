"""
QA Agent — subscriber entry point.

Subscribes to the crash_analysed Redis channel and calls the QA Agent
for every new incident.

Run with:
    python -m agents.qa.main
"""

import asyncio
import logging
import os

import redis.asyncio as aioredis

from agents.qa.agent import handle
from core.config import get_redis_url
from core.db import get_db, get_project
from core.events import subscribe
from core.github_app import get_installation_token
from core.models import CrashReport, Project, ProjectSettings
from core.state import read_crash_report

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def main() -> None:
    """
    Subscribe to crash_analysed events and run the QA Agent for each one.

    If the CrashReport is not in Redis (e.g. expired), the event is skipped
    with a warning rather than crashing the loop.
    """
    logger.info("=== QA Agent starting ===")
    redis_url = get_redis_url()
    logger.info("qa agent connecting to redis", extra={"redis_url": redis_url})
    redis_client = aioredis.from_url(redis_url, decode_responses=False)
    logger.info("qa agent subscriber started — listening on helix:events:crash_analysed")

    async for incident_id, payload in subscribe(redis_client, "crash_analysed", agent_name="qa"):
        logger.info("qa agent received event", extra={"incident_id": incident_id})
        try:
            # Prefer the Redis record (canonical); fall back to the event payload.
            logger.debug("reading crash report from redis", extra={"incident_id": incident_id})
            report = await read_crash_report(redis_client, incident_id)
            if report is None:
                logger.warning(
                    "crash report not found in redis — falling back to event payload",
                    extra={"incident_id": incident_id},
                )
                report = CrashReport.model_validate(payload)
            else:
                logger.info(
                    "crash report loaded from redis",
                    extra={"incident_id": incident_id, "severity": report.severity.value},
                )

            # Load per-project config from Postgres when available.
            project: Project | None = None
            installation_token: str | None = None
            if report.project_id and os.environ.get("DATABASE_URL"):
                try:
                    async with get_db() as db:
                        row = await get_project(db, report.project_id)
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
                        extra={"incident_id": incident_id, "project_id": report.project_id, "error": str(proj_exc)},
                    )

            await handle(report, redis_client, project=project, installation_token=installation_token)
            logger.info("qa agent finished handling incident", extra={"incident_id": incident_id})
        except Exception as exc:
            logger.error(
                "qa agent failed for incident",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
