FROM python:3.12-slim

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------
# git       — Dev Agent clones the target repo before invoking claude CLI
# curl/ca   — NodeSource setup script + TLS
# nodejs    — required to run the Claude Code CLI (Dev Agent, claude-code provider)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Claude Code CLI
# ---------------------------------------------------------------------------
# Installed globally so `claude` is on PATH when the Dev Agent runs
# `claude -p "<prompt>"` inside the cloned repo.
RUN npm install -g @anthropic-ai/claude-code

# ---------------------------------------------------------------------------
# Non-root user
# ---------------------------------------------------------------------------
# Claude Code CLI refuses --dangerously-skip-permissions when run as root.
RUN useradd --create-home --shell /bin/bash helix

# ---------------------------------------------------------------------------
# Python application
# ---------------------------------------------------------------------------
WORKDIR /app

# Copy manifest first — lets Docker cache the pip layer across code changes
COPY pyproject.toml .
COPY uv.lock* ./

# Install all runtime deps (no dev extras — tests are not run at runtime)
RUN pip install --no-cache-dir -e "."

# Copy the rest of the source and hand ownership to the app user
COPY . .
RUN chown -R helix:helix /app
RUN chmod +x /app/entrypoint.sh

USER helix

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
EXPOSE 8000

# ENTRYPOINT reads START_COMMAND from the environment and execs it.
# Using ENTRYPOINT (not CMD) means Railway's stored startCommand cannot
# bypass this script — Railway overrides CMD but never ENTRYPOINT.
#
# Set START_COMMAND as a Railway environment variable per service:
#   crash_handler:  uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port ${PORT:-8000}
#   qa:             python -m agents.qa.main
#   dev:            python -m agents.dev.main
#   notifier:       python -m agents.notifier.main
#   all agents:     (leave START_COMMAND unset — entrypoint starts everything)
ENTRYPOINT ["/app/entrypoint.sh"]
