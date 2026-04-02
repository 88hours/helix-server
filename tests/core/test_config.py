"""Tests for core/config.py"""
import pytest
from unittest.mock import patch

from core.config import (
    get_agent_config,
    get_email_config,
    get_event_backend,
    get_eventbridge_config,
    get_github_config,
    get_jira_config,
    get_redis_url,
    get_rollbar_config,
    get_slack_config,
)

SAMPLE_YAML = {
    "agents": {
        "crash_handler": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        "qa": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        "dev": {"provider": "claude-code", "model": "claude-sonnet-4-6"},
        "code_quality": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    },
    "events": {
        "backend": "redis",
        "redis": {"url_env": "REDIS_URL"},
        "eventbridge": {"bus": "helix-mvp", "region_env": "AWS_REGION"},
    },
    "redis": {"url_env": "REDIS_URL", "ttl_days": 7},
    "rollbar": {"webhook_secret_env": "ROLLBAR_WEBHOOK_SECRET"},
    "github": {"target_repo": "acme/backend", "base_branch": "main", "token_env": "GITHUB_TOKEN"},
    "jira": {
        "url_env": "JIRA_URL",
        "email_env": "JIRA_EMAIL",
        "token_env": "JIRA_TOKEN",
        "project_key_env": "JIRA_PROJECT_KEY",
    },
    "slack": {
        "token_env": "SLACK_BOT_TOKEN",
        "signing_secret_env": "SLACK_SIGNING_SECRET",
        "approval_channel_env": "SLACK_APPROVAL_CHANNEL",
    },
    "email": {
        "sendgrid_api_key_env": "SENDGRID_API_KEY",
        "smtp_host_env": "SMTP_HOST",
        "smtp_port": 587,
        "smtp_user_env": "SMTP_USER",
        "smtp_password_env": "SMTP_PASSWORD",
        "from_env": "EMAIL_FROM",
        "to_env": "EMAIL_TO",
    },
}


@pytest.fixture(autouse=True)
def mock_yaml():
    with patch("core.config._load_yaml", return_value=SAMPLE_YAML):
        yield


# ---------------------------------------------------------------------------
# get_agent_config
# ---------------------------------------------------------------------------

def test_get_agent_config_returns_correct_values():
    cfg = get_agent_config("dev")
    assert cfg.agent == "dev"
    assert cfg.provider == "claude-code"
    assert cfg.model == "claude-sonnet-4-6"


def test_get_agent_config_env_var_overrides(monkeypatch):
    monkeypatch.setenv("HELIX_DEV_PROVIDER", "anthropic")
    monkeypatch.setenv("HELIX_DEV_MODEL", "claude-opus-4-6")
    cfg = get_agent_config("dev")
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-opus-4-6"


def test_get_agent_config_unknown_agent_raises():
    with pytest.raises(KeyError, match="not found"):
        get_agent_config("nonexistent")


# ---------------------------------------------------------------------------
# get_event_backend
# ---------------------------------------------------------------------------

def test_get_event_backend_default_is_redis():
    assert get_event_backend() == "redis"


def test_get_event_backend_env_override(monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "eventbridge")
    assert get_event_backend() == "eventbridge"


def test_get_event_backend_invalid_raises(monkeypatch):
    monkeypatch.setenv("HELIX_EVENT_BACKEND", "kafka")
    with pytest.raises(ValueError, match="Unknown event backend"):
        get_event_backend()


# ---------------------------------------------------------------------------
# get_redis_url
# ---------------------------------------------------------------------------

def test_get_redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    assert get_redis_url() == "redis://localhost:6379"


def test_get_redis_url_missing_raises(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(EnvironmentError, match="REDIS_URL"):
        get_redis_url()


# ---------------------------------------------------------------------------
# get_rollbar_config
# ---------------------------------------------------------------------------

def test_get_rollbar_config(monkeypatch):
    monkeypatch.setenv("ROLLBAR_WEBHOOK_SECRET", "my-secret")
    cfg = get_rollbar_config()
    assert cfg.webhook_secret == "my-secret"


# ---------------------------------------------------------------------------
# get_github_config
# ---------------------------------------------------------------------------

def test_get_github_config(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    cfg = get_github_config()
    assert cfg.target_repo == "acme/backend"
    assert cfg.base_branch == "main"
    assert cfg.token == "ghp_test"


def test_get_github_config_env_repo_override(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("HELIX_GITHUB_REPO", "other-org/other-repo")
    cfg = get_github_config()
    assert cfg.target_repo == "other-org/other-repo"


def test_get_github_config_missing_repo_raises():
    yaml_no_repo = {**SAMPLE_YAML, "github": {"base_branch": "main", "token_env": "GITHUB_TOKEN"}}
    with patch("core.config._load_yaml", return_value=yaml_no_repo):
        with pytest.raises(ValueError, match="target_repo"):
            get_github_config()


# ---------------------------------------------------------------------------
# get_jira_config
# ---------------------------------------------------------------------------

def test_get_jira_config(monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "dev@acme.com")
    monkeypatch.setenv("JIRA_TOKEN", "jira-token")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "PROJ")
    cfg = get_jira_config()
    assert cfg.url == "https://acme.atlassian.net"
    assert cfg.project_key == "PROJ"


# ---------------------------------------------------------------------------
# get_slack_config
# ---------------------------------------------------------------------------

def test_get_slack_config(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "signing-secret")
    monkeypatch.setenv("SLACK_APPROVAL_CHANNEL", "C123")
    cfg = get_slack_config()
    assert cfg.token == "xoxb-test"
    assert cfg.signing_secret == "signing-secret"
    assert cfg.approval_channel == "C123"


# ---------------------------------------------------------------------------
# get_email_config
# ---------------------------------------------------------------------------

def test_get_email_config_with_sendgrid(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
    monkeypatch.setenv("EMAIL_FROM", "helix@acme.com")
    monkeypatch.setenv("EMAIL_TO", "oncall@acme.com")
    cfg = get_email_config()
    assert cfg.sendgrid_api_key == "SG.test"
    assert cfg.from_addr == "helix@acme.com"


def test_get_email_config_smtp_fallback(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.setenv("EMAIL_FROM", "helix@acme.com")
    monkeypatch.setenv("EMAIL_TO", "oncall@acme.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    cfg = get_email_config()
    assert cfg.sendgrid_api_key is None
    assert cfg.smtp_host == "smtp.example.com"


# ---------------------------------------------------------------------------
# get_eventbridge_config
# ---------------------------------------------------------------------------

def test_get_eventbridge_config(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    cfg = get_eventbridge_config()
    assert cfg.bus == "helix-mvp"
    assert cfg.region == "us-east-1"
