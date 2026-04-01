# Helix – Architecture Document (MVP)

**Version:** 1.0
**Date:** March 2026
**Scope:** Phase 1 – Core Agent Workflow

---

## System Overview

Helix is an event-driven, multi-agent system. Each agent is an independent Python process with a single responsibility. Agents do not call each other directly — they communicate exclusively through AWS EventBridge. This decouples agents, allows each to scale independently, and makes the system easy to debug and extend.

```
Sentry / App Monitor
        │
        ▼
┌───────────────────┐
│  Crash Handler    │──── CrashAnalysed ────▶ EventBridge
│  Agent            │
└───────────────────┘
                                │
                                ▼
                    ┌───────────────────┐
                    │   QA Agent        │──── TestCaseGenerated ────▶ EventBridge
                    └───────────────────┘
                                │
                                ▼
                    ┌───────────────────┐
                    │   Dev Agent       │──── PRCreated ────▶ EventBridge
                    └───────────────────┘
                                │
                                ▼
                    ┌───────────────────┐
                    │  Code Quality     │──── Slack notification
                    │  Agent            │──── (or back to Dev Agent)
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
| Trigger | Sentry webhook or API 500 error event |
| Model | Claude Haiku |
| Input | Error message, stack trace, app state, screenshot (optional) |
| Output | Structured crash report |
| Emits | `CrashAnalysed` event |

**Responsibilities:**
- Receive and validate the incoming crash payload
- Classify severity: `critical`, `high`, or `medium`
- Identify affected endpoint, component, and service
- Generate a plain-English summary of the failure
- Persist the crash report to Redis
- Emit `CrashAnalysed` to EventBridge

---

### QA Agent

| Property | Detail |
|---|---|
| Trigger | `CrashAnalysed` event |
| Model | Claude Haiku |
| Input | Crash report from Redis |
| Output | Bug ticket (created or updated) + TDD test case |
| Emits | `TestCaseGenerated` event |

**Responsibilities:**
- Query JIRA or GitHub Issues for similar open bugs
- Create a new ticket or append to an existing one
- Pull relevant source code for context
- Reproduce the bug scenario from the crash data
- Write a failing TDD test case that captures the exact failure
- Persist the test case to Redis
- Emit `TestCaseGenerated` to EventBridge

---

### Dev Agent

| Property | Detail |
|---|---|
| Trigger | `TestCaseGenerated` event |
| Model | Claude Sonnet |
| Input | Test case + relevant source code from Redis |
| Output | Code fix + passing test suite + pull request |
| Emits | `PRCreated` event |
| Max iterations | 3 |

**Responsibilities:**
- Run the test case and confirm it fails (prove the bug is real)
- Write the minimum code change to make the test pass
- Run the full test suite to check for regressions
- Retry up to 3 times if tests do not pass
- On success: open a pull request with the fix, test case, and plain-English description
- On failure after 3 iterations: escalate to human developer with full context
- Emit `PRCreated` to EventBridge

---

### Code Quality Agent

| Property | Detail |
|---|---|
| Trigger | `PRCreated` event |
| Model | Claude Sonnet |
| Input | Pull request diff and metadata |
| Output | Quality report + Slack notification or feedback to Dev Agent |
| Emits | `QualityApproved` or `QualityRejected` |

**Responsibilities:**
- Review the PR for test coverage, code standards, and design patterns
- Flag security vulnerabilities or performance regressions
- If approved: send fix summary and quality report to human reviewer via Slack
- If rejected: send structured feedback back to Dev Agent (triggers retry cycle)

---

## Event Schema

All events are published to a single EventBridge event bus (`helix-mvp`). Each event follows this envelope:

```json
{
  "source": "helix.<agent-name>",
  "detail-type": "<EventName>",
  "detail": {
    "incident_id": "uuid",
    "timestamp": "ISO-8601",
    "payload": { ... }
  }
}
```

### CrashAnalysed

```json
{
  "incident_id": "uuid",
  "severity": "critical | high | medium",
  "error_type": "string",
  "error_message": "string",
  "stack_trace": "string",
  "affected_component": "string",
  "affected_endpoint": "string",
  "summary": "string",
  "raw_payload": { ... }
}
```

### TestCaseGenerated

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
    "format": "pytest | unittest"
  },
  "relevant_files": ["string"]
}
```

### PRCreated

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

### QualityApproved

```json
{
  "incident_id": "uuid",
  "pr_url": "string",
  "quality_report": {
    "test_coverage": "string",
    "standards_check": "passed | failed",
    "security_check": "passed | failed",
    "notes": "string"
  }
}
```

### QualityRejected

```json
{
  "incident_id": "uuid",
  "pr_url": "string",
  "feedback": "string",
  "iteration": "integer"
}
```

---

## State Management

Redis is the shared state store. Agents read and write state keyed by `incident_id`.

### Key Structure

| Key | Type | Content |
|---|---|---|
| `helix:incident:{id}:crash_report` | Hash | Full crash report |
| `helix:incident:{id}:test_case` | Hash | Test case content and metadata |
| `helix:incident:{id}:pr` | Hash | PR URL, branch, fix summary |
| `helix:incident:{id}:status` | String | Current pipeline stage |
| `helix:incident:{id}:iterations` | Integer | Dev Agent retry count |

