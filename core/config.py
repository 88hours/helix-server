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
    from core.config import get_jira_config, get_slack_config

    cfg = get_agent_config("dev")       # AgentConfig(provider, model)
    url = get_redis_url()               # "redis://..."
    backend = get_event_backend()       # "redis" or "eventbridge"
    gh = get_github_config()            # GitHubConfig(target_repo, base_branch, token)
"""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

# Path to config.yaml — always relative to this file's parent directory.
_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AgentConfig:
    """Model and provider settings for a single agent."""
    agent: str      # agent name as it appears in config.yaml, e.g. "dev"
    provider: str   # "anthropic" | "openrouter" | "claude-code"
    model: str      # model identifier, e.g. "claude-sonnet-4-6"


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

    if not provider:
        raise ValueError(f"No provider configured for agent '{agent}'")
    if not model:
        raise ValueError(f"No model configured for agent '{agent}'")

    return AgentConfig(agent=agent, provider=provider, model=model)


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
