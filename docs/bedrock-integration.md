# Helix -- AWS Bedrock Integration Design

**Version:** 1.0
**Date:** May 2026
**Author:** Nomi
**Status:** Design (pre-implementation)
**Scope:** All four agents -- Crash Handler, QA, Dev, Notifier

---

## Overview

This document describes the design for adding AWS Bedrock as a first-class LLM provider in Helix. All four agents are in scope. Authentication uses the ambient IAM role attached to the host (ECS task role or EC2 instance profile) -- no credentials are stored in the database or in environment variables.

The primary use case is AWS-hosted deployments where engineering teams already have Bedrock access as part of their AWS contract and prefer to keep all LLM traffic within their AWS account boundary for compliance, data residency, or cost-consolidation reasons.

---

## Motivation

### Why Bedrock

Helix already supports Anthropic API (direct), OpenRouter, Ollama (BYOK), and Claude Code CLI. All of these require either an Anthropic API key or a personal token. Bedrock provides a fourth option for teams on AWS who:

- Have negotiated enterprise-tier Bedrock pricing as part of their AWS contract
- Must keep all LLM traffic within their AWS VPC under a specific compliance regime (HIPAA, FedRAMP, SOC 2 with strict egress controls)
- Are already running Helix on ECS Fargate and want to consolidate LLM costs into their AWS bill with a single spend commitment
- Do not want to manage a separate Anthropic API key lifecycle alongside their AWS IAM posture

### Why IAM Role Only

Storing AWS access keys per-project in `project_settings` would work, but it introduces credential rotation risk and increases the blast radius if the Postgres database is compromised. IAM role-based auth has no stored secrets -- the ECS task role is granted Bedrock invoke permissions via IAM policy and credentials rotate automatically via the instance metadata service.

This is also consistent with how Helix uses Postgres and Redis credentials: the production recommendation is Secrets Manager with IAM-based access, not environment variables.

---

## Scope and Constraints

### In scope for this design

- Adding `bedrock` as a valid provider value in `config.yaml` and `AgentOverride`
- Adding `_complete_bedrock()` to `core/llm.py` using the `AnthropicBedrock` SDK client
- Defining the Bedrock model ID mapping from Helix's internal model names
- Defining the AWS region configuration surface (`AWS_BEDROCK_REGION` env var)
- Per-agent behavior, including the Dev Agent TDD loop gate
- IAM permissions required on the task role
- Observability: LangSmith, Langfuse, and OTel span continuity
- A new TECHDECISIONS.md entry (TD-006)

### Out of scope for this design

- OpenCode CLI + Bedrock as the Dev Agent TDD loop provider (deferred, see Dev Agent section)
- Per-project Bedrock credential overrides (access key / secret) -- IAM role only in this design
- AWS PrivateLink / VPC endpoint configuration -- this is infrastructure-level and sits outside `core/`
- Bedrock model providers other than Anthropic (e.g. Amazon Titan, Meta Llama on Bedrock) -- the existing routing for those models is unaffected

---

## Authentication Design

### Credential Chain

The `AnthropicBedrock` client from the Anthropic Python SDK delegates authentication entirely to boto3. boto3 follows the standard AWS credential resolution order:

```
1. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY environment variables
2. ~/.aws/credentials shared credential file
3. AWS config file (~/.aws/config)
4. Container credential provider (ECS task role via metadata service)
5. EC2 instance metadata service (IMDSv2)
```

No code change is needed to support IAM roles. When Helix runs on ECS Fargate with a task role that has Bedrock invoke permissions, boto3 picks up the credentials automatically at step 4.

### Client Instantiation

```python
# core/llm.py

import anthropic

def _get_bedrock_client(region: str) -> anthropic.AnthropicBedrock:
    return anthropic.AnthropicBedrock(aws_region=region)
```

The client is not cached at module level because ECS task credentials rotate automatically via the metadata service. Creating a new client per completion call is safe and ensures the latest rotated credential is always used. The overhead is negligible -- the boto3 session setup is sub-millisecond.

