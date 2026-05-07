"""
Shared Pydantic models for the Helix agent pipeline.

Each model maps to a stage in the pipeline:
  RollbarEvent  — raw inbound webhook from Rollbar
  CrashReport   — Crash Handler output, persisted to Redis
  QAResult      — QA Agent output (ticket + test case), persisted to Redis
  PRResult      — stored by Human Approval agent (PR merge details)
  HelixEvent    — generic event envelope for EventBridge / Redis Pub/Sub

Project models:
  AgentOverride    — per-project LLM provider/model override for one agent
  PipelineSettings — per-project pipeline tuning (max iterations, file limits)
  ProjectSettings  — full per-project credentials and config (stored in Postgres)
  Project          — a GitHub repo plus its settings, identified by project_id
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
# User repo configuration
# ---------------------------------------------------------------------------

class RepoConfig(BaseModel):
    """
    A GitHub repository the user has configured Helix to monitor and fix.

    Stored in Redis per Auth0 user under helix:user:{sub}:repos.
    The pipeline uses these configs to know which repos to clone, comment on,
    and open PRs against.
    """
    repo: str               # "owner/name", e.g. "acme/backend"
    base_branch: str = "main"   # branch PRs are opened against
    language: str = "python"    # primary language — influences test framework selection
    added_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Project configuration (repo + credentials)
# ---------------------------------------------------------------------------

class AgentOverride(BaseModel):
    """
    Per-project LLM provider and model override for a single agent.

    When set, these values take precedence over config.yaml for that agent.
    Either field can be None to inherit the global default.

    base_url is required when provider is "ollama" — it points to the
    customer's self-hosted Ollama instance, e.g. "http://my-server:11434/v1".
    Helix never hosts Ollama itself.
    """
    provider: Optional[str] = None   # e.g. "anthropic", "openrouter", "ollama"
    model: Optional[str] = None      # e.g. "claude-sonnet-4-6", "qwen2.5"
    base_url: Optional[str] = None   # required when provider = "ollama"


class PipelineSettings(BaseModel):
    """
    Per-project pipeline tuning parameters.

    These override the hardcoded defaults in each agent.
    """
    dev_max_iterations: int = 3       # max TDD fix attempts before escalation
    qa_max_source_files: int = 8      # max source files read by QA Agent
    qa_max_file_chars: int = 4000     # max characters read per source file


class ProjectSettings(BaseModel):
    """
    Per-project credential and notification settings stored in Postgres.

    Secret values are masked to '***' before being returned by the API —
    callers send '***' back to indicate "keep the existing value unchanged".

    Required for the pipeline to run:
        anthropic_api_key        — LLM calls (Crash Handler, QA, Dev agents)
        sentry_webhook_secret    — HMAC verification for Sentry webhooks  \\
        rollbar_access_token     — token verification for Rollbar webhooks /  (at least one)

    GitHub access is provided by the GitHub App installation token (resolved
    at runtime from github_installation_id on the parent Project) — no PAT needed.

    Optional notifications:
        slack_bot_token          — post approval messages / escalations
        slack_signing_secret     — verify Slack interaction payloads
        slack_approval_channel   — channel ID or name for PR approval messages
        sendgrid_api_key         — transactional email via SendGrid
        smtp_host                — SMTP server for email (fallback if SendGrid absent)
        email_from / email_to    — sender and recipient addresses for email alerts

    Advanced:
        alert_sources            — which platforms to accept webhooks from, e.g. ["sentry"]
        agent_overrides          — per-agent LLM provider/model overrides
        pipeline                 — pipeline tuning parameters
    """
    # Required
    anthropic_api_key: Optional[str] = None
    sentry_webhook_secret: Optional[str] = None
    rollbar_access_token: Optional[str] = None
    # Optional — Slack
    slack_bot_token: Optional[str] = None
    slack_signing_secret: Optional[str] = None
    slack_approval_channel: Optional[str] = None
    # Optional — Email
    sendgrid_api_key: Optional[str] = None
    smtp_host: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[str] = None
    # Optional — Advanced
    alert_sources: list[str] = Field(default_factory=lambda: ["sentry", "rollbar"])
    agent_overrides: dict[str, AgentOverride] = Field(default_factory=dict)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)


class Project(BaseModel):
    """
    A user-configured project: a GitHub repository plus its runtime credentials.

    Stored in Postgres. The project_id is the stable identity used in webhook
    URLs (/webhook/sentry/{project_id}) and as the Redis namespace for incidents.

    GitHub access is provided via the GitHub App installation identified by
    github_installation_id — no personal access token is stored.
    """
    project_id: str                                 # UUID, stable webhook identity
    name: str                                       # human-readable display name
    repo: str                                       # "owner/name", e.g. "acme/backend"
    base_branch: str = "main"                       # branch PRs are opened against
    language: str = "python"                        # primary language — influences test framework
    github_installation_id: Optional[str] = None   # GitHub App installation ID
    added_at: datetime = Field(default_factory=_now)
    settings: ProjectSettings = Field(default_factory=ProjectSettings)


# ---------------------------------------------------------------------------
# Rollbar inbound payload
# ---------------------------------------------------------------------------

class RollbarEvent(BaseModel):
    """
    Normalised inbound crash event produced by integrations/rollbar.py and
    integrations/sentry.py.

    Both parsers produce this model so the Crash Handler Agent can treat all
    crash sources identically.  The `source` field identifies the origin.

    The raw dict is preserved in `raw` so downstream agents can access
    any fields not explicitly mapped here.
    """
    item_id: str                            # source issue / item ID (numeric string)
    occurrence_id: str                      # UUID of the specific occurrence or event
    title: str
    level: Optional[str] = None            # e.g. "error", "critical"
    environment: Optional[str] = None      # e.g. "production", "staging"
    language: Optional[str] = None         # e.g. "python", "javascript"
    culprit: Optional[str] = None          # function or file that caused the error
    stack_trace: Optional[str] = None      # formatted stack trace string
    url: Optional[str] = None             # URL of the issue in the source tool
    project_id: Optional[int] = None
    source: str = "rollbar"               # "rollbar" or "sentry"
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
    project_id: str         # which Project this incident belongs to
    source_item_id: str     # issue / item ID from the originating tool (Rollbar or Sentry)
    source: str             # "rollbar" or "sentry"
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
    ticket_id: Optional[str] = None   # None when GitHub issue creation was skipped
    ticket_url: Optional[str] = None
    ticket_action: TicketAction
    test_case: TestCase
    relevant_files: list[str] = Field(default_factory=list)  # paths read from the target repo


# ---------------------------------------------------------------------------
# Dev Agent — structured diagnosis
# ---------------------------------------------------------------------------

class BugDiagnosis(BaseModel):
    """
    Structured bug diagnosis produced by the Dev Agent's initial LLM call.

    Validated against the actual source file before being used to guide the
    TDD loop.  If validation fails the diagnosis is discarded and the agent
    falls back to unguided behaviour.
    """
    root_cause: str        # one sentence
    fix_description: str   # one sentence describing the change
    file_to_edit: str      # exact relative path, e.g. "app/payments.py"
    line_to_edit: int      # 1-indexed line number
    current_line: str      # exact current text of that line
    fixed_line: str        # exact replacement text


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
    project_id: str
    timestamp: datetime = Field(default_factory=_now)
    payload: dict = Field(default_factory=dict)
