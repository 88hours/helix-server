"""
LLM prompts for the Dev Agent.

Two prompts are used in sequence:

  build_diagnosis() — sent to the Anthropic API to produce a structured JSON
      diagnosis: exactly which file and line to change, and the before/after
      text.  The response is validated programmatically before being used.
      A human-readable version is posted as a GitHub Issue comment.

  build_tdd() — sent to the claude-code CLI (running inside the cloned repo)
      to implement the fix using a TDD loop.  When a validated BugDiagnosis is
      available it is injected so the CLI knows exactly what to change and only
      needs to apply and verify — removing the "figure out what to fix" decision.

The TDD prompt uses a sentinel protocol: the CLI must output either
"TESTS_PASSED" or "TESTS_FAILED" followed by a short explanation so the
agent can decide whether to commit the fix or retry.
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import BugDiagnosis


def build_diagnosis(
    error_type: str,
    error_message: str,
    summary: str,
    test_file_path: str,
    test_name: str,
    test_content: str,
    source_files: dict[str, str],
) -> str:
    """
    Build the structured diagnosis prompt for the Anthropic API call.

    The model returns a JSON object identifying the exact file, line, and
    text change needed.  The caller validates the response against the actual
    source before trusting it.

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
            source_section += f"\n### `{path}`\n```\n{content}\n```\n"
    else:
        source_section = "\n## Relevant Source Files\n_(No source files available.)_\n"

    return f"""\
You are a senior software engineer diagnosing a production bug.

## Bug Summary
- **Error type:** {error_type}
- **Error message:** {error_message}
- **Summary:** {summary}

## Failing Test
The following test reproduces this bug.

**File:** `{test_file_path}`
**Test:** `{test_name}`

```python
{test_content}
```
{source_section}
## Your Task

Identify the minimal single-line fix that makes the failing test pass.

Rules:
- The test asserts correct behaviour — your fix must make the function return the expected value, not raise an exception.
- Fix only the bug. Do not refactor or touch unrelated code.
- Do not suggest changes to any test file.
- The fix must be a single-line replacement (current_line → fixed_line).

Return ONLY a JSON object with exactly these fields — no other text:

{{
  "root_cause": "<one sentence>",
  "fix_description": "<one sentence describing the change>",
  "file_to_edit": "<exact relative path from the repo root>",
  "line_to_edit": <1-indexed line number>,
  "current_line": "<exact current text of that line, including indentation>",
  "fixed_line": "<exact replacement text, including indentation>"
}}
"""


