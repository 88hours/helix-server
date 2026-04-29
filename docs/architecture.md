# Helix – Architecture Document

**Version:** 3.0
**Date:** April 2026
**Scope:** Phases 1–6 (Phases 1–5 complete; Phase 6 in progress)

---

## System Overview

Helix is an event-driven, multi-agent system. Each agent is an independent Python process with a single responsibility. Agents do not call each other directly — they communicate exclusively through Redis Streams (default) or AWS EventBridge. This decouples agents, allows each to scale independently, and makes the system easy to debug and extend.

```
Sentry / Rollbar
        │
        ▼
┌───────────────────┐
│  Crash Handler    │──── crash_analysed ────▶ Redis Streams
│  Agent            │
└───────────────────┘
                                │
                                ▼
                    ┌───────────────────┐
                    │   QA Agent        │──── test_case_generated ────▶ Redis Streams
                    └───────────────────┘
                                │
                                ▼
                    ┌───────────────────┐       fix_suggested ──▶ Redis Streams
                    │   Dev Agent       │──── pr_created ────────▶ Redis Streams
                    └───────────────────┘       fix_failed ────▶ Redis Streams
                                │
                                ▼
                    ┌───────────────────┐
                    │  Notifier Agent   │──── Slack + email notifications
                    └───────────────────┘
                                │
                                ▼
                         Human Approval
                         (via Slack)
                                │
                                ▼
                          PR Merged
```

---

## Agent Responsibilities

### Crash Handler Agent

| Property | Detail |
|---|---|
| Trigger | Sentry or Rollbar webhook (`POST /webhook/sentry`, `POST /webhook/rollbar`) |
| Model | claude-haiku-4-5 (Anthropic) |
| Input | Error message, stack trace, app state, screenshot (optional) |
| Output | Structured `CrashReport` |
| Emits | `helix:events:crash_analysed` |

**Responsibilities:**
- Receive and validate the incoming crash payload (HMAC-SHA256 for Sentry, access token for Rollbar)
- Normalise Sentry and Rollbar payloads into the same internal format
- Classify severity: `low`, `medium`, `high`, or `critical`
- Identify affected endpoint, component, and service
- Generate a plain-English summary of the failure
- Persist the crash report to Redis
- Publish `helix:events:crash_analysed` to Redis Streams
- Also hosts the React dashboard at `/app`, the REST API (`/api/*`), and Slack action handler (`/slack/actions`)

---

### QA Agent

| Property | Detail |
|---|---|
| Trigger | `helix:events:crash_analysed` |
| Model | claude-haiku-4-5 (Anthropic) |
| Input | Crash report from Redis |
| Output | GitHub Issue (created or updated) + TDD test case |
| Emits | `helix:events:test_case_generated` |

**Responsibilities:**
- Search GitHub Issues for similar open bugs (deduplication)
- Create a new issue or append to an existing one
- Clone the target repo and read relevant source files from the stack trace
- Generate a failing TDD test that asserts correct behaviour (not that the crash occurs)
- Validate the test (reject `pytest.raises` misuse, retry up to 2 times)
- Post the test case to the GitHub Issue
- Persist `QAResult` to Redis
- Publish `helix:events:test_case_generated`
- Supports Python, JavaScript/TypeScript, Ruby, Java/Kotlin, Go

---

### Dev Agent

| Property | Detail |
|---|---|
| Trigger | `helix:events:test_case_generated` |
| Model | claude-sonnet-4-6 via Claude Code CLI |
| Input | `QAResult` + `CrashReport` from Redis |
| Output | Code fix + passing test suite + pull request |
| Emits | `helix:events:fix_suggested`, `helix:events:pr_created`, `helix:events:fix_failed` |
| Max iterations | 3 |

**Responsibilities:**
- Fetch source files from GitHub and call the LLM for an initial fix suggestion; post to GitHub Issue
- Publish `helix:events:fix_suggested` (Notifier Agent sends Slack/email on this)
- Acquire per-repo Redis lock (`SET NX EX 600`) to prevent concurrent fixes on the same repo
- Clone the repo, create a branch `helix/fix/{incident_id[:8]}-{iteration}`
- Invoke the Claude Code CLI in the cloned repo: confirm test fails → write fix → run full suite
- Retry up to 3 iterations; each retry passes summaries of prior failed attempts to the CLI
- On success: commit, push, create PR, persist `PRResult`, publish `helix:events:pr_created`
- On failure after 3 iterations: post failure summary to GitHub Issue, publish `helix:events:fix_failed`
- Hard 8-minute timeout (`asyncio.wait_for`) — exceeded budget escalates the same as exhausted retries

