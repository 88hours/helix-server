"""
Sentry integration for the Helix Crash Handler Agent.

Provides:
  verify_signature  — HMAC-SHA256 webhook signature verification
  parse_event       — normalise a raw Sentry webhook payload into a SentryEvent

Sentry sends a POST to your webhook URL with:
  Header:  sentry-hook-signature: <hex digest>
  Body:    JSON payload

The signature is HMAC-SHA256(secret_key, body_bytes).
"""

import hashlib
import hmac
import logging
from typing import Any

from core.models import SentryEvent

logger = logging.getLogger(__name__)


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify a Sentry webhook HMAC-SHA256 signature.

    Args:
        payload:   Raw request body bytes (before any decoding).
        signature: Value of the sentry-hook-signature header.
        secret:    SENTRY_WEBHOOK_SECRET from the environment.

    Returns:
        True if the signature is valid; False otherwise.
    """
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_event(raw: dict[str, Any]) -> SentryEvent:
    """
    Normalise a raw Sentry webhook payload into a SentryEvent.

    Sentry webhook payloads vary by action and DSN version.  This function
    handles the most common shape (issue alert / error event) and preserves
    the full raw dict so downstream agents can access any field not explicitly
    mapped here.

    Args:
        raw: The parsed JSON body of the Sentry webhook POST.

    Returns:
        A SentryEvent with all available fields populated.
    """
    event: dict[str, Any] = raw.get("event", {})

    # Extract stack trace from the first exception value.
    stack_trace = _extract_stack_trace(event)

    # The event_id may live at different depths depending on Sentry version.
    event_id = (
        event.get("event_id")
        or event.get("id")
        or raw.get("id", "")
    )

    # Title / message resolution order.
    title = (
        raw.get("message")
        or event.get("title")
        or event.get("logentry", {}).get("formatted")
        or event.get("logentry", {}).get("message")
        or "Unknown error"
    )

    logger.info(
        "sentry event parsed",
        extra={"event_id": event_id, "level": event.get("level")},
    )

    return SentryEvent(
        event_id=event_id,
        title=title,
        message=event.get("logentry", {}).get("message"),
        culprit=event.get("culprit"),
        level=event.get("level"),
        platform=event.get("platform"),
        stack_trace=stack_trace,
        url=raw.get("url"),
        project_slug=raw.get("project_slug"),
        raw=raw,
    )


def _extract_stack_trace(event: dict[str, Any]) -> str | None:
    """
    Build a human-readable stack trace string from the Sentry event.

    Processes the first exception value's stack frames, most recent last,
    in the same format Python itself uses for tracebacks.

    Args:
        event: The inner "event" dict from the Sentry webhook payload.

    Returns:
        Formatted stack trace string, or None if no frames are present.
    """
    exception_values: list[dict] = (
        event.get("exception", {}).get("values", [])
    )
    if not exception_values:
        return None

    exc = exception_values[0]
    frames: list[dict] = exc.get("stacktrace", {}).get("frames", [])
    if not frames:
        return None

    lines = ["Traceback (most recent call last):"]
    for frame in frames:
        filename = frame.get("filename", "<unknown>")
        lineno = frame.get("lineno", "?")
        function = frame.get("function", "<unknown>")
        context = frame.get("context_line", "").strip()
        lines.append(f'  File "{filename}", line {lineno}, in {function}')
        if context:
            lines.append(f"    {context}")

    exc_type = exc.get("type", "Exception")
    exc_value = exc.get("value", "")
    lines.append(f"{exc_type}: {exc_value}")

    return "\n".join(lines)
