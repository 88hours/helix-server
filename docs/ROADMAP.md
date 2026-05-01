# Helix Roadmap

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

### Phase 5 — UI, Ops, and Integration Polish (complete)
- [x] Rollbar webhook auth — fixed 401 errors caused by missing `rollbar_access_token` in project settings; added payload + auth-check debug logging to diagnose token mismatches
- [x] GitHub App Setup URL — redirect target changed to `/app/projects/new` (frontend); eliminates Auth0 session mismatch that broke the post-install callback
- [x] GitHub page — dedicated `/github` section shows all accessible repos with Private/Public badge, default branch, and which Helix project monitors each repo; handles post-install `?installation_id=` redirect and manual ID entry
- [x] Simplified project wizard — reduced from 5 steps to 4; first step is repo picker with auto-fill of project name and base branch from GitHub; GitHub connection management moved to the dedicated GitHub page
- [x] Incident list grouped by project — incidents grouped under their project with repo slug and count; ungrouped incidents fall into an "Other" section
- [x] Projects page — repo availability check on load; projects whose GitHub repo is no longer accessible via the App show a yellow warning banner with a link to the GitHub page
- [x] Incident detail live refresh — `status_changed` SSE events now trigger a full re-fetch of the incident so QA and PR sections populate in real-time without a page reload
- [x] Evals CI — eval step skips gracefully (exit 0) when `ANTHROPIC_API_KEY` or `LANGSMITH_API_KEY` secrets are not set; documented in README
- [x] Dependency security — upgraded `pytest` and `langsmith` via `uv lock` to resolve two Moderate Dependabot alerts

### Phase 6 — Multi-Tenancy and Production Scale (complete)
- [x] Account-level BYOK keys — `user_settings` Postgres table stores Anthropic, OpenRouter, and Ollama keys per user; `GET/PUT /api/settings` endpoints; Settings page in the dashboard; keys masked on read
- [x] Ollama provider — self-hosted LLM support for Crash Handler and QA agents via OpenAI-compatible API; customer provides `base_url` in project `agent_overrides`; Helix never hosts Ollama (GPU required)
- [x] Dev Agent Anthropic key gate — TDD loop skips gracefully when no Anthropic key is configured for the project; publishes `pr_skipped` event so Notifier can inform the customer
- [x] Dev Agent replica support — `deploy.replicas` in docker-compose; Redis Streams consumer groups distribute incidents across replicas automatically; no code changes required to scale
- [x] SaaS architecture documentation — `docs/SAAS.md` (tenant isolation models, expected load at 100 customers, delivery phases) and `docs/TECHDECISIONS.md` (TD-001 shared streams, TD-002 Anthropic gate, TD-003 Ollama BYOK)
- [x] Dashboard UI rebuild — new component architecture: `Pipeline`, `ActivityRail`, `ToolCalls`, `Header`, `Walkthrough`, `primitives`; all pages renamed to `*Page.tsx`; added `AgentsPage` and `SettingsPage`; removed `Repos` page
- [x] `authFetch.ts` replaces `api.ts` — cleaner token injection; `constants.ts` consolidates shared types and API helpers
- [x] Incident pipeline reliability — crash handler saves a stub report immediately on webhook receipt; any LLM or downstream failure leaves the incident in Redis with status `failed` instead of returning a 500 to the webhook caller
- [x] `core/preflight.py` — startup env-var check raises on missing LLM key; warns on missing optional vars (Sentry secret, GitHub token, Rollbar token) instead of crashing at first use
- [x] GitHub Actions release workflow — pushing a `v*` tag builds a self-contained tarball (`docker-compose.yml`, `.env.example`, `config.yaml`, `INSTALL.md`) and publishes a GitHub Release automatically
- [x] `scripts/reset_data.py` — dev utility to wipe Redis incident keys and Postgres project/settings data without restarting containers
- [x] GitHub App multi-org install flow — installation callback reliably saves `installation_id` per org
- [x] Audit trail — `audit_events` Postgres table + `core/audit.py` (fire-and-forget); hook points in `core/events.py`, `integrations/github.py`, and `agents/crash_handler/main.py`; `GET /api/audit` endpoint; `AuditTrail` React component on the incident detail page
- [x] Dashboard pipeline layouts — swimlane view (agent lanes with L-bend connectors) and horizontal card view; toggled via the tweaks panel (`Pipeline.tsx` rewrite)
- [x] Incident list status filter — multi-select dropdown for all 9 statuses; `MiniPipeline` bars replace plain status chips
- [x] Tweaks panel — density (compact/comfortable), accent colour (amber/green/violet/blue/ink), pipeline layout; accessible from the header
- [x] Projects page live stats — incident count, PR count, and merged PR count computed from live incident data (was hardcoded to 0)
- [x] Langfuse LLM observability — `core/llm.py` traces all LLM calls to Langfuse alongside LangSmith
- [x] OpenCode CLI Dev Agent provider — alternative to Claude Code CLI; supports Ollama and other non-Anthropic backends

