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

LangSmith tracing:
    When LANGSMITH_API_KEY and LANGSMITH_TRACING=true are set, every call to
    complete() is traced automatically — inputs (agent, prompt, system), output
    (response text), token usage, provider, and model are recorded in LangSmith.
"""

import asyncio
import logging
import os
from typing import Optional

from core.config import AgentConfig, get_agent_config
from core.telemetry import get_tracer

_tracer = get_tracer("helix.llm")

# LangSmith tracing — gracefully disabled when the package is not installed
# or LANGSMITH_TRACING is not set.
try:
    from langsmith import traceable as _langsmith_traceable
    from langsmith.run_helpers import get_current_run_tree as _get_run_tree
except ImportError:
    def _langsmith_traceable(**kwargs):  # type: ignore[misc]
        """No-op decorator used when langsmith is not installed."""
        def decorator(fn):
            return fn
        return decorator

    def _get_run_tree():  # type: ignore[misc]
        """Returns None when langsmith is not installed."""
        return None

# Langfuse tracing — gracefully disabled when not installed or keys not set.
try:
    from langfuse import Langfuse as _LangfuseClient
    _langfuse = (
        _LangfuseClient()
        if os.environ.get("LANGFUSE_SECRET_KEY")
        else None
    )
except ImportError:
    _langfuse = None

logger = logging.getLogger(__name__)

# Maximum tokens to request from the API. Agents that need longer responses
# (Dev Agent writing code) are served by claude-code which has no hard limit here.
_MAX_TOKENS = 8192

# Timeout in seconds for the claude-code / opencode subprocess.
_SUBPROCESS_TIMEOUT = 600
# Goose runs local models which are slower to start but shorter per-iteration.
_GOOSE_TIMEOUT = 120

# Fallback model used when Anthropic returns 529 Overloaded for the primary model.
_HAIKU_FALLBACK = "claude-haiku-4-5-20251001"

# Bedrock model ID mapping from Helix internal names to Bedrock ARN base IDs.
_BEDROCK_MODEL_IDS = {
    "claude-haiku-4-5":  "anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-sonnet-4-6": "anthropic.claude-sonnet-4-6-20250514-v1:0",
    "claude-opus-4-6":   "anthropic.claude-opus-4-6-20250514-v1:0",
}
# Cross-region inference profile prefix by AWS region prefix.
_BEDROCK_REGION_PREFIXES = {"us": "us.", "eu": "eu.", "ap": "ap."}


# ---------------------------------------------------------------------------
# Bedrock backend
# ---------------------------------------------------------------------------

def _bedrock_model_id(model: str, region: str) -> str:
    base = _BEDROCK_MODEL_IDS.get(model, model)
    prefix = _BEDROCK_REGION_PREFIXES.get(region.split("-")[0], "")
    return prefix + base


def _get_bedrock_client(region: str):
    import anthropic
    return anthropic.AnthropicBedrock(aws_region=region)


async def _complete_bedrock(
    config: AgentConfig, prompt: str, system: str
) -> tuple[str, dict]:
    from core.config import get_bedrock_region
    region = get_bedrock_region()
    bedrock_model = _bedrock_model_id(config.model, region)
    client = _get_bedrock_client(region)
    kwargs: dict = {
        "model": bedrock_model,
        "max_tokens": _MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    response = await asyncio.to_thread(client.messages.create, **kwargs)
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return response.content[0].text, usage


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

async def _complete_anthropic(
    config: AgentConfig, prompt: str, system: str
) -> tuple[str, dict]:
    """
    Call the Anthropic API directly using the Anthropic SDK.

    Requires ANTHROPIC_API_KEY in the environment.

    Args:
        config: Resolved agent config (model name used here).
        prompt: User-turn message.
        system: System prompt. Pass an empty string to omit.

    Returns:
        Tuple of (response text, usage dict with input_tokens and output_tokens).
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

    try:
        message = await client.messages.create(**kwargs)
    except anthropic.APIStatusError as exc:
        if exc.status_code == 529:
            logger.warning(
                "Anthropic model overloaded (529) — retrying with %s",
                _HAIKU_FALLBACK,
                extra={"original_model": config.model},
            )
            kwargs["model"] = _HAIKU_FALLBACK
            message = await client.messages.create(**kwargs)
        else:
            raise

    usage = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
    return message.content[0].text, usage


