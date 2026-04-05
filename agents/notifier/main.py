"""
Notifier Agent — subscriber entry point.

Subscribes to two Redis channels concurrently:
  fix_suggested — sends Slack/email with a link to the GitHub Issue.
  fix_failed    — sends Slack/email escalation when Dev Agent exhausts retries.

Run with:
    python -m agents.notifier.main
"""

import asyncio
import logging
import os

import redis.asyncio as aioredis

from agents.notifier.agent import handle, handle_escalation
from core.config import get_redis_url
from core.events import subscribe

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def _listen_fix_suggested(redis_client: aioredis.Redis) -> None:
    """Subscribe to fix_suggested and dispatch handle() for each event."""
    logger.info("notifier agent listening on helix:events:fix_suggested")
    async for incident_id, payload in subscribe(redis_client, "fix_suggested", agent_name="notifier"):
        logger.info(
            "notifier received fix_suggested",
            extra={"incident_id": incident_id},
        )
        try:
            issue_url = payload.get("issue_url", "")
            if not issue_url:
                logger.warning(
                    "fix_suggested payload missing issue_url — skipping",
                    extra={"incident_id": incident_id},
                )
                continue
            await handle(incident_id, issue_url, redis_client)
            logger.info(
                "notifier finished fix_suggested",
                extra={"incident_id": incident_id},
            )
        except Exception as exc:
            logger.error(
                "notifier failed on fix_suggested",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


async def _listen_fix_failed(redis_client: aioredis.Redis) -> None:
    """Subscribe to fix_failed and dispatch handle_escalation() for each event."""
    logger.info("notifier agent listening on helix:events:fix_failed")
    async for incident_id, payload in subscribe(redis_client, "fix_failed", agent_name="notifier"):
        logger.info(
            "notifier received fix_failed",
            extra={"incident_id": incident_id},
        )
        try:
            await handle_escalation(
                incident_id=incident_id,
                crash_summary=payload.get("crash_summary", ""),
                attempts=payload.get("attempts", 0),
                context=payload.get("context", "No attempts recorded."),
                redis_client=redis_client,
            )
            logger.info(
                "notifier finished fix_failed escalation",
                extra={"incident_id": incident_id},
            )
        except Exception as exc:
            logger.error(
                "notifier failed on fix_failed",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


async def main() -> None:
    """Connect to Redis and run both subscription loops concurrently."""
    redis_url = get_redis_url()
    logger.info("notifier agent connecting to redis", extra={"redis_url": redis_url})
    redis_client = aioredis.from_url(redis_url, decode_responses=False)

    await asyncio.gather(
        _listen_fix_suggested(redis_client),
        _listen_fix_failed(redis_client),
    )


if __name__ == "__main__":
    asyncio.run(main())
