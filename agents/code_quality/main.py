"""
Code Quality Agent — subscriber entry point.

Subscribes to the pr_created Redis channel and reviews every PR opened
by the Dev Agent.

Run with:
    python -m agents.code_quality.main
"""

import asyncio
import logging
import os

import redis.asyncio as aioredis

from agents.code_quality.agent import handle
from core.config import get_redis_url
from core.events import subscribe
from core.models import CrashReport, PRResult
from core.state import read_crash_report, read_pr_result

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def main() -> None:
    """
    Subscribe to pr_created events and run the Code Quality Agent for each one.

    If required state (CrashReport, PRResult) is missing from Redis, the event
    is skipped with an error log rather than crashing the loop.
    """
    redis_url = get_redis_url()
    logger.info("code quality agent connecting to redis", extra={"redis_url": redis_url})
    redis_client = aioredis.from_url(redis_url, decode_responses=False)
    logger.info("code quality agent subscriber started — listening on helix:events:pr_created")

    async for incident_id, payload in subscribe(redis_client, "pr_created"):
        logger.info("code quality agent received pr_created event", extra={"incident_id": incident_id})
        try:
            logger.debug("reading pr_result from redis", extra={"incident_id": incident_id})
            pr_result = await read_pr_result(redis_client, incident_id)
            if pr_result is None:
                logger.warning(
                    "pr_result not in redis — falling back to event payload",
                    extra={"incident_id": incident_id},
                )
                pr_result = PRResult.model_validate(payload)
            else:
                logger.debug("pr_result loaded from redis", extra={"incident_id": incident_id})

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

            await handle(pr_result, crash_report, redis_client)
            logger.info("code quality agent finished handling pr_created", extra={"incident_id": incident_id})
        except Exception as exc:
            logger.error(
                "code quality agent failed for incident",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
