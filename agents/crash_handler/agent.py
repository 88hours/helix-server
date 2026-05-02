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


def _stub_report(event: RollbarEvent, incident_id: str, project_id: str) -> CrashReport:
    """Build a minimal CrashReport from raw event data, without any LLM call."""
    title = event.title or "Unknown error"
    # Best-effort split of "ErrorType: message"
    if ": " in title:
        error_type, error_message = title.split(": ", 1)
    else:
        error_type, error_message = title, title
    return CrashReport(
        incident_id=incident_id,
        project_id=project_id,
        source_item_id=event.item_id,
        source=event.source,
        severity=Severity.medium,
        error_type=error_type.strip(),
        error_message=error_message.strip(),
        stack_trace=event.stack_trace or "",
        affected_component="unknown",
        affected_endpoint="unknown",
        summary=title,
        language=(event.language or "python").lower(),
        raw_payload=event.raw,
    )


async def handle(event: RollbarEvent, redis_client: redis.Redis, project_id: str = "") -> CrashReport:
    """
    Analyse a Rollbar/Sentry event and produce a structured CrashReport.

    Steps:
      1. Generate a unique incident_id and immediately persist a stub report so
         the incident is always visible in the dashboard, even if later steps fail.
      2. Call the LLM to extract severity, error details, and a plain-English summary.
      3. Overwrite the stub with the full CrashReport and publish crash_analysed.

    On any failure the incident stays in Redis with status "failed" and a
    human-readable summary of what went wrong — no 500 is propagated to the caller.
    """
    permissions = load_permissions("crash_handler")
    incident_id = str(uuid.uuid4())
    logger.info(
        "crash handler started",
        extra={"incident_id": incident_id, "source": event.source, "source_item_id": event.item_id},
    )

    # --- 1. Persist stub immediately so the incident is always visible ---
    stub = _stub_report(event, incident_id, project_id)
    await write_crash_report(redis_client, stub)
    await write_status(redis_client, incident_id, "analysing")
    await publish_ui_event(redis_client, incident_id, "agent_start", "crash_handler", "Analysing crash report…")

    # --- 2. LLM analysis ---
    try:
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
            json_mode=True,
        )
        await publish_tool_event(redis_client, incident_id, "crash_handler", "llm", "complete", "success")

        data = extract_json(raw_response)
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

    except Exception as exc:
        # Classify common failure reasons for a human-readable message.
        reason = _failure_reason(exc)
        logger.error(
            "crash handler failed: %s",
            reason,
            exc_info=True,
            extra={"incident_id": incident_id},
        )

        # Update the stub summary so the dashboard shows why it failed.
        failed_report = stub.model_copy(update={"summary": f"Analysis failed: {reason}"})
        await write_crash_report(redis_client, failed_report)
        await write_status(redis_client, incident_id, "failed")
        await publish_ui_event(redis_client, incident_id, "agent_done", "crash_handler", f"Failed: {reason}")

        return failed_report


def _failure_reason(exc: Exception) -> str:
    """Return a short human-readable description of a handler exception."""
    msg = str(exc)
    if "credit balance is too low" in msg or "insufficient_quota" in msg:
        return "Anthropic account has no credits — top up at console.anthropic.com/billing"
    if "invalid_api_key" in msg or "authentication" in msg.lower():
        return "Invalid Anthropic API key — check project settings"
    if "rate_limit" in msg or "rate limit" in msg.lower():
        return "Anthropic rate limit hit — will retry on next event"
    if "Connection" in msg or "timeout" in msg.lower():
        return "LLM connection timeout — check network or provider status"
    # Generic fallback — include exception type for debuggability.
    return f"{type(exc).__name__}: {msg[:120]}"
