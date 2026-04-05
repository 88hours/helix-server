# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Helix is an autonomous incident response platform. It runs a pipeline of three AI agents that take a production crash from Sentry all the way to a ready-to-merge pull request, with a human approval step via Slack before anything reaches production.

Pipeline: **Crash Handler → QA Agent → Dev Agent → Human Approval**

Agents communicate via events (AWS EventBridge or Redis Pub/Sub). State is shared through Redis, keyed by `incident_id`. No agent calls another agent directly.

## Language and style

- Python. Simple, readable, old-school syntax — functions and classes only, no decorators, no metaclasses, no clever abstractions.
- One function does one thing. If it needs a comment to explain what it does, simplify it first.
- Pydantic for all data models shared between agents.

## Architecture

```
agents/          One directory per agent, each self-contained
core/
  config.py      Loads config.yaml + env var overrides → get_agent_config(agent)
  events.py      EventBridge / Redis Pub/Sub publish and subscribe helpers
  state.py       Redis read/write helpers, keyed by incident_id
  models.py      Pydantic models shared across agents
  llm.py         Routes to Anthropic SDK, OpenRouter (openai SDK), or Claude Code CLI
integrations/    Thin wrappers: sentry, github, jira, slack
config.yaml      Model and provider config per agent (source of truth)
```

## Model configuration

Each agent's LLM provider and model is set in `config.yaml`. Environment variables override it at runtime:

```
HELIX_<AGENT>_PROVIDER   e.g. HELIX_DEV_PROVIDER=anthropic
HELIX_<AGENT>_MODEL      e.g. HELIX_DEV_MODEL=claude-sonnet-4-6
```

Provider options: `anthropic`, `openrouter`, `claude-code`.

The Dev Agent defaults to `claude-code` — it invokes the Claude Code CLI via subprocess (`claude -p "<prompt>"`) inside the cloned repo directory. All other agents make direct API calls.

## Event channels (Redis Pub/Sub)

```
helix:events:crash_analysed
helix:events:test_case_generated
helix:events:pr_created
```

EventBridge uses the same names as `detail-type` on the `helix-mvp` bus.

## Redis key structure

All keys are namespaced by `incident_id` with a 7-day TTL:

```
helix:incident:{id}:crash_report
helix:incident:{id}:test_case
helix:incident:{id}:pr
helix:incident:{id}:status
helix:incident:{id}:iterations
```

## Required environment variables

```
# At least one provider key required
ANTHROPIC_API_KEY
OPENROUTER_API_KEY

# Redis
REDIS_URL

# Integrations
SENTRY_WEBHOOK_SECRET
GITHUB_TOKEN
SLACK_BOT_TOKEN
SLACK_APPROVAL_CHANNEL

# Optional: JIRA (if not using GitHub Issues)
JIRA_URL
JIRA_TOKEN
JIRA_PROJECT_KEY

# Optional: model overrides (see config.yaml)
HELIX_<AGENT>_PROVIDER
HELIX_<AGENT>_MODEL
```

## Dev Agent behaviour

- Runs the failing test first to confirm the bug is real
- Writes the minimum fix to make the test pass
- Runs the full test suite to check for regressions
- Retries up to 3 times — on the 4th failure, escalates to a human with full context (crash report, test case, agent reasoning, what was tried)
- Creates a GitHub PR with the fix, test case, and plain-English description

## Scope (MVP only)

Helix fixes application-level bugs. Out of scope: infrastructure failures, performance optimisation, refactoring, mobile crashes, multi-tenant support. Do not add Phase 2 or Phase 3 features during MVP development.

## Future: Audit trail (post-MVP)

Every Helix API call (inbound webhooks, agent-to-agent events, Slack approval actions, GitHub PR operations) must have a complete, queryable audit trail. This is not in scope for MVP but must not be architected against. When building MVP code, avoid patterns that would make audit logging hard to add later (e.g. fire-and-forget calls with no request ID, silent swallowing of errors, missing `incident_id` context in log lines).

See `docs/PRD.md` for full product requirements and `docs/architecture.md` for detailed system design including hosting options and event schemas.
