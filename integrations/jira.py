"""
JIRA integration for the Helix QA Agent.

Provides async helpers for creating and updating JIRA issues.  All calls use
the JIRA REST API v3 with Basic authentication (email + API token).

Required environment variables:
    JIRA_URL          — Base URL of your JIRA instance, e.g. "https://acme.atlassian.net"
    JIRA_TOKEN        — JIRA API token (generated at id.atlassian.com)
    JIRA_EMAIL        — Email address associated with the JIRA API token
    JIRA_PROJECT_KEY  — Default project key, e.g. "PROJ"

All functions accept explicit overrides for the URL, token, email, and project
key so they can be used in multi-tenant scenarios without relying solely on env vars.
"""

import base64
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _auth_header(email: Optional[str] = None, token: Optional[str] = None) -> dict[str, str]:
    """
    Build the Basic Auth header for JIRA API requests.

    JIRA Cloud uses base64(email:token) for Basic auth.

    Args:
        email: JIRA account email. Falls back to JIRA_EMAIL env var.
        token: JIRA API token. Falls back to JIRA_TOKEN env var.

    Returns:
        Dict with a single "Authorization" header.

    Raises:
        EnvironmentError: If email or token cannot be resolved.
    """
    email = email or os.environ.get("JIRA_EMAIL")
    token = token or os.environ.get("JIRA_TOKEN")
    if not email:
        raise EnvironmentError("JIRA_EMAIL is not set")
    if not token:
        raise EnvironmentError("JIRA_TOKEN is not set")
    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}


def _base_url(jira_url: Optional[str] = None) -> str:
    """Return the JIRA base URL, falling back to the JIRA_URL env var."""
    url = jira_url or os.environ.get("JIRA_URL")
    if not url:
        raise EnvironmentError("JIRA_URL is not set")
    return url.rstrip("/")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def find_existing_issue(
    summary: str,
    project_key: Optional[str] = None,
    jira_url: Optional[str] = None,
    email: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """
    Search for an open JIRA issue with a matching summary.

    Used by the QA Agent to deduplicate: if a ticket for this bug already
    exists, update it rather than creating a duplicate.

    Args:
        summary:     Issue summary to search for (exact or near match via JQL).
        project_key: JIRA project key. Defaults to JIRA_PROJECT_KEY env var.
        jira_url:    JIRA base URL. Defaults to JIRA_URL env var.
        email:       JIRA account email. Defaults to JIRA_EMAIL env var.
        token:       JIRA API token. Defaults to JIRA_TOKEN env var.

    Returns:
        (issue_key, issue_url) if a match is found, or None.
    """
    project = project_key or os.environ.get("JIRA_PROJECT_KEY")
    if not project:
        raise EnvironmentError("JIRA_PROJECT_KEY is not set")

    base = _base_url(jira_url)
    # JQL: search for issues with a summary containing key terms, open status.
    # We truncate the summary to keep the JQL query reasonable.
    search_term = summary[:80].replace('"', "'")
    jql = f'project = "{project}" AND summary ~ "{search_term}" AND statusCategory != Done'

    url = f"{base}/rest/api/3/issue/search"
    params = {"jql": jql, "maxResults": 1, "fields": "summary,status"}
    headers = {**_auth_header(email, token), "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()

    issues = response.json().get("issues", [])
    if not issues:
        return None

    issue = issues[0]
    key = issue["key"]
    issue_url = f"{base}/browse/{key}"
    logger.info("existing jira issue found", extra={"key": key})
    return key, issue_url


async def create_issue(
    summary: str,
    description: str,
    project_key: Optional[str] = None,
    issue_type: str = "Bug",
    jira_url: Optional[str] = None,
    email: Optional[str] = None,
    token: Optional[str] = None,
) -> tuple[str, str]:
    """
    Create a new JIRA issue.

    Args:
        summary:     Issue title/summary.
        description: Detailed description in plain text (converted to ADF).
        project_key: JIRA project key. Defaults to JIRA_PROJECT_KEY env var.
        issue_type:  JIRA issue type. Defaults to "Bug".
        jira_url:    JIRA base URL. Defaults to JIRA_URL env var.
        email:       JIRA account email. Defaults to JIRA_EMAIL env var.
        token:       JIRA API token. Defaults to JIRA_TOKEN env var.

    Returns:
        (issue_key, issue_url) — e.g. ("PROJ-42", "https://acme.atlassian.net/browse/PROJ-42").

    Raises:
        httpx.HTTPStatusError: If the API request fails.
    """
    project = project_key or os.environ.get("JIRA_PROJECT_KEY")
    if not project:
        raise EnvironmentError("JIRA_PROJECT_KEY is not set")

    base = _base_url(jira_url)
    url = f"{base}/rest/api/3/issue"
    headers = {**_auth_header(email, token), "Content-Type": "application/json"}

    # JIRA Cloud requires description in Atlassian Document Format (ADF).
    payload = {
        "fields": {
            "project": {"key": project},
            "summary": summary,
            "description": _to_adf(description),
            "issuetype": {"name": issue_type},
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()

    data = response.json()
    key = data["key"]
    issue_url = f"{base}/browse/{key}"
    logger.info("jira issue created", extra={"key": key})
    return key, issue_url


async def add_comment(
    issue_key: str,
    comment: str,
    jira_url: Optional[str] = None,
    email: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """
    Add a comment to an existing JIRA issue.

    Used when deduplication finds an existing ticket — we add context rather
    than creating a duplicate.

    Args:
        issue_key: JIRA issue key, e.g. "PROJ-42".
        comment:   Plain-text comment body.
        jira_url:  JIRA base URL. Defaults to JIRA_URL env var.
        email:     JIRA account email. Defaults to JIRA_EMAIL env var.
        token:     JIRA API token. Defaults to JIRA_TOKEN env var.

    Raises:
        httpx.HTTPStatusError: If the API request fails.
    """
    base = _base_url(jira_url)
    url = f"{base}/rest/api/3/issue/{issue_key}/comment"
    headers = {**_auth_header(email, token), "Content-Type": "application/json"}
    payload = {"body": _to_adf(comment)}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()

    logger.info("jira comment added", extra={"issue_key": issue_key})


# ---------------------------------------------------------------------------
# ADF conversion
# ---------------------------------------------------------------------------

def _to_adf(text: str) -> dict:
    """
    Convert a plain-text string to the minimal Atlassian Document Format (ADF)
    structure that JIRA Cloud's API requires for description and comment fields.

    Each line becomes its own paragraph to preserve readability.

    Args:
        text: Plain-text content.

    Returns:
        ADF document dict.
    """
    paragraphs = []
    for line in text.splitlines():
        if line.strip():
            paragraphs.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": line}],
            })
        else:
            paragraphs.append({"type": "paragraph", "content": []})

    if not paragraphs:
        paragraphs = [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]

    return {
        "type": "doc",
        "version": 1,
        "content": paragraphs,
    }
