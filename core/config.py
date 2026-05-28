"""
Configuration loader for Helix.

Reads settings from config.yaml and applies environment variable overrides.
No secrets are stored in config.yaml — only the names of the env vars that
hold them (url_env, region_env, etc.).

Agent model/provider overrides:
    HELIX_<AGENT>_PROVIDER   e.g. HELIX_DEV_PROVIDER=anthropic
    HELIX_<AGENT>_MODEL      e.g. HELIX_DEV_MODEL=claude-sonnet-4-6

Event backend override:
    HELIX_EVENT_BACKEND      "redis" (default) or "eventbridge"

Redis URL (used for both state and Redis Pub/Sub):
    REDIS_URL                e.g. redis://localhost:6379

EventBridge overrides:
    HELIX_EVENTBRIDGE_BUS    event bus name (default: helix-mvp)
    AWS_REGION               AWS region for the EventBridge client

Integration env vars (names stored in config.yaml, values in environment):
    ROLLBAR_ACCESS_TOKEN     Rollbar project read token — verified against data.access_token in the payload
    GITHUB_TOKEN             GitHub personal access token or App token (repo scope)
    JIRA_URL                 JIRA base URL, e.g. https://acme.atlassian.net
    JIRA_EMAIL               JIRA account email for Basic auth
    JIRA_TOKEN               JIRA API token
    JIRA_PROJECT_KEY         Default JIRA project key, e.g. PROJ
    SLACK_BOT_TOKEN          Slack bot token (xoxb-...)
    SLACK_APPROVAL_CHANNEL   Channel ID or name for approval messages

Usage:
    from core.config import get_agent_config, get_redis_url, get_event_backend
    from core.config import get_rollbar_config, get_github_config
    from core.config import get_jira_config, get_slack_config, ProjectConfig

    cfg = get_agent_config("dev")       # AgentConfig(provider, model)
    url = get_redis_url()               # "redis://..."
    backend = get_event_backend()       # "redis" or "eventbridge"
    gh = get_github_config()            # GitHubConfig(target_repo, base_branch, token)
    ls = get_langsmith_config()         # LangSmithConfig(api_key, project, tracing_enabled)

    # Per-project config (Phase 3+):
    pc = ProjectConfig(project)
    gh = pc.github(installation_token)  # GitHubConfig using the App installation token
    sl = pc.slack()                     # SlackConfig from project settings, falls back to env vars
"""

import logging
import os

_logger = logging.getLogger(__name__)
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# Path to config.yaml — always relative to this file's parent directory.
_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AgentConfig:
    """Model and provider settings for a single agent."""
    agent: str                      # agent name as it appears in config.yaml, e.g. "dev"
    provider: str                   # "anthropic" | "openrouter" | "claude-code" | "ollama"
    model: str                      # model identifier, e.g. "claude-sonnet-4-6"
    base_url: Optional[str] = None  # required when provider = "ollama" (customer-provided)


@dataclass
class EventBridgeConfig:
    """AWS EventBridge connection settings."""
    bus: str        # event bus name, e.g. "helix-mvp"
    region: str     # AWS region, e.g. "us-east-1"


@dataclass
class RollbarConfig:
    """Rollbar webhook integration settings."""
    access_token: str   # Rollbar project read token — verified against data.access_token in the payload


@dataclass
class SentryConfig:
    """Sentry webhook integration settings."""
    webhook_secret: str | None  # Sentry client secret for HMAC-SHA256 signature verification; None → check skipped


@dataclass
class GitHubConfig:
    """GitHub integration settings."""
    target_repo: str    # "owner/name" of the repo Helix is fixing, e.g. "acme/backend"
    base_branch: str    # branch PRs are opened against, usually "main"
    token: str          # GitHub personal access token or App token


@dataclass
class JiraConfig:
    """JIRA integration settings."""
    url: str            # JIRA base URL, e.g. "https://acme.atlassian.net"
    email: str          # JIRA account email for Basic auth
    token: str          # JIRA API token
    project_key: str    # default project key, e.g. "PROJ"


@dataclass
class SlackConfig:
    """Slack integration settings."""
    token: str | None           # Slack bot token (xoxb-...); None → notifications skipped
    signing_secret: str | None  # Slack app signing secret — used to verify interaction payloads
    approval_channel: str | None  # channel ID or name for approval/escalation messages


