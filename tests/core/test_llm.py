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
    mock_msg.usage = MagicMock(input_tokens=100, output_tokens=50)
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
    mock_msg.usage = MagicMock(input_tokens=50, output_tokens=20)
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
    mock_response.usage = MagicMock(prompt_tokens=80, completion_tokens=30)
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

class _FakeStream:
    """Minimal async-iterable stream for mocking asyncio subprocess pipes."""
    def __init__(self, data: bytes):
        self._lines = [l + b"\n" for l in data.splitlines() if l]

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for line in self._lines:
            yield line

    async def read(self, n=-1):
        return b"".join(self._lines)


def _make_proc(stdout: bytes, stderr: bytes = b"", returncode: int = 0):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = _FakeStream(stdout)
    proc.stderr = _FakeStream(stderr)
    proc.wait = AsyncMock()
    proc.kill = MagicMock()
    return proc


async def test_complete_claude_code_success():
    proc = _make_proc(stdout=b"TESTS_PASSED\nFixed the bug.")

    with patch("core.llm.get_agent_config", return_value=_make_config("claude-code")):
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await complete("dev", "fix this bug", cwd="/tmp/repo")

    assert "TESTS_PASSED" in result


async def test_complete_claude_code_nonzero_exit_raises():
    proc = _make_proc(stdout=b"", stderr=b"error output", returncode=1)

    with patch("core.llm.get_agent_config", return_value=_make_config("claude-code")):
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(RuntimeError, match="claude-code exited"):
                await complete("dev", "fix this")


async def test_complete_claude_code_timeout_raises():
    proc = _make_proc(stdout=b"", stderr=b"")

    with patch("core.llm.get_agent_config", return_value=_make_config("claude-code")):
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
                with pytest.raises(asyncio.TimeoutError):
                    await complete("dev", "fix this")


# ---------------------------------------------------------------------------
# Unknown provider
# ---------------------------------------------------------------------------

async def test_complete_unknown_provider_raises():
    with patch("core.llm.get_agent_config", return_value=_make_config("unknown-llm")):
        with pytest.raises(ValueError, match="Unknown provider"):
            await complete("dev", "prompt")
