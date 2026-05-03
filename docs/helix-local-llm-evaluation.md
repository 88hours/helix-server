# Helix Server - Local LLM Evaluation Notes
Date: 2026-05-04

## Context

helix-server runs an autonomous TDD bug-fixing pipeline. The flow is:

1. Clone a GitHub repo and create a branch
2. Write a failing test for a reported bug
3. Call an LLM subprocess to run pytest, identify the bug, apply a fix, and re-run tests
4. Parse TESTS_PASSED or TESTS_FAILED from the subprocess output
5. Open a PR if passing

The goal was to run this pipeline entirely with local models via Ollama to avoid API costs and latency.

---

## Models Tested

### qwen2.5-coder (via Ollama + opencode)

**Result: Unusable**

Tool calls appeared in the content field of the response instead of the tool_use field. This is an Ollama 0.22.1 bug with this model. The fix would require upgrading Ollama, which was not pursued.

### deepseek-coder-v2 (via Ollama + opencode)

**Result: Unusable**

Does not support tool calling at all. Ruled out immediately.

### qwen3.6 (via Ollama + opencode)

**Result: Not tested properly**

Model name casing caused a ProviderModelNotFoundError in opencode. Fixed by using correct casing (Qwen3.6:latest) and creating an alias via `ollama cp`. However, the opencode issues described below were already blocking progress at this point.

### gemma4 (via Ollama + opencode)

**Result: Unusable due to opencode tool descriptions**

gemma4 refused to use tools. Root cause traced via HTTP proxy: opencode sends tool descriptions that contain instructions like "avoid ls, echo, grep" which gemma4 follows too literally and declines to call any shell commands. opencode's tool schema and prompts are written specifically for Claude and do not transfer well to smaller local models.

Additionally, opencode requires a `description` field in bash tool calls which gemma4 omits, causing the tool call to fail silently and the model to give up.

### gemma4 (via Ollama + Goose)

**Result: Partially working, not production-ready**

Switching from opencode to Goose resolved the tool-use refusal issue. gemma4 successfully called the shell tool without hesitation in isolation. However, three blockers emerged in the full TDD loop:

**Blocker 1 - Dependency installation errors**

The cloned test repo required `uv sync` before running pytest. In earlier runs the model tried `uv pip install -e .` which failed with a setuptools.backends error. After updating the prompt to use `uv sync`, this was resolved.

**Blocker 2 - Hallucinated tools**

gemma4 tried calling `read_file` and `bash`, neither of which exist in Goose. Goose only provides `shell`, `tree`, and `edit`. The model was not told this and tried tools from its training data.

**Blocker 3 - Writes prose instead of applying fixes**

This was the final and fatal blocker. After correctly running pytest and reading the traceback, gemma4 consistently wrote a markdown explanation of the proposed fix instead of calling the shell tool to apply it. Multiple prompt iterations did not resolve this reliably:

- Adding "Do not write explanations. Only call tools." had no effect.
- Providing an explicit python3 -c template did not change the behaviour.
- The model also proposed the wrong fix in some runs (replacing KeyError with ValueError when the test expected no exception at all), suggesting it does not reliably reason about what the test actually asserts.

The underlying issue is that gemma4 at 4B parameters treats code generation as a text completion task. When asked to fix a bug, its trained behaviour is to write the fix as text, not to use tools to apply it.

### devstral-small-2 (via Ollama + Goose)

**Result: Closest yet, but not production-ready**

devstral-small-2 is a Mistral model purpose-built for agentic coding tasks. It was a meaningful step forward over gemma4.

**What worked:**

- Called the shell tool immediately and without prompting.
- Ran pytest with the correct test path and parsed the traceback correctly.
- In the first successful run identified `payload['amount']` as the bug and applied `payload.get('amount', 0)` — the correct minimal fix. The test passed.

**Blocker 1 - Never outputs the completion sentinel**

Regardless of how Step 5 was phrased — plain text `TESTS_PASSED`, `echo TESTS_PASSED` shell command, `touch task_passed` file creation — the model always ended its session with "Task completed." Helix could not detect that the bug was fixed and burned all 3 iterations retrying an already-solved problem.

