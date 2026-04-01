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

Usage:
    from core.config import get_agent_config, get_redis_url, get_event_backend

    cfg = get_agent_config("dev")       # AgentConfig(provider, model)
    url = get_redis_url()               # "redis://..."
    backend = get_event_backend()       # "redis" or "eventbridge"
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