@dataclass
class LangSmithConfig:
    """LangSmith tracing and eval settings."""
    api_key: str | None     # LangSmith API key; None → tracing disabled
    project: str            # LangSmith project name, e.g. "helix"
    endpoint: str           # LangSmith API endpoint URL
    tracing_enabled: bool   # True when API key is set and LANGSMITH_TRACING=true


@dataclass
class LangfuseConfig:
    """Langfuse LLM observability settings."""
    secret_key: str | None   # LANGFUSE_SECRET_KEY; None → tracing disabled
    public_key: str | None   # LANGFUSE_PUBLIC_KEY; None → tracing disabled
    host: str                # LANGFUSE_HOST; default: https://cloud.langfuse.com
    enabled: bool            # True when both keys are set


@dataclass
class OtelConfig:
    """OpenTelemetry distributed tracing settings."""
    enabled: bool       # True when OTEL_ENABLED=true
    endpoint: str       # OTLP/gRPC endpoint, default http://localhost:4317
    service_name: str   # OTel service.name resource attribute, default "helix"


@dataclass
class EmailConfig:
    """Email notification settings — SendGrid API or SMTP fallback."""
    from_addr: str | None           # sender address; None → email notifications skipped
    to_addrs: str | None            # comma-separated recipient list; None → skipped
    sendgrid_api_key: str | None    # set → SendGrid API is used; None → SMTP fallback
    smtp_host: str | None           # SMTP hostname (only needed when no SendGrid key)
    smtp_port: int                  # SMTP port, default 587
    smtp_user: str | None           # SMTP username (only needed when no SendGrid key)
    smtp_password: str | None       # SMTP password (only needed when no SendGrid key)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_yaml() -> dict:
    """Read and parse config.yaml. Raises if the file is missing or malformed."""
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.yaml not found at {_CONFIG_PATH}")
    with _CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def _require_env(var: str) -> str:
    """Return the value of an environment variable, raising if it is not set."""
    value = os.environ.get(var)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{var}' is not set. "
            "Check your .env file or deployment config."
        )
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_agent_config(agent: str) -> AgentConfig:
    """
    Return the resolved AgentConfig for the given agent name.

    Resolution order (highest wins):
      1. Environment variable  HELIX_<AGENT>_PROVIDER / HELIX_<AGENT>_MODEL
      2. config.yaml entry for the agent

    Args:
        agent: Agent name matching a key under `agents:` in config.yaml,
               e.g. "crash_handler", "qa", "dev", "code_quality".

    Returns:
        AgentConfig with the resolved provider and model.

    Raises:
        FileNotFoundError: config.yaml does not exist.
        KeyError: The agent name is not defined in config.yaml.
        ValueError: The resolved provider or model is empty.
    """
    raw = _load_yaml()

    agents = raw.get("agents", {})
    if agent not in agents:
        available = ", ".join(agents.keys())
        raise KeyError(f"Agent '{agent}' not found in config.yaml. Available: {available}")

    agent_yaml = agents[agent]
    env_prefix = f"HELIX_{agent.upper()}_"

    provider = os.environ.get(f"{env_prefix}PROVIDER") or agent_yaml.get("provider", "")
    model = os.environ.get(f"{env_prefix}MODEL") or agent_yaml.get("model", "")
    base_url = (
        os.environ.get(f"{env_prefix}BASE_URL")
        or os.environ.get("HELIX_OLLAMA_BASE_URL")
        or agent_yaml.get("base_url")
    )

    if not provider:
        raise ValueError(f"No provider configured for agent '{agent}'")
    if not model:
        raise ValueError(f"No model configured for agent '{agent}'")

    _logger.info(
        "agent config resolved",
        extra={"agent": agent, "provider": provider, "model": model, "base_url": base_url or "not set"},
    )
    return AgentConfig(agent=agent, provider=provider, model=model, base_url=base_url)


def is_demo_mode() -> bool:
    """
    Return True when demo mode is enabled.

    In demo mode the crash handler skips webhook signature and access-token
    verification for both /webhook/rollbar and /webhook/sentry, so the
    pipeline can be exercised without real credentials.

    Resolution order:
      1. HELIX_DEMO environment variable ("false" / "0" → False, "true" / "1" → True)
      2. demo key in config.yaml (default: true)
    """
    raw = _load_yaml()
    yaml_value = raw.get("demo", False)
    env_value = os.environ.get("HELIX_DEMO", "").split("#")[0].strip().lower()
    if env_value in ("false", "0"):
        return False
    if env_value in ("true", "1"):
        return True
    return bool(yaml_value)


