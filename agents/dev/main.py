"""
Dev Agent — subscriber entry point.

Subscribes to two Redis channels:
  test_case_generated  — initial fix attempt after QA Agent completes
  quality_rejected     — retry after Code Quality Agent rejects the PR

Both channels share the same iteration counter (per incident) so the
MAX_ITERATIONS cap is enforced across all retries regardless of cause.

Run with:
    python -m agents.dev.main
"""

import asyncio
import logging
import os

import redis.asyncio as aioredis

from agents.dev.agent import handle, handle_retry
from core.config import get_redis_url
from core.events import subscribe
from core.models import CrashReport, QAResult, QualityResult
from core.state import read_crash_report, read_qa_result

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def _listen_test_case_generated(redis_client: aioredis.Redis) -> None:
    """Process test_case_generated events (initial fix attempt)."""
    async for incident_id, payload in subscribe(redis_client, "test_case_generated"):
        try:
            qa_result = await read_qa_result(redis_client, incident_id)
            if qa_result is None:
                qa_result = QAResult.model_validate(payload)

            crash_report = await read_crash_report(redis_client, incident_id)
            if crash_report is None:
                logger.error(
                    "crash_report missing for incident — skipping",
                    extra={"incident_id": incident_id},
                )
                continue

            await handle(qa_result, crash_report, redis_client)
        except Exception as exc:
            logger.error(
                "dev agent failed on test_case_generated",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


async def _listen_quality_rejected(redis_client: aioredis.Redis) -> None:
    """Process quality_rejected events (retry after code review failure)."""
    async for incident_id, payload in subscribe(redis_client, "quality_rejected"):
        try:
            quality_result = QualityResult.model_validate(payload)

            qa_result = await read_qa_result(redis_client, incident_id)
            crash_report = await read_crash_report(redis_client, incident_id)

            if qa_result is None or crash_report is None:
                logger.error(
                    "missing state for quality_rejected retry — skipping",
                    extra={"incident_id": incident_id},
                )
                continue

            await handle_retry(
                qa_result=qa_result,
                crash_report=crash_report,
                quality_feedback=quality_result.feedback or "",
                redis_client=redis_client,
            )
        except Exception as exc:
            logger.error(
                "dev agent failed on quality_rejected",
                extra={"incident_id": incident_id, "error": str(exc)},
                exc_info=True,
            )


async def main() -> None:
    """
    Run both subscriber loops concurrently using asyncio.gather.

    Each loop is independent — a crash in one does not affect the other.
    """
    redis_client = aioredis.from_url(get_redis_url(), decode_responses=False)
    logger.info("dev agent subscriber started")

    await asyncio.gather(
        _listen_test_case_generated(redis_client),
        _listen_quality_rejected(redis_client),
    )


if __name__ == "__main__":
    asyncio.run(main())
