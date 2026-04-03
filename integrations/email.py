"""
Email integration for the Helix agent pipeline.

Supports two sending backends — the active one is selected automatically:

  SendGrid API  (preferred)
    Used when SENDGRID_API_KEY is set. Calls the SendGrid v3 REST API via
    httpx (already a project dependency — no extra package needed).

  SMTP  (fallback)
    Used when SENDGRID_API_KEY is not set. Works with any SMTP provider:
    Gmail, AWS SES, Mailgun, Postmark, etc. Requires aiosmtplib.

Backend selection is handled internally by _deliver() — callers always use
the same three public functions regardless of which backend is active.

Provides three notification types that mirror the Slack integration:
  send_approval_request  — PR ready for human review (Code Quality Agent passed)
  send_escalation        — Dev Agent exhausted all retries, needs a human fix
  send_pr_merged         — confirmation after Human Approval merges the PR

Environment variables (names stored in config.yaml):
  Always required:
    EMAIL_FROM            — sender address, e.g. helix@acme.com
    EMAIL_TO              — comma-separated recipients, e.g. oncall@acme.com

  SendGrid backend (set this and SMTP vars are optional):
    SENDGRID_API_KEY      — SendGrid API key (starts with SG.)

  SMTP backend (required when SENDGRID_API_KEY is not set):
    SMTP_HOST             — e.g. smtp.gmail.com or email-smtp.us-east-1.amazonaws.com
    SMTP_PORT             — 587 (STARTTLS, default) or 465 (SSL)
    SMTP_USER             — SMTP username
    SMTP_PASSWORD         — SMTP password
"""

import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib
import httpx

from core.models import QualityReport

logger = logging.getLogger(__name__)

_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _resolve(env_var: str, override: Optional[str]) -> str:
    """Return override if set, otherwise read env_var. Raises if empty."""
    value = override or os.environ.get(env_var, "")
    if not value:
        raise EnvironmentError(f"{env_var} is not set")
    return value


def _recipients(to_override: Optional[str]) -> list[str]:
    """Parse the TO address(es) into a deduplicated list."""
    raw = _resolve("EMAIL_TO", to_override)
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


# ---------------------------------------------------------------------------
# SendGrid backend
# ---------------------------------------------------------------------------

