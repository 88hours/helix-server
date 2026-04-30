# Helix — Dashboard Frontend

The Helix dashboard is a React single-page application served directly by the Crash Handler FastAPI process at `/app`. It streams live agent activity via Server-Sent Events and provides incident management and repo configuration.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Framework | Vite + React 18 | Fast build, HMR in dev, SPA served from FastAPI at `/app` |
| Language | TypeScript | Type safety across API contracts and component props |
| Styling | Tailwind CSS | Utility-first, no build-time stylesheet overhead |
| Routing | React Router v6 | Client-side routing with `basename="/app"` |
| Real-time | Server-Sent Events | Live incident feed without WebSocket complexity |
| Auth | Auth0 React SDK (`@auth0/auth0-react`) | GitHub OAuth via Auth0, optional (demo mode if unconfigured) |
| Package manager | pnpm | Consistent lockfile, faster installs |

---

## Routes

```
/app/                          → redirects to /app/incidents
/app/incidents                 Incident list (grouped by project, newest first)
/app/incidents/:incidentId     Incident detail (live SSE stream)
/app/projects                  Project management (create projects, configure per-project credentials)
/app/projects/new              New project wizard (repo picker → GitHub App install → credentials → done)
/app/agents                    Agent status overview
/app/settings                  Account-level settings (LLM keys, Slack, email)
/github                        GitHub page (repo list, App installation management)
```

---

## Pages

### Incident List `/app/incidents`

- Polls `GET /api/incidents` every 10 seconds
- Incidents are **grouped by project** — each group shows the project name, repo slug, and incident count
- Incidents without a matched project fall into an "Other" section
- **Status filter** — multi-select dropdown listing all 9 statuses with per-status counts and a "clear" action; closes on outside click
- Table columns per incident: incident ID (mono), status badge, severity badge, error type, affected component, **4-bar mini pipeline**, timestamp
- Mini pipeline: 4 equal-width bars coloured by agent (`--handler`, `--qa`, `--dev`, `--human`); bars after the current stage are dimmed; failed incidents show a red tint
- Clicking a row navigates to the incident detail page
- Projects whose GitHub repo is no longer accessible via the App show a yellow warning banner with a link to the GitHub page

### Incident Detail `/app/incidents/:incidentId`

- Opens an SSE connection to `GET /api/stream/:incidentId` on mount
- On connect, a `snapshot` event sends the current incident state so the UI renders immediately
- Past events are replayed from Redis on connect — the `ActivityRail` and `ToolCalls` are populated even for completed incidents
- `status_changed` SSE events trigger a full re-fetch of incident state so QA and PR sections update in real-time
- Sections (in order):
  1. **Back link + header** — incident ID, error type/message, severity and status badges, rerun + approve PR actions
  2. **Pipeline tracker** — switchable between `horizontal` (cards with → separators) and `swimlane` (agent rows with L-bend connectors); layout set in the tweaks panel
  3. **Tool call list** — structured live list of tool calls (`ToolCalls` component)
  4. **PR diff** — unified diff viewer rendered from `dev.diff` in the PR result
  5. **Crash report** — error type, component, endpoint, language, source, stack trace (expandable)
  6. **Audit trail** — filterable timeline of audit events for this incident (`AuditTrail` component)
- **Activity rail** (optional, right column) — auto-scrolling live event log; toggled via `showActivityRail` tweak

### Projects `/app/projects`

- Lists all projects the authenticated user has created
- Each project card shows the repo slug, status badge, and per-project credential health
- Projects whose GitHub repo is inaccessible show a yellow warning banner
- Create project button opens the 4-step wizard (`/app/projects/new`):
  1. Repo picker — paste any GitHub URL or `owner/name`; auto-fills project name and base branch
  2. GitHub App install — links to the App install page; saves `installation_id` on return
  3. Credential config — `ANTHROPIC_API_KEY`, `SENTRY_WEBHOOK_SECRET` / `ROLLBAR_ACCESS_TOKEN`, optional Slack + email
  4. Done — project is ready; webhook URLs are shown

### Agents `/app/agents`

- Overview of all four pipeline agents (Crash Handler, QA, Dev, Notifier)
- Shows each agent's model, provider, and current status
- Walkthrough component guides new users through the pipeline flow

