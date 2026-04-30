# Helix Pro – Technical Decisions

A living record of architectural decisions, the reasoning behind them, and what was rejected.

---

## TD-001 — Redis Streams: Shared stream over per-project streams

**Date:** April 2026
**Status:** Decided

### Decision

Use a single shared Redis Stream per event type, with `project_id` embedded in every message payload. Do not create per-project streams.

```
helix:stream:crash_analysed        → all projects
helix:stream:test_case_generated   → all projects
helix:stream:pr_created            → all projects
```

Each message carries:
```python
{
    "incident_id": "...",
    "project_id":  "...",   # tenant scoping lives in the payload
    "data":        "...",
}
```

### Rejected alternative: per-project streams

```
helix:stream:proj_A:crash_analysed
helix:stream:proj_B:crash_analysed
...
```

### Reasons

**1. Redis consumer groups handle fan-out natively on a shared stream.**
One consumer group, one stream cursor, delivery-once guarantee, automatic retries — all built in. With per-project streams, agents would need to discover and subscribe to N streams dynamically. Redis has no native pattern-subscribe for streams, so we'd have to poll for new stream keys on startup, re-scan when a new project is created, and maintain a live list of active streams in memory or Postgres. That is complexity we build and maintain ourselves with no benefit at our scale.

**2. Redis Streams are fast enough that shared streams will never be the bottleneck.**
Redis handles 100k–500k messages/second on modest hardware. At 500 customers × 20 incidents/day, Helix generates ~0.1 incidents/second. A single shared stream handles tens of thousands of paying customers without saturation. We will hit LLM API rate limits, GitHub rate limits, or Claude call costs long before Redis stream throughput is a concern.

**3. Lower memory footprint.**
Redis has per-stream metadata overhead. One shared stream with `MAXLEN 50000` uses less total memory than 500 per-project streams each with `MAXLEN 1000`.

**4. Rate limiting is cleaner at ingress.**
The main argument for per-project streams is backpressure — stop reading a stream to pause a customer. Instead, we enforce rate limits at webhook ingress: if a project is over its daily limit, return 429 and never write the event. The stream stays clean regardless of topology.

### When to revisit

If a single customer generates enough volume that their events measurably delay other customers' processing — visible in per-project processing latency metrics — split that customer onto a dedicated stream. This is a good problem to have and will be obvious in monitoring before it causes harm.

---

## TD-002 — Dev Agent TDD loop requires an Anthropic API key; skipped otherwise

**Date:** April 2026
**Status:** Decided

### Decision

Dev Agent's TDD loop only runs when an Anthropic API key is available for the project (`project_settings.anthropic_api_key` or the global `ANTHROPIC_API_KEY` env var) **or** when the Dev Agent is configured to use the `opencode` or `claude-code` provider. Without an Anthropic key and without one of these CLI providers, the agent logs a warning, publishes a `pr_skipped` event with `reason: no_anthropic_key`, and moves on. No exception is raised.

**Update (April 2026):** `opencode` provider (OpenCode CLI) is now supported as an alternative to `claude-code`. OpenCode supports Ollama and other backends, so no Anthropic key is required when using this provider. The `pr_skipped` gate applies only when the Dev Agent provider is neither `anthropic`, `claude-code`, nor `opencode`.

### Rejected alternative: fail loudly / raise an exception

Crashing mid-incident with an unhandled `EnvironmentError` leaves the incident in an ambiguous state in Redis and gives the customer no actionable signal. A clean skip with a published event is recoverable — the Notifier can catch `pr_skipped` and send the customer a message explaining what to do.

### Reasons

**1. The TDD loop is fundamentally Anthropic-dependent.**
Dev Agent calls `claude -p` via Claude Code CLI (provider `claude-code`) or the Anthropic SDK directly (provider `anthropic`). Both require an Anthropic API key. There is no equivalent substitute — other providers do not support the tool-use and agentic code-editing behaviour that makes the TDD loop work.

**2. Failing silently or crashing is worse than a clear gate.**
Customers who haven't added their Anthropic key should get a clear message, not a silent no-op or a 500 error buried in logs.

**3. Consistent with BYOK model.**
Helix is BYOK (bring your own key). It is expected and valid for a customer to use OpenRouter or Ollama for Crash Handler and QA but not have an Anthropic key. The gate makes this a first-class supported configuration rather than an accidental failure mode.

### What this enables

A customer can run Crash Handler and QA on cheap open-weight models (via OpenRouter or self-hosted Ollama) and only pay for Anthropic when they want automated PRs. Helix degrades gracefully rather than refusing to run at all.

---

## TD-004 — LangChain not used

**Date:** April 2026
**Status:** Decided (rejected)

### Decision

Do not introduce LangChain (or `langchain-core`, `langchain-community`) as a dependency. All LLM routing, agent orchestration, and provider abstraction is handled by `core/llm.py` and the existing agent architecture.

### Rejected alternative: adopt LangChain for agent orchestration and LLM routing

### Reasons

**1. Conflicts with the codebase philosophy.**
`CLAUDE.md` requires simple, readable, old-school Python — functions and classes only, no clever abstractions. LangChain is decorator-heavy, uses deep inheritance chains, and stacks abstractions on abstractions. It would actively fight the style of every file in this repo.

