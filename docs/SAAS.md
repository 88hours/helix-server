# Helix Pro – SaaS Architecture

**Version:** 1.0
**Date:** April 2026
**Scope:** SaaS productisation of Helix (multi-tenant, paid tiers)

---

## Current State (Phases 1–6)

Helix is ~55% SaaS-ready out of the box:

| What exists | Status |
|---|---|
| Per-project credentials in Postgres (`project_settings`) | ✓ Done |
| Projects scoped to owner via `owner_sub` in Postgres | ✓ Done |
| Per-project LLM provider/model overrides | ✓ Done |
| Auth0 JWT authentication | ✓ Done |
| Per-project Sentry/Rollbar webhook secrets | ✓ Done |
| Account-level BYOK LLM keys (`user_settings`) | ✓ Done |
| Audit trail (`audit_events`) — queryable per `project_id` | ✓ Done |

| Critical gap | Impact |
|---|---|
| Incidents in Redis have no tenant prefix | Any logged-in user can read any incident |
| `/api/incidents` returns all incidents system-wide | Data leakage across customers |
| No incident-level authorization on API endpoints | Security vulnerability |
| Agents run in a shared pool, no per-customer compute boundary | Noisy neighbour risk |
| No usage tracking per project | Can't meter billing |

---

## Tenant Isolation Models

Three options, ordered by cost and complexity.

### Option A — Shared Pool + Namespace Isolation

One set of agent processes serves all customers. Tenant isolation is enforced entirely in software:

- Redis key prefix: `helix:project:{project_id}:incident:{id}:...`
- Auth check on every API endpoint validates `incident.project_id` against `user.owned_projects`
- Per-project credentials loaded at runtime from Postgres

```
Customer A ─┐
Customer B ─┼──▶ Shared agent pool ──▶ Namespaced Redis keys ──▶ Namespaced API responses
Customer C ─┘
```

**Suitable for:** 1–200 customers on a single Railway deployment; up to 1000 with Dev Agent replicas scaled out.
**Pro:** Cheapest to operate. Works on a single Railway deployment today.
**Con:** One heavy customer can slow down others. No hard compute boundary.

---

### Option B — Per-Customer Event Streams (Recommended for MVP SaaS)

Shared agent processes, but each project gets its own Redis Stream. Agents subscribe to all streams but only process events scoped to a single project at a time.

```
helix:stream:{project_id_A}:crash_analysed
helix:stream:{project_id_A}:test_case_generated

helix:stream:{project_id_B}:crash_analysed
helix:stream:{project_id_B}:test_case_generated
```

Combined with namespace isolation from Option A.

**Suitable for:** 1–500 customers.
**Pro:** Natural queue isolation. Rate limiting per customer is trivial (cap events per stream). Usage billing is easy (count events per stream).
**Con:** Subscribe logic in agents becomes slightly more complex (fan-out subscription across all project streams).

---

### Option C — Dedicated Agent Processes per Tenant

When a customer signs up, provision a dedicated set of 4 agent containers for them (via Kubernetes, Railway Environments, or Fly.io Machines).

```
Customer A ──▶ crash_handler_A + qa_A + dev_A + notifier_A ──▶ Redis namespace A
Customer B ──▶ crash_handler_B + qa_B + dev_B + notifier_B ──▶ Redis namespace B
```

**Suitable for:** Enterprise tier, $500+/mo.
**Pro:** True compute isolation. One customer's runaway incident cannot affect another. Easy to bill by container-hours.
**Con:** 4 containers per customer = cost scales linearly. Only viable at high price points.

---

## Recommended Architecture: Option B