### Settings `/app/settings`

- Account-level LLM key management — Anthropic, OpenRouter, Ollama `base_url`
- Slack and email notification settings
- Secret fields are masked on read; a Save button persists changes to `PUT /api/settings`

### GitHub page `/github`

- Shows all repos accessible via the authenticated GitHub App installation
- Displays Private/Public badge, default branch, and which Helix project monitors each repo
- Handles the post-install `?installation_id=` redirect and manual installation ID entry

---

## Components

```
dashboard/src/
  App.tsx                    Root: page routing, tweaks panel (density/accent/pipeline/activity rail),
                             theme + accent CSS variable updates, Auth0 token bridge
  main.tsx                   Entry: wraps App in Auth0Provider when VITE_AUTH0_DOMAIN is set
  authFetch.ts               Authenticated fetch wrapper — injects Bearer token; falls back gracefully
  constants.ts               Shared types (Agent, Incident, ToolCall, AuditEvent, etc.) and API fetch
                             helpers including useAuditEvents()
  index.css                  Global CSS custom properties; density rules via html[data-density="compact"]
  pages/
    IncidentsPage.tsx         10s polling + manual refresh, grouped by project, status multi-select filter
    IncidentDetailPage.tsx    SSE-driven detail view with event replay; passes layout to Pipeline
    ProjectsPage.tsx          Project management; live stats computed from incidents prop
    AgentsPage.tsx            Agent status overview with pipeline walkthrough
    SettingsPage.tsx          Account-level LLM keys, Slack, email settings
    GitHubPage.tsx            GitHub App repo list and installation management
    LoginPage.tsx             Auth0 login landing page with inline SVG helix logo
  components/
    Pipeline.tsx              Dual-layout pipeline: horizontal (card row) + swimlane (agent lanes with
                              L-bend CSS connectors); incidentToPipelineStages() maps status → stages
    AuditTrail.tsx            Filterable audit event timeline; filter by actor kind + full-text search;
                              expandable JSONB metadata per row
    ToolCalls.tsx             Tool call log — rendered from tool_call SSE events; PRDiff unified diff viewer
    ActivityRail.tsx          Auto-scrolling agent activity log (live event feed)
    Header.tsx                Top nav with inline SVG logo, tweaks button, user dropdown
    Walkthrough.tsx           Step-by-step pipeline explainer for new users
    primitives.tsx            Shared UI primitives — StatusPill, Severity, Icon, Button, Field
    AuthGuard.tsx             Redirects unauthenticated users to Auth0; no-op if auth disabled
```

---

## API Client

API calls use two files:

**`authFetch.ts`** — low-level authenticated fetch. Call `setTokenGetter(fn)` once on startup (done in `App.tsx` after Auth0 login); all subsequent `authFetch(url, init)` calls automatically attach `Authorization: Bearer <token>`. Falls back gracefully when no token getter is registered.

**`constants.ts`** — shared types and API fetch helpers that call `authFetch` under the hood.

### Functions (in `constants.ts`)

| Function | Method | Path | Description |
|---|---|---|---|
| `fetchIncidents()` | GET | `/api/incidents` | List all incidents |
| `fetchIncident(id)` | GET | `/api/incidents/:id` | Single incident state |
| `subscribeToIncident(id, handlers)` | EventSource | `/api/stream/:id` | Live SSE stream; returns cleanup function |
| `fetchProjects()` | GET | `/api/projects` | List user's projects |
| `fetchSettings()` | GET | `/api/settings` | Account-level LLM/notification settings |
| `saveSettings(data)` | PUT | `/api/settings` | Persist account settings |
| `fetchMe()` | GET | `/api/me` | Caller identity from JWT |
| `useAuditEvents(incidentId)` | GET | `/api/audit?incident_id=` | Audit events for an incident (hook) |

### Event types

`UIProgressEvent` is a discriminated union:

```typescript
// Agent lifecycle events — rendered in StreamPanel
type AgentProgressEvent = {
  type: 'agent_start' | 'agent_step' | 'agent_done' | 'status_changed'
  agent: string
  message: string
  incident_id: string
  timestamp: string
}

// Tool call events — rendered in ToolTimeline
type ToolCallEvent = {
  type: 'tool_call'
  agent: string
  tool: 'llm' | 'github' | 'git' | 'claude_code'
  action: string           // e.g. 'complete', 'create_issue', 'clone', 'tdd_iterate'
  status: 'success' | 'failed'
  detail: string           // e.g. '#42', '3 files', 'iteration 2/3'
  incident_id: string
  timestamp: string
}

type UIProgressEvent = AgentProgressEvent | ToolCallEvent
```