def get_event_backend() -> str:
    """
    Return the configured event backend: "redis" or "eventbridge".

    Resolution order:
      1. HELIX_EVENT_BACKEND environment variable
      2. events.backend in config.yaml
      3. Defaults to "redis"

    Raises:
        ValueError: The resolved backend is not a recognised value.
    """
    raw = _load_yaml()
    yaml_backend = raw.get("events", {}).get("backend", "redis")
    backend = os.environ.get("HELIX_EVENT_BACKEND", yaml_backend).lower()

    if backend not in ("redis", "eventbridge"):
        raise ValueError(
            f"Unknown event backend '{backend}'. Must be 'redis' or 'eventbridge'."
        )
    return backend


def get_redis_url() -> str:
    """
    Return the Redis connection URL from the environment.

    The env var name is read from config.yaml (events.redis.url_env and
    redis.url_env — both point to REDIS_URL by default).

    Raises:
        EnvironmentError: The REDIS_URL environment variable is not set.
    """
    raw = _load_yaml()
    url_env = raw.get("redis", {}).get("url_env", "REDIS_URL")
    return _require_env(url_env)


def get_bedrock_region() -> str:
    """Return the AWS region for Bedrock calls. Reads AWS_BEDROCK_REGION env var, falls back to config.yaml settings.aws_bedrock_region, then us-east-1."""
    raw = _load_yaml()
    yaml_region = raw.get("settings", {}).get("aws_bedrock_region", "us-east-1")
    return os.environ.get("AWS_BEDROCK_REGION", yaml_region)


def get_redis_mode() -> str:
    """
    Return the Redis messaging mode: "streams" or "pubsub".

    Resolution order:
      1. HELIX_REDIS_MODE environment variable
      2. events.redis.redis_mode in config.yaml
      3. Defaults to "streams"

    Raises:
        ValueError: The resolved mode is not a recognised value.
    """
    raw = _load_yaml()
    yaml_mode = raw.get("events", {}).get("redis", {}).get("redis_mode", "streams")
    mode = os.environ.get("HELIX_REDIS_MODE", yaml_mode).lower()
    if mode not in ("streams", "pubsub"):
        raise ValueError(
            f"Unknown HELIX_REDIS_MODE '{mode}'. Must be 'streams' or 'pubsub'."
        )
    return mode


def get_rollbar_config() -> RollbarConfig:
    """
    Return Rollbar webhook integration settings.

    Reads the project access token from the env var named in config.yaml
    (rollbar.access_token_env, defaulting to ROLLBAR_ACCESS_TOKEN).

    Raises:
        EnvironmentError: ROLLBAR_ACCESS_TOKEN env var is not set.
    """
    raw = _load_yaml()
    token_env = raw.get("rollbar", {}).get("access_token_env", "ROLLBAR_ACCESS_TOKEN")
    return RollbarConfig(access_token=_require_env(token_env))


def get_sentry_config() -> SentryConfig:
    """
    Return Sentry webhook integration settings.

    The webhook secret is optional — if SENTRY_WEBHOOK_SECRET is not set,
    signature verification is skipped and a warning is logged.  This allows
    the endpoint to be tested without a secret, but should always be set in
    production.

    Resolution order:
      1. SENTRY_WEBHOOK_SECRET environment variable
      2. config.yaml sentry.webhook_secret_env (defaults to SENTRY_WEBHOOK_SECRET)
    """
    raw = _load_yaml()
    secret_env = raw.get("sentry", {}).get("webhook_secret_env", "SENTRY_WEBHOOK_SECRET")
    return SentryConfig(webhook_secret=os.environ.get(secret_env) or None)


def get_github_config() -> GitHubConfig:
    """
    Return GitHub integration settings.

    Resolution order for each field:
      1. Environment variable (HELIX_GITHUB_REPO, HELIX_GITHUB_BASE_BRANCH, GITHUB_TOKEN)
      2. config.yaml (github.target_repo, github.base_branch, github.token_env)

    Raises:
        ValueError:        target_repo is not configured.
        EnvironmentError:  GITHUB_TOKEN env var is not set.
    """
    raw = _load_yaml()
    gh = raw.get("github", {})

    target_repo = os.environ.get("HELIX_GITHUB_REPO") or gh.get("target_repo", "")
    if not target_repo:
        raise ValueError(
            "github.target_repo is not set in config.yaml and HELIX_GITHUB_REPO is not set. "
            "Set it to 'owner/repo', e.g. 'acme/backend'."
        )

    base_branch = os.environ.get("HELIX_GITHUB_BASE_BRANCH") or gh.get("base_branch", "main")
    token_env = gh.get("token_env", "GITHUB_TOKEN")
    token = _require_env(token_env)

    return GitHubConfig(target_repo=target_repo, base_branch=base_branch, token=token)


