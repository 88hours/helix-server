# Helix — Feature Reference

Complete reference for all features in the current release.

---

## Pipeline Overview

```
Rollbar / Sentry crash → Crash Handler → QA Agent → Dev Agent → PR + Notifications
```

Helix takes a production crash all the way to a ready-to-merge pull request without human intervention. The three agents are fully decoupled — they communicate only via events (Redis Pub/Sub or AWS EventBridge) and share state through Redis.

---

## Crash Handler Agent

**Triggers:** `POST /webhook/rollbar`, `POST /webhook/sentry`

### Webhook receiver
- Accepts Rollbar webhook payloads at `/webhook/rollbar` — verifies the access token embedded in the payload against `ROLLBAR_ACCESS_TOKEN`
- Accepts Sentry issue-alert webhooks at `/webhook/sentry` — verifies the HMAC-SHA256 signature in `sentry-hook-signature` against `SENTRY_WEBHOOK_SECRET`
- Returns `202 Accepted` with an `incident_id` immediately; processing continues asynchronously
- Returns `401 Unauthorized` for invalid tokens or signatures
- Signature verification is **always on** by default — set `HELIX_DEMO=true` to skip it for local testing without real credentials

### Crash analysis
- Normalises Rollbar and Sentry payloads into the same internal event format before LLM analysis; the prompt labels the source correctly ("Sentry event" or "Rollbar crash event")
- Produces a `CrashReport` with: `incident_id`, `source_item_id`, `source`, `severity`, `error_type`, `error_message`, `stack_trace`, `affected_component`, `affected_endpoint`, and a plain-English `summary`
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

## Audit Trail

Every significant action in the pipeline is recorded to a queryable `audit_events` table in Postgres.

### Recorded events

| `event_type` | `source` | `action` | Trigger |
|---|---|---|---|
| `webhook` | `sentry` | `received` | Sentry webhook arrives |
| `webhook` | `rollbar` | `received` | Rollbar webhook arrives |
| `agent_event` | agent name | event name | Any `publish()` call in `core/events.py` |
| `slack_action` | `slack` | `pr_approved` | User clicks Approve in Slack |
| `slack_action` | `slack` | `pr_rejected` | User clicks Reject in Slack |
| `github_op` | `github` | `pr_created` | `integrations/github.py` creates a PR |
| `github_op` | `github` | `pr_merged` | `integrations/github.py` merges a PR |

### Storage

- Postgres table `audit_events` — `id` (BIGSERIAL), `incident_id`, `project_id` (FK → projects), `event_type`, `source`, `action`, `status` (default `ok`), `details` (JSONB), `ts` (TIMESTAMPTZ)
- Indexed on `incident_id` and `(project_id, ts DESC)` for the two main query patterns

### API

- `GET /api/audit?incident_id=<id>` — returns up to 100 audit events for a given incident, newest first
- `GET /api/audit?project_id=<id>` — returns up to 100 audit events for a project

### Implementation

- `core/audit.py` — `record(event_type, source, action, *, incident_id, project_id, status, details)` — fire-and-forget; errors are swallowed and logged as WARNING so a DB failure never breaks the request path
- Hook points added in `core/events.py` (agent events), `integrations/github.py` (PR ops), and `agents/crash_handler/main.py` (webhooks + Slack actions)

### Dashboard

The `AuditTrail` component on the incident detail page shows a filterable timeline of audit events. Filter by actor kind (all / agent / user / system) or full-text search. Each row shows timestamp, actor, action, and expandable JSONB metadata.

---

## Dashboard

The static landing page is served at `GET /` and includes a **Sign in** CTA that routes visitors to `/app`. The React dashboard is served by the Crash Handler at `/app` and streams live agent activity via SSE.

### Incident list (`/app/incidents`)
- Polls `GET /api/incidents` every 10 seconds
- **Status filter** — multi-select dropdown covering all 9 statuses (`crash`, `analysing`, `testing`, `fixing`, `pr`, `approval`, `merged`, `duplicate`, `failed`); shows count per status
- Table view: incident ID, status badge, severity badge, error type, affected component, 4-bar mini pipeline, timestamp
- Click any row to open the incident detail page

