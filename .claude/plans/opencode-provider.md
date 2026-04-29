# Plan: Add OpenCode as a Dev Agent provider

## Context

The Dev Agent's TDD loop currently supports two execution modes:
- `claude-code` — invokes `claude --dangerously-skip-permissions -p "<prompt>"` as a subprocess
- `anthropic` — direct Anthropic SDK call (no file access, less capable for full-repo editing)

The user wants to add `opencode` as a third option, allowing the Dev Agent to use OpenCode CLI (which supports Ollama and other LLMs) instead of Claude Code CLI. This is a drop-in replacement at the subprocess layer — OpenCode runs inside the cloned repo directory with full file access, just like Claude Code.

Verified invocation: `opencode run --dangerously-skip-permissions "<prompt>"` — confirmed working, produces stdout output with sentinels intact.

---

## Changes

### 1. `core/llm.py`

Add `_complete_opencode()` below `_complete_claude_code()` — structurally identical but calls `opencode run --dangerously-skip-permissions` instead of `claude --dangerously-skip-permissions -p`:

```python
async def _complete_opencode(prompt: str, cwd: Optional[str]) -> tuple[str, dict]:
    process = await asyncio.create_subprocess_exec(
        "opencode", "run", "--dangerously-skip-permissions", prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    # same timeout / logging / error handling as _complete_claude_code()
```

In `complete()`, add routing between `claude-code` and the `else` branch:
```python
elif resolved.provider == "opencode":
    response, usage = await _complete_opencode(prompt, cwd)
```

Update the `ValueError` message to include `'opencode'` in the valid providers list.

### 2. `config.yaml`

Add `opencode` to the provider options comment block:
```yaml
#   opencode    — invokes the OpenCode CLI via subprocess (Dev Agent only)
#                 configure the LLM backend in OpenCode's own config or
#                 pass --model via OPENCODE_DEFAULT_MODEL env var
```

Example to switch Dev Agent to OpenCode:
```yaml
dev:
  provider: opencode
  model: ""   # model is set in OpenCode's own config, not here
```

### 3. `docs/TECHDECISIONS.md` — TD-002

Update to note that `opencode` is also a valid TDD loop provider, relaxing the Anthropic-only gate. Append to the **Decision** section:

> **Update (April 2026):** `opencode` provider (OpenCode CLI) is now also supported for the TDD loop. OpenCode supports Ollama and other backends, so an Anthropic key is not required when using this provider. The `pr_skipped` gate applies only when the Dev Agent provider is neither `anthropic`, `claude-code`, nor `opencode`.

---

## Files to modify

| File | Change |
|---|---|
| `core/llm.py` | Add `_complete_opencode()` + routing in `complete()` + update ValueError message |
| `config.yaml` | Document `opencode` as a valid provider |
| `docs/TECHDECISIONS.md` | Update TD-002 to reflect OpenCode support |

## Not changing

- `agents/dev/agent.py` — already calls `complete(agent="dev", ..., cwd=repo_dir)`, no changes needed
- `agents/dev/prompts.py` — prompts are provider-agnostic
- `core/config.py` / `core/models.py` — no new fields needed

---

## Verification

1. Set `HELIX_DEV_PROVIDER=opencode` (or edit `config.yaml`)
2. Ensure OpenCode is installed and configured with the desired backend (Ollama, OpenAI, etc.)
3. Trigger a test incident — Dev Agent subprocess should call `opencode run --dangerously-skip-permissions "..."` in the cloned repo directory
4. Confirm `TESTS_PASSED` / `TESTS_FAILED` sentinel parsing works (output format is provider-agnostic)
