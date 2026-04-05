# Helix — Production Infrastructure (AWS)

Proposed AWS architecture for taking Helix from Railway MVP to a production-grade, multi-tenant SaaS. This document covers compute, networking, data, observability, and the migration path from the current Railway deployment.

---

## Current State (Railway MVP)

```
Internet → Railway (crash_handler) → Redis Cloud (Pub/Sub + state)
                ↓
           Railway (qa, dev, notifier) — all polling Redis
```

Four Railway services, one Redis Cloud instance, no VPC, no persistent database. Works for single-tenant early access. Does not scale to multi-tenant.

---

## Target State (AWS Production)

```
Internet
    │
    ▼
Route 53 (DNS)
    │
    ▼
CloudFront (CDN + WAF)
    │
    ├──▶ S3 (Next.js static assets)
    │
    └──▶ Application Load Balancer
              │
              ├──▶ ECS Fargate — crash_handler  (webhook receiver)
              ├──▶ ECS Fargate — api            (REST API for frontend)
              │
              └── (internal traffic only)
                        │
                        ▼
                  EventBridge (helix-prod bus)
                        │
              ┌─────────┼─────────────┐
              ▼         ▼             ▼
         ECS Fargate  ECS Fargate  ECS Fargate
            qa          dev          notifier
              │
              ▼
      ElastiCache (Redis) — state + Pub/Sub
              │
              ▼
         RDS Postgres — org config, incidents, billing
              │
              ▼
         S3 — incident archives, audit logs
```

---

## Services Breakdown

### Compute — ECS Fargate

Each agent runs as a long-lived Fargate task. Fargate is preferred over Lambda for Helix because the Dev Agent can run for several minutes (clone → iterate → PR) and Lambda's 15-minute timeout is too tight.

| Service | vCPU | Memory | Notes |
|---|---|---|---|
| crash_handler | 0.25 | 512 MB | Always-on, receives webhooks |
| api | 0.5 | 1 GB | REST API for frontend, always-on |
| qa | 0.5 | 1 GB | Scales to 0 when idle |
| dev | 1 | 2 GB | Needs headroom for repo clone + claude-code |
| notifier | 0.25 | 512 MB | Scales to 0 when idle |

**Auto-scaling:** qa, dev, and notifier scale based on EventBridge queue depth via Application Auto Scaling. crash_handler and api maintain a minimum of 2 tasks for availability.

### Container Registry — ECR

One ECR repository per service. Images are tagged by git SHA and pushed by CI (CircleCI). ECS pulls from ECR on each deployment. Lifecycle policies retain the last 10 images per repo and expire untagged images after 7 days.

### Networking — VPC

```
VPC: 10.0.0.0/16

Public subnets (2 AZs):
  10.0.1.0/24  — ALB, NAT Gateway
  10.0.2.0/24  — ALB, NAT Gateway

Private subnets (2 AZs):
  10.0.10.0/24 — ECS tasks
  10.0.11.0/24 — ECS tasks

Isolated subnets (2 AZs):
  10.0.20.0/24 — ElastiCache, RDS
  10.0.21.0/24 — ElastiCache, RDS
```

ECS tasks run in private subnets and reach the internet via NAT Gateway (for GitHub API, Anthropic API, Slack). RDS and ElastiCache are in isolated subnets with no internet access.

### Load Balancer — ALB

Single ALB with two target groups:

| Path | Target |
|---|---|
| `/webhook/*` | crash_handler ECS service |
| `/api/*` | api ECS service |

HTTPS only. HTTP redirects to HTTPS. TLS certificate from ACM (auto-renewed).

### Event Bus — EventBridge

One EventBridge bus: `helix-prod`. Rules route events to ECS task triggers via EventBridge Pipes.

| Event | Rule | Target |
|---|---|---|
| `crash_analysed` | source = `helix.crash_handler` | ECS qa task |
| `test_case_generated` | source = `helix.qa` | ECS dev task |
| `fix_suggested` | source = `helix.dev` | ECS notifier task |
| `fix_failed` | source = `helix.dev` | ECS notifier task |
| `pr_created` | source = `helix.dev` | — (archived only) |

Dead letter queue (SQS) on every rule. Failed events are retried 3 times then sent to DLQ and trigger a CloudWatch alarm.

### Cache + Pub/Sub — ElastiCache (Redis)

Single ElastiCache Serverless cluster. Automatically scales capacity. Multi-AZ with automatic failover.

Used for:
- Incident state (crash report, QA result, PR result, status, iterations)
- Redis Pub/Sub channels (same as current — no code change needed)

Encryption at rest and in transit. Auth token stored in Secrets Manager.

### Database — RDS Postgres

Required for multi-tenant SaaS features (Phase 3). Single RDS Postgres instance (db.t4g.small) with Multi-AZ standby.

Schema (initial):
```sql
organisations   — id, name, slug, plan, created_at
users           — id, org_id, email, role, auth0_id
repos           — id, org_id, github_repo, base_branch, language
incidents       — id, org_id, repo_id, status, created_at, resolved_at
api_keys        — id, org_id, key_hash, label, created_at
```

RDS Proxy sits in front of RDS to pool connections from ECS tasks.

### Object Storage — S3

Two buckets:

| Bucket | Contents |
|---|---|
| `helix-prod-frontend` | Next.js static export, served via CloudFront |
| `helix-prod-archives` | Incident archives (crash reports, test cases, PRs), audit logs |

Archive bucket has lifecycle rules: move to S3 Infrequent Access after 30 days, Glacier after 1 year.

