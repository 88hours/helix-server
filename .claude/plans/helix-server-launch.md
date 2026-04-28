# Plan: Helix Server — Self-Hosted Product Launch

## Context

Sell Helix as a downloadable, on-premises product ("Helix Server") alongside the existing Community version (open-source, free). Customers run it on their own infrastructure and bring their own API keys — Anthropic, GitHub, Sentry/Rollbar, Slack. No data or keys ever touch Helix's servers, eliminating the API key trust concern entirely.

Distribution model: Community (free, GitHub repo) + Helix Server (paid, single plan).

---

## Is the current system ready to sell?

**Yes for a technical beta audience. Three gaps need fixing first.**

Already solid:
- `docker compose up --build` brings up the full stack in one command (Redis, Postgres, 4 agents)
- Auth0 is 100% optional — demo mode is the default, customers can skip it entirely
- All secrets stay on the customer's machine — nothing transmitted to Helix's servers
- Graceful degradation: Slack, email, OpenRouter, Ollama, LangSmith, OTel are all optional
- DB schema auto-creates on first boot (`CREATE TABLE IF NOT EXISTS`) — no migration step
- Personal `GITHUB_TOKEN` works as a simple fallback before setting up a GitHub App

**Three gaps before selling:**

| Gap | Severity | Required fix |
|---|---|---|
| No preflight env var check | Medium | App starts without `ANTHROPIC_API_KEY`, fails on first incident with a cryptic error |
| No self-hosting guide | High | Customer must read the full README to know what to configure |
| GitHub App callback bug | Low | Known workaround exists (paste installation_id manually) — must be documented clearly |

---

## Pricing

Two-tier: **Community** (free, OSS) + **Helix Server** (paid, single plan).

| | |
|---|---|
| **Price** | $299 / month  or  $2,990 / year (~2 months free) |
| **Repos** | Unlimited |
| **Incidents** | Unlimited |
| **Includes** | All agents, dashboard, GitHub App, Ollama/OpenRouter support, email support, stable release builds |

**Rationale:**
- Zero hosting cost to you — customer runs it on their own infra
- Saves engineering teams ~$21,600/year at 5 incidents/day, 10% fix rate, $120/hr
- Comparable SaaS tools (PagerDuty $250/mo, Incident.io $500/mo) don't auto-fix code
- Customer also pays Anthropic API costs — price needs to feel proportionate
- 50 customers = $150K ARR with no infra cost

**Community vs Helix Server distinction:**
Community = open-source repo, self-support, no updates guarantee.
Helix Server adds: email support SLA, private stable release channel, license key for enterprise procurement.

**Payment infrastructure:** Polar.sh or LemonSqueezy — both issue license keys, support monthly/annual billing, designed for developer tools. No billing code to build.

---

## What needs to be built

### 1. Preflight startup check

New `core/preflight.py` — `check_required_env()` runs in crash_handler lifespan startup.

- **Hard fail** (raises `RuntimeError`): no LLM provider key set (must have at least one of `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`)
- **Warn only** (logs clearly, continues): `SENTRY_WEBHOOK_SECRET`, `ROLLBAR_ACCESS_TOKEN`, `GITHUB_TOKEN` missing

```python
# core/preflight.py
import os, logging
logger = logging.getLogger(__name__)

def check_required_env():
    has_llm = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not has_llm:
        raise RuntimeError(
            "No LLM provider key set. Set ANTHROPIC_API_KEY or OPENROUTER_API_KEY in your .env file."
        )
    for var in ("SENTRY_WEBHOOK_SECRET", "ROLLBAR_ACCESS_TOKEN", "GITHUB_TOKEN"):
        if not os.environ.get(var):
            logger.warning("Optional env var %s not set — related features will be disabled.", var)
```

Wire into `agents/crash_handler/main.py` lifespan:
```python
from core.preflight import check_required_env

@asynccontextmanager
async def lifespan(app):
    check_required_env()   # <-- add this line
    await init_db()
    ...
```

**Files:** `core/preflight.py` (new), `agents/crash_handler/main.py` (2-line change)

---

### 2. `docs/INSTALL.md` — self-hosting guide

Separate from README. Sections:
1. Prerequisites (Docker + Docker Compose, 1 GB RAM minimum)
2. Download the release archive (link to GitHub releases)
3. `cp .env.example .env` — fill in each variable with inline explanation
4. Personal GitHub token (simple) vs GitHub App (multi-project) — when to use each
5. First webhook test with `curl`
6. GitHub App setup step-by-step — include the "paste installation_id manually" workaround
7. Upgrading to a new version (`docker compose pull && docker compose up -d`)

**File:** `docs/INSTALL.md` (new)

---

### 3. Landing page update (`index.html`)

Current landing has a single SaaS CTA. Add a **"Self-Host Helix Server"** section:
- Headline: "Your infrastructure. Your keys. Your data."
- Body: 2–3 sentences on privacy + control
- Single pricing card: $299/mo or $2,990/yr
- Two CTAs: "Download" (→ GitHub releases) and "Get a license key" (→ Polar.sh / LemonSqueezy)
- Small "Community edition is free and open-source" note below

**File:** `index.html` (existing)

---

### 4. GitHub release packaging

GitHub Actions workflow that fires on `v*` tags and produces a release asset:
- `helix-server-v{version}.tar.gz` containing `docker-compose.yml`, `.env.example`, `config.yaml`, `docs/INSTALL.md`
- Customers download the tarball — no need to clone the repo
- Semver tags let customers pin to a version

**File:** `.github/workflows/release.yml` (new)

---

### 5. License key enforcement (defer until after beta)

Polar.sh / LemonSqueezy issue a `HELIX_LICENSE_KEY` per purchase. At startup, call their validation API with the key. If invalid, log an error and refuse to start. This is not DRM — it's an enterprise procurement signal and a mechanism to track active installs.

**Skip for first 10 paying customers.** Rely on trust during beta.

---

## Launch sequence

1. Build `core/preflight.py` + `docs/INSTALL.md` — minimum needed before sharing a download link
2. Update `index.html` with self-host section and single pricing card
3. Tag `v1.0.0`, GitHub Actions produces the release tarball
4. Set up Polar.sh / LemonSqueezy product page
5. First 5 customers: beta pricing (50% off) in exchange for written feedback
6. Add license key enforcement after beta

---

## Critical files

| File | Change |
|---|---|
| `core/preflight.py` | New — preflight env check |
| `agents/crash_handler/main.py` | Wire preflight into lifespan (2 lines) |
| `docs/INSTALL.md` | New — self-hosting guide |
| `index.html` | Add self-host section + pricing card |
| `.github/workflows/release.yml` | New — release tarball on git tag |

---

## Verification

- `docker compose up --build` with empty `.env` → preflight exits with clear error message naming the missing var
- `docker compose up --build` with minimal `.env` (just `ANTHROPIC_API_KEY` + `GITHUB_TOKEN`) → app starts, dashboard loads at `http://localhost:8000/app`
- Curl a test Sentry payload → incident flows through pipeline, dashboard shows live progress
- Landing page: self-host section renders on mobile and desktop; pricing card links to payment page
- `git tag v1.0.0 && git push origin v1.0.0` → GitHub Actions creates release with tarball attached
