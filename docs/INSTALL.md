# Helix Server — Self-Hosting Guide

Helix Server runs entirely on your own infrastructure. Your API keys and code never leave your machine.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) (v2.20+)
- 1 GB RAM minimum (2 GB recommended)
- An Anthropic or OpenRouter API key (at least one required)

---

## 1. Download the release

Download the latest release archive from the [GitHub releases page](https://github.com/88hours/helix-server/releases) and extract it:

```bash
tar -xzf helix-server-vx.0.0.tar.gz
cd helix-server-vx.0.0
```

Or clone the repo directly:

```bash
git clone https://github.com/88hours/helix-server.git
cd helix-server
```

---

## 2. Configure your environment

```bash
cp .env.example .env
```

Open `.env` and fill in the values. Every variable is explained below.

### Required

```env
# At least one LLM provider key is required.
# Helix will refuse to start if neither is set.
ANTHROPIC_API_KEY=sk-ant-...
# OPENROUTER_API_KEY=sk-or-...   # alternative to Anthropic
```

### GitHub — choose one approach

**Option A: Personal access token (simplest)**

Create a token at https://github.com/settings/tokens with `repo` scope.

```env
GITHUB_TOKEN=ghp_...
```

**Option B: GitHub App (recommended for multi-repo or team use)**

Follow the GitHub App setup in section 6 below, then set:

```env
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=/run/secrets/github_app.pem
GITHUB_APP_INSTALLATION_ID=78901234
```

### Error monitoring (optional — enable the sources you use)

```env
# Sentry
SENTRY_WEBHOOK_SECRET=...

# Rollbar
ROLLBAR_ACCESS_TOKEN=...
```

Helix will log a warning and continue if either is missing. Only configure the ones you use.

### Slack (optional — for PR approval notifications)

```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_APPROVAL_CHANNEL=#helix-approvals
```

### Email alerts (optional — SendGrid or SMTP)

```env
# SendGrid
SENDGRID_API_KEY=SG....
EMAIL_FROM=helix@yourcompany.com
EMAIL_TO=oncall@yourcompany.com

# Or plain SMTP
SMTP_HOST=smtp.yourcompany.com
```

### Database and Redis (optional overrides)

By default Helix starts its own Redis and Postgres containers. To use external instances:

```env
REDIS_URL=redis://your-redis-host:6379
DATABASE_URL=postgresql://user:password@your-db-host:5432/helix
```

### Auth (optional — skip for local/internal use)

```env
# Leave unset to run in demo mode (no login required).
AUTH0_DOMAIN=yourapp.us.auth0.com
AUTH0_AUDIENCE=https://helix.yourcompany.com
```

---

## 3. Start Helix

```bash
docker compose up --build
```

The first build takes 2–3 minutes. Once running:

- Dashboard: http://localhost:8000/app
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/healthz

All four agents (crash_handler, qa, dev, notifier) start automatically. Redis and Postgres are included — no separate setup needed.

---

## 4. Test your first webhook

Send a test Sentry payload to confirm the pipeline is reachable:

```bash
curl -X POST http://localhost:8000/webhook/sentry/test-project \
  -H "Content-Type: application/json" \
  -d '{"action": "ping"}'
```

Expected response: `{"status": "ok"}`

For a real end-to-end test, create a project in the dashboard first, then use the webhook URL shown in the project settings.

---

## 5. Personal GitHub token vs GitHub App

| | Personal token | GitHub App |
|---|---|---|
| Setup | 2 minutes | 15 minutes |
| Scope | Your personal account | Any org or repo |
| Best for | Solo developers, single repo | Teams, multiple repos |
| Expiry | Optional, up to 1 year | Never (rotated automatically) |

Start with a personal token (`GITHUB_TOKEN`). Upgrade to a GitHub App when you need multi-repo or team access.

---

## 6. GitHub App setup (optional)

1. Go to https://github.com/settings/apps/new (or your org's equivalent)
2. Set the **App name** to `Helix` (or anything you like)
3. Set **Homepage URL** to your Helix instance URL (e.g. `https://helix.yourcompany.com`)
4. Set **Callback URL** to `https://helix.yourcompany.com/api/github/callback`
5. Under **Permissions**, enable:
   - Repository: Contents (Read & Write), Pull requests (Read & Write), Issues (Read & Write)
6. Generate a **private key** and save the `.pem` file
7. Install the app on the repos you want Helix to access
8. Note the **App ID** and **Installation ID** from the app settings page

Set `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, and `GITHUB_APP_INSTALLATION_ID` in your `.env`.

### Known issue: callback URL not reached during install

If the GitHub redirect after install does not land correctly, paste the `installation_id` manually in the dashboard:

1. Go to **Settings → GitHub App** in the Helix dashboard
2. Enter the Installation ID (found at `https://github.com/settings/installations`)
3. Click **Save**

This is a known workaround during the beta. The automatic callback will be fixed in a future release.

---

## 7. Upgrading

Pull the latest image and restart:

```bash
docker compose pull
docker compose up -d
```

Database schema updates are applied automatically on startup — no manual migration step.

To pin to a specific version, edit `docker-compose.yml` and replace `latest` with the version tag (e.g. `v1.1.0`).

---

## Troubleshooting

**Helix refuses to start with "No LLM provider key set"**
Set `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY` in your `.env`.

**Dashboard shows "Database not configured"**
`DATABASE_URL` is not set and the local Postgres container is not running. Run `docker compose up` (not just the crash_handler service).

**Webhook returns 401**
Your `SENTRY_WEBHOOK_SECRET` or `ROLLBAR_ACCESS_TOKEN` in `.env` does not match what the external service is sending. Double-check both sides.

**Logs for a specific service**
```bash
docker compose logs -f crash_handler
docker compose logs -f dev
```
