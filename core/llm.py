"""
LLM router for the Helix agent pipeline.

Routes completion requests to the correct backend based on the agent's
configuration in config.yaml (or env var overrides):

    anthropic    — Anthropic SDK, direct API calls (ANTHROPIC_API_KEY)
    openrouter   — OpenAI-compatible SDK via OpenRouter (OPENROUTER_API_KEY)
    claude-code  — Claude Code CLI via subprocess: claude -p "<prompt>"
                   Used exclusively by the Dev Agent, which runs inside a
                   cloned repo directory so Claude Code has full file access.

All agents call the same function:

    response = await complete(agent="crash_handler", prompt="...", system="...")

The Dev Agent additionally passes cwd= so the subprocess runs inside the repo:

    response = await complete(agent="dev", prompt="...", cwd="/tmp/repo-abc123")
"""

import asyncio
import logging
import os
from typing import Optional

from core.config import AgentConfig, get_agent_config

logger = logging.getLogger(__name__)

# Maximum tokens to request from the API. Agents that need longer responses
# (Dev Agent writing code) are served by claude-code which has no hard limit here.
_MAX_TOKENS = 4096

# Timeout in seconds for the claude-code subprocess. Dev Agent iterations
# can be long — allow up to 10 minutes per call.
_SUBPROCESS_TIMEOUT = 600


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

async def _complete_anthropic(config: AgentConfig, prompt: str, system: str) -> str:
    """
    Call the Anthropic API directly using the Anthropic SDK.

    Requires ANTHROPIC_API_KEY in the environment.

    Args:
        config: Resolved agent config (model name used here).
        prompt: User-turn message.
        system: System prompt. Pass an empty string to omit.

    Returns:
        The model's text response.
    """
    import anthropic  # lazy import — only required for this backend

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    kwargs: dict = {
        "model": config.model,
        "max_tokens": _MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    message = await client.messages.create(**kwargs)
    return message.content[0].text


# ---------------------------------------------------------------------------
# OpenRouter backend
# ---------------------------------------------------------------------------

async def _complete_openrouter(config: AgentConfig, prompt: str, system: str) -> str:
    """
    Call OpenRouter using the OpenAI-compatible SDK.

    Requires OPENROUTER_API_KEY in the environment.

    Args:
        config: Resolved agent config (model name used here).
        prompt: User-turn message.
        system: System prompt. Prepended as a system message when non-empty.

    Returns:
        The model's text response.
    """
    import openai  # lazy import — only required for this backend

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY is not set")

    client = openai.AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        max_tokens=_MAX_TOKENS,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Claude Code CLI backend
# ---------------------------------------------------------------------------

async def _complete_claude_code(prompt: str, cwd: Optional[str]) -> str:
    """
    Invoke the Claude Code CLI as a subprocess: claude -p "<prompt>"

    This is the Dev Agent's backend. Running the CLI inside the cloned repo
    directory gives Claude Code full access to the target codebase — it can
    read files, run tests, and write fixes without any additional tooling.

    Args:
        prompt: The full prompt to pass to the CLI via -p.
        cwd:    Working directory for the subprocess. Should be the root of
                the cloned target repo. Defaults to the current directory.

    Returns:
        The CLI's stdout output (Claude's response).

    Raises:
        RuntimeError: If the CLI exits with a non-zero status.
        asyncio.TimeoutError: If the subprocess exceeds _SUBPROCESS_TIMEOUT seconds.
    """
    process = await asyncio.create_subprocess_exec(
        "claude", "--dangerously-skip-permissions", "-p", prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    logger.info("claude-code subprocess started", extra={"pid": process.pid, "cwd": cwd})

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        process.kill()
        raise asyncio.TimeoutError(
            f"claude-code subprocess timed out after {_SUBPROCESS_TIMEOUT}s"
        )

    stderr_text = stderr.decode().strip()
    stdout_text = stdout.decode().strip()

    logger.info(
        "claude-code subprocess finished",
        extra={"pid": process.pid, "returncode": process.returncode},
    )
    if stderr_text:
        logger.debug("claude-code stderr", extra={"stderr": stderr_text})
    logger.debug("claude-code stdout", extra={"stdout": stdout_text})

    if process.returncode != 0:
        raise RuntimeError(
            f"claude-code exited with code {process.returncode}: {stderr_text}"
        )

    return stdout_text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def complete(
    agent: str,
    prompt: str,
    system: str = "",
    cwd: Optional[str] = None,
) -> str:
    """
    Run a completion for the given agent, routed to the correct LLM backend.

    Args:
        agent:  Agent name as defined in config.yaml, e.g. "crash_handler",
                "qa", "dev", "code_quality".
        prompt: The main prompt / user message.
        system: Optional system prompt. Ignored by the claude-code backend
                (system context should be baked into the prompt instead).
        cwd:    Working directory for the claude-code subprocess. Only
                relevant when the agent's provider is "claude-code".
                Typically the root of the cloned target repository.

    Returns:
        The model's text response as a plain string.

    Raises:
        KeyError:          Agent not found in config.yaml.
        EnvironmentError:  Required API key not set.
        RuntimeError:      claude-code subprocess failed.
        ValueError:        Unknown provider in config.
    """
    config: AgentConfig = get_agent_config(agent)
    logger.info(
        "llm call",
        extra={"agent": agent, "provider": config.provider, "model": config.model},
    )

    if config.provider == "anthropic":
        return await _complete_anthropic(config, prompt, system)

    if config.provider == "openrouter":
        return await _complete_openrouter(config, prompt, system)

    if config.provider == "claude-code":
        return await _complete_claude_code(prompt, cwd)

    raise ValueError(
        f"Unknown provider '{config.provider}' for agent '{agent}'. "
        "Must be 'anthropic', 'openrouter', or 'claude-code'."
    )