Multiple sentinel strategies were attempted:
- Parse `TESTS_PASSED` text from response → model outputs "Task completed." instead.
- `echo TESTS_PASSED` shell command → model outputs "Task completed." instead.
- `touch task_passed` / `touch task_failed` file creation → model created `TODO.md` and `readme.md` instead.
- `write` tool to create `TESTS_PASSED` file → not tested before the model was ruled out.

**Blocker 2 - Occasionally rewrites entire source files**

In two of three runs the model replaced `fastapi_error.py` wholesale with a hallucinated FastAPI app of its own design, destroying the original code. The next iteration then failed with `ImportError: cannot import name 'trigger_key_error'` — a regression caused by the agent itself. A `RULE: NEVER use the write tool on source files` instruction was added but not tested before the model was ruled out.

**Summary:** devstral-small-2 can reason about the bug and apply the correct fix. The blocker is reliability of the agentic loop — it does not consistently complete Step 5 or constrain itself to surgical edits. The `edit` tool (targeted line replacement) rather than `write` (full file overwrite) may address the second blocker; the sentinel problem likely requires an out-of-band check by Helix rather than trusting the model's output.

---

## Infrastructure Work Completed

These changes are now in helix-server and are working regardless of model choice:

### Ollama remote access

Added systemd override on the Ubuntu machine to bind Ollama to 0.0.0.0 instead of localhost, allowing the Mac to reach it over the local network on port 11434.

File: `/etc/systemd/system/ollama.service.d/override.conf`

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```

### opencode config

`~/.config/opencode/config.json` requires `provider` (singular) not `providers`. The correct format for a local Ollama endpoint:

```json
{
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama",
      "baseURL": "http://192.168.1.9:11434/v1",
      "apiKey": "ollama"
    }
  }
}
```

### Goose integration in core/llm.py

Added Goose as the subprocess runner with the following flags:

```
goose run --no-session --model gemma4 --system "..." --debug --text "..."
```

Added two environment variables:

- `HELIX_DEV_GOOSE_MODEL` - defaults to `ollama/gemma4`
- `HELIX_DEV_GOOSE_SYSTEM` - system prompt override for local models

### Short TDD prompt

Added `build_tdd_short()` in `agents/dev/prompts.py` for local models, selecting it when the model provider is `ollama/` or `openai-compatible/`. The full Claude TDD prompt is too long and causes smaller models to write planning essays instead of calling tools.

---

## Conclusions

| Component | Verdict |
|---|---|
| Ollama for model serving | Works fine. Remote access, OpenAI-compatible API, tool calling schema all functional. |
| opencode as subprocess wrapper | Not suitable for local models. Tool descriptions are Claude-specific and cause refusals. |
| Goose as subprocess wrapper | Better fit. No restrictive tool descriptions. Model calls tools without refusal. |
| gemma4 (4B) for agentic coding | Not viable. Cannot reliably apply file edits via tools across arbitrary repos and errors. |
| devstral-small-2 (via Goose) | Partially viable. Correctly identified and fixed the bug in one run. Blocked by: (1) never outputs completion sentinel — always says "Task completed."; (2) occasionally rewrites entire source files instead of making surgical edits. Sentinel must be detected out-of-band by Helix. |
| Any sub-7B model for this task | Likely not viable. The task requires reading test output, reasoning about the fix, and applying it via a tool call - a multi-step agentic loop that small models cannot execute consistently. |

## Recommended Next Step

Use a hosted model for the fix-application step. Options in order of preference:

1. Claude claude-sonnet-4-6 via Anthropic API (via opencode or direct) - already works, tool use is reliable
2. codestral-latest via Mistral API - strong at code, supports tool use, cheaper than Claude
3. A larger local model (32B+, e.g. qwen2.5-coder:32b) if GPU memory allows - not tested

The local model path is worth revisiting once Ollama ships better tool-calling support and a 7B+ code model with reliable agentic behaviour exists.
