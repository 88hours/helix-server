"""Tests for integrations/email.py"""
import pytest
import respx
import httpx
from unittest.mock import AsyncMock, patch

from integrations import email


@pytest.fixture(autouse=True)
def email_env(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "helix@acme.com")
    monkeypatch.setenv("EMAIL_TO", "oncall@acme.com")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# _resolve
# ---------------------------------------------------------------------------

def test_resolve_uses_override():
    assert email._resolve("MISSING_VAR", "explicit") == "explicit"


def test_resolve_reads_env(monkeypatch):
    monkeypatch.setenv("MY_VAR", "from-env")
    assert email._resolve("MY_VAR", None) == "from-env"


def test_resolve_raises_when_empty(monkeypatch):
    monkeypatch.delenv("MY_VAR", raising=False)
    with pytest.raises(EnvironmentError, match="MY_VAR"):
        email._resolve("MY_VAR", None)


# ---------------------------------------------------------------------------
# _recipients
# ---------------------------------------------------------------------------

def test_recipients_single():
    assert email._recipients("a@b.com") == ["a@b.com"]


def test_recipients_multiple():
    assert email._recipients("a@b.com, c@d.com") == ["a@b.com", "c@d.com"]


def test_recipients_from_env(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "x@y.com,z@w.com")
    assert email._recipients(None) == ["x@y.com", "z@w.com"]


# ---------------------------------------------------------------------------
# SendGrid backend
# ---------------------------------------------------------------------------

@respx.mock
async def test_send_sendgrid_success():
    respx.post("https://api.sendgrid.com/v3/mail/send").mock(
        return_value=httpx.Response(202)
    )
    await email._send_sendgrid(
        api_key="SG.test",
        from_addr="helix@acme.com",
        to_addrs=["oncall@acme.com"],
        subject="Test",
        body_text="Plain",
        body_html="<p>HTML</p>",
    )


# ---------------------------------------------------------------------------
# SMTP backend
# ---------------------------------------------------------------------------

async def test_send_smtp_success(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")

    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await email._send_smtp(
            from_addr="helix@acme.com",
            to_addrs=["oncall@acme.com"],
            subject="Test",
            body_text="Plain",
            body_html="<p>HTML</p>",
            smtp_host=None,
            smtp_port=None,
            smtp_user=None,
            smtp_password=None,
        )
    mock_send.assert_awaited_once()


async def test_send_smtp_missing_host_raises(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(EnvironmentError, match="SMTP_HOST"):
        await email._send_smtp("from@a.com", ["to@b.com"], "s", "t", "h", None, None, None, None)


# ---------------------------------------------------------------------------
# _deliver — backend selection
# ---------------------------------------------------------------------------

@respx.mock
async def test_deliver_uses_sendgrid_when_key_set(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
    route = respx.post("https://api.sendgrid.com/v3/mail/send").mock(
        return_value=httpx.Response(202)
    )
    await email._deliver("from@a.com", ["to@b.com"], "subject", "text", "<html/>")
    assert route.called


async def test_deliver_uses_smtp_when_no_sendgrid(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")

    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await email._deliver("from@a.com", ["to@b.com"], "subject", "text", "<html/>")
    mock_send.assert_awaited_once()


# ---------------------------------------------------------------------------
# Public functions — SendGrid path
# ---------------------------------------------------------------------------

@respx.mock
async def test_send_escalation_sendgrid(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
    respx.post("https://api.sendgrid.com/v3/mail/send").mock(return_value=httpx.Response(202))
    await email.send_escalation(
        incident_id="inc-001",
        crash_summary="A bug occurred.",
        attempts=3,
        context="Tried A, B, C.",
        sendgrid_api_key="SG.test",
    )


@respx.mock
async def test_send_pr_merged_sendgrid(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
    respx.post("https://api.sendgrid.com/v3/mail/send").mock(return_value=httpx.Response(202))
    await email.send_pr_merged(
        incident_id="inc-001",
        pr_url="https://github.com/pr/1",
        pr_number=1,
        approved_by="alice",
        sendgrid_api_key="SG.test",
    )


# ---------------------------------------------------------------------------
# Public functions — SMTP path
# ---------------------------------------------------------------------------

async def test_send_escalation_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    with patch("aiosmtplib.send", new_callable=AsyncMock):
        await email.send_escalation("inc-001", "crash", 3, "context")


async def test_send_pr_merged_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    with patch("aiosmtplib.send", new_callable=AsyncMock):
        await email.send_pr_merged("inc-001", "https://github.com/pr/1", 1, "alice")


# ---------------------------------------------------------------------------
# _deliver — no backend configured
# ---------------------------------------------------------------------------

async def test_deliver_skips_when_no_backend_configured(monkeypatch):
    """_deliver logs a warning and returns when neither SendGrid nor SMTP is set."""
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    # Should not raise — just logs and returns
    await email._deliver("from@x.com", ["to@x.com"], "Subject", "body", "<body/>")


async def test_deliver_logs_warning_on_exception(monkeypatch):
    """_deliver swallows delivery exceptions and logs a warning."""
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.bad")
    with patch("integrations.email._send_sendgrid", new=AsyncMock(side_effect=Exception("network error"))):
        # Should not raise
        await email._deliver("from@x.com", ["to@x.com"], "Subject", "body", "<body/>",
                              sendgrid_api_key="SG.bad")


# ---------------------------------------------------------------------------
# send_escalation — skips when from/to not configured
# ---------------------------------------------------------------------------

async def test_send_escalation_skips_when_from_not_configured(monkeypatch):
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    # Should not raise
    await email.send_escalation("inc-001", "crash", 3, "ctx", from_addr=None)


async def test_send_escalation_skips_when_to_not_configured(monkeypatch):
    monkeypatch.delenv("EMAIL_TO", raising=False)
    # Should not raise
    await email.send_escalation("inc-001", "crash", 3, "ctx", to_addr=None)


# ---------------------------------------------------------------------------
# send_pr_merged — skips when from/to not configured
# ---------------------------------------------------------------------------

async def test_send_pr_merged_skips_when_from_not_configured(monkeypatch):
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    await email.send_pr_merged("inc-001", "https://github.com/pr/1", 1, "alice", from_addr=None)


async def test_send_pr_merged_skips_when_to_not_configured(monkeypatch):
    monkeypatch.delenv("EMAIL_TO", raising=False)
    await email.send_pr_merged("inc-001", "https://github.com/pr/1", 1, "alice", to_addr=None)


# ---------------------------------------------------------------------------
# send_fix_suggested
# ---------------------------------------------------------------------------

@respx.mock
async def test_send_fix_suggested_sendgrid(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
    respx.post("https://api.sendgrid.com/v3/mail/send").mock(return_value=httpx.Response(202))
    await email.send_fix_suggested(
        incident_id="inc-001",
        error_type="AttributeError",
        error_message="'NoneType' object has no attribute 'id'",
        issue_url="https://github.com/acme/repo/issues/10",
        sendgrid_api_key="SG.test",
    )


async def test_send_fix_suggested_skips_when_from_not_configured(monkeypatch):
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    await email.send_fix_suggested("inc-001", "TypeError", "bad", "https://x.com", from_addr=None)


async def test_send_fix_suggested_skips_when_to_not_configured(monkeypatch):
    monkeypatch.delenv("EMAIL_TO", raising=False)
    await email.send_fix_suggested("inc-001", "TypeError", "bad", "https://x.com", to_addr=None)
