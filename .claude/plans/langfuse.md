# Plan: Add Langfuse LLM observability

## Context

Helix already has two observability backends:
- **LangSmith** — LLM call tracing via `@_langsmith_traceable` decorator + `_get_run_tree()` metadata hook in `core/llm.py`
- **OpenTelemetry** — distributed tracing via `core/telemetry.py`, spans in `complete()`

Both are opt-in and degrade gracefully when not configured. Langfuse follows the same pattern — a third optional backend that runs alongside the existing two.

Langfuse env vars: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` (optional, defaults to cloud.langfuse.com).

---

## Changes

### 1. `pyproject.toml`

Add to dependencies alongside `langsmith`:
```toml
"langfuse>=2.0",
```

### 2. `core/config.py`

Add `LangfuseConfig` dataclass after `LangSmithConfig` (line ~124):
```python
@dataclass
class LangfuseConfig:
    """Langfuse LLM observability settings."""
    secret_key: str | None   # LANGFUSE_SECRET_KEY; None → tracing disabled
    public_key: str | None   # LANGFUSE_PUBLIC_KEY
    host: str                # LANGFUSE_HOST; default: https://cloud.langfuse.com
    enabled: bool            # True when both keys are set
```

Add `get_langfuse_config()` loader (mirrors `get_langsmith_config()` pattern).

### 3. `core/llm.py`

**Import block** — add after the LangSmith try/except block (line ~51):
```python
# Langfuse tracing — gracefully disabled when not installed or keys not set.
try:
    from langfuse import Langfuse as _LangfuseClient
    _langfuse = (
        _LangfuseClient()
        if os.environ.get("LANGFUSE_SECRET_KEY")
        else None
    )
except ImportError:
    _langfuse = None
```

The client is initialised once at module load (reads env vars automatically). No per-call overhead when disabled.

**In `complete()`** — add after the LangSmith metadata block (~line 435):
```python
if _langfuse is not None:
    try:
        _langfuse.generation(
            name=f"helix.{agent}",
            model=resolved.model,
            input={"prompt": prompt, "system": system},
            output=response,
            usage={
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
            },
            metadata={"provider": resolved.provider, "agent": agent},
        )
    except Exception:
        pass
```

Update the `complete()` docstring to mention Langfuse tracing.

### 4. `config.yaml`

Add a `langfuse:` section after the `langsmith:` section:
```yaml
langfuse:
  secret_key_env: LANGFUSE_SECRET_KEY     # required to enable tracing
  public_key_env: LANGFUSE_PUBLIC_KEY     # required to enable tracing
  host_env: LANGFUSE_HOST                 # default: https://cloud.langfuse.com
                                          # set to your self-hosted URL if applicable
```

### 5. `README.md`

- Add `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` to the env vars table (optional section)
- Add Langfuse row to the observability section alongside LangSmith

---

## Files to modify

| File | Change |
|---|---|
| `pyproject.toml` | Add `langfuse>=2.0` dependency |
| `core/config.py` | Add `LangfuseConfig` dataclass + `get_langfuse_config()` |
| `core/llm.py` | Module-level client init + `generation()` call in `complete()` |
| `config.yaml` | Add `langfuse:` config section |
| `README.md` | Document env vars + observability section |

## Not changing

- `core/telemetry.py` — OTel is unchanged; Langfuse is a separate, parallel backend
- Agent files — `complete()` is the only integration point; no agent code changes needed
- `evals/` — LangSmith eval suite is unchanged; Langfuse is tracing-only for now

---

## Verification

```bash
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_PUBLIC_KEY=pk-lf-...

# Trigger a completion (any agent call will work)
python -c "
import asyncio
from core.llm import complete
asyncio.run(complete('crash_handler', 'say hello'))
"
```

Check Langfuse dashboard — a generation named `helix.crash_handler` should appear with model, tokens, prompt, and response.