def build_tdd(
    incident_id: str,
    error_type: str,
    error_message: str,
    summary: str,
    test_file_path: str,
    test_name: str,
    iteration: int,
    prior_attempts: list[str],
    diagnosis: "Optional[BugDiagnosis]" = None,
    language: str = "python",
) -> str:
    """
    Build the implementation prompt for the claude-code CLI (TDD loop).

    This prompt is passed to `claude -p "..."` inside the cloned repo. The
    claude-code CLI runs the failing test, applies a fix, and runs the full
    suite. It must output a TESTS_PASSED or TESTS_FAILED sentinel so the
    agent can decide whether to commit or retry.

    When a validated BugDiagnosis is provided, the prompt tells the CLI
    exactly which file and line to change so it only needs to apply and verify.
    Without a diagnosis the CLI discovers the fix itself.

    Args:
        incident_id:    Helix incident ID (for traceability in commits/logs).
        error_type:     Exception class, e.g. "KeyError".
        error_message:  Exception message.
        summary:        Plain-English crash summary from the Crash Handler.
        test_file_path: Relative path to the failing test already written into
                        the repo, e.g. "tests/test_checkout.py".
        test_name:      Test function name.
        iteration:      Current attempt number (1-indexed).
        prior_attempts: Summaries from previous failed attempts, oldest first.
        diagnosis:      Pre-validated structured fix, or None to let the CLI
                        discover the fix from scratch.
        language:       Application language, e.g. "python", "javascript", "go".

    Returns:
        Prompt string ready to pass to `claude -p "..."`.
    """
    prior_section = ""
    if prior_attempts:
        prior_section = "\n## Previous Attempts (do not repeat these approaches)\n"
        for i, attempt in enumerate(prior_attempts, start=1):
            prior_section += f"\n### Attempt {i}\n{attempt}\n"

    if diagnosis:
        fix_section = (
            f"\n## Pre-Computed Fix (validated against the source file)\n"
            f"Apply this change exactly. Do not look for an alternative fix.\n\n"
            f"- **File:** `{diagnosis.file_to_edit}`\n"
            f"- **Line {diagnosis.line_to_edit} — replace:**\n\n"
            f"  ```\n"
            f"  - {diagnosis.current_line}\n"
            f"  + {diagnosis.fixed_line}\n"
            f"  ```\n\n"
            f"Root cause: {diagnosis.root_cause}\n"
        )
        fix_step = (
            "4. Apply the pre-computed fix above using the edit tool. "
            "Do not change any other code. Do not modify the test file."
        )
    else:
        fix_section = ""
        fix_step = (
            "4. Write the minimal code change that makes the test pass.\n"
            "   - The test asserts correct behaviour (e.g. a return value) — not that an\n"
            "     exception is raised. Your fix must make the function return the expected\n"
            "     value rather than crash.\n"
            "   - Fix only the bug — do not refactor, rename, or clean up unrelated code.\n"
            "   - Do not modify the test file.\n"
            "   - Do not add new dependencies."
        )

    hint_one, hint_all = _test_commands(language, test_file_path, test_name)

    discover_step = "" if diagnosis else (
        "\n3. Read the relevant source files to understand the bug.\n"
    )

    return f"""\
The repository is already cloned in the current working directory. Do NOT ask for files. Do NOT write a plan. Start immediately by running pytest on the test file. Take action now.

You are fixing a production bug for incident {incident_id} (attempt {iteration}/3).

## Bug Context
- Language:      {language}
- Error type:    {error_type}
- Error message: {error_message}
- Summary:       {summary}

## Failing Test
A test that reproduces this bug has already been written to:
  {test_file_path}

Test function: {test_name}
{prior_section}{fix_section}
## Your Task
Follow these steps exactly:

1. Discover the environment and install any missing dependencies.

   a. Read README.md (if it exists) for setup instructions.

   b. Identify the build system and test runner by checking for these files
      in order of priority:
        build.gradle / build.gradle.kts  → Gradle
        pom.xml                          → Maven
        package.json                     → npm / yarn / pnpm
        go.mod                           → go test
        Cargo.toml                       → cargo test
        pyproject.toml / setup.py /
        requirements.txt                 → pytest / unittest
        Makefile                         → check targets for "test"

   c. If the required build tool is not installed, install it now without
      asking. Use the appropriate method for the OS:
        - Java/Kotlin (Gradle or Maven): install via SDKMAN if available
          (`sdk install java`, `sdk install gradle`, `sdk install maven`),
          otherwise use the system package manager (apt-get / brew).
        - Node.js: install via nvm or system package manager.
        - Go / Rust / Python: use the system package manager or official
          installer scripts.

   d. Install project dependencies:
        Gradle  → ./gradlew dependencies  (use the wrapper if present)
        Maven   → mvn dependency:resolve -q
        npm     → npm install
        yarn    → yarn install
        pnpm    → pnpm install
        Go      → go mod download
        Rust    → cargo fetch
        Python  → pip install -r requirements.txt  (or pip install -e .[dev]
                  if pyproject.toml is present)

   Hint (based on the reported language "{language}"):
     single test : {hint_one}
     full suite  : {hint_all}
   These are hints only — if the actual build file points to a different
   tool (e.g. Gradle instead of Maven), use the correct tool.

2. Run the failing test to confirm it currently fails using the test runner
   you identified in step 1.
{discover_step}
{fix_step}

5. Run the full test suite to check for regressions.

6. Based on the results, output ONE of the following sentinel lines,
   followed by a short explanation:

   If all tests pass:
      TESTS_PASSED
      <one paragraph: what you changed and why>

   If tests still fail:
      TESTS_FAILED
      <one paragraph: what you tried and why it did not work>

Do not output anything else after the sentinel line and explanation.
"""



def _test_commands(language: str, test_file_path: str, test_name: str) -> tuple[str, str]:
    """
    Return hint commands (run_one, run_all) for the given language.

    These are passed to build_tdd() as hints only. The TDD prompt instructs
    the claude-code CLI to inspect the actual repo build files and override
    these hints when the real build system differs (e.g. Gradle instead of
    Maven for a Java repo).

    Args:
        language:       Application language, e.g. "python", "javascript".
        test_file_path: Relative path to the test file.
        test_name:      Test function/method name.

    Returns:
        A (run_one, run_all) tuple of shell command strings.
    """
    lang = language.lower()

    if lang in ("javascript", "typescript"):
        return (
            f'npx jest --testPathPattern "{test_file_path}" --testNamePattern "{test_name}" --verbose',
            "npx jest",
        )
    if lang == "ruby":
        return (
            f'bundle exec rspec "{test_file_path}" --example "{test_name}"',
            "bundle exec rspec",
        )
    if lang in ("java", "kotlin"):
        return (
            f'mvn test -Dtest="{test_name}" -q',
            "mvn test -q",
        )
    if lang == "go":
        return (
            f'go test ./... -run "^{test_name}$" -v',
            "go test ./...",
        )
    # Python (default)
    return (
        f"pytest {test_file_path}::{test_name} -v",
        "pytest",
    )