async def _send_sendgrid(
    api_key: str,
    from_addr: str,
    to_addrs: list[str],
    subject: str,
    body_text: str,
    body_html: str,
) -> None:
    """
    Deliver an email via the SendGrid v3 REST API.

    Uses httpx (already a project dependency) — no extra package needed.

    Args:
        api_key:   SendGrid API key.
        from_addr: Sender address.
        to_addrs:  List of recipient addresses.
        subject:   Email subject.
        body_text: Plain-text body (fallback for clients that don't render HTML).
        body_html: HTML body.

    Raises:
        httpx.HTTPStatusError: If the SendGrid API returns a non-2xx response.
    """
    payload = {
        "personalizations": [
            {"to": [{"email": addr} for addr in to_addrs]}
        ],
        "from": {"email": from_addr},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": body_text},
            {"type": "text/html", "value": body_html},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(_SENDGRID_API_URL, json=payload, headers=headers)
        response.raise_for_status()

    logger.info(
        "email sent via sendgrid",
        extra={"subject": subject, "to": ", ".join(to_addrs)},
    )


# ---------------------------------------------------------------------------
# SMTP backend
# ---------------------------------------------------------------------------

async def _send_smtp(
    from_addr: str,
    to_addrs: list[str],
    subject: str,
    body_text: str,
    body_html: str,
    smtp_host: Optional[str],
    smtp_port: Optional[int],
    smtp_user: Optional[str],
    smtp_password: Optional[str],
) -> None:
    """
    Deliver an email via SMTP using STARTTLS.

    Args:
        from_addr:     Sender address.
        to_addrs:      List of recipient addresses.
        subject:       Email subject.
        body_text:     Plain-text body.
        body_html:     HTML body.
        smtp_host:     SMTP hostname. Defaults to SMTP_HOST env var.
        smtp_port:     SMTP port. Defaults to SMTP_PORT env var or 587.
        smtp_user:     SMTP username. Defaults to SMTP_USER env var.
        smtp_password: SMTP password. Defaults to SMTP_PASSWORD env var.

    Raises:
        aiosmtplib.SMTPException: On SMTP-level delivery failures.
        EnvironmentError: If required SMTP env vars are not set.
    """
    host = _resolve("SMTP_HOST", smtp_host)
    port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
    user = _resolve("SMTP_USER", smtp_user)
    password = _resolve("SMTP_PASSWORD", smtp_password)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    await aiosmtplib.send(
        msg,
        hostname=host,
        port=port,
        username=user,
        password=password,
        start_tls=True,
    )
    logger.info(
        "email sent via smtp",
        extra={"subject": subject, "to": ", ".join(to_addrs), "host": host},
    )


# ---------------------------------------------------------------------------
# Backend dispatcher
# ---------------------------------------------------------------------------

async def _deliver(
    from_addr: str,
    to_addrs: list[str],
    subject: str,
    body_text: str,
    body_html: str,
    sendgrid_api_key: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Send an email using whichever backend is configured.

    Selection order:
      1. SendGrid API — if sendgrid_api_key is provided OR SENDGRID_API_KEY env var is set.
      2. SMTP         — fallback when no SendGrid key is found.

    Args:
        from_addr:        Sender address.
        to_addrs:         List of recipient addresses.
        subject:          Email subject.
        body_text:        Plain-text body.
        body_html:        HTML body.
        sendgrid_api_key: Explicit SendGrid API key override. Falls back to
                          SENDGRID_API_KEY env var.
        smtp_*:           SMTP credentials. Only used when SendGrid is not active.
    """
    api_key = sendgrid_api_key or os.environ.get("SENDGRID_API_KEY")

    if api_key:
        await _send_sendgrid(api_key, from_addr, to_addrs, subject, body_text, body_html)
    else:
        await _send_smtp(
            from_addr, to_addrs, subject, body_text, body_html,
            smtp_host, smtp_port, smtp_user, smtp_password,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def send_approval_request(
    incident_id: str,
    pr_url: str,
    report: QualityReport,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
    sendgrid_api_key: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Send an email approval request when the Code Quality Agent passes a PR.

    Sent in addition to (not instead of) the Slack approval message.

    Args:
        incident_id:      Helix incident ID.
        pr_url:           GitHub PR URL.
        report:           QualityReport from the Code Quality Agent.
        from_addr:        Sender. Defaults to EMAIL_FROM env var.
        to_addr:          Recipient(s). Defaults to EMAIL_TO env var.
        sendgrid_api_key: SendGrid API key override. Falls back to SENDGRID_API_KEY.
        smtp_*:           SMTP credentials. Used only when SendGrid is not active.
    """
    resolved_from = _resolve("EMAIL_FROM", from_addr)
    to_addrs = _recipients(to_addr)
    subject = f"[Helix] PR ready for review — incident {incident_id[:8]}"

    body_text = (
        f"A pull request is ready for your review.\n\n"
        f"Incident:      {incident_id}\n"
        f"PR:            {pr_url}\n"
        f"Test coverage: {report.test_coverage}\n"
        f"Standards:     {report.standards_check.value}\n"
        f"Security:      {report.security_check.value}\n\n"
        f"Notes:\n{report.notes}\n\n"
        f"Approve or reject via Slack."
    )
    body_html = f"""\
<html><body style="font-family: sans-serif; color: #111;">
<h2 style="color: #d63031;">&#128680; Helix &#8212; PR ready for review</h2>
<table style="border-collapse: collapse; width: 100%; max-width: 600px;">
  <tr><td style="padding: 6px; font-weight: bold;">Incident</td>
      <td style="padding: 6px; font-family: monospace;">{incident_id}</td></tr>
  <tr style="background: #f8f9fa;">
      <td style="padding: 6px; font-weight: bold;">Pull Request</td>
      <td style="padding: 6px;"><a href="{pr_url}">{pr_url}</a></td></tr>
  <tr><td style="padding: 6px; font-weight: bold;">Test coverage</td>
      <td style="padding: 6px;">{report.test_coverage}</td></tr>
  <tr style="background: #f8f9fa;">
      <td style="padding: 6px; font-weight: bold;">Standards</td>
      <td style="padding: 6px;">{report.standards_check.value}</td></tr>
  <tr><td style="padding: 6px; font-weight: bold;">Security</td>
      <td style="padding: 6px;">{report.security_check.value}</td></tr>
</table>
<p><strong>Notes:</strong><br>{report.notes}</p>
<p style="color: #636e72;">Approve or reject via Slack.</p>
</body></html>
"""

    await _deliver(
        resolved_from, to_addrs, subject, body_text, body_html,
        sendgrid_api_key, smtp_host, smtp_port, smtp_user, smtp_password,
    )
    logger.info("approval request email sent", extra={"incident_id": incident_id})


async def send_escalation(
    incident_id: str,
    crash_summary: str,
    attempts: int,
    context: str,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
    sendgrid_api_key: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Send an escalation email when the Dev Agent exhausts all retries.

    Sent in addition to the Slack escalation message.

    Args:
        incident_id:      Helix incident ID.
        crash_summary:    Plain-English crash summary.
        attempts:         Number of fix attempts made.
        context:          Full Dev Agent reasoning (what was tried, why it failed).
        from_addr:        Sender. Defaults to EMAIL_FROM env var.
        to_addr:          Recipient(s). Defaults to EMAIL_TO env var.
        sendgrid_api_key: SendGrid API key override. Falls back to SENDGRID_API_KEY.
        smtp_*:           SMTP credentials. Used only when SendGrid is not active.
    """
    resolved_from = _resolve("EMAIL_FROM", from_addr)
    to_addrs = _recipients(to_addr)
    subject = f"[Helix] Dev Agent escalation — incident {incident_id[:8]}"

    body_text = (
        f"The Dev Agent could not fix this bug after {attempts} attempts.\n\n"
        f"Incident:      {incident_id}\n\n"
        f"Crash summary:\n{crash_summary}\n\n"
        f"What the agent tried:\n{context}"
    )
    safe_context = context[:4000].replace("<", "&lt;").replace(">", "&gt;")
    body_html = f"""\
<html><body style="font-family: sans-serif; color: #111;">
<h2 style="color: #d63031;">&#128682; Helix &#8212; Dev Agent needs human help</h2>
<table style="border-collapse: collapse; width: 100%; max-width: 600px;">
  <tr><td style="padding: 6px; font-weight: bold;">Incident</td>
      <td style="padding: 6px; font-family: monospace;">{incident_id}</td></tr>
  <tr style="background: #f8f9fa;">
      <td style="padding: 6px; font-weight: bold;">Attempts exhausted</td>
      <td style="padding: 6px;">{attempts}</td></tr>
</table>
<p><strong>Crash summary:</strong><br>{crash_summary}</p>
<p><strong>What the agent tried:</strong></p>
<pre style="background: #f8f9fa; padding: 12px; border-radius: 4px;
            font-size: 13px; overflow-x: auto;">{safe_context}</pre>
</body></html>
"""

    await _deliver(
        resolved_from, to_addrs, subject, body_text, body_html,
        sendgrid_api_key, smtp_host, smtp_port, smtp_user, smtp_password,
    )
    logger.info("escalation email sent", extra={"incident_id": incident_id})


async def send_pr_merged(
    incident_id: str,
    pr_url: str,
    pr_number: int,
    approved_by: str,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
    sendgrid_api_key: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Send a confirmation email after the Human Approval agent merges the PR.

    Args:
        incident_id:      Helix incident ID.
        pr_url:           GitHub PR URL.
        pr_number:        GitHub PR number.
        approved_by:      Slack username of the reviewer who approved.
        from_addr:        Sender. Defaults to EMAIL_FROM env var.
        to_addr:          Recipient(s). Defaults to EMAIL_TO env var.
        sendgrid_api_key: SendGrid API key override. Falls back to SENDGRID_API_KEY.
        smtp_*:           SMTP credentials. Used only when SendGrid is not active.
    """
    resolved_from = _resolve("EMAIL_FROM", from_addr)
    to_addrs = _recipients(to_addr)
    subject = f"[Helix] PR #{pr_number} merged — incident {incident_id[:8]}"

    body_text = (
        f"The Helix-generated pull request has been approved and merged.\n\n"
        f"Incident:    {incident_id}\n"
        f"PR:          {pr_url}\n"
        f"Approved by: {approved_by}\n"
    )
    body_html = f"""\
<html><body style="font-family: sans-serif; color: #111;">
<h2 style="color: #00b894;">&#9989; Helix &#8212; PR merged</h2>
<table style="border-collapse: collapse; width: 100%; max-width: 600px;">
  <tr><td style="padding: 6px; font-weight: bold;">Incident</td>
      <td style="padding: 6px; font-family: monospace;">{incident_id}</td></tr>
  <tr style="background: #f8f9fa;">
      <td style="padding: 6px; font-weight: bold;">Pull Request</td>
      <td style="padding: 6px;"><a href="{pr_url}">PR #{pr_number}</a></td></tr>
  <tr><td style="padding: 6px; font-weight: bold;">Approved by</td>
      <td style="padding: 6px;">{approved_by}</td></tr>
</table>
</body></html>
"""

    await _deliver(
        resolved_from, to_addrs, subject, body_text, body_html,
        sendgrid_api_key, smtp_host, smtp_port, smtp_user, smtp_password,
    )
    logger.info(
        "pr merged email sent",
        extra={"incident_id": incident_id, "pr_number": pr_number},
    )


async def send_fix_suggested(
    incident_id: str,
    error_type: str,
    error_message: str,
    issue_url: str,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
    sendgrid_api_key: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Send a notification email when the Dev Agent posts a fix suggestion.

    Args:
        incident_id:   Helix incident ID.
        error_type:    Exception class, e.g. "AttributeError".
        error_message: Exception message.
        issue_url:     GitHub Issue URL where the fix comment was posted.
        from_addr:     Sender. Defaults to EMAIL_FROM env var.
        to_addr:       Recipient(s). Defaults to EMAIL_TO env var.
        sendgrid_api_key: SendGrid API key override.
        smtp_*:        SMTP credentials. Used only when SendGrid is not active.
    """
    resolved_from = _resolve("EMAIL_FROM", from_addr)
    to_addrs = _recipients(to_addr)
    subject = f"[Helix] Fix suggested for {error_type} — incident {incident_id[:8]}"

    body_text = (
        f"Helix has suggested a fix for the following incident.\n\n"
        f"Incident:  {incident_id}\n"
        f"Error:     {error_type}: {error_message}\n"
        f"Review:    {issue_url}\n\n"
        f"The suggested fix has been posted as a comment on the GitHub Issue above.\n"
        f"Please review and apply it manually.\n"
    )
    body_html = f"""\
<html><body style="font-family: sans-serif; color: #111;">
<h2 style="color: #0984e3;">&#128296; Helix &#8212; Fix Suggested</h2>
<table style="border-collapse: collapse; width: 100%; max-width: 600px;">
  <tr><td style="padding: 6px; font-weight: bold;">Incident</td>
      <td style="padding: 6px; font-family: monospace;">{incident_id}</td></tr>
  <tr style="background: #f8f9fa;">
      <td style="padding: 6px; font-weight: bold;">Error</td>
      <td style="padding: 6px; font-family: monospace;">{error_type}: {error_message}</td></tr>
  <tr><td style="padding: 6px; font-weight: bold;">Review Fix</td>
      <td style="padding: 6px;"><a href="{issue_url}">View on GitHub</a></td></tr>
</table>
<p style="color: #636e72; font-size: 13px;">
  The fix has been posted as a comment on the GitHub Issue. Please review and apply it manually.
</p>
</body></html>
"""

    await _deliver(
        resolved_from, to_addrs, subject, body_text, body_html,
        sendgrid_api_key, smtp_host, smtp_port, smtp_user, smtp_password,
    )
    logger.info("fix suggested email sent", extra={"incident_id": incident_id})
