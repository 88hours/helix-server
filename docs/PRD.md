# Helix – Product Requirements Document

**Version:** 1.0
**Date:** March 2026
**Author:** Nomi

---

## Overview

Helix is an autonomous incident response and self-healing platform for software that detects crashes and errors in live production applications and resolves them automatically. It does this by mimicking the combined skills of a QA engineer, software developer, and tester through a coordinated network of AI agents. Humans remain in the loop for final approval via Slack before any fix reaches production. The result is a system that reduces bug-to-fix time from days to minutes without removing human judgment from the process.

---

## Problem Statement

When a production application crashes or an API returns a 500 error, the resolution process is slow and heavily manual. The current workflow typically looks like this:

1. Sentry detects the crash and sends a Slack notification
2. A developer reads the notification and manually creates a JIRA ticket
3. The ticket waits to be picked up in the next sprint cycle
4. A developer checks the logs, attempts to reproduce the bug, and investigates the root cause
5. The developer writes a fix, creates a pull request, and waits for code review
6. The fix is approved and released

This process can take days. During that time, the bug remains live in production, affecting real users. Each step is manual, requiring developer time and attention that could be spent on new features. Reproduction of bugs is particularly time-consuming and sometimes inconsistent.

---

## Target Users

- **Primary:** Engineering teams and software developers who maintain production applications and are responsible for resolving incidents quickly.
- **Secondary:** Product Owners and Engineering Managers who need visibility into incident resolution and make final approval decisions on production changes.

---

## Core Value Proposition

Helix reduces bug-to-fix time from days to minutes by automating the entire incident response workflow: crash detection, issue creation, reproduction, test case generation, and code fix. Developers receive a ready-to-merge pull request with a verified fix, rather than a raw crash notification to investigate manually. Human approval is always required before anything reaches production.

---

## User Flow

### Step 1: Crash Handler Agent

**Triggered by:** Sentry or Rollbar webhook

The Crash Handler Agent receives the application crash data including the error message, stack trace, application state, and any available screenshot. It analyses the data using Claude and builds a structured crash report. The report includes error classification, severity level, affected endpoints or components, and a plain-English summary of what went wrong. The agent emits a `CrashAnalysed` event to the event bus.

### Step 2: QA Agent

**Triggered by:** `CrashAnalysed` event

The QA Agent receives the crash report and performs two tasks. First, it searches existing GitHub Issues for similar open bugs. If a similar issue exists, it adds the new crash data to it. If no similar issue exists, it creates a new bug ticket. Second, it attempts to reproduce the bug by analysing the crash data, application state, and relevant code. Once reproduced, it generates a comprehensive TDD test case that asserts correct behaviour (not just that the crash occurs) and validates the test before emitting a `TestCaseGenerated` event. Supports Python, JavaScript/TypeScript, Ruby, Java/Kotlin, and Go.

### Step 3: Dev Agent

**Triggered by:** `TestCaseGenerated` event

The Dev Agent receives the test case and relevant code context. It follows TDD strictly:

1. Posts a fix suggestion to the GitHub Issue
2. Runs the test case and confirms it fails (verifying the bug is real)
3. Writes the minimum code required to make the test pass
4. Runs the full test suite to confirm nothing else is broken
5. Iterates up to three times if tests do not pass; on the fourth failure, escalates to a human with full context

Once all tests pass, the Dev Agent creates a pull request with the fix, the new test case, and a plain-English description of what was changed and why. The agent emits a `PRCreated` or `FixFailed` event.

### Step 4: Notifier Agent

**Triggered by:** `FixSuggested`, `PRCreated`, and `FixFailed` events

The Notifier Agent handles all outbound communication: fix suggestion previews, PR links with Slack Approve/Reject buttons, and escalation alerts when the Dev Agent exhausts retries. Supports Slack and email (SendGrid or SMTP fallback).

### Step 5: Human Approval

**Triggered by:** Slack Approve/Reject button

The reviewer reads the summary, reviews the PR if needed, and approves or rejects via Slack. On approval, the PR is merged and the fix is deployed.

---

## Feature Set

### Phase 1 – MVP (Core Agent Workflow)

#### Crash detection and intake
- Receive crash events from Sentry including error message, stack trace, app state, and screenshot
- Detect API 500 errors from application monitoring
- Classify crash severity as critical, high, or medium
- Build structured crash report using Claude

#### Issue management
- Search existing JIRA or GitHub Issues for similar open bugs
- Create new bug ticket with crash report if no similar issue exists
- Update existing ticket if a similar issue is found

