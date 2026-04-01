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
    redis_client = aioredis.from_url(get_redis_url(), decode_responses=False)
    logger.info("code quality agent subscriber started")

    async for incident_id, payload in subscribe(redis_client, "pr_created"):
        try:
            pr_result = await read_pr_result(redis_client, incident_id)
            if pr_result is None:
                pr_result = PRResult.model_validate(payload)

            crash_report = await read_crash_report(redis_client, incident_id)
            if crash_report is None:
                logger.error(
                    "crash_report missing for incident — skipping",
                    extra={"incident_id": incident_id},
                )
                continue

            await handle(pr_result, crash_report, redis_client)
        except Exception as exc:
            logger.error(
                "code quality agent failed for incident",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
