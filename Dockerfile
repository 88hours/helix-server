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
# Python application
# ---------------------------------------------------------------------------
WORKDIR /app

# Copy manifest first — lets Docker cache the pip layer across code changes
COPY pyproject.toml .
COPY uv.lock* ./

# Install all runtime deps (no dev extras — tests are not run at runtime)
RUN pip install --no-cache-dir -e "."

# Copy the rest of the source
COPY . .

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
# crash_handler (port 8000) is the HTTP service. The other agents (qa, dev)
# are Redis subscribers with no inbound port.
EXPOSE 8000

# Default: start the Crash Handler webhook server.
# Override CMD in docker-compose or at `docker run` time to run other agents:
#   python -m agents.qa.main
#   python -m agents.dev.main
CMD ["uvicorn", "agents.crash_handler.main:app", "--host", "0.0.0.0", "--port", "8000"]
