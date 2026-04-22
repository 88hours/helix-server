"""
LangSmith evaluator functions for the Helix agent eval suite.

Each evaluator follows the LangSmith signature:

    def evaluator_name(run, example) -> dict

Where:
    run.outputs  — the dict returned by the eval target function
    example.inputs   — the inputs passed to the target
    example.metadata — metadata attached to the dataset example (expected values)

Return value must be a dict with at least:
    "key"   — metric name shown in LangSmith
    "score" — 1 (pass) or 0 (fail)
    "comment" — optional human-readable explanation

Evaluators are stateless, synchronous, and have no side effects.
"""

import json
from typing import Any


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_output(run) -> str:
    """Extract the raw string output from a run."""
    return run.outputs.get("output", "") if run.outputs else ""


def _parse_json(run) -> tuple[dict | None, str]:
    """
    Try to parse the run output as JSON.

    Returns:
        (parsed dict or None, error message or "")
    """
    raw = _get_output(run)
    if not raw:
        return None, "output is empty"
    # Strip markdown fences if the model wrapped the JSON despite instructions
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        stripped = "\n".join(lines[1:-1]) if len(lines) > 2 else stripped
    try:
        return json.loads(stripped), ""
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc}"


# ---------------------------------------------------------------------------
# Crash Handler evaluators
# ---------------------------------------------------------------------------

def valid_json_crash_handler(run, example) -> dict:
    """
    Check that the crash handler output is valid JSON.

    The prompt explicitly asks for JSON only — any prose or markdown wrapping
    indicates a prompt compliance failure.
    """
    parsed, error = _parse_json(run)
    if parsed is None:
        return {"key": "valid_json", "score": 0, "comment": error}
    return {"key": "valid_json", "score": 1}


def has_required_crash_fields(run, example) -> dict:
    """
    Check that all required CrashReport fields are present in the output.

    Required: severity, error_type, error_message, stack_trace,
              affected_component, affected_endpoint, summary, language.
    """
    required = {
        "severity", "error_type", "error_message", "stack_trace",
        "affected_component", "affected_endpoint", "summary", "language",
    }
    parsed, error = _parse_json(run)
    if parsed is None:
        return {"key": "has_required_fields", "score": 0, "comment": error}

    missing = required - set(parsed.keys())
    if missing:
        return {
            "key": "has_required_fields",
            "score": 0,
            "comment": f"Missing fields: {sorted(missing)}",
        }
    return {"key": "has_required_fields", "score": 1}


def valid_severity(run, example) -> dict:
    """
    Check that the severity field is one of the three allowed values.

    Expected values: "critical", "high", "medium".
    """
    parsed, error = _parse_json(run)
    if parsed is None:
        return {"key": "valid_severity", "score": 0, "comment": error}

    severity = parsed.get("severity", "")
    allowed = {"critical", "high", "medium"}
    if severity not in allowed:
        return {
            "key": "valid_severity",
            "score": 0,
            "comment": f"Got '{severity}', expected one of {allowed}",
        }
    return {"key": "valid_severity", "score": 1}


def correct_error_type(run, example) -> dict:
    """
    Check that the error_type in the output matches the expected value from
    the dataset example metadata.

    Skipped (score=1) when no expected_error_type is provided in metadata.
    """
    expected = (example.metadata or {}).get("expected_error_type")
    if not expected:
        return {"key": "correct_error_type", "score": 1, "comment": "no expectation set"}

    parsed, error = _parse_json(run)
    if parsed is None:
        return {"key": "correct_error_type", "score": 0, "comment": error}

    got = parsed.get("error_type", "")
    if got != expected:
        return {
            "key": "correct_error_type",
            "score": 0,
            "comment": f"Expected '{expected}', got '{got}'",
        }
    return {"key": "correct_error_type", "score": 1}


# ---------------------------------------------------------------------------
# QA Agent evaluators
# ---------------------------------------------------------------------------

def valid_json_qa(run, example) -> dict:
    """Check that the QA agent output is valid JSON."""
    parsed, error = _parse_json(run)
    if parsed is None:
        return {"key": "valid_json", "score": 0, "comment": error}
    return {"key": "valid_json", "score": 1}


def has_required_qa_fields(run, example) -> dict:
    """
    Check that the QA agent output contains all required test case fields.

    Required: file_path, test_name, content.
    """
    required = {"file_path", "test_name", "content"}
    parsed, error = _parse_json(run)
    if parsed is None:
        return {"key": "has_required_fields", "score": 0, "comment": error}

    missing = required - set(parsed.keys())
    if missing:
        return {
            "key": "has_required_fields",
            "score": 0,
            "comment": f"Missing fields: {sorted(missing)}",
        }
    return {"key": "has_required_fields", "score": 1}