For a $49–$199/mo product, Option B gives customers the *feel* of an isolated pipeline (their events never mix with another customer's stream) without the operational cost of dedicated containers.

### Data layer

```
Postgres (shared)
  users           — Auth0 subject, email
  projects        — owner_sub FK, name, repo
  project_settings — all credentials + agent_overrides
  usage           — NEW: token_count, incident_count, reset_at per project

Redis (shared, namespaced)
  helix:project:{project_id}:incident:{incident_id}:crash_report
  helix:project:{project_id}:incident:{incident_id}:test_case
  helix:project:{project_id}:incident:{incident_id}:pr
  helix:project:{project_id}:incident:{incident_id}:status
  helix:project:{project_id}:incident:{incident_id}:iterations

  helix:stream:{project_id}:crash_analysed        (per-project event stream)
  helix:stream:{project_id}:test_case_generated
  helix:stream:{project_id}:pr_created
```

### Agent layer

Agents subscribe to a wildcard pattern across all project streams. They load project credentials from Postgres at the start of each event and operate fully within that project's namespace.

```
QA Agent
  subscribe: helix:stream:*:crash_analysed
  on event:  load project_settings for project_id
             read crash_report from helix:project:{project_id}:incident:{id}:crash_report
             write test_case to   helix:project:{project_id}:incident:{id}:test_case
             publish to           helix:stream:{project_id}:test_case_generated
```

### API layer

Every incident endpoint must verify ownership:

```python
# Before: no check
incident = read_crash_report(incident_id)

# After: verify caller owns the project
incident = read_crash_report(project_id, incident_id)
if incident.project_id not in user_owned_project_ids:
    raise HTTPException(403)
```

---

## Expected Load at 100 Customers

| Metric | Estimate |
|---|---|
| Incidents/day (average) | 100 customers × 5 incidents = **500/day** |
| Incidents/second (average) | ~0.006/sec — negligible for Redis |
| Peak burst | ~20 simultaneous incidents (bad deploy at 9am) |
| Dev Agent wall-clock per incident | 2–10 min (clone + test + fix + PR) |
| Concurrent Dev Agent slots needed at peak | 4–6 |
| Dev Agent replicas required | 2 (handles ~4 concurrent jobs) |
| Queue drain time at peak burst | ~30 min with 2 replicas |

**Verdict:** A single Railway deployment with **2 Dev Agent replicas** handles 100 customers comfortably. The bottleneck is never Redis — it's Dev Agent concurrency, which is solved by scaling replicas, not infrastructure.

---

## SaaS Delivery Phases

### Phase 1 — Critical Security (1 week)

Fix the authorization gaps that block a safe public launch.

1. Add `project_id` namespace to all Redis state keys (`core/state.py`)
2. Update all Redis state read/write functions to require `project_id`
3. Add ownership check to `/api/incidents/{incident_id}` — validate `incident.project_id` is owned by `current_user`
4. Filter `/api/incidents` to return only incidents belonging to the caller's projects
5. Validate webhook origin: confirm `project_id` in webhook URL matches the credential used to sign the request

**Files to change:** `core/state.py`, `agents/crash_handler/main.py`

---

### Phase 2 — Per-Project Event Streams (1 week)

Isolate event delivery so customers never share a queue.

1. Update `publish()` in `core/events.py` to write to `helix:stream:{project_id}:{event}` instead of `helix:stream:{event}`
2. Update `subscribe()` to accept a project_id filter or subscribe with key pattern `helix:stream:*:{event}`
3. Update all agent subscriber loops to pass `project_id` through the event payload
4. Test that two simultaneous incidents from different projects do not interfere

**Files to change:** `core/events.py`, `agents/qa/main.py`, `agents/dev/main.py`, `agents/notifier/main.py`

---

### Phase 3 — Usage Tracking (1 week)

Enable per-project metering as the foundation for billing.

1. Add `usage` table to Postgres:
   ```sql
   CREATE TABLE usage (
     project_id    TEXT REFERENCES projects(project_id),
     period_start  TIMESTAMPTZ NOT NULL,
     incidents     INTEGER DEFAULT 0,
     llm_tokens    BIGINT  DEFAULT 0,
     github_calls  INTEGER DEFAULT 0,
     PRIMARY KEY (project_id, period_start)
   );
   ```
2. Increment `incidents` counter each time crash handler creates an incident
3. Record token counts from every LLM completion response
4. Expose `/api/usage` endpoint returning current period stats per project
5. Add usage panel to React dashboard

**Files to change:** `core/db.py`, `core/llm.py`, `agents/crash_handler/main.py`, frontend dashboard

---

### Phase 4 — Rate Limiting (3 days)

Prevent abuse and enforce plan limits.

1. Add `plan` column to `projects` table: `free | starter | pro`
2. Define limits per plan:
   ```
   free:     5 incidents/day,  50k tokens/day
   starter:  50 incidents/day, 500k tokens/day
   pro:      unlimited
   ```
3. Check limits at webhook ingress — return 429 if exceeded
4. Surface limit usage in the dashboard

---

### Phase 5 — Billing Integration (1 week)

1. Integrate Lemon Squeezy for one-time source code purchase
2. Integrate Stripe for recurring subscription plans
3. On successful payment, set `projects.plan` via webhook
4. Email invoice + access confirmation via SendGrid

---

## Bring-Your-Own-Key vs. Helix-Managed Keys

Two business models are possible:

| Model | Customer brings | Helix charges for |
|---|---|---|
| **BYOK (current)** | Anthropic API key, GitHub token, Slack token | Helix platform access only |
| **Managed** | Nothing | Helix bills per incident (includes LLM cost markup) |

**Recommendation for MVP:** Start with BYOK. It eliminates LLM cost risk, customers retain data control, and it is already implemented. Add managed mode in a later phase if customers request it.

---

## Team / Organisation Support

Not in scope for MVP SaaS. Current model: one Auth0 user = one account = N projects.

Future: add `organisations` table with many-to-many membership, role column (`admin | member | viewer`), and `org_id` foreign key on `projects`. This is Phase 6 work defined in the architecture document.

---

## Deployment Model

| Scale | Recommended stack |
|---|---|
| 1–200 customers | Railway — single deployment, default config, 2 Dev Agent replicas |
| 200–1000 customers | Railway — Dev Agent scaled to 3–5 replicas + Postgres connection pooling |
| 1000+ customers | Job queue in front of Dev Agent + Fly.io or Render with multi-region workers |

All three options use the same codebase. The only difference is the infrastructure config and the number of agent replicas.

---

## Key Files Reference

| File | Relevance to SaaS work |
|---|---|
| `core/state.py` | All Redis key builders — add `project_id` namespace here |
| `core/events.py` | `publish()` and `subscribe()` — switch to per-project streams |
| `core/db.py` | Postgres schema — add `usage` table, `plan` column |
| `core/auth.py` | JWT validation — already in place, extend to load owned project IDs |
| `core/llm.py` | LLM completions — add token count recording here |
| `agents/crash_handler/main.py` | Webhook ingress + all dashboard API endpoints — add auth checks |
| `agents/qa/main.py` | Subscriber loop — update to per-project stream |
| `agents/dev/main.py` | Subscriber loop — update to per-project stream |
| `agents/notifier/main.py` | Subscriber loop — update to per-project stream |
