"""
Email integration for the Helix agent pipeline.

Sends transactional notifications via SMTP using aiosmtplib (async).
Works with any SMTP provider: Gmail, SendGrid, AWS SES, Mailgun, Postmark, etc.

Provides three notification types that mirror the Slack integration:
  send_approval_request  — PR ready for human review (Code Quality Agent passed)
  send_escalation        — Dev Agent exhausted all retries, needs human fix
  send_pr_merged         — confirmation after Human Approval merges the PR

Required environment variables (names stored in config.yaml):
    SMTP_HOST      — e.g. smtp.sendgrid.net or smtp.gmail.com
    SMTP_PORT      — typically 587 (STARTTLS) or 465 (SSL)
    SMTP_USER      — SMTP username or API key username
    SMTP_PASSWORD  — SMTP password or API key
    EMAIL_FROM     — sender address, e.g. helix@acme.com
    EMAIL_TO       — comma-separated recipient list, e.g. oncall@acme.com
"""

import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from core.models import QualityReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve(env_var: str, override: Optional[str]) -> str:
    """Return override if set, otherwise read the env var. Raises if empty."""
    value = override or os.environ.get(env_var, "")
    if not value:
        raise EnvironmentError(f"{env_var} is not set")
    return value


def _recipients(to_override: Optional[str]) -> list[str]:
    """Parse the TO address(es) into a list."""
    raw = _resolve("EMAIL_TO", to_override)
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def _build_message(
    subject: str,
    body_text: str,
    body_html: str,
    from_addr: str,
    to_addrs: list[str],
) -> MIMEMultipart:
    """
    Build a MIME multipart/alternative email with plain-text and HTML parts.

    Args:
        subject:   Email subject line.
        body_text: Plain-text fallback body.
        body_html: HTML body.
        from_addr: Sender address.
        to_addrs:  List of recipient addresses.

    Returns:
        Assembled MIMEMultipart message ready to send.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    return msg


async def _send(
    msg: MIMEMultipart,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Deliver a message via SMTP using STARTTLS.

    Args:
        msg:           Assembled MIME message.
        smtp_host:     SMTP host. Defaults to SMTP_HOST env var.
        smtp_port:     SMTP port. Defaults to SMTP_PORT env var or 587.
        smtp_user:     SMTP username. Defaults to SMTP_USER env var.
        smtp_password: SMTP password. Defaults to SMTP_PASSWORD env var.
    """
    host = _resolve("SMTP_HOST", smtp_host)
    port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
    user = _resolve("SMTP_USER", smtp_user)
    password = _resolve("SMTP_PASSWORD", smtp_password)

    await aiosmtplib.send(
        msg,
        hostname=host,
        port=port,
        username=user,
        password=password,
        start_tls=True,
    )
    logger.info(
        "email sent",
        extra={"subject": msg["Subject"], "to": msg["To"]},
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
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Send an email approval request when the Code Quality Agent passes a PR.

    Mirrors the Slack approval message — sent in addition to (not instead of) Slack.

    Args:
        incident_id:   Helix incident ID.
        pr_url:        GitHub PR URL.
        report:        QualityReport from the Code Quality Agent.
        from_addr:     Sender. Defaults to EMAIL_FROM env var.
        to_addr:       Recipient(s). Defaults to EMAIL_TO env var.
        smtp_*:        SMTP credentials. Default to SMTP_* env vars.
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
        f"Review and approve or reject via Slack."
    )

    body_html = f"""\
<html><body style="font-family: sans-serif; color: #111;">
<h2 style="color: #d63031;">🚨 Helix — PR ready for review</h2>
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

    msg = _build_message(subject, body_text, body_html, resolved_from, to_addrs)
    await _send(msg, smtp_host, smtp_port, smtp_user, smtp_password)
    logger.info("approval request email sent", extra={"incident_id": incident_id})


async def send_escalation(
    incident_id: str,
    crash_summary: str,
    attempts: int,
    context: str,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Send an escalation email when the Dev Agent exhausts all retries.

    Mirrors the Slack escalation message — sent in addition to Slack.

    Args:
        incident_id:   Helix incident ID.
        crash_summary: Plain-English crash summary.
        attempts:      Number of fix attempts made.
        context:       Full Dev Agent reasoning — what was tried and why it failed.
        from_addr:     Sender. Defaults to EMAIL_FROM env var.
        to_addr:       Recipient(s). Defaults to EMAIL_TO env var.
        smtp_*:        SMTP credentials. Default to SMTP_* env vars.
    """
    resolved_from = _resolve("EMAIL_FROM", from_addr)
    to_addrs = _recipients(to_addr)

    subject = f"[Helix] 🆘 Dev Agent escalation — incident {incident_id[:8]}"

    body_text = (
        f"The Dev Agent could not fix this bug after {attempts} attempts.\n\n"
        f"Incident:      {incident_id}\n\n"
        f"Crash summary:\n{crash_summary}\n\n"
        f"What the agent tried:\n{context}"
    )

    safe_context = context[:4000].replace("<", "&lt;").replace(">", "&gt;")
    body_html = f"""\
<html><body style="font-family: sans-serif; color: #111;">
<h2 style="color: #d63031;">🆘 Helix — Dev Agent needs human help</h2>
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

    msg = _build_message(subject, body_text, body_html, resolved_from, to_addrs)
    await _send(msg, smtp_host, smtp_port, smtp_user, smtp_password)
    logger.info("escalation email sent", extra={"incident_id": incident_id})


async def send_pr_merged(
    incident_id: str,
    pr_url: str,
    pr_number: int,
    approved_by: str,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Send a confirmation email after the Human Approval agent merges the PR.

    Args:
        incident_id:  Helix incident ID.
        pr_url:       GitHub PR URL.
        pr_number:    GitHub PR number.
        approved_by:  Slack username of the reviewer who approved.
        from_addr:    Sender. Defaults to EMAIL_FROM env var.
        to_addr:      Recipient(s). Defaults to EMAIL_TO env var.
        smtp_*:       SMTP credentials. Default to SMTP_* env vars.
    """
    resolved_from = _resolve("EMAIL_FROM", from_addr)
    to_addrs = _recipients(to_addr)

    subject = f"[Helix] ✅ PR #{pr_number} merged — incident {incident_id[:8]}"

    body_text = (
        f"The Helix-generated pull request has been approved and merged.\n\n"
        f"Incident:    {incident_id}\n"
        f"PR:          {pr_url}\n"
        f"Approved by: {approved_by}\n"
    )

    body_html = f"""\
<html><body style="font-family: sans-serif; color: #111;">
<h2 style="color: #00b894;">✅ Helix — PR merged</h2>
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

    msg = _build_message(subject, body_text, body_html, resolved_from, to_addrs)
    await _send(msg, smtp_host, smtp_port, smtp_user, smtp_password)
    logger.info("pr merged email sent", extra={"incident_id": incident_id, "pr_number": pr_number})