### Incident detail (`/app/incidents/:id`)
- Opens an SSE connection to `GET /api/stream/:id` on mount
- **Pipeline tracker** — switchable between `horizontal` (card row with → separators) and `swimlane` (each agent in its own lane with L-bend connectors); layout controlled by the tweaks panel
- **Tool call timeline** — structured list of every external tool call made by agents: LLM completions, GitHub API calls, git clone, Claude Code TDD iterations
- **Agent activity log** — auto-scrolling live event log
- **Crash report** — error type, component, endpoint, language, source, stack trace (expandable)
- **QA result** — issue link, test file path, test content (expandable)
- **PR result** — PR link, branch, fix summary, files changed, iterations taken
- **Audit trail** — filterable timeline of all audit events for the incident

### Projects (`/app/projects`)
- A **project** is a GitHub repository plus all the credentials Helix needs to run the pipeline against it
- Create a project by pasting any GitHub URL (`https://github.com/owner/name`, SSH `git@github.com:owner/name.git`, or a plain `owner/name` slug) — the slug is normalised automatically
- Each project has a settings panel grouped into three sections:
  - **Core credentials** (required): `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `REDIS_URL`, and at least one of `SENTRY_WEBHOOK_SECRET` / `ROLLBAR_ACCESS_TOKEN`
  - **Slack notifications** (optional): `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APPROVAL_CHANNEL`
  - **Email notifications** (optional): `SENDGRID_API_KEY`, `SMTP_HOST`
- Secret values are returned as `***` after being saved — the UI shows an "Already set" indicator so users know a field is configured without exposing the value
- Typing a new value into a secret field replaces it; leaving it blank keeps the existing value
- A **Ready** badge appears on a project card once all required credentials are set
- Stored in Postgres (`projects` table) and per Auth0 user in Redis at `helix:user:{sub}:projects` (no TTL — permanent user data)
- API: `GET /api/projects`, `POST /api/projects`, `PUT /api/projects/{owner}/{name}/settings`, `DELETE /api/projects/{owner}/{name}`

### Repo configuration (`/app/repos`)
- Lists all repos the authenticated user has configured
- Add repo form: repository (`owner/name`), base branch, language
- Remove button per repo
- Calls `GET/POST/DELETE /api/repos` — changes are saved per user in Redis

### Live streaming architecture
- On connect, the SSE endpoint sends a `snapshot` event with current incident state so the UI renders immediately
- Subsequent `progress` events carry `UIProgressEvent` payloads (agent steps) and `ToolCallEvent` payloads (tool calls)
- Each agent publishes to `helix:ui:{incident_id}` via Redis Pub/Sub; the SSE endpoint uses a dedicated Redis client per connection
- Past events are persisted to Redis (`helix:ui:{id}:events`) and replayed on page load so the ToolTimeline and StreamPanel are not empty for completed incidents
- `status_changed` SSE events trigger a full re-fetch of the incident so QA and PR sections populate in real-time without a page reload

---

## Authentication

### Auth0 + GitHub login
- Auth is **optional** — if `AUTH0_DOMAIN` is not set, all API routes and the dashboard are accessible without login (demo / local-dev mode)
- When enabled, the dashboard requires an Auth0 JWT in `Authorization: Bearer` on all `/api/*` requests
- The SSE stream endpoint accepts a `?access_token=` query parameter as a fallback (EventSource cannot send headers)
- Tokens are validated using RS256 via JWKS fetched from `https://{domain}/.well-known/jwks.json` — no client secret required on the backend
- Auth0 handles GitHub OAuth so users log in with their GitHub account; no separate GitHub OAuth flow is needed

### Roles (current)
Single-user per deployment. Multi-tenant role-based access is planned for Phase 6.

### Frontend
- `Auth0Provider` wraps the app in `main.tsx` only when `VITE_AUTH0_DOMAIN` is set
- `AuthGuard` component redirects unauthenticated users to the Auth0 login page
- `TokenProviderBridge` registers the Auth0 token-getter with the API client so all `fetch` calls include the Bearer token automatically
- `NavUserChip` shows the user's GitHub avatar, name, and a sign-out button in the nav bar

---

## Repo Configuration

Users configure which GitHub repositories Helix monitors via the dashboard Repos page or the API directly.

### Data model (`RepoConfig`)
| Field | Type | Default | Description |
|---|---|---|---|
| `repo` | `string` | — | Repository in `owner/name` format, e.g. `acme/backend` |
| `base_branch` | `string` | `main` | Branch PRs are opened against |
| `language` | `string` | `python` | Primary language — used to select the test framework |
| `added_at` | `datetime` | now | When the repo was added |

### Storage
- Stored per Auth0 user in Redis at `helix:user:{sub}:repos` (no TTL — permanent user data)
- Multiple repos per user; order is preserved (insertion order)

### API
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/repos` | List calling user's repos |
| `POST` | `/api/repos` | Add a repo (`repo`, `base_branch`, `language` in JSON body) |
| `DELETE` | `/api/repos/{owner}/{name}` | Remove a repo |
| `GET` | `/api/me` | Return caller's identity (`sub`, `name`, `email`, `picture`) from JWT |

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

User configuration (no TTL — permanent):

| Key | Contents |
|---|---|
| `helix:user:{sub}:repos` | JSON list of `RepoConfig` for the Auth0 user |

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

Supported providers: `anthropic`, `openrouter`, `claude-code`, `opencode`, `ollama`.

All LLM calls are traced to **Langfuse** (and optionally LangSmith) via `core/llm.py`. Enable with `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`.

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

## GitHub App Integration

Helix uses a GitHub App to obtain per-installation access tokens rather than a single `GITHUB_TOKEN`. This allows Helix to operate on repos where a personal access token lacks write access.

- Per-project installation tokens, JWT flow, and token caching in Postgres (`core/github_app.py`)
- Token is injected into all Git push operations as `x-access-token:{token}` URL format
- `GITHUB_TOKEN` is still used as a fallback if no installation token is available

### GitHub page (`/github`)

- Shows all repos accessible via the authenticated GitHub App installation
- Displays Private/Public badge, default branch, and which Helix project monitors each repo
- Handles the post-install `?installation_id=` redirect from GitHub and saves the installation ID
- Manual ID entry field for cases where the redirect does not fire reliably

---

## Observability

### LangSmith tracing and evals

- Every LLM call in `core/llm.py` is traced with prompt, response, and token usage via LangSmith
- Eval suite covers Crash Handler (4 examples), QA Agent (2 examples), Dev Agent (3 examples)
- Evaluators are pure Python — no LLM-as-judge cost
- CI runs evals on every push to `main` and on PRs (`evals.yml`); fails if any agent scores below 0.8
- The eval step skips gracefully (exit 0) when `ANTHROPIC_API_KEY` or `LANGSMITH_API_KEY` is not set as a GitHub Actions secret

### OpenTelemetry tracing

- End-to-end distributed tracing across all four agents, disabled by default
- One parent span per incident per agent; one child span per LLM call
- Key attributes: `helix.agent`, `helix.incident_id`, `helix.provider`, `helix.model`, `helix.input_tokens`, `helix.output_tokens`
- Enabled via `OTEL_ENABLED=true`; exports via OTLP/gRPC to Datadog, Grafana Tempo, Jaeger, or any compatible backend
- Zero overhead when disabled — the OTel API's no-op tracer is used automatically

---

## Scope

Helix fixes **application-level bugs** only.

Out of scope for the current release:
- Infrastructure failures (network, database connectivity, memory pressure)
- Performance optimisation or refactoring
- Mobile crash reports
- Multi-tenant support (single-user per deployment; multi-org planned for Phase 6)
