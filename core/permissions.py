"""
Scoped tool access enforcement for Helix agents.

Each agent declares its allowed tool operations in config.yaml under
agents.<name>.permissions. This module loads those declarations and
provides a single require() function that agents call before any
integration or state operation.

If an agent attempts an operation that is not in its declared permission
list, PermissionDenied is raised immediately — the integration is never
called.

Usage:
    from core.permissions import load_permissions, require

    permissions = load_permissions("qa")
    require(permissions, "github", "create_issue")          # passes
    require(permissions, "github", "create_pull_request")   # raises PermissionDenied

Permission declarations in config.yaml:

    agents:
      qa:
        permissions:
          github:
            - clone_repo
            - create_issue
            - add_issue_comment
          slack: []
          redis:
            - write_qa_result
            - write_status

Tool names match the integration module names (github, slack, email, redis, events).
Operation names match the function names in those modules, or logical operation
labels for Redis keys and event channels.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


class PermissionDenied(Exception):
    """
    Raised when an agent attempts a tool operation it is not permitted to perform.

    Attributes:
        agent:     The agent that attempted the operation.
        tool:      The integration or resource (e.g. "github", "slack").
        operation: The specific operation attempted (e.g. "create_pull_request").
    """

    def __init__(self, agent: str, tool: str, operation: str, allowed: list[str]) -> None:
        self.agent = agent
        self.tool = tool
        self.operation = operation
        self.allowed = allowed
        allowed_str = ", ".join(allowed) if allowed else "none"
        super().__init__(
            f"Agent '{agent}' does not have permission for {tool}.{operation}. "
            f"Allowed {tool} operations: {allowed_str}"
        )


@dataclass
class AgentPermissions:
    """
    Declared tool permissions for a single agent.

    Attributes:
        agent: Agent name as defined in config.yaml, e.g. "qa".
        tools: Mapping of tool name → list of allowed operation names.
               An empty list means the agent has no access to that tool.
    """

    agent: str
    tools: dict[str, list[str]] = field(default_factory=dict)


def load_permissions(agent: str) -> AgentPermissions:
    """
    Load the declared tool permissions for the given agent from config.yaml.

    Args:
        agent: Agent name matching a key under agents: in config.yaml,
               e.g. "crash_handler", "qa", "dev", "notifier".

    Returns:
        AgentPermissions with the agent's declared allowed operations.
        If the agent has no permissions block, an empty AgentPermissions
        is returned (all operations will be denied).

    Raises:
        FileNotFoundError: config.yaml does not exist.
        KeyError: The agent name is not defined in config.yaml.
    """
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.yaml not found at {_CONFIG_PATH}")

    with _CONFIG_PATH.open() as f:
        raw = yaml.safe_load(f)

    agents = raw.get("agents", {})
    if agent not in agents:
        available = ", ".join(agents.keys())
        raise KeyError(
            f"Agent '{agent}' not found in config.yaml. Available: {available}"
        )

    tools = agents[agent].get("permissions", {})
    logger.debug(
        "agent permissions loaded",
        extra={"agent": agent, "tools": list(tools.keys())},
    )
    return AgentPermissions(agent=agent, tools=tools)


def require(permissions: AgentPermissions, tool: str, operation: str) -> None:
    """
    Assert that the agent has permission to perform an operation on a tool.

    Call this immediately before every integration or state operation.
    If the agent's declared permissions do not include the operation,
    PermissionDenied is raised and the operation is never attempted.

    Args:
        permissions: The agent's loaded AgentPermissions.
        tool:        Integration or resource name, e.g. "github", "slack",
                     "redis", "events".
        operation:   Specific operation name, e.g. "create_pull_request",
                     "post_message", "write_status".

    Raises:
        PermissionDenied: The agent does not have permission for this operation.
    """
    allowed: list[str] = permissions.tools.get(tool, [])
    if operation not in allowed:
        logger.error(
            "permission denied",
            extra={
                "agent": permissions.agent,
                "tool": tool,
                "operation": operation,
                "allowed": allowed,
            },
        )
        raise PermissionDenied(
            agent=permissions.agent,
            tool=tool,
            operation=operation,
            allowed=allowed,
        )