#### Bug reproduction and test case generation
- Analyse crash data and relevant code to reproduce the bug
- Generate a comprehensive TDD test case written to fail first
- Support BDD and TDD test formats

#### Automated code fix
- Run the test case and confirm it fails
- Write a fix using TDD (minimum code to make the test pass)
- Run the full test suite and confirm no regressions
- Retry up to three times before escalating to a human developer

#### Pull request creation
- Create a pull request with the fix and test case
- Include a plain-English description of the change and rationale
- Tag the PR with Helix metadata

#### Human approval workflow
- Slack notification to designated reviewer with fix summary
- Approve or request changes directly from Slack
- On approval, merge PR and trigger deployment

---

### Phase 2 – Full-Stack Agent Experience (complete)

#### React dashboard with streaming responses
A real-time web interface showing live agent activity via SSE. As each agent works, its reasoning streams to the dashboard. Developers see which agent is active, what it is doing, and why.

#### Tool visualisation
Live tool call timeline in the dashboard showing LLM, GitHub, Git, and Claude Code calls with status and timing.

#### Auth0 + GitHub login
JWT validation via JWKS (RS256). Optional — demo mode is used when `AUTH0_DOMAIN` is not set. GitHub social login via Auth0.

#### Scoped tool access
Each agent only has permission to call the tools it needs. The Dev Agent cannot approve its own PR. The QA Agent cannot push to production. Permissions are declared per agent in `config.yaml` and enforced at runtime via `core/permissions.py`.

#### Repo and project configuration
Users add and manage repos via `/app/repos`. Projects are created with a GitHub URL, and per-project credentials (API keys, tokens, Slack, email) are configured via `/app/projects`. Secret values are masked on read.

---

### Phase 3 – Per-Project GitHub App and Platform Maturity (complete)

#### GitHub App integration
Per-project installation tokens, JWT flow, and token caching in Postgres (`core/github_app.py`). Installation tokens are threaded through all GitHub API calls, resolving 403s on repos where the fallback `GITHUB_TOKEN` lacks write access.

#### Postgres layer
`projects`, `github_installations`, and per-project settings tables (`core/db.py`). Replaces the static single-repo `config.yaml` approach with a runtime-queryable config store.

#### Per-project webhooks
Each project gets a dedicated Sentry/Rollbar webhook URL scoped to its credentials.

#### Project onboarding wizard
4-step UI: repo URL → GitHub App install → credential config → done. First step is a repo picker with auto-fill of project name and base branch from GitHub.

#### SSE event replay
Past agent events persisted to Redis and replayed on page load. ToolTimeline and StreamPanel are no longer empty for completed incidents.

---

### Phase 4 – Observability and Scale (complete)

#### LangSmith tracing and evals
Every LLM call in `core/llm.py` is traced with prompt, response, and token usage. A heuristic eval suite covers Crash Handler, QA Agent, and Dev Agent. Evaluators are pure Python — no LLM-as-judge cost. Any agent scoring below 0.8 fails the CI check. Evals run automatically on every push to `main` via GitHub Actions; skipped gracefully if API keys are absent.

#### OpenTelemetry tracing
End-to-end distributed tracing across all four agents. One parent span per incident per agent; one child span per LLM call. Key attributes: `helix.agent`, `helix.incident_id`, `helix.provider`, `helix.model`, `helix.input_tokens`, `helix.output_tokens`. Enabled via `OTEL_ENABLED=true`; exports via OTLP/gRPC to Datadog, Grafana Tempo, Jaeger, or any compatible backend. Zero overhead when disabled.

#### Per-repo Redis lock
Prevents concurrent Dev Agent workers from cloning the same repo simultaneously. Lock: `SET helix:repo_lock:{repo} {incident_id} NX EX 600`. A second incident on the same repo retries every 30 seconds for up to 6 minutes; if the lock is still held it escalates to a human.

#### Dev Agent timeout
Hard 8-minute wall-clock budget per incident (`asyncio.wait_for`). Exceeded budget escalates to human via Slack rather than holding a worker indefinitely.

---

### Phase 5 – UI, Ops, and Integration Polish (complete)

#### Rollbar webhook auth
Fixed 401 errors caused by missing `rollbar_access_token` in project settings; added payload and auth-check debug logging.

#### GitHub page
Dedicated `/github` section showing all accessible repos with Private/Public badge, default branch, and which Helix project monitors each repo. Handles post-install `?installation_id=` redirect and manual ID entry.

#### Incident list grouped by project
Incidents grouped under their project with repo slug and count. Ungrouped incidents fall into an "Other" section.

