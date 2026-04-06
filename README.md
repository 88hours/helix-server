[![CircleCI](https://dl.circleci.com/status-badge/img/gh/88hours/helix/tree/main.svg?style=svg&circle-token=CCIPRJ_Ep6waV9SHZqBRZGvT3jMRw_67ae3a13933cdc72c40be855fe2fc8b931f54f1c)](https://dl.circleci.com/status-badge/redirect/gh/88hours/helix/tree/main)
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/88hours/helix)
[![Website](https://img.shields.io/badge/website-live-brightgreen)](https://playful-seahorse-1785f6.netlify.app)
# Helix

Helix is an autonomous incident response platform. It takes a production crash from Sentry or Rollbar all the way to a ready-to-merge pull request in under 10 minutes — no human involvement required until the PR review.

## How it works

```
Sentry / Rollbar crash → Crash Handler → QA Agent → Dev Agent → PR + Notifications
```

1. **Crash Handler** — receives Sentry or Rollbar webhooks, classifies severity, and produces a structured crash report
2. **QA Agent** — deduplicates against open GitHub Issues, generates a TDD test that asserts the correct behaviour (not that the crash occurs), validates the test and retries if needed. Supports Python, JavaScript/TypeScript, Ruby, and Java/Kotlin.
3. **Dev Agent** — generates a fix suggestion and posts it to the GitHub Issue, then runs a full TDD loop: clones the repo, runs the failing test, writes the minimum fix, verifies the full suite; retries up to 3 times before escalating
4. **Notifier Agent** — handles all outbound Slack and email notifications: fix suggestions, PR links, and escalation alerts when the Dev Agent exhausts retries

Agents communicate via Redis Streams (or AWS EventBridge). Shared state lives in Redis, keyed by `incident_id`.

## Project structure

```
agents/
  crash_handler/       FastAPI webhook server — receives Sentry/Rollbar events, publishes crash_analysed
    agent.py           Core logic: LLM analysis → CrashReport
    prompts.py         System + user prompt templates
    main.py            Entry point: POST /webhook/sentry, POST /webhook/rollbar, GET /healthz
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
    agent.py           Slack + email for fix suggestions and escalations
    main.py            Entry point: two concurrent subscriber loops
    railway.json       Railway service config for this agent
core/
  config.py            Typed config loaders for all agents and integrations
  events.py            Redis Streams / Pub/Sub / EventBridge publish and subscribe helpers
  state.py             Redis read/write helpers, keyed by incident_id
  models.py            Pydantic models shared across all agents
  llm.py               Routes to Anthropic SDK, OpenRouter, or Claude Code CLI
  utils.py             extract_json() — parses structured JSON from LLM output
integrations/
  sentry.py            HMAC-SHA256 signature verification + Sentry webhook payload parsing
  rollbar.py           Access token verification + Rollbar webhook payload parsing
  github.py            Git CLI wrappers (clone, branch, commit, push) + GitHub REST API
  jira.py              JIRA REST API v3 — create and update issues
  slack.py             Slack Web API — notifications and escalation alerts
  email.py             SendGrid API (preferred) or SMTP fallback
config.yaml            Source of truth for all non-secret config (models, Redis, integrations)
index.html             Landing page
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
- [uv](https://docs.astral.sh/uv/) — package manager
- Redis (local or cloud — see Docker section)
- Claude Code CLI — required for the Dev Agent (`claude-code` provider)

## Setup

**1. Install dependencies**

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
| `GITHUB_TOKEN` | GitHub personal access token with `repo` + `issues` scope |
| `SLACK_BOT_TOKEN` | Slack bot token (`xoxb-...`) with `chat:write` scope (optional — logs warning if absent) |
| `SLACK_SIGNING_SECRET` | Slack app signing secret — from app settings → Basic Information |
| `SLACK_APPROVAL_CHANNEL` | Channel ID or name for approval messages (optional) |
| `SENDGRID_API_KEY` | SendGrid API key with Mail Send permission (preferred over SMTP) |
| `SMTP_HOST` | SMTP server fallback, e.g. `smtp.gmail.com` (used if SendGrid key not set) |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP password or app password |
| `EMAIL_FROM` | Sender address, e.g. `helix@acme.com` (optional — logs warning if absent) |
| `EMAIL_TO` | Comma-separated recipients, e.g. `oncall@acme.com` (optional) |
| `HELIX_DEMO` | Set to `true` to skip all webhook signature/token verification (useful for local testing) |

Slack and email are optional — missing configuration is logged as a warning and the pipeline continues. See `.env.example` for the full list including optional variables.

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
# Crash Handler — webhook server (receives Sentry and Rollbar events)
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

### Testing the webhook locally

**Send a test payload**

Rollbar:
```bash
curl -X POST http://localhost:8000/webhook/rollbar \
  -H "Content-Type: application/json" \
  -d @test_payloads/rollbar_new_item.json
```

Sentry (demo mode skips signature verification — set `HELIX_DEMO=true` in `.env`):
```bash
curl -X POST http://localhost:8000/webhook/sentry \
  -H "Content-Type: application/json" \
  -d @test_payloads/sentry_event.json
```

A successful request returns `202 Accepted` with an `incident_id`.

**Verify the result in Redis**

```bash
redis-cli GET helix:incident:<incident_id>:crash_report | python3 -m json.tool
redis-cli GET helix:incident:<incident_id>:status
```

## Tests

```bash
uv run pytest
```

161 tests across agents, core, and integrations. All tests use mocks — no live Redis, GitHub, or LLM calls required.

## Agent models

| Agent | Provider | Model | Why |
|---|---|---|---|
| Crash Handler | Anthropic | claude-haiku-4-5 | Structured extraction — fast and cheap |
| QA Agent | Anthropic | claude-haiku-4-5 | Pattern-matching test generation |
| Dev Agent | Claude Code CLI | claude-sonnet-4-6 | Deep reasoning + full repo file access |

All models are configurable in `config.yaml` or via `HELIX_<AGENT>_PROVIDER` / `HELIX_<AGENT>_MODEL` env vars.

## Event channels

| Channel | Published by | Consumed by |
|---|---|---|
| `helix:events:crash_analysed` | Crash Handler | QA Agent |
| `helix:events:test_case_generated` | QA Agent | Dev Agent |
| `helix:events:fix_suggested` | Dev Agent | Notifier Agent |
| `helix:events:pr_created` | Dev Agent | — |
| `helix:events:fix_failed` | Dev Agent (on exhaustion) | Notifier Agent |

EventBridge uses the same names as `detail-type` on the `helix-mvp` bus. Switch backends with `HELIX_EVENT_BACKEND=eventbridge`.

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

### Concurrent fixes on the same repo

If the same repo has two crashes at the same time, two Dev Agent workers will clone it simultaneously, create conflicting branches, and potentially open duplicate PRs.

**Fix:** a per-repo lock in Redis before starting the TDD loop. One line: `SET helix:{org_id}:repo_lock:{repo} 1 NX EX 600`. If the lock is held, the incident waits in a short retry queue.

### No Dev Agent timeout budget

The Dev Agent retries up to 3 times but has no wall-clock limit. A pathological case (large repo, flaky tests) can hold a worker indefinitely.

**Fix:** a hard timeout per incident (e.g. 8 minutes total). If the budget is exceeded, escalate rather than continuing to retry. The timeout is enforced at the worker level, not inside the agent.

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
| Concurrent repo fixes | Per-repo Redis lock (`SET NX EX`) | Low |
| No Dev Agent timeout | Wall-clock budget at worker level | Low |
| ~~Message loss on restart~~ | ~~Redis Streams instead of Pub/Sub~~ | Done — Redis Streams is the default |
| Single-tenant config | Postgres org/repo tables | High — requires Phase 3 work |

None of these require changes to agent logic. The event-driven architecture is the right foundation — these are distribution and configuration concerns layered on top of it.

---

## Roadmap

### Phase 2 — Make it deployable
- [x] Add one-click Railway deploy button — railway.json + deploy badge in README
- [x] Add Sentry webhook support alongside Rollbar
- [x] Switch event bus from Redis Pub/Sub to Redis Streams (configurable)
- [x] Add demo mode (`HELIX_DEMO`) to skip webhook signature verification for local testing
- [x] Multi-language support in QA and Dev agents (Python, JavaScript/TypeScript, Ruby, Java/Kotlin)
- [ ] Add Human Approval workflow — Slack Approve/Reject buttons, merge PR on approval

### Phase 3 — Make it a SaaS
- [ ] Add Postgres — store per-org config, replace static config.yaml for multi-tenant data
- [ ] Add Auth0/Clerk authentication — login/signup, org model, all resources scoped by org_id
- [ ] Add GitHub OAuth — repo connection via OAuth App instead of manual token setup
- [ ] Add Slack OAuth app install — "Add to Slack" flow, store bot token per org
- [ ] Add BYO Anthropic key — required on Free tier, optional override on paid tiers
- [ ] Add Stripe billing — Free / Pro ($49/mo) / Team ($199/mo), metered by incidents resolved
- [ ] Build onboarding wizard — connect GitHub → connect Slack → paste Rollbar webhook URL → test fire
- [ ] Build incident dashboard — live incident feed, agent activity log, repo settings, usage meter

### Phase 4 — Launch
- [ ] Build landing page — value prop, how-it-works diagram, demo video, deploy button
- [ ] Record demo video — crash → test case → PR → merged (2 min)
