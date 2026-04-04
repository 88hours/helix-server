"""
Notifier Agent — subscriber entry point.

Subscribes to the fix_suggested Redis channel and calls the Notifier Agent
for every new incident.

Run with:
    python -m agents.notifier.main
"""

import asyncio
import logging
import os

import redis.asyncio as aioredis

from agents.notifier.agent import handle
from core.config import get_redis_url
from core.events import subscribe

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def main() -> None:
    """
    Subscribe to fix_suggested events and run the Notifier Agent for each one.

    Reads issue_url from the event payload. If the payload is malformed or
    missing issue_url, the event is skipped with a warning rather than crashing
    the loop.
    """
    redis_url = get_redis_url()
    logger.info("notifier agent connecting to redis", extra={"redis_url": redis_url})
    redis_client = aioredis.from_url(redis_url, decode_responses=False)
    logger.info("notifier agent started — listening on helix:events:fix_suggested")

    async for incident_id, payload in subscribe(redis_client, "fix_suggested"):
        logger.info("notifier agent received event", extra={"incident_id": incident_id})
        try:
            issue_url = payload.get("issue_url", "")
            if not issue_url:
                logger.warning(
                    "fix_suggested payload missing issue_url — skipping",
                    extra={"incident_id": incident_id},
                )
                continue

            await handle(incident_id, issue_url, redis_client)
            logger.info("notifier agent finished", extra={"incident_id": incident_id})
        except Exception as exc:
            logger.error(
                "notifier agent failed for incident",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