### Region Configuration

Bedrock is regional. The region is set via an environment variable:

```
AWS_BEDROCK_REGION=us-east-1
```

Default: `us-east-1`. This is read once at startup in `core/config.py` and passed through to `_complete_bedrock()`. Agents do not need to know about the region directly.

There is no per-project region override in this design -- one Helix deployment maps to one AWS region. Multi-region deployments are separate Helix instances.

---

## Model ID Mapping

Bedrock uses its own model ID format, which differs from the Anthropic API format. Helix uses Anthropic SDK-style model names internally (`claude-haiku-4-5`, `claude-sonnet-4-6`). The Bedrock provider must translate these.

### Cross-Region Inference Profiles (Recommended)

AWS cross-region inference profiles route requests to the nearest available region within a geography and improve availability. They are identified by a geographic prefix (`us.`, `eu.`, `ap.`).

| Helix internal model name | Bedrock model ID (US cross-region) |
|---|---|
| `claude-haiku-4-5` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `claude-sonnet-4-6` | `us.anthropic.claude-sonnet-4-6-20250514-v1:0` |
| `claude-opus-4-6` | `us.anthropic.claude-opus-4-6-20250514-v1:0` |

The geographic prefix is derived from `AWS_BEDROCK_REGION`:

| Region prefix | Cross-region prefix |
|---|---|
| `us-*` | `us.` |
| `eu-*` | `eu.` |
| `ap-*` | `ap.` |

If the region does not match a known prefix, Helix falls back to the base model ID without a prefix (e.g. `anthropic.claude-haiku-4-5-20251001-v1:0`). This ensures the provider does not crash on unexpected region values.

### Mapping Implementation

```python
# core/llm.py

_BEDROCK_MODEL_IDS = {
    "claude-haiku-4-5":  "anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-sonnet-4-6": "anthropic.claude-sonnet-4-6-20250514-v1:0",
    "claude-opus-4-6":   "anthropic.claude-opus-4-6-20250514-v1:0",
}

_BEDROCK_REGION_PREFIXES = {
    "us": "us.",
    "eu": "eu.",
    "ap": "ap.",
}

def _bedrock_model_id(model: str, region: str) -> str:
    base = _BEDROCK_MODEL_IDS.get(model)
    if base is None:
        # Model name was already a Bedrock ID (caller passed a raw Bedrock ID)
        return model
    region_key = region.split("-")[0]
    prefix = _BEDROCK_REGION_PREFIXES.get(region_key, "")
    return prefix + base
```

---

## Provider Implementation

### New Function: `_complete_bedrock()`

Added to `core/llm.py` alongside the existing `_complete_anthropic()`, `_complete_openrouter()`, and `_complete_ollama()` functions.

```python
# core/llm.py

async def _complete_bedrock(
    prompt: str,
    *,
    system: str | None = None,
    model: str,
    max_tokens: int = 4096,
    region: str,
) -> str:
    bedrock_model = _bedrock_model_id(model, region)
    client = _get_bedrock_client(region)

    messages = [{"role": "user", "content": prompt}]
    kwargs: dict = {
        "model": bedrock_model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system

    response = await asyncio.to_thread(client.messages.create, **kwargs)
    return response.content[0].text
```

`asyncio.to_thread` is used because the `AnthropicBedrock` client is synchronous -- the same pattern already used for the Claude Code CLI subprocess invocation. This keeps `complete()` fully async without requiring an async Bedrock client.

### Routing in `complete()`

The existing `complete()` function in `core/llm.py` dispatches to the correct backend based on `config.provider`. Adding the `bedrock` case:

