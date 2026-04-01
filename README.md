# Helix

Helix is an autonomous incident response platform. It takes a production crash from Sentry all the way to a ready-to-merge pull request in under 10 minutes, with a human approval step via Slack before anything reaches production.

## How it works

```
Sentry crash → Crash Handler → QA Agent → Dev Agent → Code Quality Agent → Human Approval → PR merged
```

1. **Crash Handler** — receives the Sentry webhook, classifies severity, and produces a structured crash report
2. **QA Agent** — deduplicates against open JIRA tickets, then writes a failing TDD test that reproduces the bug
3. **Dev Agent** — runs the failing test, writes the minimum fix, runs the full suite, retries up to 3 times, then opens a PR
4. **Code Quality Agent** — reviews the PR for coverage, standards, and security; routes back to Dev Agent or posts an approval request to Slack
5. **Human Approval** — reviewer clicks Approve in Slack; the PR is merged and deployed

Agents communicate via Redis Pub/Sub (or AWS EventBridge). Shared state lives in Redis, keyed by `incident_id`.

## Project structure

```
agents/
  crash_handler/       FastAPI webhook server — receives Sentry events, publishes crash_analysed
    agent.py           Core logic: LLM analysis → CrashReport
    prompts.py         System + user prompt templates
    main.py            Entry point: POST /webhook/sentry, GET /healthz
  qa/                  Subscribes to crash_analysed
    agent.py           JIRA deduplication, repo clone, LLM test case generation
    prompts.py
    main.py            Entry point: subscriber loop
  dev/                 Subscribes to test_case_generated and quality_rejected
    agent.py           Clone → write test → claude-code fix loop → GitHub PR
    prompts.py         claude-code CLI prompt with TESTS_PASSED/TESTS_FAILED protocol
    main.py            Entry point: two concurrent subscriber loops
  code_quality/        Subscribes to pr_created
    agent.py           Fetches PR diff, LLM review, Slack approval or quality_rejected
    prompts.py
    main.py            Entry point: subscriber loop
  human_approval/      FastAPI webhook — receives Slack Approve/Reject button clicks
    agent.py           handle_approve: merges PR + notifies; handle_reject: posts Slack note
    main.py            Entry point: POST /slack/interactions, GET /healthz
core/
  config.py            Typed config loaders for all agents and integrations
  events.py            EventBridge / Redis Pub/Sub publish and subscribe helpers
  state.py             Redis read/write helpers, keyed by incident_id
  models.py            Pydantic models shared across all agents
  llm.py               Routes to Anthropic SDK, OpenRouter, or Claude Code CLI
  utils.py             extract_json() — parses structured JSON from LLM output
integrations/
  sentry.py            HMAC-SHA256 signature verification + payload parsing
  github.py            Git CLI wrappers (clone, branch, commit, push) + GitHub REST API
  jira.py              JIRA REST API v3 — create/search issues, add comments
  slack.py             Slack Web API — approval Block Kit messages, escalation alerts
config.yaml            Source of truth for all non-secret config (models, Redis, integrations)
pyproject.toml         Python package definition and dependencies
uv.lock                Pinned dependency lockfile
.env.example           Template for all required environment variables
docs/
  PRD.md               Full product requirements
  architecture.md      System design, event schemas, hosting options
```

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — package manager
- Redis (local or cloud)
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
| `ANTHROPIC_API_KEY` | Anthropic API key (crash handler, QA, code quality agents) |
| `REDIS_URL` | Redis connection URL, e.g. `redis://localhost:6379` |
| `SENTRY_WEBHOOK_SECRET` | HMAC secret from your Sentry webhook settings |
| `GITHUB_TOKEN` | GitHub token with `repo` scope |
| `JIRA_URL` | JIRA base URL, e.g. `https://acme.atlassian.net` |
| `JIRA_EMAIL` | JIRA account email |
| `JIRA_TOKEN` | JIRA API token |
| `JIRA_PROJECT_KEY` | JIRA project key, e.g. `PROJ` |
| `SLACK_BOT_TOKEN` | Slack bot token (`xoxb-...`) with `chat:write` scope |
| `SLACK_SIGNING_SECRET` | Slack app signing secret — from app settings → Basic Information |
| `SLACK_APPROVAL_CHANNEL` | Channel ID or name for approval messages |
| `SMTP_HOST` | SMTP server, e.g. `smtp.sendgrid.net` or `smtp.gmail.com` |
| `SMTP_USER` | SMTP username or API key username |
| `SMTP_PASSWORD` | SMTP password or API key |
| `EMAIL_FROM` | Sender address, e.g. `helix@acme.com` |
| `EMAIL_TO` | Comma-separated recipients, e.g. `oncall@acme.com` |

See `.env.example` for the full list including optional variables.

## Running

Each agent runs as its own process. Start them all:

```bash
# Crash Handler — webhook server (receives Sentry events)
uv run uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port 8000

# QA Agent — subscribes to crash_analysed
uv run python -m agents.qa.main

# Dev Agent — subscribes to test_case_generated and quality_rejected
uv run python -m agents.dev.main

# Code Quality Agent — subscribes to pr_created
uv run python -m agents.code_quality.main

# Human Approval Agent — receives Slack button clicks (Approve / Reject)
# Configure Slack Interactivity Request URL: http://<host>:8001/slack/interactions
uv run uvicorn agents.human_approval.main:app --host 0.0.0.0 --port 8001
```

Point your Sentry webhook at `http://<host>:8000/webhook/sentry`.

## Agent models

| Agent | Provider | Model | Why |
|---|---|---|---|
| Crash Handler | Anthropic | claude-haiku-4-5 | Structured extraction — fast and cheap |
| QA Agent | Anthropic | claude-haiku-4-5 | Pattern-matching test generation |
| Dev Agent | Claude Code CLI | claude-sonnet-4-6 | Deep reasoning + full repo file access |
| Code Quality | Anthropic | claude-sonnet-4-6 | Security and standards review |

All models are configurable in `config.yaml` or via `HELIX_<AGENT>_PROVIDER` / `HELIX_<AGENT>_MODEL` env vars.

## Event channels

| Channel | Published by | Consumed by |
|---|---|---|
| `helix:events:crash_analysed` | Crash Handler | QA Agent |
| `helix:events:test_case_generated` | QA Agent | Dev Agent |
| `helix:events:pr_created` | Dev Agent | Code Quality Agent |
| `helix:events:quality_approved` | Code Quality Agent | Human Approval |
| `helix:events:quality_rejected` | Code Quality Agent | Dev Agent |

EventBridge uses the same names as `detail-type` on the `helix-mvp` bus. Switch backends with `HELIX_EVENT_BACKEND=eventbridge`.

## Event backend

| Backend | When to use |
|---|---|
| `redis` | Local dev, Railway, any non-AWS deployment (default) |
| `eventbridge` | AWS Lambda or ECS deployments |

## Hosting

| Stage | Recommended |
|---|---|
| Local dev | Single machine, Redis via Docker |
| MVP launch | Railway (one service per agent) + Redis Cloud |
| AWS-native | Lambda per agent + EventBridge + ElastiCache |

See `docs/architecture.md` for a full breakdown.

## Scope

Helix fixes **application-level bugs** only. Out of scope for MVP: infrastructure failures, performance optimisation, refactoring, mobile crashes, multi-tenant support.