### CDN + WAF — CloudFront

CloudFront distribution with two origins:
- `helix-prod-frontend` S3 bucket — static assets
- ALB — API and webhook traffic

AWS WAF attached to CloudFront with managed rule groups:
- Core rule set (OWASP top 10)
- Rate limiting on `/webhook/*` — 100 requests/minute per IP

### Secrets — Secrets Manager

All secrets stored in Secrets Manager. ECS tasks pull secrets at startup via IAM task role — no secrets in environment variables or ECR images.

| Secret | Contents |
|---|---|
| `helix/prod/anthropic` | `ANTHROPIC_API_KEY` |
| `helix/prod/github` | `GITHUB_TOKEN` |
| `helix/prod/rollbar` | `ROLLBAR_ACCESS_TOKEN` |
| `helix/prod/redis` | ElastiCache auth token |
| `helix/prod/postgres` | RDS credentials |
| `helix/prod/slack` | `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` |
| `helix/prod/sendgrid` | `SENDGRID_API_KEY` |
| `helix/prod/stripe` | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` |

### DNS — Route 53

| Record | Target |
|---|---|
| `helix.ai` | CloudFront distribution |
| `api.helix.ai` | CloudFront → ALB `/api/*` |
| `app.helix.ai` | CloudFront → S3 (Next.js frontend) |

---

## Observability

### Logging — CloudWatch Logs

All ECS tasks log to CloudWatch Logs. Log group per service: `/helix/prod/<service>`. Retention: 90 days.

Structured JSON logs (already implemented) make CloudWatch Logs Insights queries straightforward:

```sql
-- All events for a given incident
filter incident_id = "abc-123"
| sort @timestamp asc
```

### Metrics — CloudWatch + EMF

Key metrics emitted via Embedded Metric Format from each agent:

- `helix.incident.started` — count
- `helix.incident.resolved` — count, with `iterations` dimension
- `helix.incident.failed` — count
- `helix.agent.duration_ms` — per-agent latency
- `helix.llm.tokens_used` — by agent and model

### Alarms

| Alarm | Threshold | Action |
|---|---|---|
| DLQ depth > 0 | Any message in DLQ | PagerDuty alert |
| crash_handler 5xx rate > 1% | 5 minutes | PagerDuty alert |
| Dev Agent p95 duration > 10 min | 15 minutes | Slack alert |
| RDS CPU > 80% | 10 minutes | Slack alert |
| ElastiCache evictions > 0 | Any | Slack alert |

### Tracing — X-Ray

AWS X-Ray enabled on ECS tasks and ALB. Traces span from webhook receipt through all agent invocations to PR creation. Useful for diagnosing slow incidents.

---

## CI/CD

```
git push → CircleCI
              │
              ├── pytest (skip if only .md changes)
              ├── docker build + push to ECR (per service)
              └── ecs deploy (rolling update, one service at a time)
```

ECS rolling updates with minimum 100% healthy — no downtime during deploys. Deploy order: crash_handler → api → qa → dev → notifier.

Infrastructure managed with Terraform (one module per service). State in S3 + DynamoDB locking.

---

## IAM

Each ECS task has a dedicated IAM task role with least-privilege permissions:

| Role | Permissions |
|---|---|
| crash_handler | `secretsmanager:GetSecretValue`, `events:PutEvents`, `elasticache:Connect` |
| qa | `secretsmanager:GetSecretValue`, `events:PutEvents`, `elasticache:Connect` |
| dev | `secretsmanager:GetSecretValue`, `events:PutEvents`, `elasticache:Connect` |
| notifier | `secretsmanager:GetSecretValue`, `elasticache:Connect` |
| api | `secretsmanager:GetSecretValue`, `rds-db:connect`, `elasticache:Connect`, `s3:GetObject` |

No task role has `iam:*`, `s3:*`, or `ec2:*`.

---

## Multi-tenancy

All Postgres queries are scoped by `org_id`. Redis keys are namespaced:

```
helix:{org_id}:incident:{incident_id}:crash_report
helix:{org_id}:incident:{incident_id}:status
...
```

Agents receive `org_id` in the event payload and pass it through every Redis read/write and Postgres query.

---

## Migration from Railway

| Step | Action |
|---|---|
| 1 | Provision VPC, RDS, ElastiCache, ECR via Terraform |
| 2 | Push Docker images to ECR via CircleCI |
| 3 | Deploy ECS services (crash_handler, api first) |
| 4 | Smoke test: POST a test webhook, verify pipeline runs |
| 5 | Update Rollbar webhook URL to the new ALB endpoint |
| 6 | Run Railway and AWS in parallel for 48 hours |
| 7 | Tear down Railway services |

Zero-downtime: Rollbar webhook URL is the only external dependency. Switching it is a single config change in Rollbar.

---

## Cost Estimate (MVP scale, ~100 incidents/day)

| Service | Monthly cost |
|---|---|
| ECS Fargate (5 services) | ~$40 |
| ALB | ~$20 |
| RDS Postgres (db.t4g.small, Multi-AZ) | ~$50 |
| ElastiCache Serverless | ~$15 |
| CloudFront + S3 | ~$5 |
| EventBridge | ~$1 |
| NAT Gateway | ~$35 |
| Secrets Manager | ~$5 |
| CloudWatch | ~$10 |
| **Total** | **~$180/month** |

Scales linearly with incident volume up to ~10,000 incidents/day before needing to review RDS tier and ElastiCache capacity.