---

### Notifier Agent

| Property | Detail |
|---|---|
| Trigger | `helix:events:fix_suggested`, `helix:events:fix_failed` |
| Model | None (no LLM calls) |
| Input | Event payload + `CrashReport` from Redis |
| Output | Slack messages, emails |

**Responsibilities:**
- Run two concurrent subscriber loops (one per event channel)
- On `fix_suggested`: send Slack message + email with issue link and error context
- On `fix_failed`: send escalation Slack message + email with attempt summaries
- Skip gracefully (WARNING log) if Slack or email credentials are not configured
- Supports SendGrid (preferred) or SMTP fallback for email

---

## Event Schema

All events are published to Redis Streams (default) or AWS EventBridge. Each event is a JSON object serialised into the stream. The EventBridge envelope wraps the same payload under `detail`.

### crash_analysed (`helix:events:crash_analysed`)

```json
{
  "incident_id": "uuid",
  "severity": "critical | high | medium | low",
  "error_type": "string",
  "error_message": "string",
  "stack_trace": "string",
  "affected_component": "string",
  "affected_endpoint": "string",
  "summary": "string",
  "source": "sentry | rollbar",
  "source_item_id": "string"
}
```

### test_case_generated (`helix:events:test_case_generated`)

```json
{
  "incident_id": "uuid",
  "ticket_id": "string",
  "ticket_url": "string",
  "ticket_action": "created | updated",
  "test_case": {
    "file_path": "string",
    "test_name": "string",
    "content": "string",
    "format": "pytest | jest | rspec | junit"
  },
  "relevant_files": ["string"]
}
```

### fix_suggested (`helix:events:fix_suggested`)

```json
{
  "incident_id": "uuid",
  "issue_url": "string",
  "fix_summary": "string"
}
```

### pr_created (`helix:events:pr_created`)

```json
{
  "incident_id": "uuid",
  "pr_url": "string",
  "pr_number": "integer",
  "branch_name": "string",
  "iterations_taken": "integer",
  "files_changed": ["string"],
  "fix_summary": "string"
}
```

### fix_failed (`helix:events:fix_failed`)

```json
{
  "incident_id": "uuid",
  "incident_id": "uuid",
  "attempts": "integer",
  "attempt_summaries": ["string"],
  "crash_summary": "string"
}
```

---

## State Management

Redis is the shared state store. Agents read and write state keyed by `incident_id`.

### Key Structure

| Key | Type | Content |
|---|---|---|
| `helix:incident:{id}:crash_report` | String (JSON) | Serialised `CrashReport` |
| `helix:incident:{id}:qa_result` | String (JSON) | Serialised `QAResult` (test case, ticket) |
| `helix:incident:{id}:pr` | String (JSON) | Serialised `PRResult` (PR URL, branch, fix summary) |
| `helix:incident:{id}:status` | String | Current pipeline stage |
| `helix:incident:{id}:iterations` | String (int) | Dev Agent retry count |
| `helix:repo_lock:{repo}` | String | Dev Agent per-repo mutex (`SET NX EX 600`) |
| `helix:ui:{id}` | Pub/Sub channel | Ephemeral dashboard progress events |
| `helix:ui:{id}:events` | List | Persisted SSE events for replay on page load |
| `helix:user:{sub}:repos` | String (JSON) | User repo config (no TTL) |
| `helix:user:{sub}:projects` | String (JSON) | User project config (no TTL) |

TTL: 7 days per incident key. User config keys have no TTL.

### Postgres tables

| Table | Purpose |
|---|---|
| `users` | Auth0 user profiles (`sub` as PK) |
| `projects` | Per-user projects (`project_id` UUID, `owner_sub` FK) |
| `project_settings` | Per-project credentials — Sentry/Rollbar secrets, Slack, email, `agent_overrides` JSON |
| `github_installations` | GitHub App installation tokens, cached with expiry |
| `user_settings` | Account-level LLM keys — `anthropic_api_key`, `openrouter_api_key`, `ollama_base_url` |

Key resolution order for LLM API keys: project-level override → user-level settings → global env var.

---

## Redis Options

### Redis Cloud (Recommended)

Redis Cloud is a fully managed Redis service hosted by Redis Ltd. It works with any hosting option above — Railway, Lambda, ECS, or VPS — as an external connection.

| Aspect | Detail |
|---|---|
| Provider | Redis Cloud (redis.io/cloud) |
| Free tier | 30 MB, single database — sufficient for MVP |
| Paid tier | From ~$7/month for 100 MB with persistence |
| Connection | TLS-secured endpoint, works from any network |
| Persistence | Optional RDB snapshots and AOF |