#### Incident detail live refresh
`status_changed` SSE events trigger a full re-fetch of the incident so QA and PR sections populate in real-time without a page reload.

#### Dependency security
Upgraded `pytest` and `langsmith` to resolve Dependabot alerts.

---

### Phase 6 – Multi-Tenancy and Production Scale (planned)

#### Organisations table
`org_id` threaded through all event payloads. Agents look up the correct project at runtime from `org_id` + `repo`, removing the static `config.yaml` GitHub fallback.

#### Priority queues per plan tier
Free / Pro / Team incidents route to separate Redis Stream keys. Workers poll high-priority streams first. Team orgs get dedicated worker pools.

#### Worker pool per agent
Multiple concurrent instances pulling from the same stream. ECS Fargate auto-scaling on queue depth eliminates the sequential processing bottleneck.

#### Audit trail
Queryable log of every inbound webhook, agent event, Slack action, and GitHub operation, keyed by `incident_id` and `org_id`.

---

## Out of Scope

Always out of scope (not planned for any phase):

- Automatic deployment without human approval
- Fixing infrastructure-level issues such as server outages or database failures
- Performance optimisation or refactoring (Helix fixes bugs, not technical debt)
- Support for mobile application crashes
- Real-time chat interface for interacting with agents

Deferred to Phase 6:

- Multi-tenant / multi-org support (single team or organisation through Phase 5)

---

## Key Product Decisions

### Why keep humans in the loop for approval?
Production code changes carry risk. Helix is confident in its analysis and fixes, but it is not infallible. A human reviewer provides the final quality gate, especially for complex business logic or security-sensitive code. This also builds trust in the system over time.

### Why TDD for the fix?
TDD ensures the fix addresses the root cause, not just the symptom. Writing a failing test first proves the bug is real and reproducible. Passing code proves the fix works. Running the full suite proves nothing else broke.

### Why escalate after three iterations?
If the Dev Agent fails after three iterations, it escalates to a human developer with the full context: crash report, test case, agent reasoning, and what was tried. This is better than an automated fix that does not work.

### Why use cheaper models for routine tasks?
The Crash Handler and QA agents perform largely pattern-matching and structured analysis. Claude Haiku is sufficient and significantly cheaper. The Dev Agent requires deeper reasoning and uses Claude Sonnet. This cost optimisation keeps Helix economically viable at scale.

---

## Success Metrics

### Phase 1 (MVP)
- End-to-end time from crash detection to pull request creation is under 10 minutes for reproducible bugs
- Dev Agent successfully generates a passing fix in three iterations or fewer for at least 70% of well-defined bug reports
- Human reviewer approves the fix without requesting changes in at least 60% of cases in the first month
- Developer time spent per incident is reduced to review and approval only (under 5 minutes of human time per bug)
- Monthly token cost per incident is calculated and tracked from day one

### Phase 2
- Dashboard active usage by at least 80% of the engineering team within one month of launch
- Zero unauthorised tool access incidents after OAuth2 rollout

### Phase 3
- Agent reliability measured by evals: QA Agent test case accuracy above 80%, Dev Agent fix success rate above 70%
- Mean time to resolution (MTTR) reduced by at least 60% compared to manual process baseline
- At least two other engineering teams using the Helix platform layer for their own agent workflows

---

## Development Approach

Helix is built agentic-first and event-driven. Each agent operates in its own context window with a focused purpose. Agents communicate via events (AWS EventBridge) rather than direct calls. No agent knows about or depends on another agent's internal state.

The system is built in phases: Crash Handler and QA Agent first, then Dev Agent. Each phase is validated in staging before the next phase begins. Human approval is non-negotiable at every phase of the build.

See `CLAUDE.md` for development instructions for Claude Code sessions.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| LLM | Claude Haiku 4.5 (analysis), Claude Sonnet 4.6 via Claude Code CLI (reasoning) |
| Event bus | Redis Streams (default) or AWS EventBridge |
| State store | Redis |
| Database | Postgres (projects, GitHub App installations, per-project settings) |
| Issue tracking | GitHub Issues |
| Notifications | Slack, email (SendGrid or SMTP) |
| Crash monitoring | Sentry, Rollbar |
| Frontend | React + TypeScript + Tailwind + Vite, SSE streaming |
| Auth | Auth0 (JWT/RS256 via JWKS) — optional, demo mode if not configured |
| Observability | OpenTelemetry (OTLP/gRPC), LangSmith tracing + evals |
| Hosting | Railway (default), Docker Compose (local), AWS ECS + EventBridge |
