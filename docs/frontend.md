# Helix — Frontend

Proposed frontend for the Helix SaaS product. Built with Next.js 15 (App Router), TypeScript, and React.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Framework | Next.js 15 (App Router) | Server components, file-based routing, API routes for BFF pattern |
| Language | TypeScript | Type safety across API contracts and component props |
| Styling | Tailwind CSS | Fast iteration, consistent design tokens |
| Components | shadcn/ui | Unstyled, accessible components — full control over look |
| Auth | Clerk | Drop-in auth with org/team model, GitHub OAuth built-in |
| Data fetching | TanStack Query | Caching, background refetch, optimistic updates |
| Real-time | Server-Sent Events (SSE) | Live incident feed without WebSocket complexity |
| Forms | React Hook Form + Zod | Validation co-located with TypeScript types |
| Payments | Stripe.js + Elements | Embedded card form, no redirect |
| Deployment | CloudFront + S3 (static export) | See infrastructure.md |

---

## Routes

```
/                          Landing page (public)
/pricing                   Pricing page (public)

/sign-in                   Clerk sign-in
/sign-up                   Clerk sign-up
/onboarding                Onboarding wizard (new orgs)
  /onboarding/connect-github
  /onboarding/connect-slack
  /onboarding/connect-rollbar
  /onboarding/test-fire

/dashboard                 Incident feed (default view)
/dashboard/incidents       All incidents
/dashboard/incidents/[id]  Single incident detail
/settings                  Org settings
  /settings/repos          Connected repositories
  /settings/integrations   Slack, Rollbar, GitHub tokens
  /settings/team           Members and roles
  /settings/billing        Plan, usage, payment method
  /settings/api-keys       API key management
```

---

## Pages

### Landing Page `/`

Public marketing page. Sections:
- Hero: headline, sub-headline, "Deploy on Railway" button, demo GIF
- How it works: 4-step pipeline diagram (Crash → Test → Fix → PR)
- Social proof: incident count ticker, example PRs generated
- Pricing cards
- Footer: GitHub link, docs, status page

No authentication required. Statically generated.

---

### Onboarding Wizard `/onboarding`

Step-by-step setup for new organisations. Progress is saved after each step so users can drop off and return.

**Step 1 — Connect GitHub**
- GitHub OAuth via Clerk
- Repo picker: search and select the target repository
- Branch picker: default to `main`
- Helix writes a test commit to verify write access

**Step 2 — Connect Slack (optional)**
- "Add to Slack" OAuth button
- Channel picker for notifications
- Sends a test message to confirm

**Step 3 — Connect Rollbar**
- Displays the Helix webhook URL for this org
- User pastes it into Rollbar
- "Send test ping" button: fires Rollbar's test payload and waits for the 202 response
- Green tick on success

**Step 4 — Test fire**
- Optional: fire a sample crash payload to see the full pipeline run
- Live progress indicator as events flow through agents
- Shows the resulting GitHub Issue and (simulated) PR

---

### Incident Dashboard `/dashboard`

The primary view. Real-time feed of all incidents for the organisation.

**Layout**
```
┌─────────────────────────────────────────────────┐
│  Sidebar: nav links, org switcher, user avatar  │
├─────────────┬───────────────────────────────────┤
│  Filters    │  Incident feed                    │
│  Status     │  ┌─────────────────────────────┐  │
│  Severity   │  │ inc-abc123  KeyError  high   │  │
│  Repo       │  │ checkout    2 min ago   ✓ PR │  │
│  Date range │  ├─────────────────────────────┤  │
│             │  │ inc-def456  TypeError  med   │  │
│             │  │ auth        5 min ago  ↻ fix │  │
│             │  └─────────────────────────────┘  │
└─────────────┴───────────────────────────────────┘
```

**Incident card states**
- `crash_analysed` — grey dot, "Analysing"
- `test_case_generated` — blue dot, "Writing test"
- `fix_suggested` — blue dot, "Fixing"
- `pr_created` — green dot, PR link
- `fix_failed` — red dot, "Escalated", link to GitHub Issue