def get_jira_config() -> JiraConfig:
    """
    Return JIRA integration settings.

    All values come from env vars whose names are stored in config.yaml.
    Resolution order: environment variable → config.yaml default env var name.

    Raises:
        EnvironmentError: Any required env var is not set.
    """
    raw = _load_yaml()
    jira = raw.get("jira", {})

    url_env = jira.get("url_env", "JIRA_URL")
    email_env = jira.get("email_env", "JIRA_EMAIL")
    token_env = jira.get("token_env", "JIRA_TOKEN")
    project_key_env = jira.get("project_key_env", "JIRA_PROJECT_KEY")

    return JiraConfig(
        url=_require_env(url_env),
        email=_require_env(email_env),
        token=_require_env(token_env),
        project_key=_require_env(project_key_env),
    )


def get_slack_config() -> SlackConfig:
    """
    Return Slack integration settings.

    Resolution order: environment variable → config.yaml default env var name.
    Missing variables resolve to None — callers must handle None gracefully
    (the Slack integration logs a warning and skips rather than raising).
    """
    raw = _load_yaml()
    slack = raw.get("slack", {})

    token_env = slack.get("token_env", "SLACK_BOT_TOKEN")
    signing_secret_env = slack.get("signing_secret_env", "SLACK_SIGNING_SECRET")
    channel_env = slack.get("approval_channel_env", "SLACK_APPROVAL_CHANNEL")

    return SlackConfig(
        token=os.environ.get(token_env) or None,
        signing_secret=os.environ.get(signing_secret_env) or None,
        approval_channel=os.environ.get(channel_env) or None,
    )


def get_email_config() -> EmailConfig:
    """
    Return email notification settings.

    SendGrid is used when SENDGRID_API_KEY is set. SMTP is used as a fallback
    when no SendGrid key is present. If neither backend is configured, or
    EMAIL_FROM / EMAIL_TO are missing, the email integration logs a warning
    and skips rather than raising.
    """
    raw = _load_yaml()
    email = raw.get("email", {})

    from_env = email.get("from_env", "EMAIL_FROM")
    to_env = email.get("to_env", "EMAIL_TO")
    sg_env = email.get("sendgrid_api_key_env", "SENDGRID_API_KEY")
    smtp_host_env = email.get("smtp_host_env", "SMTP_HOST")
    smtp_user_env = email.get("smtp_user_env", "SMTP_USER")
    smtp_password_env = email.get("smtp_password_env", "SMTP_PASSWORD")
    _smtp_port_raw = os.environ.get("SMTP_PORT", str(email.get("smtp_port", 587)))
    # Strip inline comments (e.g. "587 # STARTTLS") and fall back to 587 on bad values.
    _smtp_port_raw = _smtp_port_raw.split("#")[0].strip()
    try:
        smtp_port = int(_smtp_port_raw)
    except ValueError:
        smtp_port = 587

    return EmailConfig(
        from_addr=os.environ.get(from_env) or None,
        to_addrs=os.environ.get(to_env) or None,
        sendgrid_api_key=os.environ.get(sg_env) or None,
        smtp_host=os.environ.get(smtp_host_env) or None,
        smtp_port=smtp_port,
        smtp_user=os.environ.get(smtp_user_env) or None,
        smtp_password=os.environ.get(smtp_password_env) or None,
    )


def get_langsmith_config() -> LangSmithConfig:
    """
    Return LangSmith tracing and eval settings.

    Tracing is enabled when LANGSMITH_API_KEY is set AND LANGSMITH_TRACING is
    "true".  If LANGSMITH_API_KEY is absent, tracing is always disabled.

    Resolution order for each field:
      1. Environment variable (LANGSMITH_API_KEY, LANGSMITH_PROJECT,
         LANGSMITH_TRACING, LANGSMITH_ENDPOINT)
      2. config.yaml (langsmith.api_key_env, langsmith.project_env,
         langsmith.tracing_env, langsmith.endpoint_env)
      3. Defaults: project → "helix",
                   endpoint → "https://api.smith.langchain.com",
                   tracing → disabled
    """
    raw = _load_yaml()
    ls = raw.get("langsmith", {})

    api_key_env = ls.get("api_key_env", "LANGSMITH_API_KEY")
    project_env = ls.get("project_env", "LANGSMITH_PROJECT")
    tracing_env = ls.get("tracing_env", "LANGSMITH_TRACING")
    endpoint_env = ls.get("endpoint_env", "LANGSMITH_ENDPOINT")

    api_key = os.environ.get(api_key_env) or None
    project = os.environ.get(project_env) or "helix"
    endpoint = os.environ.get(endpoint_env) or "https://api.smith.langchain.com"
    tracing_flag = os.environ.get(tracing_env, "").lower()
    tracing_enabled = api_key is not None and tracing_flag in ("true", "1")

    return LangSmithConfig(
        api_key=api_key,
        project=project,
        endpoint=endpoint,
        tracing_enabled=tracing_enabled,
    )


