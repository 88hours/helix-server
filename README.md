# Helix

Helix is an autonomous incident response platform. It takes a production crash from Sentry all the way to a ready-to-merge pull request in under 10 minutes, with a human approval step via Slack before anything reaches production.

## How it works

```
Sentry crash → Crash Handler → QA Agent → Dev Agent → Code Quality Agent → Human Approval → PR merged
```

1. **Crash Handler** — receives the Sentry webhook, classifies severity, and produces a structured crash report
2. **QA Agent** — deduplicates against open JIRA/GitHub tickets, then writes a failing TDD test that reproduces the bug
3. **Dev Agent** — runs the failing test, writes the minimum fix, runs the full suite, retries up to 3 times, then opens a PR
4. **Code Quality Agent** — reviews the PR for coverage, standards, and security; routes back to Dev Agent or notifies the human reviewer
5. **Human Approval** — reviewer clicks Approve in Slack; the PR is merged and deployed

Agents communicate via AWS EventBridge (or Redis Pub/Sub for simpler deployments). Shared state lives in Redis, keyed by `incident_id`.

## Project structure

```
agents/
  crash_handler/       Webhook receiver, crash parser, severity classifier
  qa/                  Issue deduplication, test case generator
  dev/                 Fix writer, test runner, PR creator
  code_quality/        PR reviewer, Slack notifier
core/
  config.py            Loads config.yaml + env var overrides
  events.py            EventBridge / Redis Pub/Sub publish and subscribe
  state.py             Redis read/write helpers, keyed by incident_id
  models.py            Pydantic models shared across all agents
  llm.py               Routes to Anthropic SDK, OpenRouter, or Claude Code CLI
integrations/
  sentry.py            Webhook validation and payload parsing
  github.py            PR creation and merge
  jira.py              Ticket search and creation
  slack.py             Approval notifications and webhook handling
config.yaml            Model, provider, Redis, and event bus config
docs/
  PRD.md               Full product requirements
  architecture.md      System design, event schemas, hosting options
```

## Configuration

All non-secret configuration lives in `config.yaml`. Secrets are set as environment variables.

Copy `.env.example` to `.env` and fill in the values:

```
# LLM providers (at least one required)
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=

# Redis (state store and event bus)
REDIS_URL=redis://localhost:6379

# Integrations
SENTRY_WEBHOOK_SECRET=
GITHUB_TOKEN=
SLACK_BOT_TOKEN=
SLACK_APPROVAL_CHANNEL=

# Optional: JIRA (falls back to GitHub Issues if not set)
JIRA_URL=
JIRA_TOKEN=
JIRA_PROJECT_KEY=

# Optional: event backend (default: redis)
HELIX_EVENT_BACKEND=redis

# Optional: per-agent model overrides
HELIX_DEV_PROVIDER=claude-code
HELIX_DEV_MODEL=claude-sonnet-4-6
```

## Agent models

| Agent | Provider | Model |
|---|---|---|
| Crash Handler | Anthropic | claude-haiku-4-5 |
| QA Agent | Anthropic | claude-haiku-4-5 |
| Dev Agent | Claude Code CLI | claude-sonnet-4-6 |
| Code Quality | Anthropic | claude-sonnet-4-6 |

Haiku handles structured pattern-matching tasks (crash classification, test generation). Sonnet handles deeper reasoning (writing fixes, reviewing code quality).

## Event bus

Helix supports two event backends, set via `HELIX_EVENT_BACKEND`:

| Backend | When to use |
|---|---|
| `redis` | Railway, local dev, any non-AWS deployment |
| `eventbridge` | AWS Lambda or ECS deployments |

## Hosting

| Stage | Recommended |
|---|---|
| Local dev / testing | Single process, Redis via Docker |
| MVP launch | Railway (one service per agent) + Redis Cloud |
| AWS-native | Lambda per agent + EventBridge + ElastiCache |

See `docs/architecture.md` for a full breakdown of each hosting option.

## Scope

Helix fixes **application-level bugs** only. Out of scope for MVP: infrastructure failures, performance optimisation, refactoring, mobile crashes, multi-tenant support.