**2. `core/llm.py` already does what LangChain's model layer provides.**
Multi-provider routing across Anthropic, OpenRouter, Ollama, and Claude Code CLI is already implemented. LangChain's `ChatModel` abstraction would be a redundant layer on top of working code with no added capability.

**3. The Dev Agent's core mechanism is outside LangChain's scope.**
The Dev Agent invokes the Claude Code CLI via subprocess inside a cloned repo directory. LangChain has no abstraction for shell-invoked agentic tools with full file access. That code would still need to be written from scratch regardless.

**4. The event-driven architecture does not fit LangChain's agent loop model.**
LangChain agents assume a synchronous request-response or internal tool loop. Helix agents are decoupled processes that communicate via Redis Streams. LangChain would add an abstraction layer that conflicts with this model rather than supporting it.

**5. Versioning instability is a production liability.**
LangChain has a history of breaking changes between minor versions and mid-flight package splits (`langchain` → `langchain-core` → `langchain-community`). Adding it as a dependency introduces ongoing maintenance cost with no offsetting benefit.

**6. Competing abstractions with Pydantic models.**
All shared data models (`CrashReport`, `QAResult`, `PRResult`) are Pydantic. LangChain has its own message and document types. Any integration point would require translation between them.

### What LangChain would offer (and why it does not apply here)

- **Community integrations** (GitHub, Slack, document loaders): Helix already has thin wrappers in `integrations/` covering the same ground.
- **LCEL prompt chains**: Neither Crash Handler nor QA Agent requires complex branching chains — each makes 1–2 direct LLM calls.
- **LangSmith native tracing**: LangSmith tracing is already wired in `core/llm.py` via the SDK directly. It does not require LangChain.

### When to revisit

If a future agent requires a complex multi-step tool loop that the Claude Code CLI cannot handle and that would take significant custom code to build, evaluate LangChain's LCEL + tool-use primitives at that point. For the current four-agent pipeline this threshold is not met.

---

## TD-003 — Ollama supported as BYOK (customer self-hosted); never hosted by Helix

**Date:** April 2026
**Status:** Decided

### Decision

Ollama is a supported LLM provider for Crash Handler and QA agents. Customers configure it via `project_settings.agent_overrides`:

```json
{
  "qa": { "provider": "ollama", "model": "qwen2.5", "base_url": "http://my-server:11434/v1" }
}
```

Helix calls it as an OpenAI-compatible endpoint. No Ollama binary, model weights, or GPU is provisioned by Helix. Dev Agent cannot use Ollama (see TD-002).

### Rejected alternatives

**Bundle Ollama in the Dockerfile:** Model weights are 4–6 GB per model. The Docker image becomes 6–8 GB, Railway rebuild times exceed 10 minutes, and cold starts are unusable. Rejected.

**Run Ollama as a separate Railway service:** Railway has no GPU instances. CPU inference on a 7B model yields ~1–5 tokens/second. A QA agent generating 800 tokens takes 3–15 minutes — longer than the Dev Agent timeout. Rejected.

### Reasons

**1. GPU is required for usable inference speed.**
At CPU speeds (1–5 tok/s), a single QA completion blocks the pipeline for minutes. Customers who want self-hosted Ollama already have a GPU server or a cloud GPU instance (RunPod, Vast.ai, ~$0.30/hr). Helix does not need to provide this.

**2. OpenRouter is the better managed alternative.**
OpenRouter already supports Qwen, Mistral, DeepSeek, GLM, and Llama via a single API key. It is already implemented in `core/llm.py`. Customers who want open-weight models without self-hosting should use OpenRouter — adding Ollama to our Railway infrastructure would duplicate that capability at significant operational cost.

**3. Consistent with BYOK model.**
Helix charges for platform access, not LLM inference. Customers own their inference costs and infrastructure. This keeps Helix's operating costs predictable regardless of model size or usage volume.

### Implementation

- `core/models.py` — `AgentOverride.base_url: Optional[str]` added
- `core/config.py` — `AgentConfig.base_url: Optional[str]` added; `ProjectConfig.agent()` passes it through
- `core/llm.py` — `_complete_ollama()` added; `complete()` accepts optional pre-resolved `config` param for per-project routing

---

## TD-005 — Langfuse added alongside LangSmith for LLM observability

**Date:** May 2026
**Status:** Decided

### Decision

Both **Langfuse** and **LangSmith** are used for LLM observability. Each LLM call in `core/llm.py` sends a trace to whichever backends are configured. Either can be used independently; both can run simultaneously.

### Reasons

**1. Langfuse is self-hostable.**
LangSmith is SaaS-only. Customers with data-residency requirements can run Langfuse on their own infrastructure and point Helix at it via `LANGFUSE_HOST`. LangSmith has no equivalent.

**2. Different pricing models.**
Langfuse has a generous free tier and predictable per-event pricing. LangSmith free tier limits are lower for high-volume evals. Having both means customers can choose based on their usage.

**3. No additional complexity at the call site.**
Both backends are optional. `core/llm.py` checks for keys at call time and fires to whichever are present. Call sites do not change.

### Rejected alternative: Langfuse-only

LangSmith evals are already wired into CI (`evals.yml`). Removing LangSmith would require rewriting the eval runner. Not worth the churn.

### Activation

Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` (and optionally `LANGFUSE_HOST` for self-hosted). LangSmith remains active independently via `LANGSMITH_API_KEY`.
