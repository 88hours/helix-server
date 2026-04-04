#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# railway-deploy.sh — create and deploy all Helix services on Railway
#
# Usage:
#   ./railway-deploy.sh              # deploy all four agents
#   ./railway-deploy.sh crash_handler qa   # deploy specific agents only
#
# Prerequisites:
#   - railway CLI installed and logged in (railway login)
#   - project linked (railway link)
#   - environment variables set in Railway dashboard or via:
#       railway variable --service <name> set KEY=value
# ---------------------------------------------------------------------------
set -euo pipefail

# Service name → start command
declare -A START_COMMANDS=(
  [crash_handler]="uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port \$PORT"
  [qa]="python -m agents.qa.main"
  [dev]="python -m agents.dev.main"
  [notifier]="python -m agents.notifier.main"
)

# Deploy order
ALL_SERVICES=(crash_handler qa dev notifier)

# If args given, deploy only those; otherwise deploy all
if [[ $# -gt 0 ]]; then
  TARGETS=("$@")
else
  TARGETS=("${ALL_SERVICES[@]}")
fi

# Validate requested service names
for target in "${TARGETS[@]}"; do
  if [[ -z "${START_COMMANDS[$target]+_}" ]]; then
    echo "error: unknown service '$target'" >&2
    echo "valid services: ${ALL_SERVICES[*]}" >&2
    exit 1
  fi
done

# Ensure we are linked to a Railway project
if ! railway status &>/dev/null; then
  echo "error: not linked to a Railway project — run 'railway link' first" >&2
  exit 1
fi

echo "Project: $(railway status | grep Project | awk '{print $2}')"
echo ""

# Clean up any leftover railway.json from a previous failed run
trap 'rm -f railway.json' EXIT

for service in "${TARGETS[@]}"; do
  cmd="${START_COMMANDS[$service]}"
  echo "──────────────────────────────────────"
  echo "Service: $service"
  echo "Command: $cmd"
  echo ""

  # Create the service if it does not already exist
  if railway add --service "$service" 2>&1 | grep -q "already exists"; then
    echo "  service already exists — skipping create"
  else
    echo "  service created"
  fi

  # Write a temporary root railway.json with this service's start command.
  # railway up reads this file to configure the build and start command.
  cat > railway.json <<EOF
{
  "\$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "startCommand": "$cmd",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
EOF

  echo "  deploying..."
  railway up --service "$service" --detach
  echo "  ✓ deployment queued"

  rm railway.json
  echo ""
done

echo "──────────────────────────────────────"
echo "All deployments queued."
echo ""
echo "Monitor logs:"
for service in "${TARGETS[@]}"; do
  echo "  railway logs --service $service"
done
echo ""
echo "Open dashboard:"
echo "  railway open"