```python
async def complete(prompt: str, *, config: AgentConfig, ...) -> str:
    match config.provider:
        case "anthropic":
            return await _complete_anthropic(...)
        case "openrouter":
            return await _complete_openrouter(...)
        case "ollama":
            return await _complete_ollama(...)
        case "bedrock":                          # new
            return await _complete_bedrock(
                prompt,
                system=system,
                model=config.model,
                max_tokens=max_tokens,
                region=settings.aws_bedrock_region,
            )
        case "claude-code" | "opencode":
            return await _invoke_cli(...)
        case _:
            raise ValueError(f"Unknown provider: {config.provider}")
```

### Dependency

The `AnthropicBedrock` client is already available via the `anthropic` package (version 0.25+). No new Python dependency is introduced. boto3 is required for the credential chain but is already a transitive dependency of many AWS-related packages commonly installed in production Python environments.

If boto3 is not already present in `pyproject.toml`, add:

```toml
[project.dependencies]
boto3 = ">=1.34"
```

---

## Configuration Changes

### `config.yaml`

Two changes are needed: a new valid provider value and a default region.

```yaml
# config.yaml

settings:
  aws_bedrock_region: us-east-1   # new -- overridden by AWS_BEDROCK_REGION env var

agents:
  crash_handler:
    provider: bedrock              # new valid value
    model: claude-haiku-4-5
  qa:
    provider: bedrock
    model: claude-haiku-4-5
  dev:
    provider: claude-code          # unchanged -- see Dev Agent section
    model: claude-sonnet-4-6
  notifier:
    provider: none                 # no LLM calls -- unchanged
```

### `core/models.py`

The `AgentOverride` Pydantic model currently validates `provider` as a string with no constraint. Add `bedrock` to the documented valid values in the field description. No runtime change is needed -- validation is structural, not enum-based.

If provider is currently validated against an enum or Literal type, extend it:

```python
provider: Literal[
    "anthropic", "openrouter", "claude-code", "opencode", "ollama", "bedrock"
] | None = None
```

### `core/config.py`

Add `aws_bedrock_region` to the `Settings` config loader:

```python
class Settings(BaseSettings):
    ...
    aws_bedrock_region: str = "us-east-1"
```

This is read from the `AWS_BEDROCK_REGION` environment variable automatically via Pydantic Settings.

### `project_settings` Table

No change to the Postgres schema. Bedrock auth is IAM-based and does not require per-project credentials. The `agent_overrides` JSONB column accepts `{"crash_handler": {"provider": "bedrock"}}` without schema changes.

---

## Per-Agent Behavior

### Crash Handler

No change to the pipeline flow. The Crash Handler calls `complete()` once to produce the `CrashReport`. With `provider: bedrock`, `_complete_bedrock()` is called instead of `_complete_anthropic()`. The output schema is identical.

Recommended Bedrock model: `claude-haiku-4-5` (maps to `us.anthropic.claude-haiku-4-5-20251001-v1:0`). Same model used today via the Anthropic API.

### QA Agent

No change to the pipeline flow. The QA Agent calls `complete()` for test case generation and for validation retries. With `provider: bedrock`, all three calls route through `_complete_bedrock()`.

Recommended Bedrock model: `claude-haiku-4-5`. Same as today.

### Dev Agent -- Fix Suggestion

The Dev Agent makes one direct `complete()` call to generate the initial fix suggestion that is posted to the GitHub Issue. This call routes through `_complete_bedrock()` without any special handling.

Recommended Bedrock model: `claude-sonnet-4-6` (maps to `us.anthropic.claude-sonnet-4-6-20250514-v1:0`). Same model used today.

### Dev Agent -- TDD Loop (Gate)

The TDD loop invokes the Claude Code CLI (`claude -p`) or OpenCode CLI (`opencode run`) as a subprocess inside the cloned repo directory. Neither CLI supports Bedrock as an API endpoint -- both are hardcoded to call the Anthropic API directly.

This means the TDD loop cannot be driven by Bedrock in Phase 1. The behavior follows the same gate pattern established in TD-002:

- If `dev.provider` is `bedrock`, the fix suggestion is posted to GitHub and `fix_suggested` is emitted, but the TDD loop is skipped.
- `pr_skipped` is published with `reason: bedrock_tdd_not_supported`.
- The Notifier Agent sends the customer a Slack and email message explaining that the automated fix loop requires the Claude Code CLI or OpenCode CLI and that a manual fix is needed.
- The failing test case written by the QA Agent remains on the GitHub Issue so engineers can reproduce and fix manually.

This is a first-class supported configuration, not a failure mode. Customers using Bedrock for Crash Handler and QA get automated crash analysis, issue deduplication, and a failing test case. They do not get an automated PR. This is documented explicitly in the project settings UI.

#### Phase 2: OpenCode + Bedrock TDD Loop

OpenCode CLI uses the Vercel AI SDK internally and supports `@ai-sdk/amazon-bedrock` as a provider. A future design document will cover configuring OpenCode to use Bedrock by writing a project-scoped `~/.config/opencode/config.json` before invoking the CLI, allowing the TDD loop to run via Bedrock-hosted Claude Sonnet.

This is deferred from Phase 1 because:
- OpenCode Bedrock configuration requires writing a config file to the container filesystem, which is a side effect that does not yet have a clean abstraction in Helix
- The OpenCode Bedrock provider needs validation against the full TDD loop -- local LLM evaluations (see `helix-local-llm-evaluation.md`) showed that CLI tool calling behavior varies significantly across providers
- Claude Sonnet via Bedrock and Claude Sonnet via Anthropic API are API-compatible, so the Phase 2 path is achievable once the config injection pattern is defined

### Notifier Agent

The Notifier Agent makes no LLM calls. No changes are needed. It does need to handle the new `pr_skipped` event with `reason: bedrock_tdd_not_supported` and send an appropriate message.

```python
# agents/notifier/agent.py -- new pr_skipped handler branch

if event["reason"] == "bedrock_tdd_not_supported":
    await send_slack(
        channel=config.slack_approval_channel,
        text=(
            f"Helix analysed the crash and generated a failing test case "
            f"(issue: {event['issue_url']}), but the automated fix loop "
            f"requires the Claude Code CLI and is not available when using "
            f"the Bedrock provider. A manual fix is needed."
        ),
    )
```

---

## IAM Permissions

The ECS task role for each agent service needs the following permissions. These are added to the existing task role policy alongside the Secrets Manager and ElastiCache permissions.

### Minimum Required Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeModels",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6-20250514-v1:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-6-20250514-v1:0"
      ]
    },
    {
      "Sid": "BedrockCrossRegionInference",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-sonnet-4-6-20250514-v1:0",
        "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-opus-4-6-20250514-v1:0"
      ]
    }
  ]
}
```

`InvokeModelWithResponseStream` is included for forward compatibility with streaming responses. Phase 1 uses non-streaming completions only.

### Bedrock Model Access

IAM permissions alone are not sufficient. Each Anthropic model on Bedrock must be explicitly enabled in the AWS console:

1. Open the AWS Bedrock console
2. Navigate to Model access
3. Request access to the Anthropic Claude models required
4. Access is granted within minutes for Anthropic models (no review required in most regions)

Model access is per-region. If deploying to `us-east-1` and `eu-west-1`, access must be granted in each region independently.

### Terraform Snippet

```hcl
resource "aws_iam_role_policy" "helix_bedrock" {
  name = "helix-bedrock-invoke"
  role = aws_iam_role.helix_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvokeModels"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6-20250514-v1:0",
          "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-sonnet-4-6-20250514-v1:0",
        ]
      }
    ]
  })
}
```

---

## Observability Continuity

### LangSmith and Langfuse

`_complete_bedrock()` follows the same instrumentation pattern as `_complete_anthropic()`. The LangSmith run and Langfuse trace are created before the Bedrock call and updated with token counts from the response after it returns. No observability gaps.

The `provider` field in the LangSmith run metadata and the Langfuse span is set to `bedrock` so traces are distinguishable from Anthropic API traces in the dashboard.

### OpenTelemetry

The OTel span for each LLM call uses the `helix.*` attribute namespace. For Bedrock calls, the relevant attributes are:

```
helix.provider = "bedrock"
helix.model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"    # Bedrock model ID
helix.aws_region = "us-east-1"                                  # new attribute
helix.input_tokens = <integer>
helix.output_tokens = <integer>
```

`helix.aws_region` is a new attribute, added only when `provider == "bedrock"`. No breaking change to existing traces.

### CloudWatch

When running on ECS with the AWS distro for OTel (ADOT), Bedrock invocations appear in CloudWatch Application Signals automatically via the OTel exporter. No additional configuration is needed.

---

## Configuration Examples

### Full Bedrock deployment (all agents on Bedrock)

```yaml
# config.yaml

