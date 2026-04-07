"""
Crash Handler Agent — core logic.

Receives a parsed RollbarEvent, calls the LLM to extract structured crash
information, persists the result to Redis, and publishes the crash_analysed
event to trigger the QA Agent.

Entry point: handle()
"""

import logging
import uuid

import redis.asyncio as redis

from agents.crash_handler import prompts
from core.events import publish
from core.llm import complete
from core.models import CrashReport, RollbarEvent, Severity
from core.permissions import load_permissions, require
from core.state import write_crash_report, write_status
from core.ui_events import publish_tool_event, publish_ui_event
from core.utils import extract_json

logger = logging.getLogger(__name__)


async def handle(event: RollbarEvent, redis_client: redis.Redis, project_id: str = "") -> CrashReport:
    """
    Analyse a Rollbar/Sentry event and produce a structured CrashReport.

    Steps:
      1. Generate a unique incident_id.
      2. Call the LLM to extract severity, error details, and a plain-English summary.
      3. Persist the CrashReport to Redis.
      4. Publish the crash_analysed event to trigger the QA Agent.

    Args:
        event:        Normalised RollbarEvent from integrations/rollbar.py or sentry.py.
        redis_client: Async Redis client for state and event publishing.
        project_id:   Project UUID — identifies which project this incident belongs to.
                      Empty string for legacy single-project deployments.

    Returns:
        The persisted CrashReport.

    Raises:
        ValueError: If the LLM returns malformed JSON or an unknown severity value.
    """
    permissions = load_permissions("crash_handler")
    incident_id = str(uuid.uuid4())
    logger.info(
        "crash handler started",
        extra={"incident_id": incident_id, "source": event.source, "source_item_id": event.item_id},
    )
    await publish_ui_event(redis_client, incident_id, "agent_start", "crash_handler", "Analysing crash report…")

    prompt = prompts.user(
        event_title=event.title,
        level=event.level or "error",
        culprit=event.culprit or "",
        stack_trace=event.stack_trace or "(no stack trace)",
        raw_summary=event.title,
        known_language=event.language or "",
        source=event.source,
    )

    await publish_ui_event(redis_client, incident_id, "agent_step", "crash_handler", "Calling LLM to classify crash…")
    raw_response = await complete(
        agent="crash_handler",
        prompt=prompt,
        system=prompts.SYSTEM,
    )
    await publish_tool_event(redis_client, incident_id, "crash_handler", "llm", "complete", "success")

    data = extract_json(raw_response)

    # Language: prefer Rollbar-provided value, fall back to LLM detection.
    language = (event.language or data.get("language") or "python").lower()

    report = CrashReport(
        incident_id=incident_id,
        project_id=project_id,
        source_item_id=event.item_id,
        source=event.source,
        severity=Severity(data["severity"]),
        error_type=data["error_type"],
        error_message=data["error_message"],
        stack_trace=data.get("stack_trace") or event.stack_trace or "",
        affected_component=data["affected_component"],
        affected_endpoint=data["affected_endpoint"],
        summary=data["summary"],
        language=language,
        raw_payload=event.raw,
    )

    await publish_ui_event(
        redis_client, incident_id, "agent_step", "crash_handler",
        f"Crash classified: {report.severity.value} severity — {report.error_type}",
    )
    logger.debug("writing crash_report to redis", extra={"incident_id": incident_id})
    require(permissions, "redis", "write_crash_report")
    await write_crash_report(redis_client, report)
    require(permissions, "redis", "write_status")
    await write_status(redis_client, incident_id, "crash_analysed")
    await publish_ui_event(redis_client, incident_id, "status_changed", "crash_handler", "crash_analysed")
    logger.debug("publishing crash_analysed event", extra={"incident_id": incident_id})
    require(permissions, "events", "publish:crash_analysed")
    await publish(redis_client, "crash_analysed", incident_id, report.model_dump(mode="json"))
    await publish_ui_event(redis_client, incident_id, "agent_done", "crash_handler", "Crash analysis complete — handing off to QA Agent")

    logger.info(
        "crash handler complete",
        extra={
            "incident_id": incident_id,
            "severity": report.severity,
            "affected_component": report.affected_component,
        },
    )
    return report
