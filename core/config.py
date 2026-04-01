"""
Configuration loader for Helix.

Reads agent model/provider settings from config.yaml, then applies environment
variable overrides in the form:

    HELIX_<AGENT>_PROVIDER   e.g. HELIX_DEV_PROVIDER=anthropic
    HELIX_<AGENT>_MODEL      e.g. HELIX_DEV_MODEL=claude-sonnet-4-6

The agent name is uppercased and underscores are preserved, so the QA agent
is addressed as HELIX_QA_PROVIDER / HELIX_QA_MODEL, and crash_handler as
HELIX_CRASH_HANDLER_PROVIDER / HELIX_CRASH_HANDLER_MODEL.

Usage:
    from core.config import get_agent_config

    cfg = get_agent_config("dev")
    print(cfg.provider)  # "claude-code"
    print(cfg.model)     # "claude-sonnet-4-6"
"""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

# Path to config.yaml — always relative to this file's parent directory.
_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@dataclass
class AgentConfig:
    """Model and provider settings for a single agent."""
    agent: str      # agent name as it appears in config.yaml, e.g. "dev"
    provider: str   # "anthropic" | "openrouter" | "claude-code"
    model: str      # model identifier, e.g. "claude-sonnet-4-6"


def _load_yaml() -> dict:
    """Read and parse config.yaml. Raises if the file is missing or malformed."""
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.yaml not found at {_CONFIG_PATH}")
    with _CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


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