**Why Redis Cloud over self-hosted Redis:**
- Zero ops — no Redis process to manage or restart
- Works out of the box with Railway and Lambda (no VPC peering required)
- Free tier covers MVP incident volumes comfortably
- Upgrade path is seamless (no migration, just increase plan size)

---

### Redis Streams as Event Bus (default)

The default event backend is Redis Streams (`XADD`/`XREAD`). Messages persist until consumed and survive agent restarts. Switch backends with `HELIX_EVENT_BACKEND=eventbridge`.

Within Redis, the transport mode is configurable in `config.yaml`:

| Mode | Behaviour |
|---|---|
| `streams` | Redis Streams — messages persist across restarts (default) |
| `pubsub` | Redis Pub/Sub — fire-and-forget, messages lost if no subscriber is running |

#### Channel names

```
helix:events:crash_analysed
helix:events:test_case_generated
helix:events:fix_suggested
helix:events:pr_created
helix:events:fix_failed
```

#### Redis Streams vs EventBridge

| | Redis Streams | AWS EventBridge |
|---|---|---|
| Setup complexity | None — same Redis instance | Medium — AWS account, rules, targets |
| Cost | Included in Redis plan | $1 per million events |
| Durability | Yes — persists until consumed | At-least-once with retry |
| Message replay | Yes | No |
| Dead letter handling | Manual | Built-in DLQ support |
| Audit trail | None built-in | Full event history in CloudWatch |
| Best for | Railway / non-AWS deployments (default) | AWS-native deployments |

**Recommendation:** Use **Redis Streams** (the default) for all Railway and Docker deployments. Switch to **EventBridge** only when deploying on AWS and the built-in audit trail or DLQ behaviour is specifically needed.

---

## Source Code Access

The Dev Agent and QA Agent need read access to the target application's source code to reproduce bugs and write fixes. For MVP, this is achieved by cloning the target repository at runtime using a scoped GitHub token. The relevant files are identified from the stack trace and passed to the agent as context.

---

## Slack Integration

The Code Quality Agent sends notifications to a designated Slack channel using the Slack Web API. The notification includes:

- Incident ID and severity
- One-line summary of the bug
- Link to the PR
- Quality report highlights
- Approve / Request Changes buttons (linked to a webhook endpoint)

The approval webhook triggers PR merge via the GitHub API.

---

## Repository Structure

```
helix/
├── agents/
│   ├── crash_handler/
│   │   ├── agent.py           # LLM analysis → CrashReport
│   │   ├── prompts.py         # System + user prompt templates
│   │   ├── main.py            # FastAPI: webhooks, dashboard API, Slack actions
│   │   └── railway.json
│   ├── qa/
│   │   ├── agent.py           # GitHub Issues dedup, repo clone, test generation + validation
│   │   ├── prompts.py
│   │   ├── main.py            # Subscriber loop
│   │   └── railway.json
│   ├── dev/
│   │   ├── agent.py           # Fix suggestion → GitHub comment → TDD loop → PR or escalate
│   │   ├── prompts.py         # build_suggestion() and build_tdd()
│   │   ├── main.py            # Subscriber loop
│   │   └── railway.json
│   └── notifier/
│       ├── agent.py           # Slack + email for fix suggestions and escalations
│       ├── main.py            # Two concurrent subscriber loops
│       └── railway.json
├── core/
│   ├── config.py              # Typed config loaders for all agents; AgentConfig.base_url for Ollama
│   ├── events.py              # Redis Streams / Pub/Sub / EventBridge helpers
│   ├── state.py               # Redis read/write helpers, keyed by incident_id
│   ├── models.py              # Pydantic models: CrashReport, QAResult, PRResult, RepoConfig, Project, AgentOverride
│   ├── llm.py                 # Routes to Anthropic SDK, OpenRouter, Ollama, or Claude Code CLI; LangSmith + OTel instrumentation
│   ├── telemetry.py           # OpenTelemetry setup
│   ├── permissions.py         # Per-agent tool access control
│   ├── ui_events.py           # Dashboard event publishing (Redis Pub/Sub + persistence)
│   ├── auth.py                # Auth0 JWT validation (RS256 via JWKS)
│   ├── utils.py               # extract_json() — parses structured JSON from LLM output
│   ├── preflight.py           # Startup env-var checks — raises on missing LLM key, warns on optional vars
│   ├── db.py                  # Async Postgres helpers — projects, github_installations, user_settings tables
│   └── github_app.py          # GitHub App JWT generation, installation access token fetch/cache
├── integrations/
│   ├── sentry.py              # HMAC-SHA256 verification + payload parsing
│   ├── rollbar.py             # Access token verification + payload parsing
│   ├── github.py              # Git CLI wrappers + GitHub REST API
│   ├── slack.py               # Slack Web API — notifications and approval buttons
│   └── email.py               # SendGrid (preferred) or SMTP fallback
├── dashboard/                 # React + TypeScript + Tailwind
│   └── src/
│       ├── App.tsx
│       ├── authFetch.ts       # Authenticated fetch wrapper (Bearer token injection)
│       ├── constants.ts       # Shared types and API fetch helpers
│       ├── main.tsx
│       ├── pages/             # IncidentsPage, IncidentDetailPage, ProjectsPage, AgentsPage, SettingsPage, GitHubPage, LoginPage
│       └── components/        # Pipeline, ActivityRail, ToolCalls, Header, Walkthrough, primitives, AuthGuard
├── evals/                     # LangSmith eval suite (datasets, evaluators, runner)
├── config.yaml                # Source of truth for models, Redis, permissions, LangSmith
├── index.html                 # Landing page
├── docs/
│   ├── architecture.md        # This file
│   ├── PRD.md                 # Product requirements
│   ├── features.md            # Feature reference
│   ├── SAAS.md                # SaaS architecture — tenant isolation, scaling, delivery phases
│   ├── TECHDECISIONS.md       # Technical decision log
│   └── plans/                 # Implementation plans for in-progress work
├── scripts/
├── CLAUDE.md
└── pyproject.toml
```

