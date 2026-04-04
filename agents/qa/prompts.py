"""
LLM prompts for the QA Agent.

The agent receives a CrashReport plus a snapshot of relevant source files
and must produce a single failing pytest test case that reproduces the bug.
"""

SYSTEM = """\
You are an expert QA engineer working in a TDD pipeline.
Given a production crash report and the relevant source code, write a minimal
pytest test that asserts the CORRECT, expected behaviour of the function.

Rules:
- The test MUST assert the desired correct outcome — NOT that an exception is raised.
  Do NOT use pytest.raises() unless the correct behaviour genuinely is to raise a
  specific, intentional exception (e.g. a ValueError on invalid input).
- The test MUST fail on the current buggy code (because the code does not yet
  produce the correct outcome).
- The test MUST pass once the correct fix is applied.
- Keep it minimal — one test function, no unnecessary fixtures.
- Use pytest conventions. Import only what already exists in the codebase.
- The test should target the specific function or code path that crashed.

Always respond with a single JSON object — no prose, no markdown fences.
"""


def rejection_note(problem: str) -> str:
    """
    Return a prompt section appended when the LLM's previous test was rejected.

    Args:
        problem: Plain-English description of why the test failed validation.

    Returns:
        A string to append to the base user prompt before retrying.
    """
    return f"""

## IMPORTANT — Previous Attempt Rejected

Your previous response was rejected for the following reason:

  {problem}

Write a NEW test that asserts the CORRECT, expected return value of the function.
Do NOT use pytest.raises() for the crash exception type. Instead, call the function
and assert what it should return (e.g. None, a default value, an error dict).
"""


def user(
    error_type: str,
    error_message: str,
    stack_trace: str,
    affected_component: str,
    affected_endpoint: str,
    summary: str,
    source_files: dict[str, str],
) -> str:
    """
    Build the user-turn prompt for the QA Agent LLM call.

    Args:
        error_type:          Exception class name.
        error_message:       Exception message.
        stack_trace:         Cleaned stack trace.
        affected_component:  Service/module name.
        affected_endpoint:   Endpoint or function that crashed.
        summary:             Plain-English crash summary.
        source_files:        Mapping of relative file path → file content
                             for the files most likely involved in the crash.

    Returns:
        Formatted prompt string.
    """
    files_section = ""
    for path, content in source_files.items():
        files_section += f"\n### {path}\n```python\n{content}\n```\n"

    if not files_section:
        files_section = "(no source files available)"

    return f"""\
A production crash has occurred. Your job is to write a pytest test that asserts
the CORRECT, expected behaviour of the affected function — not that it crashes.

The test must currently FAIL (because the bug means the function does not yet
produce the correct result), and PASS once the fix is applied.

## Crash Report
- Error type:          {error_type}
- Error message:       {error_message}
- Affected component:  {affected_component}
- Affected endpoint:   {affected_endpoint}
- Summary:             {summary}

## Stack Trace
{stack_trace}

## Relevant Source Files
{files_section}

## What to write
Assert what the function SHOULD return or do — not that it raises an exception.
For example, if a function crashes when a user is missing, the correct test checks
that calling it with a missing user returns a safe fallback (e.g. None, "", a
default object), not that it raises AttributeError.

## Output Format
Return a JSON object with exactly these fields:

  file_path  — relative path in the repo where the test file should be written,
                e.g. "tests/test_checkout.py"
  test_name  — the name of the test function (describe the expected outcome,
                e.g. "test_checkout_returns_error_for_missing_item")
  content    — the full content of the test file, ready to be written to disk

Example shape:
{{
  "file_path": "tests/test_checkout.py",
  "test_name": "test_checkout_returns_error_for_missing_item",
  "content": "from checkout import process\\n\\ndef test_checkout_returns_error_for_missing_item():\\n    result = process(item_id=None)\\n    assert result is not None\\n    assert result['error'] == 'item_not_found'\\n"
}}
"""