agents:
  crash_handler:
    provider: bedrock
    model: claude-haiku-4-5
  qa:
    provider: bedrock
    model: claude-haiku-4-5
  dev:
    provider: bedrock          # TDD loop is gated; fix suggestion still runs
    model: claude-sonnet-4-6
  notifier:
    provider: none
```

```bash
# Environment variables
AWS_BEDROCK_REGION=us-east-1
# No ANTHROPIC_API_KEY required
```

### Mixed deployment (Bedrock for analysis, Claude Code for Dev Agent)

```yaml
agents:
  crash_handler:
    provider: bedrock
    model: claude-haiku-4-5
  qa:
    provider: bedrock
    model: claude-haiku-4-5
  dev:
    provider: claude-code       # TDD loop active
    model: claude-sonnet-4-6
  notifier:
    provider: none
```

```bash
AWS_BEDROCK_REGION=us-east-1
ANTHROPIC_API_KEY=sk-ant-...    # required for Dev Agent Claude Code CLI
```

### Per-project override via project_settings

```json
{
  "agent_overrides": {
    "crash_handler": { "provider": "bedrock", "model": "claude-haiku-4-5" },
    "qa":            { "provider": "bedrock", "model": "claude-haiku-4-5" }
  }
}
```

The project-level override has no `anthropic_api_key` set. The key resolution in `core/llm.py` skips Anthropic key validation for Bedrock calls.

---

## Key Resolution Update

The existing key resolution order in `core/llm.py` is:

```
project-level anthropic_api_key -> user_settings.anthropic_api_key -> ANTHROPIC_API_KEY env var
```

For Bedrock calls, the Anthropic API key is irrelevant. The resolution logic must skip the Anthropic key check when `provider == "bedrock"`:

```python
def resolve_llm_key(config: AgentConfig, project: Project | None) -> str | None:
    if config.provider == "bedrock":
        return None    # credentials come from IAM role -- no key needed
    # existing resolution logic ...
```

The `preflight.py` startup check also needs updating. Currently it raises if no LLM key is found. With Bedrock, a deployment where `ANTHROPIC_API_KEY` is not set is valid as long as at least one agent is configured with `provider: bedrock` and the ECS task role has Bedrock permissions. The preflight check should warn, not raise, when no Anthropic key is present but a Bedrock provider is configured.

---

## Deployment Checklist

For a new deployment using Bedrock:

- [ ] Enable Anthropic Claude model access in the AWS Bedrock console for the target region
- [ ] Attach the Bedrock invoke IAM policy to the ECS task role
- [ ] Set `AWS_BEDROCK_REGION` in the ECS task environment (or rely on the default `us-east-1`)
- [ ] Set `provider: bedrock` in `config.yaml` for the target agents
- [ ] Remove or omit `ANTHROPIC_API_KEY` from the task environment (or keep it if Dev Agent uses Claude Code)
- [ ] Update Terraform with the Bedrock IAM policy resource
- [ ] Verify model access by sending a test webhook and checking the dashboard

For an existing deployment migrating from Anthropic to Bedrock:

- [ ] Complete the above steps
- [ ] Roll the ECS service to pick up the new config (rolling deploy, no downtime)
- [ ] Monitor LangSmith / Langfuse for `provider = bedrock` traces to confirm routing
- [ ] Keep `ANTHROPIC_API_KEY` in Secrets Manager until the migration is validated end to end

---

## Open Questions

**Q1: Should `bedrock` be supported on Railway deployments?**

Railway is not AWS. The IAM role approach does not apply. A Railway deployment could use Bedrock by setting `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables -- boto3 picks these up at step 1 of the credential chain -- but this is not the intended use case and requires careful secret management outside of IAM. Recommendation: document that Bedrock is an ECS/Lambda deployment feature; Railway users should use Anthropic, OpenRouter, or Ollama.