---

## Data Flow Summary

```
1. Sentry / Rollbar webhook → Crash Handler Agent
   - Verifies signature / access token
   - Parses and classifies crash (LLM)
   - Writes crash_report to Redis
   - Publishes helix:events:crash_analysed to Redis Streams

2. Redis Streams → QA Agent
   - Reads crash_report from Redis
   - Searches GitHub Issues for duplicates
   - Creates or updates issue
   - Clones repo, reads source files
   - Generates and validates failing TDD test (up to 3 LLM attempts)
   - Posts test case to GitHub Issue
   - Writes qa_result to Redis
   - Publishes helix:events:test_case_generated

3. Redis Streams → Dev Agent
   - Reads qa_result + crash_report from Redis
   - Fetches source files from GitHub, generates fix suggestion (LLM)
   - Posts fix suggestion to GitHub Issue
   - Publishes helix:events:fix_suggested
   - Acquires per-repo Redis lock
   - Clones repo, creates branch, writes test, invokes Claude Code CLI
   - CLI: confirm test fails → write fix → run full suite
   - Retries up to 3 iterations
   - On success: commit + push, create PR, write pr to Redis, publish helix:events:pr_created
   - On failure: post failure summary to issue, publish helix:events:fix_failed

4. Redis Streams → Notifier Agent (two concurrent loops)
   - On fix_suggested: Slack message + email with issue link
   - On fix_failed: escalation Slack message + email with attempt summaries

5. Slack → Human Reviewer
   - Reviewer clicks Approve button
   - Slack action webhook → crash_handler → GitHub API → PR merged
```

---

## Hosting Options

Each agent runs as an independent process. The table below compares three viable hosting strategies for MVP.

### Option A – AWS Lambda (Recommended for MVP)

Each agent is deployed as a Lambda function triggered by an EventBridge rule.

| Aspect | Detail |
|---|---|
| Agent runtime | AWS Lambda (Python, up to 15 min timeout) |
| Event routing | EventBridge → Lambda triggers per agent |
| State | ElastiCache for Redis (Serverless) |
| Sentry webhook receiver | API Gateway → Lambda |
| Slack webhook receiver | API Gateway → Lambda |
| Repo cloning | Lambda with an EFS mount (ephemeral `/tmp` for small repos) |

**Pros:**
- No servers to manage
- Pay per invocation — near-zero cost at low volume
- Native EventBridge integration
- Scales automatically with incident volume

**Cons:**
- 15-minute Lambda timeout may be tight for the Dev Agent on large codebases
- Cold starts add latency on the first invocation (mitigated with provisioned concurrency on Dev Agent)
- EFS mount required if repos exceed the 512 MB `/tmp` limit

---

### Option B – AWS ECS (Fargate)

Each agent runs as a long-lived Fargate task, woken by EventBridge.

