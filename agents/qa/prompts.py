"""
LLM prompts for the QA Agent.

The agent receives a CrashReport plus a snapshot of relevant source files
and must produce a single failing pytest test case that reproduces the bug.
"""

SYSTEM = """\
You are an expert QA engineer working in a TDD pipeline.
Given a production crash report and the relevant source code, write a minimal
failing pytest test that reproduces the bug exactly.

Rules:
- The test MUST fail before any fix is applied.
- The test MUST pass after the correct fix is applied.
- Keep it minimal — one test function, no unnecessary fixtures.
- Use pytest conventions. Import only what already exists in the codebase.
- The test should target the specific function or code path that crashed.

Always respond with a single JSON object — no prose, no markdown fences.
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
Write a failing pytest test that reproduces the following production crash.

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

## Output Format
Return a JSON object with exactly these fields:

  file_path  — relative path in the repo where the test file should be written,
                e.g. "tests/test_checkout.py"
  test_name  — the name of the test function, e.g. "test_checkout_raises_on_missing_item"
  content    — the full content of the test file, ready to be written to disk

Example shape:
{{
  "file_path": "tests/test_checkout.py",
  "test_name": "test_checkout_raises_on_missing_item",
  "content": "import pytest\\nfrom checkout import process\\n\\ndef test_checkout_raises_on_missing_item():\\n    ..."
}}
"""
