"""
LLM prompts for the Dev Agent.

The Dev Agent uses the claude-code CLI backend, which runs inside the cloned
target repository.  The prompt is passed directly to `claude -p "..."`.

The agent looks for the sentinel strings "TESTS_PASSED" or "TESTS_FAILED"
in the CLI response to determine whether to commit the fix or retry.
"""


def build(
    incident_id: str,
    error_type: str,
    error_message: str,
    summary: str,
    test_file_path: str,
    test_name: str,
    iteration: int,
    prior_attempts: list[str],
    quality_feedback: str = "",
) -> str:
    """
    Build the full prompt string for a Dev Agent fix attempt.

    Args:
        incident_id:      Helix incident ID (for traceability in logs/commits).
        error_type:       Exception class, e.g. "KeyError".
        error_message:    Exception message.
        summary:          Plain-English crash summary from the Crash Handler.
        test_file_path:   Relative path to the failing test file already written
                          into the repo, e.g. "tests/test_checkout.py".
        test_name:        Test function name, e.g. "test_checkout_raises_on_missing_item".
        iteration:        Current attempt number (1-indexed).
        prior_attempts:   List of summaries from previous failed attempts, oldest first.
        quality_feedback: Structured feedback from the Code Quality Agent if this
                          is a retry after a quality rejection.  Empty string on
                          the first attempt.

    Returns:
        Prompt string ready to pass to `claude -p "..."`.
    """
    prior_section = ""
    if prior_attempts:
        prior_section = "\n## Previous Attempts (do not repeat these approaches)\n"
        for i, attempt in enumerate(prior_attempts, start=1):
            prior_section += f"\n### Attempt {i}\n{attempt}\n"

    quality_section = ""
    if quality_feedback:
        quality_section = f"\n## Code Review Feedback (must be addressed)\n{quality_feedback}\n"

    return f"""\
You are fixing a production bug for incident {incident_id} (attempt {iteration}/3).

## Bug Context
- Error type:    {error_type}
- Error message: {error_message}
- Summary:       {summary}

## Failing Test
A test that reproduces this bug has already been written to:
  {test_file_path}

Test function: {test_name}
{prior_section}{quality_section}
## Your Task
Follow these steps exactly:

1. Run the failing test to confirm it currently fails:
      pytest {test_file_path}::{test_name} -v

2. Read the relevant source files to understand the bug.

3. Write the minimal code change that makes the test pass.
   - Fix only the bug — do not refactor, rename, or clean up unrelated code.
   - Do not modify the test file.
   - Do not add new dependencies.

4. Run the full test suite to check for regressions:
      pytest

5. Based on the results, output ONE of the following sentinel lines,
   followed by a short explanation:

   If all tests pass:
      TESTS_PASSED
      <one paragraph: what you changed and why>

   If tests still fail:
      TESTS_FAILED
      <one paragraph: what you tried and why it did not work>

Do not output anything else after the sentinel line and explanation.
"""