def get_langfuse_config() -> LangfuseConfig:
    """
    Return Langfuse observability settings.

    Tracing is enabled when both LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY
    are set. If either is absent, tracing is disabled.

    Resolution order for each field:
      1. Environment variable (LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY,
         LANGFUSE_HOST)
      2. config.yaml (langfuse.secret_key_env, langfuse.public_key_env,
         langfuse.host_env)
      3. Defaults: host → "https://cloud.langfuse.com"
    """
    raw = _load_yaml()
    lf = raw.get("langfuse", {})

    secret_key_env = lf.get("secret_key_env", "LANGFUSE_SECRET_KEY")
    public_key_env = lf.get("public_key_env", "LANGFUSE_PUBLIC_KEY")
    host_env = lf.get("host_env", "LANGFUSE_HOST")

    secret_key = os.environ.get(secret_key_env) or None
    public_key = os.environ.get(public_key_env) or None
    host = os.environ.get(host_env) or "https://cloud.langfuse.com"

    return LangfuseConfig(
        secret_key=secret_key,
        public_key=public_key,
        host=host,
        enabled=secret_key is not None and public_key is not None,
    )


def get_pipeline_config() -> dict:
    """
    Return pipeline behaviour settings with environment variable overrides.

    Resolution order for each value:
      1. Environment variable
      2. config.yaml pipeline section
      3. Hardcoded default

    Returns:
        dict with keys:
          dev_max_iterations (int)  — max TDD fix attempts before escalation
          dev_tdd_timeout    (int)  — TDD loop wall-clock budget in seconds
          qa_max_source_files (int) — max source files read by QA Agent
          qa_max_file_chars   (int) — max chars read per source file by QA Agent
    """
    raw = _load_yaml()
    p = raw.get("pipeline", {})

    def _int(env_var: str, yaml_key: str, default: int) -> int:
        raw_val = os.environ.get(env_var, "").split("#")[0].strip()
        try:
            return int(raw_val)
        except ValueError:
            pass
        return int(p.get(yaml_key, default))

    return {
        "dev_max_iterations": _int("HELIX_DEV_MAX_ITERATIONS", "dev_max_iterations", 3),
        "dev_tdd_timeout": _int("HELIX_DEV_TDD_TIMEOUT", "dev_tdd_timeout", 480),
        "qa_max_source_files": _int("HELIX_QA_MAX_SOURCE_FILES", "qa_max_source_files", 8),
        "qa_max_file_chars": _int("HELIX_QA_MAX_FILE_CHARS", "qa_max_file_chars", 4000),
        "qa_max_test_retries": _int("HELIX_QA_MAX_TEST_RETRIES", "qa_max_test_retries", 1),
    }


def get_otel_config() -> OtelConfig:
    """
    Return OpenTelemetry tracing settings.

    Tracing is enabled only when OTEL_ENABLED is set to "true" or "1".
    When disabled the OTel API's built-in no-op tracer is used automatically —
    no overhead, no errors.

    Resolution order for each field:
      1. Environment variable (OTEL_ENABLED, OTEL_EXPORTER_OTLP_ENDPOINT,
         OTEL_SERVICE_NAME)
      2. config.yaml (otel.enabled_env, otel.endpoint_env, otel.service_name_env)
      3. Defaults: endpoint → "http://localhost:4317", service_name → "helix"
    """
    raw = _load_yaml()
    otel = raw.get("otel", {})

    enabled_env = otel.get("enabled_env", "OTEL_ENABLED")
    endpoint_env = otel.get("endpoint_env", "OTEL_EXPORTER_OTLP_ENDPOINT")
    service_name_env = otel.get("service_name_env", "OTEL_SERVICE_NAME")

    enabled = os.environ.get(enabled_env, "").lower() in ("true", "1")
    endpoint = os.environ.get(endpoint_env) or "http://localhost:4317"
    service_name = os.environ.get(service_name_env) or "helix"

    return OtelConfig(enabled=enabled, endpoint=endpoint, service_name=service_name)


