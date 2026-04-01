"""Tests for integrations/jira.py"""
import pytest
import respx
import httpx

from integrations import jira


JIRA_URL = "https://acme.atlassian.net"
ENV = {
    "JIRA_URL": JIRA_URL,
    "JIRA_EMAIL": "dev@acme.com",
    "JIRA_TOKEN": "jira-api-token",
    "JIRA_PROJECT_KEY": "PROJ",
}


@pytest.fixture(autouse=True)
def set_jira_env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


# ---------------------------------------------------------------------------
# _auth_header
# ---------------------------------------------------------------------------

def test_auth_header_missing_email_raises(monkeypatch):
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    with pytest.raises(EnvironmentError, match="JIRA_EMAIL"):
        jira._auth_header()


def test_auth_header_missing_token_raises(monkeypatch):
    monkeypatch.delenv("JIRA_TOKEN", raising=False)
    with pytest.raises(EnvironmentError, match="JIRA_TOKEN"):
        jira._auth_header()


def test_base_url_missing_raises(monkeypatch):
    monkeypatch.delenv("JIRA_URL", raising=False)
    with pytest.raises(EnvironmentError, match="JIRA_URL"):
        jira._base_url()


# ---------------------------------------------------------------------------
# find_existing_issue
# ---------------------------------------------------------------------------

@respx.mock
async def test_find_existing_issue_found():
    respx.get(f"{JIRA_URL}/rest/api/3/issue/search").mock(
        return_value=httpx.Response(200, json={"issues": [{"key": "PROJ-1"}]})
    )
    result = await jira.find_existing_issue("KeyError: missing key")
    assert result == ("PROJ-1", f"{JIRA_URL}/browse/PROJ-1")


@respx.mock
async def test_find_existing_issue_not_found():
    respx.get(f"{JIRA_URL}/rest/api/3/issue/search").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )
    result = await jira.find_existing_issue("Some unique error")
    assert result is None


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------

@respx.mock
async def test_create_issue():
    respx.post(f"{JIRA_URL}/rest/api/3/issue").mock(
        return_value=httpx.Response(201, json={"key": "PROJ-42"})
    )
    key, url = await jira.create_issue("Bug summary", "Description here")
    assert key == "PROJ-42"
    assert "PROJ-42" in url


# ---------------------------------------------------------------------------
# add_comment
# ---------------------------------------------------------------------------

@respx.mock
async def test_add_comment():
    respx.post(f"{JIRA_URL}/rest/api/3/issue/PROJ-1/comment").mock(
        return_value=httpx.Response(201, json={})
    )
    await jira.add_comment("PROJ-1", "Helix re-detected this crash.")


# ---------------------------------------------------------------------------
# _to_adf
# ---------------------------------------------------------------------------

def test_to_adf_converts_text():
    doc = jira._to_adf("Line one\nLine two")
    assert doc["type"] == "doc"
    assert doc["version"] == 1
    paragraphs = doc["content"]
    assert any(
        p["content"] and p["content"][0]["text"] == "Line one"
        for p in paragraphs
    )


def test_to_adf_empty_string():
    doc = jira._to_adf("")
    assert doc["type"] == "doc"
    assert len(doc["content"]) >= 1


def test_to_adf_blank_lines_become_empty_paragraphs():
    doc = jira._to_adf("Line one\n\nLine two")
    # The blank line should produce an empty paragraph
    empty = [p for p in doc["content"] if not p["content"]]
    assert len(empty) >= 1
