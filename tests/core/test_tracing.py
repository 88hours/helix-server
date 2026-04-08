"""Tests for LangSmith tracing configuration and llm.py integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.config import get_langsmith_config
from core.llm import complete
from core.config import AgentConfig


def _make_config(provider: str, model: str = "claude-test") -> AgentConfig:
    return AgentConfig(agent="test", provider=provider, model=model)


# ---------------------------------------------------------------------------
# get_langsmith_config
# ---------------------------------------------------------------------------

def test_langsmith_config_disabled_when_no_api_key(monkeypatch):
    """Tracing is disabled when LANGSMITH_API_KEY is not set."""
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    cfg = get_langsmith_config()
    assert cfg.api_key is None
    assert cfg.tracing_enabled is False


def test_langsmith_config_disabled_when_tracing_flag_not_set(monkeypatch):
    """API key present but LANGSMITH_TRACING not set → tracing still disabled."""
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-key")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    cfg = get_langsmith_config()
    assert cfg.api_key == "ls-test-key"
    assert cfg.tracing_enabled is False


def test_langsmith_config_enabled(monkeypatch):
    """Tracing is enabled when both API key and LANGSMITH_TRACING=true are set."""
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    cfg = get_langsmith_config()
    assert cfg.api_key == "ls-test-key"
    assert cfg.tracing_enabled is True


def test_langsmith_config_project_default(monkeypatch):
    """Default project name is 'helix' when LANGSMITH_PROJECT is not set."""
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    cfg = get_langsmith_config()
    assert cfg.project == "helix"


def test_langsmith_config_project_override(monkeypatch):
    """LANGSMITH_PROJECT overrides the default project name."""
    monkeypatch.setenv("LANGSMITH_PROJECT", "helix-staging")
    cfg = get_langsmith_config()
    assert cfg.project == "helix-staging"


def test_langsmith_config_endpoint_default(monkeypatch):
    """Default endpoint is the LangChain API URL when LANGSMITH_ENDPOINT is not set."""
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)
    cfg = get_langsmith_config()
    assert cfg.endpoint == "https://api.smith.langchain.com"


def test_langsmith_config_endpoint_override(monkeypatch):
    """LANGSMITH_ENDPOINT overrides the default endpoint."""
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.api.smith.langchain.com")
    cfg = get_langsmith_config()
    assert cfg.endpoint == "https://eu.api.smith.langchain.com"


def test_langsmith_config_tracing_false_string(monkeypatch):
    """LANGSMITH_TRACING=false disables tracing even with an API key."""
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    cfg = get_langsmith_config()
    assert cfg.tracing_enabled is False


# ---------------------------------------------------------------------------
# complete() — metadata attachment (no-op when langsmith not configured)
# ---------------------------------------------------------------------------

async def test_complete_anthropic_adds_metadata_to_run_tree(monkeypatch):
    """
    When a LangSmith run tree is active, complete() calls add_metadata()
    with provider, model, and token counts.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    mock_usage = MagicMock(input_tokens=120, output_tokens=40)
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="result")]
    mock_msg.usage = mock_usage
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_msg

    mock_rt = MagicMock()

    with patch("core.llm.get_agent_config", return_value=_make_config("anthropic")):
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("core.llm._get_run_tree", return_value=mock_rt):
                result = await complete("crash_handler", "prompt", system="sys")

    assert result == "result"
    mock_rt.add_metadata.assert_called_once()
    metadata = mock_rt.add_metadata.call_args[0][0]
    assert metadata["provider"] == "anthropic"
    assert metadata["input_tokens"] == 120
    assert metadata["output_tokens"] == 40


async def test_complete_openrouter_adds_metadata_to_run_tree(monkeypatch):
    """complete() adds token usage metadata for OpenRouter responses."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    mock_usage = MagicMock(prompt_tokens=80, completion_tokens=30)
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="openrouter result"))]
    mock_response.usage = mock_usage
    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = mock_response

    mock_rt = MagicMock()

    with patch("core.llm.get_agent_config", return_value=_make_config("openrouter")):
        with patch("openai.AsyncOpenAI", return_value=mock_client):
            with patch("core.llm._get_run_tree", return_value=mock_rt):
                result = await complete("qa", "prompt", system="sys")

    assert result == "openrouter result"
    metadata = mock_rt.add_metadata.call_args[0][0]
    assert metadata["input_tokens"] == 80
    assert metadata["output_tokens"] == 30


async def test_complete_claude_code_adds_metadata_no_tokens(monkeypatch):
    """claude-code backend adds provider/model metadata but no token counts."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"fixed the bug", b"")

    mock_rt = MagicMock()

    with patch("core.llm.get_agent_config", return_value=_make_config("claude-code")):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("core.llm._get_run_tree", return_value=mock_rt):
                result = await complete("dev", "fix this", cwd="/tmp/repo")

    assert "fixed the bug" in result
    metadata = mock_rt.add_metadata.call_args[0][0]
    assert metadata["provider"] == "claude-code"
    # No token keys for subprocess backend
    assert "input_tokens" not in metadata
    assert "output_tokens" not in metadata


async def test_complete_anthropic_falls_back_to_haiku_on_529(monkeypatch):
    """
    When Anthropic returns 529 Overloaded for the primary model, complete()
    retries with claude-haiku-4-5-20251001 and returns the response.
    """
    import anthropic as _anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    overloaded_exc = _anthropic.APIStatusError(
        "overloaded",
        response=MagicMock(status_code=529),
        body={},
    )
    fallback_msg = MagicMock()
    fallback_msg.content = [MagicMock(text="haiku fallback response")]
    fallback_msg.usage = MagicMock(input_tokens=50, output_tokens=20)

    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = [overloaded_exc, fallback_msg]

    with patch("core.llm.get_agent_config", return_value=_make_config("anthropic", "claude-sonnet-4-6")):
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("core.llm._get_run_tree", return_value=None):
                result = await complete("crash_handler", "prompt")

    assert result == "haiku fallback response"
    # Second call should use the haiku model
    second_call_kwargs = mock_client.messages.create.call_args_list[1][1]
    assert second_call_kwargs["model"] == "claude-haiku-4-5-20251001"


async def test_complete_anthropic_reraises_non_529_errors(monkeypatch):
    """Non-529 API errors are re-raised and not swallowed by the fallback logic."""
    import anthropic as _anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    auth_exc = _anthropic.APIStatusError(
        "auth error",
        response=MagicMock(status_code=401),
        body={},
    )
    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = auth_exc

    with patch("core.llm.get_agent_config", return_value=_make_config("anthropic")):
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with pytest.raises(_anthropic.APIStatusError):
                await complete("crash_handler", "prompt")


async def test_complete_metadata_silently_skipped_when_run_tree_none(monkeypatch):
    """
    When _get_run_tree() returns None (tracing disabled), complete() still
    returns the response and does not raise.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="no trace result")]
    mock_msg.usage = MagicMock(input_tokens=10, output_tokens=5)
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_msg

    with patch("core.llm.get_agent_config", return_value=_make_config("anthropic")):
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("core.llm._get_run_tree", return_value=None):
                result = await complete("crash_handler", "prompt")

    assert result == "no trace result"