def get_eventbridge_config() -> EventBridgeConfig:
    """
    Return EventBridge connection settings.

    Resolution order for each field:
      1. Environment variable (HELIX_EVENTBRIDGE_BUS, AWS_REGION)
      2. config.yaml (events.eventbridge.bus, events.eventbridge.region_env)

    Raises:
        EnvironmentError: AWS_REGION is not set.
    """
    raw = _load_yaml()
    eb_yaml = raw.get("events", {}).get("eventbridge", {})

    bus = os.environ.get("HELIX_EVENTBRIDGE_BUS") or eb_yaml.get("bus", "helix-mvp")
    region_env = eb_yaml.get("region_env", "AWS_REGION")
    region = _require_env(region_env)

    return EventBridgeConfig(bus=bus, region=region)


# ---------------------------------------------------------------------------
# Per-project config adapter (Phase 3+)
# ---------------------------------------------------------------------------

class ProjectConfig:
    """
    Adapter that exposes typed config objects from a Project's settings.

    For each config type, project-level settings take precedence over
    environment variables. If a project setting is None, the global env var
    (or config.yaml default) is used as a fallback.

    This allows single-project deployments that use only env vars to continue
    working without changes, while multi-project deployments can have
    per-project credentials.

    Usage::

        pc = ProjectConfig(project)
        gh = pc.github(installation_token="ghs_...")
        sl = pc.slack()
        em = pc.email()
        ag = pc.agent("dev")
    """

    def __init__(self, project: "Project") -> None:  # noqa: F821 — Project imported below
        self._project = project

    def github(self, installation_token: str | None = None) -> GitHubConfig:
        """
        Return GitHubConfig for this project.

        Args:
            installation_token: GitHub App installation access token. When
                provided it takes precedence over the global GITHUB_TOKEN env var.
                Pass the result of core.github_app.get_installation_token().

        Returns:
            GitHubConfig with target_repo, base_branch, and resolved token.
        """
        token = installation_token or os.environ.get("GITHUB_TOKEN", "")
        return GitHubConfig(
            target_repo=self._project.repo,
            base_branch=self._project.base_branch,
            token=token,
        )

    def slack(self) -> SlackConfig:
        """
        Return SlackConfig for this project.

        Project settings override env vars; missing project settings fall back
        to the global env var values.
        """
        s = self._project.settings
        global_slack = get_slack_config()
        return SlackConfig(
            token=s.slack_bot_token or global_slack.token,
            signing_secret=s.slack_signing_secret or global_slack.signing_secret,
            approval_channel=s.slack_approval_channel or global_slack.approval_channel,
        )

    def email(self) -> EmailConfig:
        """
        Return EmailConfig for this project.

        Project settings override env vars; missing project settings fall back
        to the global env var values.
        """
        s = self._project.settings
        global_email = get_email_config()
        return EmailConfig(
            from_addr=s.email_from or global_email.from_addr,
            to_addrs=s.email_to or global_email.to_addrs,
            sendgrid_api_key=s.sendgrid_api_key or global_email.sendgrid_api_key,
            smtp_host=s.smtp_host or global_email.smtp_host,
            smtp_port=global_email.smtp_port,
            smtp_user=global_email.smtp_user,
            smtp_password=global_email.smtp_password,
        )

    def agent(self, name: str) -> AgentConfig:
        """
        Return AgentConfig for the given agent, applying per-project overrides.

        Resolution order:
          1. project.settings.agent_overrides[name].provider / .model
          2. HELIX_<AGENT>_PROVIDER / HELIX_<AGENT>_MODEL env vars
          3. config.yaml defaults

        Args:
            name: Agent name, e.g. "dev", "qa", "crash_handler".
        """
        global_cfg = get_agent_config(name)
        overrides = self._project.settings.agent_overrides.get(name)
        if overrides is None:
            return global_cfg
        return AgentConfig(
            agent=name,
            provider=overrides.provider or global_cfg.provider,
            model=overrides.model or global_cfg.model,
            base_url=overrides.base_url or global_cfg.base_url,
        )

    def anthropic_api_key(self) -> str:
        """
        Return the Anthropic API key for this project.

        Falls back to the global ANTHROPIC_API_KEY env var.
        """
        return self._project.settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")


# Avoid circular import — Project is defined in core.models
from core.models import Project  # noqa: E402
