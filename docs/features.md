# Helix — Feature Reference

Complete reference for all features in the current release.

---

## Pipeline Overview

```
Rollbar crash → Crash Handler → QA Agent → Dev Agent → PR + Notifications
```

Helix takes a production crash all the way to a ready-to-merge pull request without human intervention. The four agents are fully decoupled — they communicate only via events (Redis Pub/Sub or AWS EventBridge) and share state through Redis.

---

## Crash Handler Agent

**Trigger:** `POST /webhook/rollbar`

### Webhook receiver
- Accepts Rollbar webhook payloads over HTTP POST at `/webhook/rollbar`
- Verifies the Rollbar access token on every request (checked against `ROLLBAR_ACCESS_TOKEN`)
- Returns `202 Accepted` with an `incident_id` immediately; processing continues asynchronously
- Returns `400 Bad Request` for invalid or missing tokens

### Crash analysis
- Passes the raw Rollbar payload to the LLM for structured extraction
- Produces a `CrashReport` with: `incident_id`, `rollbar_item_id`, `severity`, `error_type`, `error_message`, `stack_trace`, `affected_component`, `affected_endpoint`, and a plain-English `summary`
- Classifies severity as `low`, `medium`, `high`, or `critical`

### State and events
- Persists the `CrashReport` to Redis under `helix:incident:{id}:crash_report`
- Sets incident status to `crash_analysed` in Redis
- Publishes `helix:events:crash_analysed` to trigger the QA Agent

### Health check
- `GET /healthz` returns `200 OK` — used by Docker Compose and load balancers

---

## QA Agent

**Trigger:** `helix:events:crash_analysed`

### GitHub Issue management
- Searches open GitHub Issues for an existing ticket with the same error title
- If found: adds a re-detection comment to the existing issue, records `ticket_action: updated`
- If not found: creates a new issue with the crash summary, stack trace, and severity label; records `ticket_action: created`
- Labels new issues with `bug` and `helix`

### Repository analysis
- Clones the target repository to a temporary directory
- Parses the stack trace to extract relevant file paths
- Filters out stdlib and `site-packages` paths — only application code is read
- Reads up to 8 source files, capped at 4,000 characters each to keep the prompt manageable
- Most recent stack frame is read first (closest to the error)

### Test case generation
- Calls the LLM to generate a minimal failing pytest test that asserts the **correct expected behaviour** of the affected function — not that an exception is raised
- Test is designed to fail on the buggy code and pass once the fix is applied
- The generated test targets the specific function or code path from the stack trace

### Test validation and retry
- Checks the generated test for the most common mistake: using `pytest.raises(<CrashExceptionType>)`, which would pass on the buggy code and prevent the Dev Agent from ever applying a fix
- If the test fails validation, appends a `rejection_note` to the prompt and retries the LLM call
- Retries up to 2 times (3 total LLM calls) before proceeding with the best available output

### GitHub comment
- Posts the generated test case as a formatted code block on the GitHub Issue
- Marks the incident as in-progress: `Helix is now running this test and attempting a fix`

### State and events
- Persists the `QAResult` (test case, ticket details, relevant files) to Redis
- Sets incident status to `test_case_generated`
- Publishes `helix:events:test_case_generated` to trigger the Dev Agent

---

## Dev Agent

**Trigger:** `helix:events:test_case_generated`

### Fix suggestion (LLM API call)
- Fetches relevant source files from the GitHub Contents API (no full clone at this stage)
- Calls the LLM to produce a minimal fix suggestion with:
  - Root cause in one sentence
  - BEFORE and AFTER code blocks (AFTER must include the defensive guard — it cannot be identical to BEFORE)
  - Explanation of why the change makes the test pass
- Posts the fix suggestion as a formatted comment on the GitHub Issue for the engineering team to review immediately

### Notification delegation
- Publishes `helix:events:fix_suggested` with the issue URL after posting the GitHub comment
- The Notifier Agent receives this event and sends Slack and email notifications — the Dev Agent has no direct Slack or email code

