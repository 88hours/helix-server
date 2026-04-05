#!/bin/sh
# entrypoint.sh — resolve the start command and run it.
#
# If START_COMMAND is set, exec that single command (used for individual agents).
# If START_COMMAND is not set, start all agents together (default for the "all" service).
#
# START_COMMAND is set per-service as a Railway environment variable.
# Using ENTRYPOINT (not CMD) ensures Railway's stored startCommand cannot bypass this.

if [ -n "${START_COMMAND:-}" ]; then
  echo "[entrypoint] START_COMMAND=${START_COMMAND}"
  exec sh -c "$START_COMMAND"
fi

# No START_COMMAND — start all agents in this container.
echo "[entrypoint] START_COMMAND not set — starting all agents"

uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
PID_CRASH=$!
echo "[entrypoint] crash_handler started (pid $PID_CRASH)"

python -m agents.qa.main &
PID_QA=$!
echo "[entrypoint] qa started (pid $PID_QA)"

python -m agents.dev.main &
PID_DEV=$!
echo "[entrypoint] dev started (pid $PID_DEV)"

python -m agents.notifier.main &
PID_NOTIFIER=$!
echo "[entrypoint] notifier started (pid $PID_NOTIFIER)"

echo "[entrypoint] all agents running"

# Exit as soon as any agent process exits so the container restarts cleanly.
wait -n 2>/dev/null || wait
echo "[entrypoint] an agent exited — shutting down"
exit 1
