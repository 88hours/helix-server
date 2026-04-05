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
from core.events import subscribe
from core.models import CrashReport, QAResult
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

            await handle(qa_result, crash_report, redis_client)
            logger.info("dev agent finished handling test_case_generated", extra={"incident_id": incident_id})
        except Exception as exc:
            logger.error(
                "dev agent failed on test_case_generated",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
