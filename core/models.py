"""
Shared Pydantic models for the Helix agent pipeline.

Each model maps to a stage in the pipeline:
  RollbarEvent  — raw inbound webhook from Rollbar
  CrashReport   — Crash Handler output, persisted to Redis
  QAResult      — QA Agent output (ticket + test case), persisted to Redis
  PRResult      — stored by Human Approval agent (PR merge details)
  HelixEvent    — generic event envelope for EventBridge / Redis Pub/Sub
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class Severity(str, Enum):
    """Crash severity classification produced by the Crash Handler."""
    critical = "critical"
    high = "high"
    medium = "medium"


class TestFormat(str, Enum):
    """Test framework used by the generated test case."""
    pytest = "pytest"       # Python
    unittest = "unittest"   # Python (legacy)
    jest = "jest"           # JavaScript / TypeScript
    rspec = "rspec"         # Ruby
    junit = "junit"         # Java / Kotlin
    go_test = "go_test"     # Go


def language_to_test_format(language: str) -> "TestFormat":
    """
    Map a language name (as reported by Rollbar) to its default test framework.

    Args:
        language: Language string, e.g. "python", "javascript", "ruby".

    Returns:
        The TestFormat enum value for the language's default test framework.
        Falls back to pytest for unknown languages.
    """
    mapping = {
        "python": TestFormat.pytest,
        "javascript": TestFormat.jest,
        "typescript": TestFormat.jest,
        "ruby": TestFormat.rspec,
        "java": TestFormat.junit,
        "kotlin": TestFormat.junit,
        "go": TestFormat.go_test,
    }
    return mapping.get(language.lower(), TestFormat.pytest)


class TicketAction(str, Enum):
    """Whether the QA Agent created a new ticket or updated an existing one."""
    created = "created"
    updated = "updated"


# ---------------------------------------------------------------------------
# Rollbar inbound payload
# ---------------------------------------------------------------------------

class RollbarEvent(BaseModel):
    """
    Normalised representation of a Rollbar webhook payload.

    The raw dict is preserved in `raw` so downstream agents can access
    any fields not explicitly mapped here.
    """
    item_id: str                            # Rollbar item ID (numeric, as string)
    occurrence_id: str                      # UUID of the specific occurrence
    title: str
    level: Optional[str] = None            # e.g. "error", "critical"
    environment: Optional[str] = None      # e.g. "production", "staging"
    language: Optional[str] = None         # e.g. "python", "javascript"
    culprit: Optional[str] = None          # Rollbar occurrence context
    stack_trace: Optional[str] = None      # formatted stack trace string
    url: Optional[str] = None             # URL of the Rollbar item
    project_id: Optional[int] = None
    raw: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Crash Handler output
# ---------------------------------------------------------------------------

class CrashReport(BaseModel):
    """
    Structured crash report produced by the Crash Handler Agent.

    Written to Redis at key: helix:incident:{incident_id}:crash_report
    Published as the payload of the CrashAnalysed event.
    """
    incident_id: str
    rollbar_item_id: str
    severity: Severity
    error_type: str                 # e.g. "KeyError", "NullPointerException"
    error_message: str
    stack_trace: str
    affected_component: str         # e.g. "auth", "payments", "api-gateway"
    affected_endpoint: str          # e.g. "/api/v1/checkout"
    summary: str                    # plain-English, one paragraph
    language: str = "python"        # e.g. "python", "javascript", "ruby", "java", "go"
    timestamp: datetime = Field(default_factory=_now)
    raw_payload: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# QA Agent output
# ---------------------------------------------------------------------------

class TestCase(BaseModel):
    """
    A single failing test case that reproduces the crash.

    Written by the QA Agent and consumed by the Dev Agent.
    """
    file_path: str          # relative path in the target repo, e.g. "tests/test_checkout.py"
    test_name: str          # function name, e.g. "test_checkout_raises_on_missing_item"
    content: str            # full source of the test file
    format: TestFormat = TestFormat.pytest


class QAResult(BaseModel):
    """
    Output of the QA Agent: a JIRA/GitHub ticket and a failing TDD test case.

    Written to Redis at key: helix:incident:{incident_id}:test_case
    Published as the payload of the TestCaseGenerated event.
    """
    incident_id: str
    ticket_id: str          # e.g. "PROJ-123" (JIRA) or "#42" (GitHub Issues)
    ticket_url: str
    ticket_action: TicketAction
    test_case: TestCase
    relevant_files: list[str] = Field(default_factory=list)  # paths read from the target repo


# ---------------------------------------------------------------------------
# Dev Agent output
# ---------------------------------------------------------------------------

class PRResult(BaseModel):
    """
    Output of the Dev Agent: a merged-ready pull request with the fix.

    Written to Redis at key: helix:incident:{incident_id}:pr
    Published as the payload of the PRCreated event.
    """
    incident_id: str
    pr_url: str
    pr_number: int
    branch_name: str
    iterations_taken: int           # number of fix-and-test cycles used (max 3)
    files_changed: list[str] = Field(default_factory=list)
    fix_summary: str                # plain-English description for the PR body


# ---------------------------------------------------------------------------
# Generic event envelope
# ---------------------------------------------------------------------------

class HelixEvent(BaseModel):
    """
    Envelope for all events published to EventBridge or Redis Pub/Sub.

    The `payload` field holds the serialised model for that event type
    (e.g. CrashReport.model_dump() for CrashAnalysed).
    """
    incident_id: str
    timestamp: datetime = Field(default_factory=_now)
    payload: dict = Field(default_factory=dict)
