"""
Tests for core/permissions.py — scoped tool access enforcement.

Covers:
  - load_permissions() loading from config.yaml
  - require() passing for allowed operations
  - require() raising PermissionDenied for denied operations
  - PermissionDenied exception attributes and message
  - Edge cases: unknown agents, empty permission lists, missing tool sections
"""

import pytest

from core.permissions import AgentPermissions, PermissionDenied, load_permissions, require


# ---------------------------------------------------------------------------
# load_permissions() tests
# ---------------------------------------------------------------------------

class TestLoadPermissions:
    """load_permissions() reads declared permissions from config.yaml."""

    def test_crash_handler_has_no_github_access(self):
        perms = load_permissions("crash_handler")
        assert perms.agent == "crash_handler"
        assert perms.tools.get("github") == []

    def test_crash_handler_can_write_crash_report(self):
        perms = load_permissions("crash_handler")
        assert "write_crash_report" in perms.tools.get("redis", [])

    def test_crash_handler_can_write_status(self):
        perms = load_permissions("crash_handler")
        assert "write_status" in perms.tools.get("redis", [])

    def test_qa_can_create_github_issue(self):
        perms = load_permissions("qa")
        assert "create_issue" in perms.tools.get("github", [])

    def test_qa_cannot_create_pull_request(self):
        perms = load_permissions("qa")
        assert "create_pull_request" not in perms.tools.get("github", [])

    def test_qa_cannot_commit_and_push(self):
        perms = load_permissions("qa")
        assert "commit_and_push" not in perms.tools.get("github", [])

    def test_dev_can_create_pull_request(self):
        perms = load_permissions("dev")
        assert "create_pull_request" in perms.tools.get("github", [])

    def test_dev_can_commit_and_push(self):
        perms = load_permissions("dev")
        assert "commit_and_push" in perms.tools.get("github", [])

    def test_dev_has_no_slack_access(self):
        perms = load_permissions("dev")
        assert perms.tools.get("slack") == []

    def test_notifier_can_post_slack_message(self):
        perms = load_permissions("notifier")
        assert "post_message" in perms.tools.get("slack", [])

    def test_notifier_can_post_approval_request(self):
        perms = load_permissions("notifier")
        assert "post_approval_request" in perms.tools.get("slack", [])

    def test_notifier_has_no_github_access(self):
        perms = load_permissions("notifier")
        assert perms.tools.get("github") == []

    def test_notifier_cannot_write_to_redis(self):
        perms = load_permissions("notifier")
        redis_ops = perms.tools.get("redis", [])
        assert "write_crash_report" not in redis_ops
        assert "write_status" not in redis_ops
        assert "write_pr_result" not in redis_ops

    def test_unknown_agent_raises_key_error(self):
        with pytest.raises(KeyError, match="not found in config.yaml"):
            load_permissions("nonexistent_agent")


# ---------------------------------------------------------------------------
# require() tests — passing cases
# ---------------------------------------------------------------------------

class TestRequireAllowed:
    """require() does not raise when the operation is in the allowed list."""

    def test_allowed_operation_passes(self):
        perms = AgentPermissions(
            agent="test_agent",
            tools={"github": ["create_issue", "add_issue_comment"]},
        )
        require(perms, "github", "create_issue")  # must not raise

    def test_multiple_allowed_operations(self):
        perms = AgentPermissions(
            agent="test_agent",
            tools={"github": ["clone_repo", "create_issue"], "slack": ["post_message"]},
        )
        require(perms, "github", "clone_repo")
        require(perms, "github", "create_issue")
        require(perms, "slack", "post_message")

    def test_real_qa_allowed_operations(self):
        perms = load_permissions("qa")
        require(perms, "github", "find_existing_issue")
        require(perms, "github", "create_issue")
        require(perms, "github", "add_issue_comment")
        require(perms, "github", "clone_repo")

    def test_real_dev_allowed_operations(self):
        perms = load_permissions("dev")
        require(perms, "github", "fetch_source_files")
        require(perms, "github", "clone_repo")
        require(perms, "github", "checkout_branch")
        require(perms, "github", "write_file")
        require(perms, "github", "commit_and_push")
        require(perms, "github", "create_pull_request")
        require(perms, "github", "add_issue_comment")

    def test_real_notifier_allowed_operations(self):
        perms = load_permissions("notifier")
        require(perms, "slack", "post_message")
        require(perms, "slack", "post_escalation")
        require(perms, "slack", "post_approval_request")
        require(perms, "email", "send_fix_suggested")
        require(perms, "email", "send_escalation")
        require(perms, "email", "send_pr_merged")