**Q2: Bedrock model availability varies by region. Should Helix validate this at startup?**

Calling `bedrock:ListFoundationModels` at startup to verify the configured model is available in the region adds an IAM permission and a round-trip. The failure mode (model not available) produces a clear `ValidationException` from Bedrock on the first completion call, which Helix already surfaces as an incident failure with a Slack escalation. Startup validation is not recommended -- the error is already handled gracefully by the existing retry and escalation path.

**Q3: Should Bedrock support streaming responses?**

Phase 1 uses non-streaming completions to match the existing `_complete_anthropic()` behavior. `AnthropicBedrock` supports streaming via `.stream()` the same way the base client does. Streaming Bedrock responses to the Helix dashboard is a Phase 2 item, consistent with how streaming is handled for other providers today.

---

## Technical Decision Record -- TD-006

### TD-006 -- AWS Bedrock added as LLM provider; IAM role auth only

**Date:** May 2026
**Status:** Design (pending implementation)

#### Decision

Add `bedrock` as a valid `provider` value in `core/llm.py`, `config.yaml`, and `AgentOverride`. Credentials come from the ambient IAM role (ECS task role or EC2 instance profile) via boto3's default credential chain. No AWS access key or secret key is stored in Postgres or environment variables.

The Dev Agent TDD loop is gated when `dev.provider == bedrock`: the fix suggestion is posted to GitHub, but the CLI subprocess is not invoked and `pr_skipped` is published with `reason: bedrock_tdd_not_supported`. All other agent LLM calls (Crash Handler, QA, Dev fix suggestion) work fully.

#### Rejected alternatives

**Per-project AWS access key in project_settings.** Storing `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` per project in Postgres introduces key rotation risk and increases the blast radius of a database compromise. IAM role auth has no stored secrets and credentials rotate automatically. Rejected.

**OpenCode CLI with Bedrock for the Dev Agent TDD loop.** OpenCode supports `@ai-sdk/amazon-bedrock` via the Vercel AI SDK. Configuring this requires writing a project-scoped config file to the container filesystem before invoking the CLI. The local LLM evaluation doc showed that CLI tool-calling behavior varies significantly across providers. Validating OpenCode + Bedrock through the full TDD loop is deferred to Phase 2 to avoid shipping an untested code path.

**Boto3 directly (without AnthropicBedrock client).** The Bedrock runtime API (`bedrock-runtime:InvokeModel`) takes a JSON body that must be formatted to Anthropic's message spec, then unwrapped from the Bedrock envelope on response. `AnthropicBedrock` from the Anthropic SDK handles this automatically and is already a dependency. Using boto3 directly adds unnecessary serialization code with no benefit.

#### Consequences

Teams running Helix on ECS can configure Bedrock as their LLM provider with no stored API keys. The Dev Agent TDD loop remains on Claude Code CLI (Anthropic API) unless the team has a separate Anthropic key. A mixed configuration -- Bedrock for Crash Handler and QA, Claude Code for Dev Agent -- is explicitly supported and documented.

The `pr_skipped` event with `reason: bedrock_tdd_not_supported` is a new event variant the Notifier Agent must handle. The Slack and email messages for this case are defined above.
