"""Tests for core/llm.py"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.config import AgentConfig
from core.llm import complete


def _make_config(provider: str, model: str = "claude-test") -> AgentConfig:
    return AgentConfig(agent="test", provider=provider, model=model)


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

async def test_complete_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="analysis result")]
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_msg

    with patch("core.llm.get_agent_config", return_value=_make_config("anthropic")):
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await complete("crash_handler", "analyze this", system="you are an expert")

    assert result == "analysis result"


async def test_complete_anthropic_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("core.llm.get_agent_config", return_value=_make_config("anthropic")):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            await complete("crash_handler", "prompt")


async def test_complete_anthropic_no_system(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="result")]
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_msg

    with patch("core.llm.get_agent_config", return_value=_make_config("anthropic")):
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await complete("crash_handler", "prompt")  # no system

    assert result == "result"
    call_kwargs = mock_client.messages.create.call_args[1]
    assert "system" not in call_kwargs


# ---------------------------------------------------------------------------
# OpenRouter backend
# ---------------------------------------------------------------------------

async def test_complete_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="openrouter result"))]
    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("core.llm.get_agent_config", return_value=_make_config("openrouter")):
        with patch("openai.AsyncOpenAI", return_value=mock_client):
            result = await complete("qa", "prompt", system="sys")

    assert result == "openrouter result"


async def test_complete_openrouter_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch("core.llm.get_agent_config", return_value=_make_config("openrouter")):
        with pytest.raises(EnvironmentError, match="OPENROUTER_API_KEY"):
            await complete("qa", "prompt")


# ---------------------------------------------------------------------------
# Claude Code CLI backend
# ---------------------------------------------------------------------------

async def test_complete_claude_code_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"TESTS_PASSED\nFixed the bug.", b"")

    with patch("core.llm.get_agent_config", return_value=_make_config("claude-code")):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await complete("dev", "fix this bug", cwd="/tmp/repo")

    assert "TESTS_PASSED" in result


async def test_complete_claude_code_nonzero_exit_raises():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = (b"", b"error output")

    with patch("core.llm.get_agent_config", return_value=_make_config("claude-code")):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="claude-code exited"):
                await complete("dev", "fix this")


async def test_complete_claude_code_timeout_raises():
    mock_proc = AsyncMock()
    mock_proc.communicate.side_effect = asyncio.TimeoutError()
    mock_proc.kill = MagicMock()

    with patch("core.llm.get_agent_config", return_value=_make_config("claude-code")):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(asyncio.TimeoutError):
                await complete("dev", "fix this")


# ---------------------------------------------------------------------------
# Unknown provider
# ---------------------------------------------------------------------------

async def test_complete_unknown_provider_raises():
    with patch("core.llm.get_agent_config", return_value=_make_config("unknown-llm")):
        with pytest.raises(ValueError, match="Unknown provider"):
            await complete("dev", "prompt")
