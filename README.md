[![CircleCI](https://dl.circleci.com/status-badge/img/gh/88hours/helix/tree/main.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/88hours/helix/tree/main)
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/88hours/helix)
[![Website](https://img.shields.io/badge/website-live-brightgreen)](https://helix-production-3b95.up.railway.app/)
[![codecov](https://codecov.io/github/88hours/helix-cloud/branch/main/graph/badge.svg?token=KSOHW3E365)](https://codecov.io/github/88hours/helix-cloud)
# Helix

Helix is an autonomous incident response platform. It takes a production crash from Sentry or Rollbar all the way to a ready-to-merge pull request in under 10 minutes — no human involvement required until the PR review.

## How it works

```
Sentry / Rollbar crash → Crash Handler → QA Agent → Dev Agent → PR + Notifications
                                                                        ↓
                                                              Human Approval (Slack)
```

1. **Crash Handler** — receives Sentry or Rollbar webhooks, classifies severity, and produces a structured crash report
2. **QA Agent** — deduplicates against open GitHub Issues, generates a TDD test that asserts the correct behaviour (not that the crash occurs), validates the test and retries if needed. Supports Python, JavaScript/TypeScript, Ruby, and Java/Kotlin.
3. **Dev Agent** — generates a fix suggestion and posts it to the GitHub Issue, then runs a full TDD loop: clones the repo, runs the failing test, writes the minimum fix, verifies the full suite; retries up to 3 times before escalating
4. **Notifier Agent** — handles all outbound Slack and email notifications: fix suggestions, PR links, Slack Approve/Reject buttons for human approval, and escalation alerts when the Dev Agent exhausts retries

Agents communicate via Redis Streams (or AWS EventBridge). Shared state lives in Redis, keyed by `incident_id`.

## Project structure

```
agents/
  crash_handler/       FastAPI webhook server — receives Sentry/Rollbar events, hosts the dashboard API
    agent.py           Core logic: LLM analysis → CrashReport
    prompts.py         System + user prompt templates
    main.py            GET / (landing page), POST /webhook/sentry, POST /webhook/rollbar, POST /slack/actions
                       GET /api/incidents, GET /api/incidents/{id}, GET /api/stream/{id} (SSE)
                       GET/POST/DELETE /api/repos — per-user repo configuration
                       GET/POST /api/projects, PUT /api/projects/{owner}/{name}/settings,
                       DELETE /api/projects/{owner}/{name} — per-project credential settings
                       GET /api/me — caller identity from JWT
                       GET /app/* (serves the React dashboard)
    railway.json       Railway service config for this agent
  qa/                  Subscribes to crash_analysed
    agent.py           GitHub Issues deduplication, repo clone, LLM test generation + validation
    prompts.py         Correct-behaviour test prompt + rejection_note for retries
    main.py            Entry point: subscriber loop
    railway.json       Railway service config for this agent
  dev/                 Subscribes to test_case_generated
    agent.py           LLM fix suggestion → GitHub comment → TDD loop → PR or escalate
    prompts.py         build_suggestion() for API call; build_tdd() for claude-code CLI
    main.py            Entry point: subscriber loop
    railway.json       Railway service config for this agent
  notifier/            Subscribes to fix_suggested and fix_failed
    agent.py           Slack + email for fix suggestions, PR approvals, and escalations
    main.py            Entry point: two concurrent subscriber loops
    railway.json       Railway service config for this agent
core/
  config.py            Typed config loaders for all agents and integrations
  events.py            Redis Streams / Pub/Sub / EventBridge publish and subscribe helpers
  state.py             Redis read/write helpers, keyed by incident_id (incidents + user repo/project configs)
  models.py            Pydantic models shared across all agents (CrashReport, QAResult, PRResult, RepoConfig, Project, ProjectSettings)
  llm.py               Routes to Anthropic SDK, OpenRouter, or Claude Code CLI; instruments every call with LangSmith tracing and OTel spans
  telemetry.py         OpenTelemetry setup — call setup_tracing() once at startup; no-op when OTEL_ENABLED is not true
  permissions.py       Per-agent tool access control — declare and enforce at runtime
  ui_events.py         Dashboard event publishing — agent progress + tool call events persisted to Redis + forwarded via Pub/Sub
  auth.py              Auth0 JWT validation (RS256 via JWKS) — optional, falls back to demo user
  utils.py             extract_json() — parses structured JSON from LLM output
  db.py                Async Postgres helpers — projects, github_installations, per-project settings tables
  github_app.py        GitHub App JWT generation, installation access token fetch/cache, repo listing
integrations/
  sentry.py            HMAC-SHA256 signature verification + Sentry webhook payload parsing
  rollbar.py           Access token verification + Rollbar webhook payload parsing
  github.py            Git CLI wrappers (clone, branch, commit, push) + GitHub REST API
  jira.py              JIRA REST API v3 — create and update issues
  slack.py             Slack Web API — notifications, approval buttons, and escalation alerts
  email.py             SendGrid API (preferred) or SMTP fallback
dashboard/             React + TypeScript + Tailwind — streaming incident dashboard
  src/
    App.tsx            Root app with React Router (base: /app/) — Incidents + Projects + Repos nav
    api.ts             fetch wrappers, EventSource subscription, Auth0 token injection
    main.tsx           Entry point — wraps app in Auth0Provider when VITE_AUTH0_DOMAIN is set
    pages/
      IncidentList.tsx   Polls /api/incidents — table of all incidents, newest first
      IncidentDetail.tsx Opens SSE stream — pipeline progress, tool calls, live log, crash/QA/PR details
      Projects.tsx       Project management — create projects, configure per-project credentials (API keys, tokens)
      Repos.tsx          Repo configuration — add / remove repos per user
    components/
      PipelineProgress.tsx    4-step pipeline tracker with checkmarks
      StreamPanel.tsx          Auto-scrolling live agent activity log
      ToolTimeline.tsx         Live tool call log — LLM, GitHub, Git, Claude Code calls with status
      StatusBadge.tsx          Pill badge for pipeline status
      SeverityBadge.tsx        Pill badge for crash severity
      AuthGuard.tsx            Redirects unauthenticated users to Auth0 login
      NavUserChip.tsx          Avatar + name + sign-out button in nav bar
      TokenProviderBridge.tsx  Registers Auth0 token-getter with the API client
  .env.example         Frontend env var template (VITE_AUTH0_DOMAIN, VITE_AUTH0_CLIENT_ID, etc.)
  vite.config.ts       Base /app/, proxies /api → localhost:8000 in dev
evals/
  datasets.py          Sample inputs for each agent eval — uploaded to LangSmith datasets
  evaluators.py        Heuristic evaluator functions (no LLM calls) — score each agent's output
  run.py               CLI runner — uploads datasets, runs evals, prints pass/fail summary
config.yaml            Source of truth for all non-secret config (models, Redis, permissions, LangSmith)
index.html             Landing page — served at GET /, Sign In CTA routes to /app
scripts/
  close_all.py         Close all open PRs and issues in a repo (uses GITHUB_TOKEN)
pyproject.toml         Python package definition and dependencies
uv.lock                Pinned dependency lockfile
.env.example           Template for all required environment variables
railway-deploy.sh      One-command multi-service deployment to Railway
docs/
  PRD.md               Full product requirements
  architecture.md      System design, event schemas, hosting options
  features.md          Complete feature reference
```

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — Python package manager
- [pnpm](https://pnpm.io) — Node.js package manager (dashboard only)
- Redis (local or cloud — see Docker section)
- Claude Code CLI — required for the Dev Agent (`claude-code` provider)

## Setup

**1. Install Python dependencies**

```bash
uv sync --extra dev
```

**2. Configure the target repository**

Open `config.yaml` and set `github.target_repo` to the repo Helix will fix bugs in:

```yaml
github:
  target_repo: "your-org/your-repo"
```

**3. Set environment variables**

```bash
cp .env.example .env
# edit .env and fill in all required values
```

Required variables:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key (crash handler, QA agents) |
| `REDIS_URL` | Redis connection URL — leave unset when using local Docker Redis |
| `SENTRY_WEBHOOK_SECRET` | Sentry client secret — used for HMAC-SHA256 signature verification |
| `ROLLBAR_ACCESS_TOKEN` | Rollbar project read token — verified against each webhook payload |
| `GITHUB_TOKEN` | GitHub personal access token with `repo` + `issues` scope — used as fallback when no GitHub App installation token is available |
| `GITHUB_APP_ID` | Numeric GitHub App ID (Phase 3+) |
| `GITHUB_APP_PRIVATE_KEY` | GitHub App RSA private key, base64-encoded (Phase 3+) |
| `GITHUB_APP_SLUG` | GitHub App slug for building the installation URL, e.g. `helix-bot` (Phase 3+) |
| `DATABASE_URL` | Postgres connection URL — required for Phase 3 per-project config and GitHub App token caching |
| `SLACK_BOT_TOKEN` | Slack bot token (`xoxb-...`) with `chat:write` scope (optional — logs warning if absent) |
| `SLACK_SIGNING_SECRET` | Slack app signing secret — from app settings → Basic Information |
| `SLACK_APPROVAL_CHANNEL` | Channel ID or name for approval messages (optional) |
| `SENDGRID_API_KEY` | SendGrid API key with Mail Send permission (preferred over SMTP) |
| `SMTP_HOST` | SMTP server fallback, e.g. `smtp.gmail.com` (used if SendGrid key not set) |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP password or app password |
| `EMAIL_FROM` | Sender address, e.g. `helix@acme.com` (optional — logs warning if absent) |
| `EMAIL_TO` | Comma-separated recipients, e.g. `oncall@acme.com` (optional) |
| `LANGSMITH_API_KEY` | LangSmith API key — enables LLM call tracing and the eval suite (optional; tracing disabled if unset) |
| `LANGSMITH_PROJECT` | LangSmith project name (default: `helix`) |
| `LANGSMITH_TRACING` | Set to `true` to enable LangSmith tracing in `core/llm.py` (requires `LANGSMITH_API_KEY`) |
| `OTEL_ENABLED` | Set to `true` to enable OpenTelemetry distributed tracing across all agents |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/gRPC endpoint to export traces to (default: `http://localhost:4317`) |
| `OTEL_SERVICE_NAME` | OTel service name tag on all spans (default: `helix`) |
| `HELIX_DEMO` | Set to `true` to skip webhook signature/token verification — local testing only; **default is `false`** |
| `AUTH0_DOMAIN` | Auth0 tenant domain, e.g. `your-tenant.auth0.com` (optional — leave unset for demo mode) |
| `AUTH0_AUDIENCE` | Auth0 API identifier, e.g. `https://api.helix.yourapp.com` (required when `AUTH0_DOMAIN` is set) |

Slack, email, and Auth0 are optional — missing configuration is logged as a warning and the pipeline/dashboard continues. See `.env.example` for the full list.

## Running

### Docker (recommended)

The fastest way to run the full stack locally. Requires [Docker](https://docs.docker.com/get-docker/) and Docker Compose.

**1. Configure secrets**

```bash
cp .env.example .env
# edit .env and fill in all required values
```

**2. Set the target repository in `config.yaml`**

```yaml
github:
  target_repo: "your-org/your-repo"
```

**3. Start everything**

```bash
docker compose up --build
```

Redis starts automatically. If `REDIS_URL` in `.env` points to `localhost`, it is automatically redirected to the Docker Redis container.

To use an external Redis (Redis Cloud, AWS ElastiCache, etc.), set `REDIS_URL` to a non-localhost URL in `.env` before starting.

This starts all four agents. The crash handler is available at `http://localhost:8000` with endpoints at `/webhook/sentry` and `/webhook/rollbar`.

**Individual agent logs**

```bash
docker compose logs -f dev
docker compose logs -f crash_handler
```

**Rebuild after code changes**

```bash
docker compose up --build
```

**Stop the stack**

```bash
docker compose down
```

---

### Exposing the Crash Handler to Sentry / Rollbar (ngrok)

Sentry and Rollbar need a public HTTPS URL to POST webhook events to. For local development, use [ngrok](https://ngrok.com) to tunnel your local port.

**1. Install ngrok**

```bash
brew install ngrok
```

**2. Start the tunnel**

```bash
ngrok http 8000
```

ngrok output will look like this:

```
Account        88Hours (Plan: Free)
Version        3.37.3
Region         Australia (au)
Latency        20ms
Web Interface  http://127.0.0.1:4040
Forwarding     https://carroty-cris-uncravingly.ngrok-free.app -> http://localhost:8000
```

**3. Configure the webhook in Sentry or Rollbar**

**Sentry:** Project Settings → **Integrations → Webhooks**, set the URL to:

```
https://carroty-cris-uncravingly.ngrok-free.app/webhook/sentry
```

**Rollbar:** Settings → **Notifications → Webhook**, set the URL to:

```
https://carroty-cris-uncravingly.ngrok-free.app/webhook/rollbar
```

> **Note:** The ngrok URL changes each time you restart ngrok on the free plan. Update the webhook URL whenever it changes, or use a paid ngrok plan with a fixed domain.

**4. Monitor live requests**

ngrok's web interface at `http://127.0.0.1:4040` shows every request and response in real time — useful for debugging webhook payloads.

---

### Running without Docker

Each agent runs as its own process. Start them all:

```bash
# Crash Handler — webhook server + dashboard API (receives Sentry and Rollbar events)
uv run uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port 8000

# QA Agent — subscribes to crash_analysed
uv run --env-file .env python -m agents.qa.main

# Dev Agent — subscribes to test_case_generated
uv run --env-file .env python -m agents.dev.main

# Notifier Agent — subscribes to fix_suggested and fix_failed
uv run --env-file .env python -m agents.notifier.main
```

Point your Sentry webhook at `http://<host>:8000/webhook/sentry` or Rollbar at `http://<host>:8000/webhook/rollbar`.

---

### Dashboard

The React dashboard streams live agent activity and shows all incidents at `http://localhost:8000/app`.

**Build for production** (required before the dashboard loads from FastAPI):

```bash
cd dashboard
pnpm install
pnpm build
```

The built files are written to `dashboard/dist/` and served automatically by the crash handler at `/app`.

**Local development** (Vite dev server with hot reload):

```bash
cd dashboard
pnpm install
pnpm dev   # http://localhost:5173/app
```

Vite proxies `/api` → `http://localhost:8000` during dev, so the FastAPI backend must be running.

**Auth0 setup (optional — skip for demo mode)**

Without `AUTH0_DOMAIN` set, the dashboard is accessible without login. To enable GitHub login via Auth0:

1. Create an Auth0 tenant and add a **Single Page Application** (note the Client ID)
2. Create an **API** — the Identifier becomes `AUTH0_AUDIENCE` (e.g. `https://helix.api`); enable **User Access** for your SPA
3. Enable the **GitHub** social connection: Auth0 → Authentication → Social → GitHub
4. In your Auth0 Application Settings:
   - **Allowed Callback URLs:** `https://<your-app>.up.railway.app/callback, http://localhost:5173/app/`
   - **Allowed Logout URLs:** `https://<your-app>.up.railway.app, http://localhost:5173/app/`
   - **Allowed Web Origins / CORS:** `https://<your-app>.up.railway.app, http://localhost:5173`
5. Optionally paste `dashboard/login.html` into Auth0 → Branding → Universal Login → Custom Login Page for a Helix-branded login screen
6. Set in your `.env`:
   ```
   AUTH0_DOMAIN=your-tenant.auth0.com
   AUTH0_AUDIENCE=https://helix.api
   ```
7. Create `dashboard/.env.local`:
   ```
   VITE_AUTH0_DOMAIN=your-tenant.auth0.com
   VITE_AUTH0_CLIENT_ID=your-spa-client-id
   VITE_AUTH0_AUDIENCE=https://helix.api
   ```

---

### Testing the webhook locally

**Send a test payload**

Rollbar:
```bash
curl -X POST http://localhost:8000/webhook/rollbar \
  -H "Content-Type: application/json" \
  -d @test_payloads/rollbar_new_item.json
```

Sentry (signature is verified — set `HELIX_DEMO=true` in `.env` to skip verification during local testing):
```bash
curl -X POST http://localhost:8000/webhook/sentry \
  -H "Content-Type: application/json" \
  -H "sentry-hook-signature: <hmac-sha256-of-body>" \
  -d @test_payloads/sentry_event.json
```

A successful request returns `202 Accepted` with an `incident_id`. Open `http://localhost:8000/app` to watch the pipeline run live.

**Verify the result in Redis**

```bash
redis-cli GET helix:incident:<incident_id>:crash_report | python3 -m json.tool
redis-cli GET helix:incident:<incident_id>:status
```

## Scripts

### Reset cloud data (Railway)

Flush all Helix state from Redis and Postgres. Use `$REDIS_URL` and `$DATABASE_URL` from your Railway environment variables or `.env`.

**Redis — nuke all Helix keys:**
```bash
redis-cli -u "$REDIS_URL" --scan --pattern "helix:*" | xargs redis-cli -u "$REDIS_URL" DEL
```

Or flush the entire Redis instance (if it's Helix-only):
```bash
redis-cli -u "$REDIS_URL" FLUSHALL
```

**Postgres — drop and recreate the public schema:**
```bash
psql "$DATABASE_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

---

### Close all open PRs and issues

Useful for resetting a test repository between runs.

```bash
# Dry run — prints what would be closed without making any changes
python scripts/close_all.py owner/repo --dry-run

# Close everything
python scripts/close_all.py owner/repo
```

Reads `GITHUB_TOKEN` from the environment or `.env`. Requires the token to have `repo` scope.

---

## Tests

```bash
uv run pytest
```

161 tests across agents, core, and integrations. All tests use mocks — no live Redis, GitHub, or LLM calls required.

## Evals

LangSmith evals measure agent output quality. Each eval calls the real LLM and scores the response using heuristic evaluators (no LLM-as-judge, no extra cost beyond the API call itself).

Agents covered: Crash Handler (4 examples), QA Agent (2 examples), Dev Agent (3 examples).

**Push datasets only (no LLM calls):**

```bash
uv run --env-file .env python -m evals.run --dataset-only
```

**Run all evals:**

```bash
uv run --env-file .env python -m evals.run
```

**Run one agent:**

```bash
uv run --env-file .env python -m evals.run --agent crash_handler
uv run --env-file .env python -m evals.run --agent qa
uv run --env-file .env python -m evals.run --agent dev
```

Evals also run automatically in CI on every push to `main` and on PRs targeting `main` (`.github/workflows/evals.yml`). The CI job tags each experiment with the commit SHA so any LangSmith run is traceable to the exact commit. The job exits non-zero if any agent scores below 0.8, failing the check.

**The eval step is skipped automatically if `ANTHROPIC_API_KEY` or `LANGSMITH_API_KEY` is not set as a GitHub Actions secret** — the job exits 0 with a skip message rather than failing. To enable evals in CI, add both as repository secrets: GitHub → Settings → Secrets and variables → Actions.

## OpenTelemetry tracing

End-to-end distributed tracing across all four agents. Disabled by default — zero overhead unless explicitly enabled.

**Enable:**

```bash
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # or your backend's endpoint
```

**Span hierarchy per incident:**

```
crash_handler.handle_incident  (one parent span per webhook)
  └── llm.complete             (one child span per LLM call)

qa.handle_incident
  └── llm.complete

dev.handle_incident
  └── llm.complete

notifier.fix_suggested / fix_failed / pr_created / duplicate_detected
```

**Attributes on every span:** `helix.agent`, `helix.incident_id`, `helix.provider`, `helix.model`, `helix.input_tokens`, `helix.output_tokens`

**Compatible backends:** Datadog, Grafana Tempo, Jaeger, Honeycomb, AWS X-Ray — any OTLP/gRPC-compatible receiver.

When `OTEL_ENABLED` is not set, the OTel API's built-in no-op tracer is used — no packages need to be running, no errors thrown.

## Agent models

| Agent | Provider | Model | Why |
|---|---|---|---|
| Crash Handler | Anthropic | claude-haiku-4-5 | Structured extraction — fast and cheap |
| QA Agent | Anthropic | claude-haiku-4-5 | Pattern-matching test generation |
| Dev Agent | Claude Code CLI | claude-sonnet-4-6 | Deep reasoning + full repo file access |

All models are configurable in `config.yaml` or via `HELIX_<AGENT>_PROVIDER` / `HELIX_<AGENT>_MODEL` env vars.

## Agent permissions

Each agent declares exactly which tools it is allowed to call. Permissions are enforced at runtime via `core/permissions.py` — a `PermissionDenied` exception is raised before any unauthorised operation executes.

| Agent | Can do | Cannot do |
|---|---|---|
| Crash Handler | Write Redis, publish `crash_analysed` | GitHub, Slack |
| QA Agent | Read GitHub, write Redis, publish `test_case_generated` | Create PRs, push code |
| Dev Agent | Clone repo, push code, create PRs, write Redis | Slack, approve own PRs |
| Notifier | Post to Slack, send email | Write Redis, touch GitHub |

Permissions are declared in `config.yaml` under the `permissions:` key for each agent.

## Event channels

| Channel | Published by | Consumed by |
|---|---|---|
| `helix:events:crash_analysed` | Crash Handler | QA Agent |
| `helix:events:test_case_generated` | QA Agent | Dev Agent |
| `helix:events:fix_suggested` | Dev Agent | Notifier Agent |
| `helix:events:pr_created` | Dev Agent | — |
| `helix:events:fix_failed` | Dev Agent (on exhaustion) | Notifier Agent |

EventBridge uses the same names as `detail-type` on the `helix-mvp` bus. Switch backends with `HELIX_EVENT_BACKEND=eventbridge`.

The dashboard subscribes to a separate per-incident channel (`helix:ui:{incident_id}`) for fine-grained live progress events. These are ephemeral — Pub/Sub only, not persisted.

## Event backend

| Backend | When to use |
|---|---|
| `redis` | Local dev, Railway, any non-AWS deployment (default) |
| `eventbridge` | AWS Lambda or ECS deployments |

Redis is the default. Within Redis, the event transport can be configured with `redis_mode` in `config.yaml`:

| Mode | Behaviour |
|---|---|
| `streams` | Redis Streams — messages persist across agent restarts (default) |
| `pubsub` | Redis Pub/Sub — fire-and-forget, messages lost if no subscriber is running |

## Hosting

| Stage | Recommended |
|---|---|
| Local dev | `docker compose up --build` |
| MVP launch | Railway (one service per agent) + Redis Cloud |
| AWS-native | Lambda per agent + EventBridge + ElastiCache |

### One-click Railway deploy

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/88hours/helix)

The button deploys the **crash_handler** (the webhook-receiving service) as the primary service. After it's running:

1. Set the required environment variables in the Railway dashboard (see `.env.example` for the full list)
2. Add Redis: Railway dashboard → **New** → **Database** → **Redis**
3. Deploy the remaining three agents:
```bash
railway link   # link to the newly created project
./railway-deploy.sh --env-file .env qa dev notifier
```

See `docs/architecture.md` for a full breakdown.

## Scope

Helix fixes **application-level bugs** only. Out of scope for MVP: infrastructure failures, performance optimisation, refactoring, mobile crashes, multi-tenant support.

---

## Known Issues

### GitHub App callback not firing — installation ID must be entered manually

After a user installs the GitHub App, GitHub is supposed to redirect to the configured callback URL with `installation_id` in the query string. This redirect is not reliably firing in the current deployment, which means the installation ID is never automatically saved to the project.

**Workaround:** after installing the app, find the installation ID in the GitHub App settings page (Settings → Applications → Installed GitHub Apps → Configure — the ID is in the URL: `github.com/settings/installations/<id>`) and paste it manually into the Helix Projects page using the manual entry field.

**Root cause:** the OAuth callback URL may not be correctly configured in the GitHub App settings, or the redirect is being swallowed before it reaches the handler.

---

## Production Considerations

Known limitations of the current architecture and what needs to change before running Helix as a multi-tenant SaaS.

### Sequential processing bottleneck

Each agent is a single process that handles one incident at a time. At scale, incidents queue behind each other:

```
Org A crash → dev agent processing (5–10 min)
Org B crash → waiting...
Org C crash → waiting...
```

The Dev Agent is the worst offender — it clones a repo, runs tests, and iterates up to 3 times. A single slow incident blocks every other org.

**Fix:** run each agent as a pool of workers pulling from a queue. In ECS Fargate, this means multiple task instances per agent with auto-scaling based on queue depth. The agent logic itself does not change — only how work is distributed to it.

### No per-org isolation

All orgs share the same worker pool. A single org with a burst of crashes can starve others.

**Fix:** priority queues per plan tier. Free incidents go into a low-priority queue; Pro into a standard queue; Team gets dedicated workers. Redis Streams supports this with multiple stream keys — workers poll the high-priority stream first.

| Plan | Model |
|---|---|
| Free | Shared pool, low-priority queue |
| Pro | Shared pool, standard-priority queue |
| Team | Dedicated worker pool — no noisy neighbour |

### ~~Concurrent fixes on the same repo~~ (resolved)

Before a TDD loop starts, the Dev Agent acquires `SET helix:repo_lock:{repo} {incident_id} NX EX 600` in Redis. A second incident on the same repo retries every 30 seconds for up to 6 minutes; if the lock is still held it escalates to a human rather than forging ahead with a conflicting branch.

### ~~No Dev Agent timeout budget~~ (resolved)

The TDD loop is now wrapped in `asyncio.wait_for(..., timeout=480)`. If the 8-minute budget is exceeded the incident is escalated via the same path as exhausted retries — the human always gets a Slack alert. The lock TTL (600 s) is intentionally longer than the timeout so the lock always expires cleanly even if cancellation interrupts the Redis delete.

### ~~Redis Pub/Sub is fire-and-forget~~ (resolved)

Helix now uses Redis Streams (`XADD`/`XREAD`) by default. Messages persist until consumed and survive agent restarts. Redis Pub/Sub is still available via `redis_mode: pubsub` in `config.yaml` for backwards compatibility.

### Static `config.yaml` does not support multiple organisations

`config.yaml` holds a single `github.target_repo`. There is no concept of per-org configuration, tokens, or repo lists.

**Fix:** replace `config.yaml` with a Postgres table (`repos`, `organisations`). Agents receive `org_id` in the event payload and look up config at runtime. Required before any multi-tenant work.

### Summary

| Concern | Fix | Complexity |
|---|---|---|
| Sequential bottleneck | Multiple ECS task instances + auto-scaling | Low — ECS handles this |
| No org isolation | Priority queues per plan tier | Medium |
| ~~Concurrent repo fixes~~ | ~~Per-repo Redis lock (`SET NX EX`)~~ | Done — `agents/dev/agent.py` |
| ~~No Dev Agent timeout~~ | ~~Wall-clock budget at worker level~~ | Done — `asyncio.wait_for` 8 min |
| ~~Message loss on restart~~ | ~~Redis Streams instead of Pub/Sub~~ | Done — Redis Streams is the default |
| ~~Single-tenant config~~ | ~~Postgres org/repo tables~~ | Done — Phase 3 Postgres layer |

None of these require changes to agent logic. The event-driven architecture is the right foundation — these are distribution and configuration concerns layered on top of it.

---

## Roadmap

### Phase 1 — MVP (complete)
- [x] Crash Handler — Sentry + Rollbar webhook ingestion, LLM crash classification
- [x] QA Agent — GitHub Issues deduplication, repo clone, TDD test generation + validation
- [x] Dev Agent — LLM fix suggestion, TDD loop, PR creation, retry + escalation
- [x] Notifier Agent — Slack + email for fix suggestions and escalations
- [x] Human Approval workflow — Slack Approve/Reject buttons, merge PR on approval
- [x] Redis Streams event bus (configurable; AWS EventBridge also supported)
- [x] Demo mode — skip signature verification for local testing
- [x] Multi-language support — Python, JavaScript/TypeScript, Ruby, Java/Kotlin, Go
- [x] One-click Railway deploy

### Phase 2 — Full-Stack Agent Experience (complete)
- [x] Scoped tool access — per-agent permission declarations enforced at runtime (`core/permissions.py`)
- [x] Streaming dashboard — React + Vite frontend with live agent activity via SSE (`dashboard/`)
- [x] Tool visualisation — live tool call timeline in the dashboard (LLM, GitHub, Git, Claude Code)
- [x] Auth0 + GitHub login — JWT validation via JWKS, optional (demo mode if `AUTH0_DOMAIN` unset)
- [x] Repo configuration — users add/manage repos via `/app/repos`; stored per user in Redis
- [x] Landing page — `index.html` served at `GET /`; Sign In CTA routes to `/app`
- [x] Projects page — create projects with a GitHub URL, configure per-project credentials (API keys, tokens, Slack, email) via `/app/projects`; secret values masked on read
- [x] Sentry webhook signature verification — HMAC-SHA256 verification working end-to-end
- [x] Demo mode default — flipped to `false`; production deployments verify signatures without any extra config

### Phase 3 — Per-Project GitHub App and Platform Maturity (complete)
- [x] GitHub App integration — per-project installation tokens, JWT flow, token caching in Postgres (`core/github_app.py`)
- [x] Postgres layer — projects, github_installations, per-project settings tables (`core/db.py`)
- [x] Per-project webhooks — each project gets a dedicated Sentry/Rollbar webhook URL scoped to its credentials
- [x] Project onboarding wizard — 5-step UI: repo URL → GitHub App install → credential config → done
- [x] Installation token threaded through all GitHub API calls — fixes 403s on repos where `GITHUB_TOKEN` lacks write access
- [x] Git push auth fix — GitHub App tokens use `x-access-token:{token}` URL format; fixes headless push failures
- [x] SSE event replay — past agent events persisted to Redis and replayed on page load; ToolTimeline and StreamPanel no longer empty for completed incidents
- [x] Email resilience — missing or invalid SendGrid key warns and skips instead of crashing the notifier
- [x] Local Postgres container in Docker Compose

### Phase 4 — Observability and Scale (complete)
- [x] LangSmith tracing — every LLM call in `core/llm.py` is traced with prompt, response, and token usage
- [x] LangSmith eval suite — Crash Handler, QA Agent, and Dev Agent; heuristic evaluators, no LLM-as-judge cost
- [x] Evals in CI — GitHub Actions workflow runs evals on every push to `main` and on PRs; fails if any agent scores below 0.8
- [x] OpenTelemetry tracing — end-to-end spans across all four agents, exportable to Datadog, Grafana, Jaeger, or any OTLP backend; enabled via `OTEL_ENABLED=true`
- [x] Per-repo Redis lock — prevents concurrent Dev Agent workers from cloning the same repo simultaneously and opening conflicting branches or duplicate PRs
- [x] Dev Agent timeout — hard 8-minute wall-clock budget per incident; exceeded budget escalates to human via Slack rather than holding a worker indefinitely
- [x] Responsive landing page — mobile hamburger nav, scaled typography and padding, scrollable language table; self-healing product framing with countdown timer

### Phase 5 — UI, Ops, and Integration Polish
- [x] Rollbar webhook auth — fixed 401 errors caused by missing `rollbar_access_token` in project settings; added payload + auth-check debug logging to diagnose token mismatches
- [x] GitHub App Setup URL — redirect target changed to `/app/projects/new` (frontend); eliminates Auth0 session mismatch that broke the post-install callback
- [x] GitHub page — dedicated `/github` section shows all accessible repos with Private/Public badge, default branch, and which Helix project monitors each repo; handles post-install `?installation_id=` redirect and manual ID entry
- [x] Simplified project wizard — reduced from 5 steps to 4; first step is repo picker with auto-fill of project name and base branch from GitHub; GitHub connection management moved to the dedicated GitHub page
- [x] Incident list grouped by project — incidents grouped under their project with repo slug and count; ungrouped incidents fall into an "Other" section
- [x] Projects page — repo availability check on load; projects whose GitHub repo is no longer accessible via the App show a yellow warning banner with a link to the GitHub page
- [x] Incident detail live refresh — `status_changed` SSE events now trigger a full re-fetch of the incident so QA and PR sections populate in real-time without a page reload
- [x] Evals CI — eval step skips gracefully (exit 0) when `ANTHROPIC_API_KEY` or `LANGSMITH_API_KEY` secrets are not set; documented in README
- [x] Dependency security — upgraded `pytest` and `langsmith` via `uv lock` to resolve two Moderate Dependabot alerts

### Phase 6 — Multi-Tenancy and Production Scale (planned)
- [ ] `organisations` Postgres table — org_id, name, plan tier, owner; foreign key on all projects
- [ ] `org_id` threaded through event payloads — agents look up the correct `Project` at runtime from `org_id` + `repo`; removes the static `config.yaml` GitHub fallback entirely
- [ ] Priority queues per plan tier — Free / Pro / Team incidents route to separate Redis Stream keys; workers poll high-priority streams first; Team orgs get dedicated worker pools
- [ ] Worker pool per agent — multiple concurrent instances pulling from the same stream; ECS Fargate auto-scaling on queue depth eliminates the sequential processing bottleneck
- [ ] Per-org noisy-neighbour protection — burst limiting so a single org with many crashes cannot starve others on the shared pool
- [ ] GitHub App multi-org install flow — installation callback reliably saves `installation_id` per org
- [ ] Audit trail — queryable log of every inbound webhook, agent event, Slack action, and GitHub operation, keyed by `incident_id` and `org_id`
