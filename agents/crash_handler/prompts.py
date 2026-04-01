"""
LLM prompts for the Crash Handler Agent.

The agent receives a raw Sentry event and must return a structured JSON
object that maps to the CrashReport model.
"""

SYSTEM = """\
You are an expert SRE analysing production crash reports.
Your job is to extract structured information from a Sentry error event so it
can feed into an automated incident response pipeline.

Always respond with a single JSON object — no prose, no markdown fences.
"""


def user(event_title: str, level: str, culprit: str, stack_trace: str, raw_summary: str) -> str:
    """
    Build the user-turn prompt for the Crash Handler LLM call.

    Args:
        event_title:  Sentry event title / exception message.
        level:        Sentry severity level string, e.g. "error", "fatal".
        culprit:      Sentry culprit field — best guess at the offending call.
        stack_trace:  Formatted stack trace string.
        raw_summary:  Any additional context from the raw payload (log message etc.).

    Returns:
        Formatted prompt string.
    """
    return f"""\
Analyse the following Sentry crash event and return a JSON object with exactly
these fields:

  severity          — one of: "critical", "high", "medium"
                      (critical = data loss / full outage; high = feature broken;
                       medium = degraded but recoverable)
  error_type        — the exception class name, e.g. "KeyError"
  error_message     — the exception message
  stack_trace       — the cleaned stack trace (keep it concise; remove noise)
  affected_component — the service or module name, e.g. "payments", "auth"
  affected_endpoint  — the HTTP endpoint or function that triggered the error,
                       e.g. "/api/v1/checkout" or "process_payment()"
  summary           — 2–3 sentence plain-English description of what went wrong
                      and the likely user impact

---
Event title:   {event_title}
Sentry level:  {level}
Culprit:       {culprit}
Stack trace:
{stack_trace}

Additional context:
{raw_summary}
---

Respond with JSON only. Example shape:
{{
  "severity": "high",
  "error_type": "KeyError",
  "error_message": "'item_id' not found in cart",
  "stack_trace": "...",
  "affected_component": "checkout",
  "affected_endpoint": "/api/v1/checkout",
  "summary": "A KeyError is raised when an item_id is missing from the cart dict ..."
}}
"""
