"""
Audit trail — thin helper for recording every significant Helix operation.

Call audit.record() from any agent or integration; it inserts one row into
the audit_events table and swallows errors so a DB hiccup never breaks the
main request path.
"""

import json
import logging
from typing import Any

from sqlalchemy import text

from .db import get_db

logger = logging.getLogger(__name__)


async def record(
    event_type: str,
    source: str,
    action: str,
    *,
    incident_id: str | None = None,
    project_id: str | None = None,
    status: str = "ok",
    details: dict[str, Any] | None = None,
) -> None:
    """
    Insert one audit event row.

    Args:
        event_type:  Category — "webhook", "agent_event", "slack_action", "github_op".
        source:      Origin — "rollbar", "sentry", "slack", "github", or agent name.
        action:      What happened — "received", "crash_analysed", "pr_approved", etc.
        incident_id: Related incident UUID (if known).
        project_id:  Related project UUID (if known).
        status:      "ok" or "error".
        details:     Arbitrary JSON for extra context (payload excerpt, error message).
    """
    try:
        async with get_db() as db:
            await db.execute(
                text("""
                    INSERT INTO audit_events
                        (incident_id, project_id, event_type, source, action, status, details)
                    VALUES
                        (:incident_id, :project_id, :event_type, :source, :action, :status, :details)
                """),
                {
                    "incident_id": incident_id,
                    "project_id": project_id,
                    "event_type": event_type,
                    "source": source,
                    "action": action,
                    "status": status,
                    "details": json.dumps(details) if details else None,
                },
            )
    except Exception as exc:
        logger.warning("audit record failed — continuing", extra={"error": str(exc)})