**Real-time updates**
SSE stream from `/api/incidents/stream?org_id=...`. The server pushes a JSON event whenever an incident's status changes. TanStack Query updates the cache on each SSE message — no polling.

---

### Incident Detail `/dashboard/incidents/[id]`

Full timeline for a single incident.

```
┌──────────────────────────────────────────────┐
│  KeyError: 'item_id'              high  ✓ PR │
│  checkout  /api/v1/checkout  2026-04-05 14:32│
├──────────────────────────────────────────────┤
│  Timeline                                    │
│                                              │
│  14:32  Crash received from Rollbar          │
│  14:32  Crash Handler — classified high      │
│  14:33  QA Agent — GitHub Issue #42 created  │
│  14:33  QA Agent — test case generated       │
│         tests/test_checkout.py::test_...     │
│  14:34  Dev Agent — fix suggestion posted    │
│  14:36  Dev Agent — PR #17 created  ↗        │
│                                              │
├──────────────────────────────────────────────┤
│  Stack Trace                                 │
│  ┌────────────────────────────────────────┐  │
│  │ File "checkout.py", line 42, in process│  │
│  │   item = cart[item_id]                 │  │
│  │ KeyError: 'item_id'                    │  │
│  └────────────────────────────────────────┘  │
├──────────────────────────────────────────────┤
│  Generated Test Case                         │
│  ┌────────────────────────────────────────┐  │
│  │ def test_checkout_returns_none_...():  │  │
│  │     result = process(item_id=None)     │  │
│  │     assert result is None              │  │
│  └────────────────────────────────────────┘  │
├──────────────────────────────────────────────┤
│  Fix Summary                                 │
│  Added a None guard before accessing         │
│  cart[item_id]. Returns None when item_id    │
│  is not in the cart.                         │
└──────────────────────────────────────────────┘
```

---

### Settings — Repos `/settings/repos`

List of connected repositories. Each row shows:
- Repo name and branch
- Language detected
- Incidents resolved (last 30 days)
- Edit / disconnect buttons

Add repo flow: GitHub OAuth repo picker → save.

---

### Settings — Billing `/settings/billing`

- Current plan (Free / Pro / Team)
- Usage meter: incidents resolved this month vs plan limit
- Upgrade / downgrade buttons
- Stripe Elements: update payment method
- Invoice history (links to Stripe-hosted PDFs)

---

## API Contract (BFF)

The Next.js app talks to a thin BFF (Backend for Frontend) layer — Next.js API routes that proxy to the Helix Python API. This keeps auth token handling server-side.

### Incidents

```
GET  /api/incidents                    List incidents (paginated, filterable)
GET  /api/incidents/:id                Single incident with full timeline
GET  /api/incidents/stream             SSE stream of status updates

Response shape:
{
  "id": "inc-abc123",
  "org_id": "org-xyz",
  "status": "pr_created",
  "severity": "high",
  "error_type": "KeyError",
  "error_message": "'item_id'",
  "affected_component": "checkout",
  "affected_endpoint": "/api/v1/checkout",
  "pr_url": "https://github.com/acme/app/pull/17",
  "ticket_url": "https://github.com/acme/app/issues/42",
  "created_at": "2026-04-05T14:32:00Z",
  "resolved_at": "2026-04-05T14:36:00Z",
  "iterations_taken": 1
}
```

### Organisations

```
GET  /api/org                          Current org settings
PUT  /api/org                          Update org settings
GET  /api/org/repos                    List connected repos
POST /api/org/repos                    Connect a repo
DEL  /api/org/repos/:id                Disconnect a repo
GET  /api/org/usage                    Incidents used this billing period
```

### Onboarding

```
GET  /api/onboarding/status            Current step + completion state
POST /api/onboarding/test-ping         Fire a test Rollbar payload
GET  /api/onboarding/test-ping/status  Poll/stream result of test ping
```

---

## Authentication

