# Plan: SaaS scaling correction + per-agent LLM + Dev Agent Anthropic gate

## Context

Three changes requested after reviewing the SaaS architecture:
1. Correct the "1–1000 customers on a single Railway deployment" claim in SAAS.md — it was optimistic. Real ceiling is ~200 on a single deployment.
2. Add per-agent LLM flexibility: QA and Crash Handler can use ollama (Qwen, GLM, etc), but Dev Agent's TDD loop only runs if the customer provides an Anthropic API key.
3. Add an ollama provider to `core/llm.py` so customers can point QA/Crash Handler at a self-hosted model.
4. Record both decisions in TECHDECISIONS.md.

---

## Expected incident volume at 100 customers

- 100 customers × ~5 incidents/day average = **500 incidents/day**
- Peak burst (bad deploy at 9am): ~20 simultaneous incidents
- Dev Agent per incident: 2–10 min wall-clock
- With 2 Dev Agent replicas: handles ~4 concurrent jobs → queue drains in ~30 min at peak burst
- Verdict: **single Railway deployment + 2 Dev Agent replicas comfortably handles 100 customers**

---

## Changes

### 1. Update `docs/SAAS.md`

- Remove "1–1000 customers on a single Railway deployment" from Option A
- Add an **Expected Load at 100 Customers** section with the numbers above
- Correct the scaling table at the bottom:
  - 1–200 customers → single deployment, default config
  - 200–1000 → Dev Agent scaled to 3–5 replicas + Postgres pooling
  - 1000+ → job queue + multi-region

### 2. Add ollama provider to `core/llm.py`

Ollama is **never hosted by Helix**. GPU requirements and model weight sizes (4–6 GB per model) make bundling in the Dockerfile or running as a Railway service impractical. Instead, customers self-host Ollama and provide their `base_url` in project settings. Helix calls it as an OpenAI-compatible endpoint.

For customers who want managed open-weight models with no self-hosting, OpenRouter (already implemented) is the recommended path — it supports Qwen, Mistral, DeepSeek, and others via a single API key.

Add client code only:

```python
async def _complete_ollama(prompt, model, system, base_url, **kwargs):
    # OpenAI-compatible client pointed at customer-provided Ollama base URL
    # e.g. "http://my-server:11434/v1" — set in project_settings.agent_overrides
    # No API key needed (pass "ollama" as placeholder)
    client = AsyncOpenAI(base_url=base_url, api_key="ollama")
    ...
```

Wire it into the `complete()` dispatch at lines 282–292.

**File:** `core/llm.py`

### 3. Add `base_url` to `AgentOverride` model

Ollama needs a base URL to reach the self-hosted instance. Add one optional field to `AgentOverride`:

```python
class AgentOverride(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None   # NEW — required when provider = "ollama"
```

`ProjectConfig.agent()` in `core/config.py` (lines 644–664) already passes provider/model through — extend it to pass `base_url` into `AgentConfig` as well.

**Files:** `core/models.py`, `core/config.py`

### 4. Add Anthropic key gate to Dev Agent

In `agents/dev/main.py`, after loading per-project config (line ~112) and before calling `handle()` (line ~116), add:

```python
dev_cfg = pc.agent("dev") if pc else get_agent_config("dev")
anthropic_key = (pc._project.settings.anthropic_api_key if pc else None) or os.getenv("ANTHROPIC_API_KEY")

if dev_cfg.provider in ("anthropic", "claude-code") and not anthropic_key:
    logger.warning(
        "incident_id=%s project_id=%s Skipping TDD loop — no Anthropic API key configured for this project",
        incident_id, project_id,
    )
    # Publish a degraded result so Notifier can inform the customer
    await publish("pr_skipped", {"incident_id": incident_id, "project_id": project_id, "reason": "no_anthropic_key"})
    continue
```

No changes needed inside `agent.py` — the gate is at the subscriber loop level so the whole `handle()` call is skipped cleanly.

**File:** `agents/dev/main.py`

### 5. Update `docs/TECHDECISIONS.md`

Add two entries:

**TD-002 — Dev Agent requires Anthropic key; TDD loop is skipped otherwise**
- Decision: Dev Agent's TDD loop only runs when `anthropic_api_key` is set for the project (or ANTHROPIC_API_KEY env var is present). Without it, a `pr_skipped` event is published and Notifier informs the customer.
- Reason: TDD loop calls `claude -p` via subprocess (Claude Code CLI) or the Anthropic SDK directly. Neither works without an Anthropic key. Failing silently or crashing mid-incident is worse than a clear gate at ingress with a user-facing message.

**TD-003 — Ollama supported as BYOK (customer self-hosted), never hosted by Helix**
- Decision: Add ollama as a 4th LLM provider (OpenAI-compatible). Crash Handler and QA can use it via `agent_overrides[agent].base_url` pointing to a customer-provided Ollama instance. Dev Agent excluded (see TD-002). Helix never runs Ollama itself.
- Reason: Ollama requires a GPU for usable inference speed (CPU = 1–5 tok/s, too slow for the pipeline). Railway has no GPU instances. Model weights are 4–6 GB, making Docker bundling impractical. Customers who want managed open-weight models should use OpenRouter instead (already implemented, supports Qwen/Mistral/DeepSeek/GLM).

---

## Critical files

| File | Change |
|---|---|
| `docs/SAAS.md` | Correct scaling claims, add incident volume section |
| `docs/TECHDECISIONS.md` | Add TD-002 and TD-003 |
| `core/llm.py` | Add `_complete_ollama()`, wire into `complete()` dispatch |
| `core/models.py` | Add `base_url: Optional[str]` to `AgentOverride` |
| `core/config.py` | Pass `base_url` through `ProjectConfig.agent()` and `AgentConfig` |
| `agents/dev/main.py` | Add Anthropic key gate before `handle()` call |

---

## Verification

1. Set `agent_overrides = {"qa": {"provider": "ollama", "model": "qwen2.5", "base_url": "http://localhost:11434/v1"}}` for a test project — QA agent should use ollama, Dev Agent should use Anthropic.
2. Remove `anthropic_api_key` from a test project — Dev Agent should log the warning, publish `pr_skipped`, and Notifier should fire.
3. Run existing test suite — no regressions in LLM routing or config resolution.
