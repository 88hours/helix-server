"""
LLM prompts for the QA Agent.

The agent receives a CrashReport plus a snapshot of relevant source files
and must produce a single failing pytest test case that reproduces the bug.
"""

SYSTEM = """\
You are an expert QA engineer. You write minimal test cases for a TDD pipeline.

You will receive a crash report and source code. Your ONLY job is to output a JSON object.

OUTPUT FORMAT — you must return exactly this JSON shape, nothing else:
{
  "file_path": "<relative path where the test file should be written>",
  "test_name": "<name of the test function>",
  "content": "<full content of the test file as a string>"
}

Rules for the test:
- ONLY import and call functions that exist in the provided source files.
- The test must call the EXACT function that crashed, with inputs that trigger the bug.
- Assert the CORRECT expected outcome (e.g. a return value, None, a default).
- Do NOT assert that an exception is raised — assert what should happen instead.
- The test must FAIL on current buggy code and PASS once the fix is applied.
- One test function only. No fixtures. No extra imports beyond what the codebase has.

No prose, no markdown fences, no explanation — JSON only.
"""


def rejection_note(problem: str, test_format: str = "pytest") -> str:
    """
    Return a prompt section appended when the LLM's previous test was rejected.

    Args:
        problem:     Plain-English description of why the test failed validation.
        test_format: Test framework in use, e.g. "pytest", "jest", "rspec".

    Returns:
        A string to append to the base user prompt before retrying.
    """
    framework_example = {
        "pytest":   "assert what it should return (e.g. None, a default value, an error dict).",
        "jest":     "assert the expected return value (e.g. expect(result).toBeNull()).",
        "rspec":    "assert the expected return value (e.g. expect(result).to be_nil).",
        "junit":    "assert the expected return value (e.g. assertNull(result)).",
        "go_test":  "assert the expected return value (e.g. if result != nil { t.Fatal(...) }).",
    }.get(test_format, "assert what it should return (e.g. a safe fallback value).")

    return f"""

## IMPORTANT — Previous Attempt Rejected

Your previous response was rejected for the following reason:

  {problem}

Write a NEW test that asserts the CORRECT, expected return value of the function.
Do NOT use the framework's exception assertion for the crash exception type. Instead,
call the function and {framework_example}
"""


def user(
    error_type: str,
    error_message: str,
    stack_trace: str,
    affected_component: str,
    affected_endpoint: str,
    summary: str,
    source_files: dict[str, str],
    language: str = "python",
    test_format: str = "pytest",
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
        language:            Application language, e.g. "python", "javascript".
        test_format:         Test framework to use, e.g. "pytest", "jest", "rspec".

    Returns:
        Formatted prompt string.
    """
    fence = _language_fence(language)
    files_section = ""
    for path, content in source_files.items():
        files_section += f"\n### {path}\n```{fence}\n{content}\n```\n"

    if not files_section:
        files_section = "(no source files available)"

    example = _test_file_example(language, test_format)

    return f"""\
A production crash has occurred. Write a {test_format} test for it.

Return ONLY this JSON — no other text:
{example}

The "content" field must be a non-empty string containing the full test file.
The "file_path" field must be a relative path like "tests/test_something.py".

## Crash
- Error type:     {error_type}
- Error message:  {error_message}
- Endpoint:       {affected_endpoint}
- Summary:        {summary}

## Stack Trace
{stack_trace}

## Source Files (use ONLY these — do not import anything else)
{files_section}

## Stack Trace
Write the test to call the EXACT function that appears in the stack trace above,
with inputs that reproduce the bug. Assert the correct outcome — not that it raises.
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _language_fence(language: str) -> str:
    """Return the markdown code fence language tag for syntax highlighting."""
    return {
        "javascript": "javascript",
        "typescript": "typescript",
        "ruby": "ruby",
        "java": "java",
        "kotlin": "kotlin",
        "go": "go",
    }.get(language.lower(), "python")


def _test_file_example(language: str, test_format: str) -> str:
    """Return a concrete JSON output example for the given language/framework."""
    examples = {
        "jest": (
            '{{\n'
            '  "file_path": "src/__tests__/checkout.test.ts",\n'
            '  "test_name": "returns null for missing item",\n'
            '  "content": "import {{ process }} from \'../checkout\';\\n\\n'
            "test('returns null for missing item', () => {{\\n"
            '  const result = process(null);\\n'
            '  expect(result).toBeNull();\\n'
            '}});\\n"\n'
            "}}"
        ),
        "rspec": (
            '{{\n'
            '  "file_path": "spec/checkout_spec.rb",\n'
            '  "test_name": "returns nil for missing item",\n'
            '  "content": "require \'checkout\'\\n\\n'
            "RSpec.describe Checkout do\\n"
            "  it 'returns nil for missing item' do\\n"
            "    result = Checkout.process(nil)\\n"
            "    expect(result).to be_nil\\n"
            "  end\\n"
            'end\\n"\n'
            "}}"
        ),
        "junit": (
            '{{\n'
            '  "file_path": "src/test/java/CheckoutTest.java",\n'
            '  "test_name": "testProcessReturnsNullForMissingItem",\n'
            '  "content": "import org.junit.jupiter.api.Test;\\n'
            "import static org.junit.jupiter.api.Assertions.*;\\n\\n"
            "public class CheckoutTest {{\\n"
            "  @Test\\n"
            "  public void testProcessReturnsNullForMissingItem() {{\\n"
            "    Object result = Checkout.process(null);\\n"
            "    assertNull(result);\\n"
            "  }}\\n"
            '}}\\n"\n'
            "}}"
        ),
        "go_test": (
            '{{\n'
            '  "file_path": "checkout/checkout_test.go",\n'
            '  "test_name": "TestProcessReturnsNilForMissingItem",\n'
            '  "content": "package checkout\\n\\n'
            "import \\\"testing\\\"\\n\\n"
            "func TestProcessReturnsNilForMissingItem(t *testing.T) {{\\n"
            "  result := Process(nil)\\n"
            "  if result != nil {{\\n"
            "    t.Fatalf(\\\"expected nil, got %v\\\", result)\\n"
            "  }}\\n"
            '}}\\n"\n'
            "}}"
        ),
    }
    return examples.get(test_format, (
        '{{\n'
        '  "file_path": "tests/test_checkout.py",\n'
        '  "test_name": "test_checkout_returns_error_for_missing_item",\n'
        '  "content": "from checkout import process\\n\\ndef test_checkout_returns_error_for_missing_item():\\n'
        "    result = process(item_id=None)\\n"
        "    assert result is not None\\n"
        "    assert result['error'] == 'item_not_found'\\n\"\n"
        "}}"
    ))
