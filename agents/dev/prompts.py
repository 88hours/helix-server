"""
LLM prompts for the Dev Agent.

The Dev Agent uses the Anthropic API to generate a minimal code fix for a
failing test case. The response is posted directly to the GitHub Issue as a
comment for the engineering team to review and apply.
"""


def build(
    error_type: str,
    error_message: str,
    summary: str,
    test_file_path: str,
    test_name: str,
    test_content: str,
    source_files: dict[str, str],
) -> str:
    """
    Build the fix-suggestion prompt for the Dev Agent.

    Args:
        error_type:     Exception class, e.g. "AttributeError".
        error_message:  Exception message.
        summary:        Plain-English crash summary from the Crash Handler.
        test_file_path: Path to the failing test file.
        test_name:      Failing test function name.
        test_content:   Full content of the failing test.
        source_files:   Mapping of file path → content for relevant source files.

    Returns:
        Prompt string ready to send to the Anthropic API.
    """
    source_section = ""
    if source_files:
        source_section = "\n## Relevant Source Files\n"
        for path, content in source_files.items():
            source_section += f"\n### `{path}`\n```python\n{content}\n```\n"
    else:
        source_section = "\n## Relevant Source Files\n_(No source files available.)_\n"

    return f"""\
You are a senior software engineer reviewing a production bug.

## Bug Summary
- **Error type:** {error_type}
- **Error message:** {error_message}
- **Summary:** {summary}

## Failing Test
The following test was written to reproduce this bug. It currently fails.

**File:** `{test_file_path}`
**Test:** `{test_name}`

```python
{test_content}
```
{source_section}
## Your Task

Write the minimal code change that will make the failing test pass without breaking other functionality.

Your response must:
1. Identify the root cause in one sentence.
2. Show the exact code change using a diff or clearly labelled before/after blocks.
3. Explain why this change fixes the bug in 2–3 sentences.

Be concise. Do not refactor unrelated code. Do not add new dependencies.
"""