def test_content_not_empty(run, example) -> dict:
    """Check that the generated test content is non-empty and looks like code."""
    parsed, error = _parse_json(run)
    if parsed is None:
        return {"key": "test_content_not_empty", "score": 0, "comment": error}

    content = parsed.get("content", "")
    if not content or len(content.strip()) < 20:
        return {
            "key": "test_content_not_empty",
            "score": 0,
            "comment": f"Content too short or empty: {repr(content[:80])}",
        }
    return {"key": "test_content_not_empty", "score": 1}


def test_avoids_exception_assertion(run, example) -> dict:
    """
    Check that the generated test does NOT use pytest.raises or similar
    exception assertions for the crash exception type.

    The QA prompt explicitly asks for positive assertions — the test should
    check what the function SHOULD return, not that it raises.
    """
    parsed, error = _parse_json(run)
    if parsed is None:
        return {"key": "no_exception_assertion", "score": 0, "comment": error}

    content = parsed.get("content", "")
    forbidden_patterns = ["pytest.raises", ".toThrow", "assertThrows", "raise_error"]
    found = [p for p in forbidden_patterns if p in content]
    if found:
        return {
            "key": "no_exception_assertion",
            "score": 0,
            "comment": f"Test uses forbidden exception assertion(s): {found}",
        }
    return {"key": "no_exception_assertion", "score": 1}


# ---------------------------------------------------------------------------
# Dev Agent evaluators
#
# The Dev Agent's build_suggestion() returns plain text (not JSON) with three
# required sections: a one-sentence root cause, labelled BEFORE/AFTER code
# blocks, and a short explanation. These evaluators check structural compliance
# without making any LLM calls.
# ---------------------------------------------------------------------------

def has_root_cause_sentence(run, example) -> dict:
    """
    Check that the fix suggestion identifies a root cause in one sentence.

    The prompt explicitly asks for the root cause as the first item. Its
    presence is a reliable signal that the model followed the structure.
    """
    output = _get_output(run).lower()
    if "root cause" in output:
        return {"key": "has_root_cause", "score": 1}
    return {
        "key": "has_root_cause",
        "score": 0,
        "comment": "Output does not contain a root cause statement",
    }


def has_before_block(run, example) -> dict:
    """
    Check that the fix suggestion contains a BEFORE code block.

    The prompt requires clearly labelled BEFORE and AFTER blocks so the
    reviewer can see exactly what changed.
    """
    output = _get_output(run)
    if "BEFORE" in output or "before" in output.lower():
        return {"key": "has_before_block", "score": 1}
    return {
        "key": "has_before_block",
        "score": 0,
        "comment": "Output does not contain a BEFORE block",
    }


def has_after_block(run, example) -> dict:
    """
    Check that the fix suggestion contains an AFTER code block.

    An AFTER block is required — without it the developer cannot see what
    the fixed code should look like.
    """
    output = _get_output(run)
    if "AFTER" in output or "after" in output.lower():
        return {"key": "has_after_block", "score": 1}
    return {
        "key": "has_after_block",
        "score": 0,
        "comment": "Output does not contain an AFTER block",
    }


def after_block_differs_from_before(run, example) -> dict:
    """
    Check that the AFTER block is not identical to the BEFORE block.

    If they are the same the model produced a no-op fix, which would not
    make the failing test pass.
    """
    output = _get_output(run)
    upper = output.upper()
    before_pos = upper.find("BEFORE")
    after_pos = upper.find("AFTER")
    if before_pos == -1 or after_pos == -1 or after_pos <= before_pos:
        return {
            "key": "after_differs_from_before",
            "score": 0,
            "comment": "Could not locate distinct BEFORE and AFTER sections",
        }
    before_text = output[before_pos:after_pos].strip()
    after_text = output[after_pos:].strip()
    if before_text == after_text:
        return {
            "key": "after_differs_from_before",
            "score": 0,
            "comment": "BEFORE and AFTER blocks are identical — fix is a no-op",
        }
    return {"key": "after_differs_from_before", "score": 1}


def no_new_imports_in_fix(run, example) -> dict:
    """
    Check that the AFTER block does not introduce new import statements.

    The prompt says not to add new dependencies. Any new import in the fix
    violates that constraint and may break the target environment.
    """
    output = _get_output(run)
    if not output:
        return {"key": "no_new_imports", "score": 0, "comment": "no output"}
    upper = output.upper()
    after_pos = upper.find("AFTER")
    if after_pos == -1:
        return {"key": "no_new_imports", "score": 1, "comment": "no AFTER block found — skipped"}
    after_text = output[after_pos:]
    lines = after_text.splitlines()
    new_imports = [
        l.strip() for l in lines
        if l.strip().startswith("import ") or l.strip().startswith("from ")
    ]
    if new_imports:
        return {
            "key": "no_new_imports",
            "score": 0,
            "comment": f"AFTER block introduces new import(s): {new_imports[:3]}",
        }
    return {"key": "no_new_imports", "score": 1}
