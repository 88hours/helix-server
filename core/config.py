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
    SENTRY_WEBHOOK_SECRET    HMAC-SHA256 secret for Sentry webhook verification
    GITHUB_TOKEN             GitHub personal access token or App token (repo scope)
    JIRA_URL                 JIRA base URL, e.g. https://acme.atlassian.net
    JIRA_EMAIL               JIRA account email for Basic auth
    JIRA_TOKEN               JIRA API token
    JIRA_PROJECT_KEY         Default JIRA project key, e.g. PROJ
    SLACK_BOT_TOKEN          Slack bot token (xoxb-...)
    SLACK_APPROVAL_CHANNEL   Channel ID or name for approval messages

Usage:
    from core.config import get_agent_config, get_redis_url, get_event_backend
    from core.config import get_sentry_config, get_github_config
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
class SentryConfig:
    """Sentry webhook integration settings."""
    webhook_secret: str     # HMAC-SHA256 secret for verifying Sentry webhook payloads


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
    token: str              # Slack bot token (xoxb-...)
    approval_channel: str   # channel ID or name for approval/escalation messages


@dataclass
class EmailConfig:
    """SMTP email notification settings."""
    smtp_host: str      # SMTP server hostname
    smtp_port: int      # SMTP port (587 for STARTTLS, 465 for SSL)
    smtp_user: str      # SMTP username or API key username
    smtp_password: str  # SMTP password or API key
    from_addr: str      # sender address, e.g. "helix@acme.com"
    to_addrs: str       # comma-separated recipient list


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


def get_sentry_config() -> SentryConfig:
    """
    Return Sentry webhook integration settings.

    Reads the webhook secret from the env var named in config.yaml
    (sentry.webhook_secret_env, defaulting to SENTRY_WEBHOOK_SECRET).

    Raises:
        EnvironmentError: The webhook secret env var is not set.
    """
    raw = _load_yaml()
    secret_env = raw.get("sentry", {}).get("webhook_secret_env", "SENTRY_WEBHOOK_SECRET")
    return SentryConfig(webhook_secret=_require_env(secret_env))


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

    Raises:
        EnvironmentError: SLACK_BOT_TOKEN or SLACK_APPROVAL_CHANNEL is not set.
    """
    raw = _load_yaml()
    slack = raw.get("slack", {})

    token_env = slack.get("token_env", "SLACK_BOT_TOKEN")
    channel_env = slack.get("approval_channel_env", "SLACK_APPROVAL_CHANNEL")

    return SlackConfig(
        token=_require_env(token_env),
        approval_channel=_require_env(channel_env),
    )


def get_email_config() -> EmailConfig:
    """
    Return SMTP email notification settings.

    Resolution order for each field:
      1. Environment variable (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
         EMAIL_FROM, EMAIL_TO)
      2. config.yaml defaults (smtp_port only; all others must be in env vars)

    Raises:
        EnvironmentError: Any required env var is not set.
    """
    raw = _load_yaml()
    email = raw.get("email", {})

    smtp_host_env = email.get("smtp_host_env", "SMTP_HOST")
    smtp_user_env = email.get("smtp_user_env", "SMTP_USER")
    smtp_password_env = email.get("smtp_password_env", "SMTP_PASSWORD")
    from_env = email.get("from_env", "EMAIL_FROM")
    to_env = email.get("to_env", "EMAIL_TO")
    smtp_port = int(os.environ.get("SMTP_PORT", str(email.get("smtp_port", 587))))

    return EmailConfig(
        smtp_host=_require_env(smtp_host_env),
        smtp_port=smtp_port,
        smtp_user=_require_env(smtp_user_env),
        smtp_password=_require_env(smtp_password_env),
        from_addr=_require_env(from_env),
        to_addrs=_require_env(to_env),
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
