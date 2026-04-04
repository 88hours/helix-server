[![CircleCI](https://dl.circleci.com/status-badge/img/gh/88hours/helix/tree/main.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/88hours/helix/tree/main)
# Helix

Helix is an autonomous incident response platform. It takes a production crash from Rollbar all the way to a ready-to-merge pull request in under 10 minutes, with a human approval step via Slack before anything reaches production.

## How it works

```
Rollbar crash → Crash Handler → QA Agent → Dev Agent → Code Quality Agent → Human Approval → PR merged
```

1. **Crash Handler** — receives the Rollbar webhook, classifies severity, and produces a structured crash report
2. **QA Agent** — deduplicates against open GitHub Issues, then writes a failing TDD test that reproduces the bug
3. **Dev Agent** — runs the failing test, writes the minimum fix, runs the full suite, retries up to 3 times, then opens a PR
4. **Code Quality Agent** — reviews the PR for coverage, standards, and security; routes back to Dev Agent or posts an approval request to Slack
5. **Human Approval** — reviewer clicks Approve in Slack; the PR is merged and deployed

Agents communicate via Redis Pub/Sub (or AWS EventBridge). Shared state lives in Redis, keyed by `incident_id`.

## Project structure

```
agents/
  crash_handler/       FastAPI webhook server — receives Rollbar events, publishes crash_analysed
    agent.py           Core logic: LLM analysis → CrashReport
    prompts.py         System + user prompt templates
    main.py            Entry point: POST /webhook/rollbar, GET /healthz
  qa/                  Subscribes to crash_analysed
    agent.py           GitHub Issues deduplication, repo clone, LLM test case generation
    prompts.py
    main.py            Entry point: subscriber loop
  dev/                 Subscribes to test_case_generated and quality_rejected
    agent.py           Clone → write test → claude-code fix loop → GitHub PR
    prompts.py         claude-code CLI prompt with TESTS_PASSED/TESTS_FAILED protocol
    main.py            Entry point: two concurrent subscriber loops
  notifier/            Subscribes to fix_suggested
    agent.py           Sends Slack and email notifications with a link to the fix
    main.py            Entry point: subscriber loop
  code_quality/        Subscribes to pr_created
    agent.py           Fetches PR diff, LLM review, Slack approval or quality_rejected
    prompts.py
    main.py            Entry point: subscriber loop
core/
  config.py            Typed config loaders for all agents and integrations
  events.py            EventBridge / Redis Pub/Sub publish and subscribe helpers
  state.py             Redis read/write helpers, keyed by incident_id
  models.py            Pydantic models shared across all agents
  llm.py               Routes to Anthropic SDK, OpenRouter, or Claude Code CLI
  utils.py             extract_json() — parses structured JSON from LLM output
integrations/
  rollbar.py           Access token verification + Rollbar webhook payload parsing
  github.py            Git CLI wrappers (clone, branch, commit, push) + GitHub REST API (Issues, PRs)
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
| `ROLLBAR_ACCESS_TOKEN` | Rollbar project read token — verified against `data.access_token` in each webhook payload |
| `GITHUB_TOKEN` | GitHub personal access token with `repo` + `issues` scope |
| `SLACK_BOT_TOKEN` | Slack bot token (`xoxb-...`) with `chat:write` scope |
| `SLACK_SIGNING_SECRET` | Slack app signing secret — from app settings → Basic Information |
| `SLACK_APPROVAL_CHANNEL` | Channel ID or name for approval messages |
| `SENDGRID_API_KEY` | SendGrid API key with Mail Send permission (preferred) |
| `SMTP_HOST` | SMTP server fallback, e.g. `smtp.gmail.com` (used if SendGrid key not set) |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP password or app password |
| `EMAIL_FROM` | Sender address, e.g. `helix@acme.com` |
| `EMAIL_TO` | Comma-separated recipients, e.g. `oncall@acme.com` |

See `.env.example` for the full list including optional variables.

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
  target_repo: "88hours/helix"
```

**3. Start everything**

```bash
docker compose up --build
```

This starts Redis plus all five agents. The crash handler is available at `http://localhost:8000` and the Slack approval webhook at `http://localhost:8001`.

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

### Exposing the Crash Handler to Rollbar (ngrok)

Rollbar needs a public HTTPS URL to POST webhook events to. For local development, use [ngrok](https://ngrok.com) to tunnel your local port.

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
Account        Nomi (Plan: Free)
Version        3.37.3
Region         Australia (au)
Latency        20ms
Web Interface  http://127.0.0.1:4040
Forwarding     https://carroty-cris-uncravingly.ngrok-free.app -> http://localhost:8000
```

**3. Configure the Rollbar webhook**

In Rollbar → your project → **Settings → Notifications → Webhook**, set the URL to:

```
https://carroty-cris-uncravingly.ngrok-free.app/webhook/rollbar
```

> **Note:** The ngrok URL changes each time you restart ngrok on the free plan. Update the Rollbar webhook URL whenever it changes, or use a paid ngrok plan with a fixed domain.

**4. Monitor live requests**

ngrok's web interface at `http://127.0.0.1:4040` shows every request and response in real time — useful for debugging webhook payloads.

---

### Running only the Crash Handler

Useful for developing or testing the webhook pipeline in isolation.

**1. Start Redis**

```bash
docker run -p 6379:6379 redis:7-alpine
```

**2. Start the Crash Handler**

```bash
uv run --env-file .env uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port 8000 --reload
```

The `--env-file .env` flag is required — uvicorn does not load `.env` automatically.

**3. Check it's alive**

```bash
curl http://localhost:8000/healthz
```

**4. Send a test webhook**

Save the payload to a file first (multi-line JSON in `-d` causes control character errors):

```bash
cat > /tmp/rollbar_test.json << 'EOF'
{
  "event_name": "new_item",
  "data": {
    "access_token": "<your ROLLBAR_ACCESS_TOKEN>",
    "item": {
      "id": 12345,
      "title": "KeyError: item_id",
      "level": "error",
      "environment": "production",
      "project_id": 654321,
      "last_occurrence": {
        "id": "occ-001",
        "language": "python",
        "context": "checkout.process",
        "body": {
          "trace": {
            "frames": [{"filename": "checkout.py", "lineno": 42, "method": "process", "code": "item = cart[item_id]"}],
            "exception": {"class": "KeyError", "message": "item_id"}
          }
        }
      }
    }
  }
}
EOF

curl -X POST http://localhost:8000/webhook/rollbar \
  -H "Content-Type: application/json" \
  -d @test_payloads/rollbar_new_item.json
```

Replace `<your ROLLBAR_ACCESS_TOKEN>` with the value from your `.env`. A successful request returns `202 Accepted` with an `incident_id`.

**5. Verify the result in Redis**

The 202 response includes an `incident_id`. Use it to inspect what was written to Redis:

```bash
redis-cli
```

```bash
# List all helix keys
KEYS helix:incident:*

# Check the crash report and status (replace <incident_id> with the value from the 202 response)
GET helix:incident:<incident_id>:crash_report
GET helix:incident:<incident_id>:status
```

For readable JSON output:

```bash
redis-cli GET helix:incident:<incident_id>:crash_report | python3 -m json.tool
```

**6. Run only the Crash Handler tests**

```bash
uv run pytest tests/agents/test_crash_handler.py tests/integrations/test_rollbar.py -v
```

---

### Without Docker

Each agent runs as its own process. Start them all:

```bash
# Crash Handler — webhook server (receives Rollbar events)
uv run uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port 8000

# QA Agent — subscribes to crash_analysed
uv run --env-file .env python -m agents.qa.main

# Dev Agent — subscribes to test_case_generated and quality_rejected
uv run --env-file .env python -m agents.dev.main

# Notifier Agent — subscribes to fix_suggested, sends Slack + email
uv run --env-file .env python -m agents.notifier.main

```

Point your Rollbar webhook at `http://<host>:8000/webhook/rollbar`.

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

---

## Roadmap

### Phase 1 — Make it work
- [ ] Restore Dev Agent TDD loop — clone repo, run failing test, write fix, run full suite, retry up to 3x, open GitHub PR
- [ ] Restore Human Approval workflow — Slack Approve/Reject buttons, merge PR on approval, escalate on rejection

### Phase 2 — Make it deployable
- [ ] Add Sentry integration — webhook parser + signature verification, replace Rollbar as primary crash source
- [ ] Add one-click Railway deploy button — railway.json + deploy badge in README

### Phase 3 — Make it a SaaS
- [ ] Add Postgres — store per-org config, replace static config.yaml for multi-tenant data
- [ ] Add Auth0/Clerk authentication — login/signup, org model, all resources scoped by org_id
- [ ] Add GitHub OAuth — repo connection via OAuth App instead of manual token setup
- [ ] Add Slack OAuth app install — "Add to Slack" flow, store bot token per org
- [ ] Add BYO Anthropic key — required on Free tier, optional override on paid tiers
- [ ] Add Stripe billing — Free / Pro ($49/mo) / Team ($199/mo), metered by incidents resolved
- [ ] Build onboarding wizard — connect GitHub → connect Slack → paste Sentry webhook URL → test fire
- [ ] Build incident dashboard — live incident feed, agent activity log, repo settings, usage meter

### Phase 4 — Launch
- [ ] Build landing page — value prop, how-it-works diagram, demo video, deploy button
- [ ] Record demo video — crash → test case → PR → Slack approval → merged (2 min)