# ---------------------------------------------------------------------------
# require() tests — denied cases
# ---------------------------------------------------------------------------

class TestRequireDenied:
    """require() raises PermissionDenied for any operation not in the allowed list."""

    def test_denied_operation_raises(self):
        perms = AgentPermissions(
            agent="test_agent",
            tools={"github": ["create_issue"]},
        )
        with pytest.raises(PermissionDenied):
            require(perms, "github", "create_pull_request")

    def test_empty_tool_list_denies_all(self):
        perms = AgentPermissions(
            agent="test_agent",
            tools={"github": []},
        )
        with pytest.raises(PermissionDenied):
            require(perms, "github", "create_issue")

    def test_missing_tool_section_denies_all(self):
        perms = AgentPermissions(agent="test_agent", tools={})
        with pytest.raises(PermissionDenied):
            require(perms, "github", "create_issue")

    def test_qa_cannot_create_pull_request(self):
        perms = load_permissions("qa")
        with pytest.raises(PermissionDenied):
            require(perms, "github", "create_pull_request")

    def test_qa_cannot_commit_and_push(self):
        perms = load_permissions("qa")
        with pytest.raises(PermissionDenied):
            require(perms, "github", "commit_and_push")

    def test_crash_handler_cannot_use_github(self):
        perms = load_permissions("crash_handler")
        with pytest.raises(PermissionDenied):
            require(perms, "github", "create_issue")

    def test_crash_handler_cannot_use_slack(self):
        perms = load_permissions("crash_handler")
        with pytest.raises(PermissionDenied):
            require(perms, "slack", "post_message")

    def test_dev_cannot_use_slack(self):
        perms = load_permissions("dev")
        with pytest.raises(PermissionDenied):
            require(perms, "slack", "post_approval_request")

    def test_notifier_cannot_use_github(self):
        perms = load_permissions("notifier")
        with pytest.raises(PermissionDenied):
            require(perms, "github", "create_issue")

    def test_notifier_cannot_write_redis(self):
        perms = load_permissions("notifier")
        with pytest.raises(PermissionDenied):
            require(perms, "redis", "write_status")


# ---------------------------------------------------------------------------
# PermissionDenied exception tests
# ---------------------------------------------------------------------------

class TestPermissionDeniedException:
    """PermissionDenied carries structured context about the violation."""

    def test_exception_attributes(self):
        perms = AgentPermissions(
            agent="qa",
            tools={"github": ["create_issue"]},
        )
        with pytest.raises(PermissionDenied) as exc_info:
            require(perms, "github", "create_pull_request")

        exc = exc_info.value
        assert exc.agent == "qa"
        assert exc.tool == "github"
        assert exc.operation == "create_pull_request"
        assert exc.allowed == ["create_issue"]

    def test_exception_message_contains_agent(self):
        perms = AgentPermissions(agent="qa", tools={})
        with pytest.raises(PermissionDenied, match="qa"):
            require(perms, "github", "create_pull_request")

    def test_exception_message_contains_operation(self):
        perms = AgentPermissions(agent="qa", tools={})
        with pytest.raises(PermissionDenied, match="create_pull_request"):
            require(perms, "github", "create_pull_request")

    def test_exception_message_shows_none_when_empty(self):
        perms = AgentPermissions(agent="qa", tools={"github": []})
        with pytest.raises(PermissionDenied, match="none"):
            require(perms, "github", "create_pull_request")