| Aspect | Detail |
|---|---|
| Agent runtime | ECS Fargate task (Python container) |
| Event routing | EventBridge → ECS task trigger via EventBridge Pipes |
| State | ElastiCache for Redis |
| Sentry webhook receiver | Application Load Balancer → ECS service |
| Slack webhook receiver | Application Load Balancer → ECS service |
| Repo cloning | Container-local ephemeral storage |

**Pros:**
- No timeout constraints — suitable for long-running Dev Agent iterations
- Full control over container environment and dependencies
- Predictable latency, no cold starts

**Cons:**
- Higher baseline cost than Lambda (billed per vCPU/memory second)
- More infrastructure to configure (task definitions, ECR, ALB)
- Overkill for MVP incident volumes

---

### Option C – Railway (Recommended for Fastest MVP Launch)

Each agent is deployed as a Railway service (Python container). Railway handles builds, deploys, and networking with minimal configuration.

| Aspect | Detail |
|---|---|
| Agent runtime | Railway services (Python containers, one per agent) |
| Event routing | EventBridge (via AWS SDK from Railway) or Redis Pub/Sub (see below) |
| State | Redis Cloud (see below) |
| Sentry webhook receiver | Railway service with public URL |
| Slack webhook receiver | Railway service with public URL |
| Repo cloning | Container-local ephemeral storage |

**Pros:**
- Deploy from GitHub in minutes — no AWS account required for compute
- Automatic HTTPS, public URLs, and environment variable management built in
- Per-service logs and metrics in the Railway dashboard
- Free tier available; paid plans start at ~$5/month per service
- No cold starts, no timeout constraints on agent execution
- Works seamlessly with Redis Cloud as an external add-on

**Cons:**
- Less control than ECS/Lambda for fine-grained IAM and VPC networking
- Not ideal if the rest of the stack is already deep in AWS (adds a cross-cloud dependency)
- Persistent disk storage is limited — large repo clones should use ephemeral temp dirs

---

### Option D – Single Server / VPS (Simplest for Early Testing)

All agents run as Python processes on a single server (e.g. EC2 t3.medium or Hetzner VPS).

| Aspect | Detail |
|---|---|
| Agent runtime | Python processes (systemd or supervisor) |
| Event routing | EventBridge or Redis Pub/Sub |
| State | Redis (self-hosted on same server or Redis Cloud) |
| Sentry webhook receiver | FastAPI app on the server |
| Slack webhook receiver | FastAPI app on the server |
| Repo cloning | Local disk |

**Pros:**
- Cheapest option (~$10–20/month)
- Simplest to debug locally
- No cold starts, no container overhead

**Cons:**
- Single point of failure
- Manual scaling if incident volume grows
- Not production-grade without additional work

---

### Recommendation

| Stage | Recommended option |
|---|---|
| Local development and early testing | Option D (single server or local) |
| MVP launch | Option C (Railway) — fastest to ship, minimal ops |
| AWS-native or scale needs | Option A (Lambda) or Option B (ECS Fargate) |

Start with **Option C (Railway)** for MVP. It is the fastest path from code to a running system. Migrate to Lambda or ECS if AWS-native tooling becomes a priority or incident volume demands it.

---

## Key Design Decisions

**Why Redis Streams over direct agent calls?**
Agents are fully decoupled. A failed agent does not cascade. Each agent can be redeployed independently. Streams persist messages across restarts, so no events are lost if an agent is temporarily down.

**Why Redis for incident state?**
Agents are stateless processes. Redis provides fast, shared, ephemeral storage keyed by incident ID. No database migrations, no schema changes — just key-value reads and writes.

**Why Postgres for project config?**
Project credentials, GitHub App installation tokens, and per-project settings are long-lived and structured. Redis is unsuitable for relational queries (e.g. look up a project by GitHub repo slug). Postgres provides the right durability and query model for this data.

**Why clone the repo at runtime?**
Avoids the complexity of a persistent code sync mechanism. The target repo is cloned once per incident into a temp directory by the QA and Dev agents, then discarded.

**Why the Claude Code CLI for the Dev Agent?**
The Dev Agent needs to read, understand, and modify a full codebase — not just a few pasted snippets. The Claude Code CLI runs inside the cloned repo directory with full file access and tool use (read, edit, run tests). This is significantly more capable than passing code snippets to the API.

**Why separate models per agent?**
Crash Handler and QA are structured analysis and pattern-matching tasks — claude-haiku-4-5 is fast and cheap. The Dev Agent requires deep reasoning over a full codebase — claude-sonnet-4-6 via the Claude Code CLI. This routing is centralised in `core/llm.py`.