TTL: 7 days per incident key.

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

### Redis Pub/Sub as Event Bus

EventBridge can be replaced with Redis Pub/Sub as the event routing mechanism. This is simpler to set up and removes the AWS dependency entirely — a good fit if hosting on Railway.

#### How it works

Each agent subscribes to a channel on startup. When an agent completes its work, it publishes an event to the next agent's channel. Redis delivers the message immediately to all active subscribers.

```
Crash Handler publishes → channel: helix:events:crash_analysed
QA Agent subscribes    → channel: helix:events:crash_analysed

QA Agent publishes     → channel: helix:events:test_case_generated
Dev Agent subscribes   → channel: helix:events:test_case_generated

Dev Agent publishes    → channel: helix:events:pr_created
Code Quality subscribes→ channel: helix:events:pr_created
```

#### Channel naming convention

```
helix:events:<event_name>
```

Examples:
- `helix:events:crash_analysed`
- `helix:events:test_case_generated`
- `helix:events:pr_created`
- `helix:events:quality_approved`
- `helix:events:quality_rejected`

#### Pub/Sub vs EventBridge

| | Redis Pub/Sub | AWS EventBridge |
|---|---|---|
| Setup complexity | Low — one Redis connection | Medium — AWS account, rules, targets |
| Cost | Included in Redis plan | $1 per million events |
| Delivery guarantee | At-most-once (no persistence) | At-least-once with retry |
| Audit trail | None built-in | Full event history in CloudWatch |
| Dead letter handling | Manual | Built-in DLQ support |
| Best for | Railway / simple deployments | AWS-native deployments |

**Recommendation:** Use **Redis Pub/Sub** when hosting on Railway or a VPS. Use **EventBridge** when hosting on AWS (Lambda/ECS) where the audit trail and DLQ support are worth the setup cost.

#### Important caveat

Redis Pub/Sub is fire-and-forget. If an agent is not running when a message is published, the message is lost. For MVP this is acceptable — a Sentry alert will re-trigger the pipeline. For production, add a Redis Stream (`XADD` / `XREAD`) as a durable alternative that persists messages until consumed.

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
│   │   ├── agent.py
│   │   ├── parser.py
│   │   └── classifier.py
│   ├── qa/
│   │   ├── agent.py
│   │   ├── issue_search.py
│   │   └── test_generator.py
│   ├── dev/
│   │   ├── agent.py
│   │   ├── fix_writer.py
│   │   └── test_runner.py
│   └── code_quality/
│       ├── agent.py
│       └── reviewer.py
├── core/
│   ├── events.py          # EventBridge publish/subscribe helpers
│   ├── state.py           # Redis read/write helpers
│   ├── models.py          # Shared data models (Pydantic)
│   └── llm.py             # Claude API wrapper (Haiku / Sonnet)
├── integrations/
│   ├── sentry.py
│   ├── github.py
│   ├── jira.py
│   └── slack.py
├── docs/
│   ├── PRD.md
│   └── architecture.md
├── tests/
├── CLAUDE.md
└── pyproject.toml
```

---

## Data Flow Summary

```
1. Sentry webhook → Crash Handler Agent
   - Parses and classifies crash
   - Writes crash_report to Redis
   - Publishes CrashAnalysed to EventBridge

2. EventBridge → QA Agent
   - Reads crash_report from Redis
   - Searches JIRA/GitHub for duplicates
   - Creates or updates ticket
   - Generates failing test case
   - Writes test_case to Redis
   - Publishes TestCaseGenerated to EventBridge

3. EventBridge → Dev Agent
   - Reads crash_report + test_case from Redis
   - Clones target repo, runs failing test
   - Writes fix, runs full suite
   - Retries up to 3x
   - Creates PR on GitHub
   - Writes pr metadata to Redis
   - Publishes PRCreated to EventBridge

4. EventBridge → Code Quality Agent
   - Reads PR diff from GitHub
   - Reviews quality
   - If pass: notifies Slack reviewer
   - If fail: publishes QualityRejected → Dev Agent retries

5. Slack → Human Reviewer
   - Reviewer clicks Approve
   - Webhook triggers PR merge via GitHub API
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

**Why EventBridge over direct agent calls?**
Agents are fully decoupled. A failed agent does not cascade. Each agent can be redeployed independently. EventBridge also provides a built-in audit trail of every event in the pipeline.

**Why Redis for state?**
Agents are stateless processes. Redis provides fast, shared, ephemeral storage keyed by incident ID. No database migrations, no schema changes — just key-value reads and writes.

**Why clone the repo at runtime?**
Avoids the complexity of a persistent code sync mechanism in MVP. The target repo is cloned once per incident into a temp directory, used by the QA and Dev agents, then discarded.

**Why separate models per agent?**
Crash Handler and QA are structured analysis tasks — Haiku is fast and cheap. Dev Agent and Code Quality require deeper reasoning — Sonnet is worth the cost. This model routing is centralised in `core/llm.py`.