Clerk handles all auth. Organisation model: each user belongs to one org. Roles: `owner`, `admin`, `member`.

- `owner` — full access including billing and org deletion
- `admin` — full access except billing
- `member` — read-only dashboard, no settings access

GitHub OAuth via Clerk — used for repo connection. Clerk stores the GitHub OAuth token; the backend exchanges it for a scoped GitHub token when cloning repos.

All API routes check `auth()` from `@clerk/nextjs/server`. Unauthenticated requests return 401.

---

## Real-time Feed (SSE)

The incident feed uses Server-Sent Events rather than WebSockets or polling.

```typescript
// app/dashboard/page.tsx
const { data: incidents } = useQuery({
  queryKey: ['incidents', orgId],
  queryFn: fetchIncidents,
})

useEffect(() => {
  const es = new EventSource(`/api/incidents/stream?org_id=${orgId}`)
  es.onmessage = (e) => {
    const update = JSON.parse(e.data)
    queryClient.setQueryData(['incidents', orgId], (old) =>
      old.map(i => i.id === update.id ? { ...i, ...update } : i)
    )
  }
  return () => es.close()
}, [orgId])
```

The `/api/incidents/stream` Next.js route subscribes to the Redis Pub/Sub channel for the org and forwards events as SSE messages.

---

## Key Components

```
components/
  incidents/
    IncidentFeed.tsx        Virtualised list of incident cards
    IncidentCard.tsx        Single card with status indicator
    IncidentTimeline.tsx    Full event timeline for detail view
    StatusBadge.tsx         Coloured dot + label for pipeline status
    SeverityBadge.tsx       high / medium / low badge
  onboarding/
    OnboardingWizard.tsx    Step controller + progress bar
    ConnectGitHub.tsx       Repo + branch picker
    ConnectSlack.tsx        OAuth button + channel picker
    ConnectRollbar.tsx      Webhook URL display + test ping
  settings/
    RepoCard.tsx            Connected repo row
    BillingPanel.tsx        Plan + usage + Stripe Elements
    ApiKeyRow.tsx           Key label, last used, revoke button
  layout/
    Sidebar.tsx             Nav links + org switcher
    TopBar.tsx              Page title + breadcrumbs
    OrgSwitcher.tsx         Dropdown for multi-org users
```

---

## Billing Integration (Stripe)

Three plans:

| Plan | Price | Incidents/month | Features |
|---|---|---|---|
| Free | $0 | 10 | 1 repo, community support |
| Pro | $49/mo | 100 | 5 repos, Slack + email, priority support |
| Team | $199/mo | Unlimited | Unlimited repos, SSO, audit log, SLA |

Stripe Checkout for upgrades. Stripe Customer Portal for plan changes and invoice history. Stripe webhooks update the `organisations.plan` column in Postgres.

Usage-based metering: `incidents_resolved` is reported to Stripe Metered Billing at the end of each billing period for overage on the Pro plan.

---

## Folder Structure

```
helix-web/                     Separate repo (or helix/frontend/)
  app/
    (marketing)/               Route group — no sidebar layout
      page.tsx                 Landing page
      pricing/page.tsx         Pricing page
    (app)/                     Route group — authenticated + sidebar
      layout.tsx               Sidebar + auth guard
      dashboard/
        page.tsx               Incident feed
        incidents/[id]/page.tsx  Incident detail
      onboarding/
        page.tsx               Wizard controller
      settings/
        repos/page.tsx
        integrations/page.tsx
        team/page.tsx
        billing/page.tsx
        api-keys/page.tsx
    api/                       BFF routes
      incidents/
        route.ts
        [id]/route.ts
        stream/route.ts
      org/
        route.ts
        repos/route.ts
      onboarding/
        test-ping/route.ts
  components/                  Shared components (see above)
  lib/
    api.ts                     Typed API client
    auth.ts                    Clerk helpers
    stripe.ts                  Stripe client
  types/
    incident.ts                TypeScript types mirroring API response shapes
    org.ts
```