> **Organisation/team support** (org table, org_id in payloads, per-org noisy-neighbour limits) is deferred until a customer explicitly requires it. The current single-user-per-account model handles 100+ customers on a single Railway deployment without it.

---

### Phase 7 — Scale and Axon (planned)

- [ ] Priority queues per plan tier — Free / Pro / Team incidents route to separate Redis Stream keys; workers poll high-priority streams first
- [ ] Worker pool per agent — multiple concurrent instances with Railway replica scaling or ECS Fargate auto-scaling on queue depth
- [ ] On-prem source protection — compile `agents/`, `core/`, `integrations/` to native `.so` binaries via Cython in a Docker build stage; ship the runtime image without `.py` source files; `__init__.py` stubs retained for import compatibility

#### Axon

Axon is the event-driven, distributed agent infrastructure extracted from Helix's `core/` and open-sourced as a standalone Python package. It gives other teams the event bus, shared state, and LLM routing layer without requiring them to build it from scratch — the gap that LangChain leaves unfilled for distributed, multi-process agent pipelines.

See `docs/TECHDECISIONS.md` TD-004 for why LangChain was not used and what architectural gap Axon fills.

#### Extraction — rename and parameterise (low effort)
- [ ] `events.py` — generalise `helix:stream:` prefix → configurable; rename `incident_id` → `job_id`; remove `helix-mvp` EventBridge bus hardcoding
- [ ] `llm.py` — make LangSmith run name and OTel span attribute prefix configurable; strip `helix.*` hardcoding
- [ ] `telemetry.py` — parameterise tracer scope names; no logic changes

#### Rewrites — make generic (medium effort)
- [ ] `state.py` — remove Helix-specific typed accessors (`CrashReport`, `QAResult`, `PRResult`); replace with generic `read(job_id, key)` / `write(job_id, key, value, ttl)`; users define typed wrappers on top in their own codebase
- [ ] `config.py` — extract `AgentConfig`, env override pattern, OTel/LangSmith config loading into Axon; GitHub, Sentry, Rollbar, Slack, Jira configs remain in Helix

#### New framework code
- [ ] Agent base class — `class Agent` with `subscribe_to`, `handle`, `emit` contract; each agent is an independent process triggered by an event
- [ ] `pyproject.toml` — standalone package, publish to PyPI
- [ ] One working example pipeline — independent from Helix; demonstrates the framework without requiring knowledge of the Helix product

#### Quality gate before publishing
- [ ] Tests for framework primitives — events (publish/subscribe/ack), state (read/write/TTL/lock), LLM routing
- [ ] README — architecture overview, quickstart, comparison with LangChain/Temporal

#### Post-v1 (deferred)
- [ ] CLI — `axon init`, `axon add-agent`, `axon run` for project scaffolding
- [ ] LangGraph adapter — drop-in compatibility for teams already using LangGraph agents who want durable event routing

> **When to start:** After Helix Server v1.0 ships and has paying customers. Axon is a developer acquisition channel for Helix, not a separate product — launch it once Helix has credibility behind it.