### TDD loop
- Clones the target repository to a temporary directory
- Creates a new branch named `helix/fix/{incident_id[:8]}-{iteration}`
- Writes the failing test file (from the QA Agent's `QAResult`) into the cloned repo
- Invokes the Claude Code CLI (`claude -p "<prompt>"`) inside the cloned repo directory
- The CLI follows these steps:
  1. Runs the failing test to confirm the bug is real (`pytest {test_file}::{test_name} -v`)
  2. Reads the relevant source files to understand the root cause
  3. Writes the minimum code change to make the test pass
  4. Runs the full test suite to check for regressions (`pytest`)
  5. Outputs a `TESTS_PASSED` or `TESTS_FAILED` sentinel followed by a short explanation

### Retry logic
- Retries up to 3 total iterations if the CLI reports `TESTS_FAILED`
- Each retry gets a new branch and includes summaries of previous failed attempts so the CLI avoids repeating the same approach
- The fix suggestion (from the LLM API call) is passed as a hint on the first iteration only, labelled "hint only — may be incomplete or wrong"

### Pull request creation
- On `TESTS_PASSED`: commits all changes and pushes the branch
- Creates a GitHub PR with:
  - Title: `[Helix] Fix {ErrorType} in {affected_component}`
  - Body: fix summary, incident ID, error details, link to the GitHub Issue, test added, number of iterations taken
- Persists the `PRResult` to Redis
- Publishes `helix:events:pr_created`

### Escalation
- If all 3 iterations are exhausted, posts a failure summary to the GitHub Issue listing what was tried in each attempt
- Publishes `helix:events:fix_failed` with the full attempt context
- The Notifier Agent receives this event and sends escalation alerts via Slack and email
- The failing test remains in the repository — engineers can use it to reproduce and investigate manually

---

## Notifier Agent

**Triggers:** `helix:events:fix_suggested`, `helix:events:fix_failed`

The Notifier Agent runs two concurrent subscriber loops — one for each event channel.

### Fix suggested notifications
- Triggered by `fix_suggested` events published by the Dev Agent
- Reads the `CrashReport` from Redis to populate error context in the message
- Sends a Slack message to the configured approval channel with: error type/message, affected component, and a link to the GitHub Issue
- Sends an email to configured recipients with the same content

### Escalation notifications
- Triggered by `fix_failed` events published by the Dev Agent
- Sends a Slack escalation message with: incident ID, crash summary, number of attempts made, and a summary of what was tried
- Sends an escalation email with the same context

### Optional configuration
- Slack notifications are skipped (with a WARNING log) if `SLACK_BOT_TOKEN` or `SLACK_APPROVAL_CHANNEL` is not set
- Email via SendGrid is used if `SENDGRID_API_KEY` is set
- Email falls back to SMTP if `SMTP_HOST` is set and SendGrid is not configured
- Email is skipped (with a WARNING log) if neither `EMAIL_FROM` nor `EMAIL_TO` is set, or if no backend is configured
- The pipeline continues in all cases — missing notification config does not stop incident handling

---

## Event System

### Channels

| Channel | Published by | Consumed by |
|---|---|---|
| `helix:events:crash_analysed` | Crash Handler | QA Agent |
| `helix:events:test_case_generated` | QA Agent | Dev Agent |
| `helix:events:fix_suggested` | Dev Agent | Notifier Agent |
| `helix:events:pr_created` | Dev Agent | — |
| `helix:events:fix_failed` | Dev Agent | Notifier Agent |

### Backends

| Backend | When to use |
|---|---|
| `redis` | Local dev, Railway, any non-AWS deployment (default) |
| `eventbridge` | AWS Lambda or ECS deployments |

Switch backends with `HELIX_EVENT_BACKEND=eventbridge`. EventBridge uses the same channel names as `detail-type` on the `helix-mvp` bus.

---

## State Management

All incident state lives in Redis, namespaced by `incident_id` with a 7-day TTL:

| Key | Contents |
|---|---|
| `helix:incident:{id}:crash_report` | Serialised `CrashReport` |
| `helix:incident:{id}:qa_result` | Serialised `QAResult` (test case, ticket) |
| `helix:incident:{id}:pr` | Serialised `PRResult` (PR URL, branch, fix summary) |
| `helix:incident:{id}:status` | Current pipeline status string |
| `helix:incident:{id}:iterations` | Number of Dev Agent fix attempts so far |

---

## LLM Routing

| Agent | Default provider | Default model | Notes |
|---|---|---|---|
| Crash Handler | `anthropic` | `claude-haiku-4-5` | Fast structured extraction |
| QA Agent | `anthropic` | `claude-haiku-4-5` | Pattern-matching test generation |
| Dev Agent | `claude-code` | `claude-sonnet-4-6` | Full repo access via CLI subprocess |

Override any agent's provider or model at runtime:

```bash
HELIX_DEV_PROVIDER=anthropic
HELIX_DEV_MODEL=claude-opus-4-6
```

Supported providers: `anthropic`, `openrouter`, `claude-code`.

---

## Deduplication

- The QA Agent searches open GitHub Issues before creating a new one
- Match is based on the issue title: `[Helix] {ErrorType}: {error_message[:120]}`
- If a matching issue is found, the new crash data is appended as a comment and the incident is marked `updated` rather than creating a duplicate

---

## Deployment

### Docker Compose (local)

```bash
# With a local Redis container
docker compose --profile local up --build

# With an external Redis (set REDIS_URL in .env first)
docker compose up --build
```

Redis is behind the `local` profile — it is optional when `REDIS_URL` points to an external instance (Redis Cloud, AWS ElastiCache, etc.).

### Railway (recommended for MVP)

One Railway service per agent + Redis Cloud. Each agent reads `REDIS_URL` from environment variables.

### AWS

Lambda per agent + EventBridge (set `HELIX_EVENT_BACKEND=eventbridge`) + ElastiCache.

---

## Observability

- All agents use Python's standard `logging` module with structured `extra` fields
- Every log line that touches an incident includes `incident_id` for end-to-end correlation
- Log levels: `INFO` for major state transitions, `DEBUG` for intermediate steps, `WARNING` for skipped notifications or retries
- `incident_id` is returned in the `202 Accepted` response from the webhook endpoint for external tracing

---

## Scope

Helix fixes **application-level bugs** only.

Out of scope for the current release:
- Infrastructure failures (network, database connectivity, memory pressure)
- Performance optimisation or refactoring
- Mobile crash reports
- Multi-tenant support
- Human approval workflow (Slack approve/reject buttons)
