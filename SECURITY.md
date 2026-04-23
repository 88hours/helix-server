# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Helix, please **do not open a public GitHub issue**.

Report it privately by emailing **security@88hours.co** with:

- A description of the vulnerability and its potential impact
- Steps to reproduce (proof-of-concept if possible)
- Any relevant logs, screenshots, or code references

We aim to acknowledge reports within **2 business days** and provide a fix or mitigation timeline within **7 days**.

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main`  | Yes       |

Older tagged releases do not receive security patches. Please run from `main`.

## Secrets and Credentials

Helix requires several secrets at runtime. **Never commit these to source control.**

| Secret | Purpose |
|--------|---------|
| `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` | LLM provider access |
| `GITHUB_TOKEN` | Cloning repos, creating issues and PRs |
| `SENTRY_WEBHOOK_SECRET` | HMAC-SHA256 verification of inbound Sentry webhooks |
| `ROLLBAR_ACCESS_TOKEN` | Token verification of inbound Rollbar webhooks |
| `SLACK_BOT_TOKEN` | Posting approval messages and receiving button actions |
| `SLACK_SIGNING_SECRET` | HMAC-SHA256 verification of inbound Slack interactions |
| `REDIS_URL` | Contains credentials for the state/event bus |
| `DATABASE_URL` | Postgres connection string including password |
| `JIRA_TOKEN` | Optional JIRA integration credentials |

Store all secrets in environment variables or a secrets manager (e.g. Railway secrets, AWS Secrets Manager). Never pass them as command-line arguments or log them.

## Webhook Security

- **Rollbar**: inbound webhooks are verified by comparing the `access_token` embedded in the payload against the per-project token stored in Postgres.
- **Sentry**: inbound webhooks are verified via HMAC-SHA256 signature (`sentry-hook-signature` header) using the per-project `sentry_webhook_secret`.
- **Slack**: inbound interactions are verified via HMAC-SHA256 signature (`X-Slack-Signature` header) using `SLACK_SIGNING_SECRET`. Requests older than 5 minutes are rejected.

All webhook endpoints reject unverified requests with `401 Unauthorized` before any processing occurs.

## Authentication

The dashboard API uses Auth0 JWT tokens (RS256, verified via JWKS). GitHub login is supported via Auth0. All authenticated endpoints validate the token on every request — there are no session cookies.

## Dependencies

Dependencies are pinned in `uv.lock`. Run `uv sync` to install exact versions. Known vulnerabilities in dependencies should be reported via the process above or by opening a private advisory on GitHub.