# ---------------------------------------------------------------------------
# OpenRouter backend
# ---------------------------------------------------------------------------

async def _complete_openrouter(
    config: AgentConfig, prompt: str, system: str
) -> tuple[str, dict]:
    """
    Call OpenRouter using the OpenAI-compatible SDK.

    Requires OPENROUTER_API_KEY in the environment.

    Args:
        config: Resolved agent config (model name used here).
        prompt: User-turn message.
        system: System prompt. Prepended as a system message when non-empty.

    Returns:
        Tuple of (response text, usage dict with input_tokens and output_tokens).
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
    usage = {
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
    }
    return response.choices[0].message.content, usage


# ---------------------------------------------------------------------------
# Ollama backend (customer self-hosted, BYOK)
# ---------------------------------------------------------------------------

async def _complete_ollama(
    config: AgentConfig, prompt: str, system: str, json_mode: bool = False
) -> tuple[str, dict]:
    """
    Call a customer-provided Ollama instance using the OpenAI-compatible API.

    Ollama is never hosted by Helix. The customer runs their own Ollama server
    (requires a GPU for usable speed) and provides the base_url in their
    project's agent_overrides. For managed open-weight models with no
    self-hosting, customers should use OpenRouter instead.

    Args:
        config:    Resolved agent config — must have base_url set.
        prompt:    User-turn message.
        system:    System prompt. Prepended as a system message when non-empty.
        json_mode: When True, passes response_format={"type":"json_object"} to
                   suppress chain-of-thought (e.g. qwen3 <think> blocks) and
                   force direct JSON output.

    Returns:
        Tuple of (response text, usage dict with input_tokens and output_tokens).

    Raises:
        ValueError: If base_url is not set on the config.
    """
    import re as _re
    import openai  # lazy import — only required for this backend

    if not config.base_url:
        raise ValueError(
            f"Agent '{config.agent}' is configured with provider 'ollama' but "
            "base_url is not set. Add base_url to the project's agent_overrides "
            "for this agent, e.g. 'http://my-server:11434/v1'."
        )

    client = openai.AsyncOpenAI(
        base_url=config.base_url,
        api_key="ollama",  # Ollama ignores the key; placeholder required by the SDK
    )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {
        "model": config.model,
        "messages": messages,
        "max_tokens": _MAX_TOKENS,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    num_ctx = int(os.environ.get("HELIX_OLLAMA_NUM_CTX", "16384"))
    kwargs["extra_body"] = {"options": {"num_ctx": num_ctx}}

    response = await client.chat.completions.create(**kwargs)
    usage = {
        "input_tokens": response.usage.prompt_tokens if response.usage else 0,
        "output_tokens": response.usage.completion_tokens if response.usage else 0,
    }
    content = response.choices[0].message.content or ""
    logger.debug("ollama raw response", extra={"agent": config.agent, "content_len": len(content), "content": content})

    # Some reasoning models (qwen3, deepseek-r1) prepend <think>…</think> blocks
    # even when JSON mode is requested via an older Ollama version. Strip them so
    # extract_json reliably finds the JSON object.
    content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()

    if not content:
        raise ValueError(
            f"Ollama returned empty content for agent '{config.agent}'. "
            "The model may have used its entire token budget for reasoning. "
            "Check HELIX_OLLAMA_BASE_URL and the model name, or increase max_tokens."
        )
    return content, usage


# ---------------------------------------------------------------------------
# Claude Code CLI backend
# ---------------------------------------------------------------------------

async def _complete_opencode(prompt: str, cwd: Optional[str]) -> tuple[str, dict]:
    """
    Invoke the OpenCode CLI as a subprocess: opencode run "<prompt>"

    Drop-in alternative to the Claude Code CLI. OpenCode supports Ollama and
    other LLM backends, so no Anthropic API key is required. Configure the
    model via OpenCode's own config or the --model flag.

    Args:
        prompt: The full prompt to pass to the CLI.
        cwd:    Working directory for the subprocess. Should be the root of
                the cloned target repo.

    Returns:
        Tuple of (CLI stdout output, empty dict — token usage not available
        for subprocess invocations).

    Raises:
        RuntimeError: If the CLI exits with a non-zero status.
        asyncio.TimeoutError: If the subprocess exceeds _SUBPROCESS_TIMEOUT seconds.
    """
    cmd = ["opencode", "run", "--dangerously-skip-permissions"]
    model = os.environ.get("HELIX_DEV_OPENCODE_MODEL")
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    logger.info("opencode subprocess started", extra={"pid": process.pid, "cwd": cwd, "model": model or "opencode-default"})

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        process.kill()
        raise asyncio.TimeoutError(
            f"opencode subprocess timed out after {_SUBPROCESS_TIMEOUT}s"
        )

    stderr_text = stderr.decode().strip()
    stdout_text = stdout.decode().strip()

    logger.info(
        "opencode subprocess finished",
        extra={"pid": process.pid, "returncode": process.returncode},
    )
    if stderr_text:
        logger.debug("opencode stderr", extra={"stderr": stderr_text})
    logger.debug("opencode stdout", extra={"stdout": stdout_text})

    if process.returncode != 0:
        raise RuntimeError(
            f"opencode exited with code {process.returncode}: {stderr_text}"
        )

    return stdout_text, {}


async def _complete_goose(prompt: str, cwd: Optional[str], system: str = "") -> tuple[str, dict]:
    """
    Invoke the Goose CLI as a subprocess: goose run --text "<prompt>"

    Drop-in alternative to opencode. Goose has model-agnostic tool descriptions
    so local models (e.g. Gemma via Ollama) call tools reliably without refusing.
    Configure the model via HELIX_DEV_GOOSE_MODEL (maps to Goose's --model flag).
    """
    cmd = ["goose", "run", "--no-session"]
    model = os.environ.get("HELIX_DEV_GOOSE_MODEL")
    if model:
        bare_model = model.split("/", 1)[-1]
        cmd += ["--model", bare_model]
    system_prompt = system or os.environ.get("HELIX_DEV_GOOSE_SYSTEM", "")
    if cwd:
        system_prompt = (system_prompt + f"\nYour working directory is: {cwd}. Do not leave this directory.").strip()
    if system_prompt:
        cmd += ["--system", system_prompt]
    if logger.isEnabledFor(logging.DEBUG):
        cmd.append("--debug")
    cmd += ["--text", prompt]

    logger.info("goose command: %s (cwd=%s)", " ".join(cmd[:-1]) + " [prompt]", cwd)
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    logger.info("goose subprocess started (pid=%s, cwd=%s)", process.pid, cwd)

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_GOOSE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        process.kill()
        raise asyncio.TimeoutError(
            f"goose subprocess timed out after {_GOOSE_TIMEOUT}s"
        )

    stderr_text = stderr.decode().strip()
    stdout_text = stdout.decode().strip()

    logger.info("goose subprocess finished (rc=%s)", process.returncode, extra={"pid": process.pid})
    if stderr_text:
        logger.debug("goose stderr:\n%s", stderr_text)
    logger.debug("goose stdout:\n%s", stdout_text)

    if process.returncode != 0:
        raise RuntimeError(
            f"goose exited with code {process.returncode}: {stderr_text or stdout_text}"
        )

    if "Network error:" in stdout_text or "Could not connect" in stdout_text:
        raise RuntimeError(f"goose network error: {stdout_text}")

    return stdout_text, {}


async def _complete_claude_code(prompt: str, cwd: Optional[str]) -> tuple[str, dict]:
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
        Tuple of (CLI stdout output, empty dict — token usage not available
        for subprocess invocations).

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

    async def _stream_stderr(stream: asyncio.StreamReader) -> str:
        lines: list[str] = []
        async for raw in stream:
            line = raw.decode().rstrip()
            lines.append(line)
            logger.info("claude-code | %s", line)
        return "\n".join(lines)

    async def _stream_stdout(stream: asyncio.StreamReader) -> str:
        lines: list[str] = []
        async for raw in stream:
            line = raw.decode().rstrip()
            lines.append(line)
            logger.info("claude-code out | %s", line)
        return "\n".join(lines).strip()

    try:
        stderr_text, stdout_text = await asyncio.wait_for(
            asyncio.gather(
                _stream_stderr(process.stderr),
                _stream_stdout(process.stdout),
            ),
            timeout=_SUBPROCESS_TIMEOUT,
        )
        await process.wait()
    except asyncio.TimeoutError:
        process.kill()
        raise asyncio.TimeoutError(
            f"claude-code subprocess timed out after {_SUBPROCESS_TIMEOUT}s"
        )

    logger.info(
        "claude-code subprocess finished",
        extra={"pid": process.pid, "returncode": process.returncode},
    )
    logger.debug("claude-code stdout", extra={"stdout": stdout_text})

    if process.returncode != 0:
        raise RuntimeError(
            f"claude-code exited with code {process.returncode}: {stderr_text}"
        )

    return stdout_text, {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@_langsmith_traceable(run_type="llm", name="helix_complete")
async def complete(
    agent: str,
    prompt: str,
    system: str = "",
    cwd: Optional[str] = None,
    config: Optional[AgentConfig] = None,
    json_mode: bool = False,
) -> str:
    """
    Run a completion for the given agent, routed to the correct LLM backend.

    When LangSmith tracing is enabled (LANGSMITH_API_KEY + LANGSMITH_TRACING=true),
    each call is recorded automatically — inputs, output, token usage, provider,
    model, and latency are captured in the LangSmith project.

    Args:
        agent:  Agent name as defined in config.yaml, e.g. "crash_handler",
                "qa", "dev", "code_quality".
        prompt: The main prompt / user message.
        system: Optional system prompt. Ignored by the claude-code backend
                (system context should be baked into the prompt instead).
        cwd:    Working directory for the claude-code subprocess. Only
                relevant when the agent's provider is "claude-code".
                Typically the root of the cloned target repository.
        config: Optional pre-resolved AgentConfig. When provided, skips the
                global config lookup — use this to pass per-project overrides
                (e.g. ollama base_url resolved via ProjectConfig.agent()).

    Returns:
        The model's text response as a plain string.

    Raises:
        KeyError:          Agent not found in config.yaml.
        EnvironmentError:  Required API key not set.
        RuntimeError:      claude-code subprocess failed.
        ValueError:        Unknown provider in config.
    """
    resolved: AgentConfig = config or get_agent_config(agent)
    logger.info(
        "llm call",
        extra={"agent": agent, "provider": resolved.provider, "model": resolved.model},
    )

    with _tracer.start_as_current_span("llm.complete") as span:
        span.set_attribute("helix.agent", agent)
        span.set_attribute("helix.provider", resolved.provider)
        span.set_attribute("helix.model", resolved.model)

        if resolved.provider == "anthropic":
            response, usage = await _complete_anthropic(resolved, prompt, system)
        elif resolved.provider == "bedrock":
            response, usage = await _complete_bedrock(resolved, prompt, system)
        elif resolved.provider == "openrouter":
            response, usage = await _complete_openrouter(resolved, prompt, system)
        elif resolved.provider == "ollama":
            response, usage = await _complete_ollama(resolved, prompt, system, json_mode=json_mode)
        elif resolved.provider == "claude-code":
            response, usage = await _complete_claude_code(prompt, cwd)
        elif resolved.provider == "opencode":
            response, usage = await _complete_opencode(prompt, cwd)
        elif resolved.provider == "goose":
            response, usage = await _complete_goose(prompt, cwd, system=system)
        else:
            raise ValueError(
                f"Unknown provider '{resolved.provider}' for agent '{agent}'. "
                "Must be 'anthropic', 'bedrock', 'openrouter', 'ollama', 'claude-code', 'opencode', or 'goose'."
            )

        span.set_attribute("helix.input_tokens", usage.get("input_tokens", 0))
        span.set_attribute("helix.output_tokens", usage.get("output_tokens", 0))

        # Attach model metadata and token usage to the active LangSmith run.
        # Silently skipped when tracing is disabled or langsmith is not installed.
        try:
            rt = _get_run_tree()
            if rt is not None:
                rt.add_metadata({
                    "provider": resolved.provider,
                    "model": resolved.model,
                    **usage,
                })
        except Exception:
            pass

        # Log a Langfuse generation. Silently skipped when not configured.
        if _langfuse is not None:
            try:
                _langfuse.generation(
                    name=f"helix.{agent}",
                    model=resolved.model,
                    input={"prompt": prompt, "system": system},
                    output=response,
                    usage={
                        "input": usage.get("input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                    },
                    metadata={"provider": resolved.provider, "agent": agent},
                )
            except Exception:
                pass

    return response