---

## Tweaks Panel

A floating settings panel toggled by the **tweaks** button in the header. Controls are persisted to `window.__TWEAKS` (session only — not stored).

| Setting | Options | Effect |
|---|---|---|
| `theme` | `light` / `dark` | Overrides CSS custom properties (`--bg`, `--ink`, `--line`, etc.) |
| `density` | `compact` / `comfortable` | Sets `html[data-density]`; CSS rules adjust padding and font sizes |
| `pipeline` | `horizontal` / `swimlane` | Passed as `layout` prop to the `Pipeline` component on incident detail |
| `accent` | `amber` / `green` / `violet` / `blue` / `ink` | Updates `--accent` CSS variable via OKLCH values |
| `activity rail` | on / off | Shows or hides the live event rail on the incident detail page |

---

## Tool Calls

The `ToolCalls` component appears on the incident detail page once the first `tool_call` event arrives. It shows every external integration call made by agents:

| Tool | Icon | Colour | Actions shown |
|---|---|---|---|
| LLM | Sparkles | Violet | `complete` (generate) |
| GitHub | GitHub logo | Gray | `create_issue`, `find_issue`, `add_comment`, `fetch_files`, `commit_push`, `create_pr` |
| Git | Terminal | Orange | `clone` |
| Claude Code | Lightning | Emerald | `tdd_iterate` |

Each row shows: tool icon, agent chip (colour-coded), tool + action label, result detail, green ✓ or red ✗, timestamp.

---

## Authentication

Auth is **optional**. The entire auth layer activates only when `VITE_AUTH0_DOMAIN` is set at build time.

### Flow
1. `main.tsx` checks `VITE_AUTH0_DOMAIN` — if set, wraps the app in `Auth0Provider`
2. `AuthGuard` calls `loginWithRedirect()` if the user is not authenticated
3. After login (GitHub OAuth via Auth0), the user is redirected back to `/app/`
4. `App.tsx` calls `setTokenGetter(getAccessTokenSilently)` to register the token supplier
5. All subsequent `authFetch` calls automatically include `Authorization: Bearer <token>`
6. The SSE stream uses `?access_token=<token>` query param (EventSource can't send headers)

### Demo mode (no auth)
When `VITE_AUTH0_DOMAIN` is not set:
- No `Auth0Provider` is mounted
- `AuthGuard` renders children immediately
- `TokenProviderBridge` and `NavUserChip` are never rendered
- The backend returns a synthetic demo user from `get_current_user()`
- All API routes work without a token

### Environment variables (frontend)

Set in `dashboard/.env.local` (git-ignored):

```
VITE_AUTH0_DOMAIN=your-tenant.auth0.com
VITE_AUTH0_CLIENT_ID=your-spa-client-id
VITE_AUTH0_AUDIENCE=https://api.helix.yourapp.com
```

The `LoginPage.tsx` component handles the in-app login landing; the Auth0 Universal Login page uses Auth0's default branding.

---

## Local Development

```bash
# Start the FastAPI backend (required — Vite proxies /api to it)
uv run uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port 8000

# In a second terminal
cd dashboard
pnpm install
pnpm dev     # http://localhost:5173/app
```

Vite proxies `/api` → `http://localhost:8000` during dev, so no CORS configuration is needed.

## Production Build (Docker)

The multi-stage `Dockerfile` builds the dashboard in a `node:20-slim` stage and copies `dashboard/dist/` into the Python image. FastAPI serves the built files at `/app/*`. No separate frontend server is needed.

```dockerfile
FROM node:20-slim AS dashboard-build
RUN npm install -g pnpm
WORKDIR /dashboard
COPY dashboard/package.json dashboard/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile
COPY dashboard/ ./
RUN pnpm build

FROM python:3.12-slim
# ... Python setup ...
COPY --from=dashboard-build /dashboard/dist ./dashboard/dist
```
