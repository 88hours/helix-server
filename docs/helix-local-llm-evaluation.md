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

**Result: Not tested properly via opencode**

Model name casing caused a ProviderModelNotFoundError in opencode. Fixed by using correct casing (Qwen3.6:latest) and creating an alias via `ollama cp`. However, the opencode issues described below were already blocking progress at this point.

### qwen3.6 (via Ollama + Goose)

**Result: Unusable — hardcoded tool schema from training**

qwen3.6 was tested via Goose after devstral-small-2 failed. It called tools immediately, which is better than gemma4. However, every tool call it made was to tools that do not exist in Goose.

Across multiple runs it attempted `developer.file.read`, `extensionmanager.list_resources`, and other Claude Code or MCP-style tool names. The prompt explicitly listed the available tools (`shell`, `tree`, `edit`, `write`) and explicitly instructed the model not to call any other tool. The model ignored the list on every run.

This is not a prompt problem. qwen3.6 was trained on Claude Code tool schemas and its tool-calling behaviour is driven by its weights, not by the system prompt. There is no prompt instruction that can override this reliably.

**Distinction from gemma4:** qwen3.6 attempts tool calls immediately and without coaxing, which is a better starting behaviour. The failure mode is different: it calls the wrong tools rather than writing prose. Both are fatal for this pipeline.

### gemma4 (via Ollama + opencode)

**Result: Unusable due to opencode tool descriptions**

gemma4 refused to use tools. Root cause traced via HTTP proxy: opencode sends tool descriptions that contain instructions like "avoid ls, echo, grep" which gemma4 follows too literally and declines to call any shell commands. opencode's tool schema and prompts are written specifically for Claude and do not transfer well to smaller local models.

Additionally, opencode requires a `description` field in bash tool calls which gemma4 omits, causing the tool call to fail silently and the model to give up.

### devstral-small-2 (via Ollama + Goose)

**Result: Best local model tested, still not viable**

devstral-small-2 is a 24B parameter Mistral model trained specifically for agentic coding tasks. It is the most capable local model tested and the only one that used tools reliably without coaxing.

**What it does well:** devstral calls shell tools immediately without hesitation, runs pytest correctly with PYTHONPATH=., reads tracebacks accurately, and identifies the exact file and line that needs changing. It does not write prose explanations before acting.

**Fatal blocker: loop continuation failure**

devstral consistently stops after running the failing test. It reads the traceback, identifies the broken line, and then ends the session without applying the fix. In the final two iterations:

- Iteration one: ran `ls -la`, analyzed file structure, never ran the test, session ended.
- Iteration two: ran pytest, saw `fastapi_error.py:62: KeyError: 'amount'`, wrote a todo list, ran pytest a second time without changing anything, then exited.

The model understands the task. It cannot execute the continuation step where the output of one tool call becomes the input to the next. It treats running the test as the complete task rather than the first step.

**Earlier failure mode:** when the model did proceed to the edit step in earlier runs, it used the write tool to replace the entire 129-line source file with a hallucinated 48-line version, removing unrelated functions and breaking imports. Explicit prompt rules against this did not reliably change the behaviour.

**Distinction from gemma4:** devstral is strictly better than gemma4. It uses tools without being forced, does not write planning essays, and correctly reads test output. The failure is at agentic loop continuation, not tool calling. This is a meaningful distinction for evaluating future larger models.

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
| gemma4 (4B) via Goose | Not viable. Cannot reliably apply file edits. Writes prose instead of calling tools. |
| devstral-small-2 (24B) via Goose | Not viable. Correctly identifies bugs and reads tracebacks but stops before applying the fix. Loop continuation is absent. |
| qwen3.6 (6B) via Goose | Not viable. Calls tools immediately but uses Claude Code tool schemas (developer.file.read, extensionmanager.list_resources) that do not exist in Goose. Prompt instructions cannot override this. |
| Any local model tested for this task | Not viable at current capability level. The task requires a multi-step agentic loop with correct tool schemas that no tested model can execute end to end. |

## Recommended Next Step

Use a hosted model for the fix-application step. The local model path is closed for now.

1. Claude claude-sonnet-4-6 via Anthropic API (via opencode or direct) - already works, tool use is reliable, zero prompt engineering required.
2. codestral-latest via Mistral API - strong at code, supports tool use, cheaper than Claude. Worth evaluating as a cost reduction.
3. A larger local model (32B+, e.g. qwen2.5-coder:32b) if GPU memory allows - not tested, may have better loop continuation behaviour.

The local model path is worth revisiting once a 7B or larger model exists with demonstrated agentic loop capability, not just code generation or tool calling in isolation.
