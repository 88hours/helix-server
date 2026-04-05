#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# railway-deploy.sh — create, configure, and deploy all Helix services
#
# Usage:
#   ./railway-deploy.sh                        # deploy all four agents
#   ./railway-deploy.sh --env-file .env        # sync .env vars first, then deploy all
#   ./railway-deploy.sh --env-only             # sync .env vars only, no deploy
#   ./railway-deploy.sh crash_handler qa       # deploy specific agents only
#   ./railway-deploy.sh --env-file .env qa     # sync vars + deploy qa only
#
# Prerequisites:
#   - railway CLI installed and logged in  (railway login)
#   - project linked to this directory     (railway link)
# ---------------------------------------------------------------------------
set -euo pipefail

# ---------------------------------------------------------------------------
# Service definitions
# ---------------------------------------------------------------------------

ALL_SERVICES=(crash_handler qa dev notifier)

start_command() {
  case "$1" in
    crash_handler) echo "sh -c 'uvicorn agents.crash_handler.main:app --host 0.0.0.0 --port \${PORT:-8000}'" ;;
    qa)            echo "python -m agents.qa.main" ;;
    dev)           echo "python -m agents.dev.main" ;;
    notifier)      echo "python -m agents.notifier.main" ;;
    *)             echo "error: unknown service '$1'" >&2; exit 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

ENV_FILE=""
ENV_ONLY=false
TARGETS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      shift
      ENV_FILE="${1:-}"
      if [[ -z "$ENV_FILE" ]]; then
        echo "error: --env-file requires a path argument" >&2
        exit 1
      fi
      shift
      ;;
    --env-only)
      ENV_ONLY=true
      shift
      ;;
    --*)
      echo "error: unknown flag '$1'" >&2
      exit 1
      ;;
    *)
      TARGETS+=("$1")
      shift
      ;;
  esac
done

# Default to all services if none specified
if [[ ${#TARGETS[@]} -eq 0 ]]; then
  TARGETS=("${ALL_SERVICES[@]}")
fi

# Validate service names
for target in "${TARGETS[@]}"; do
  start_command "$target" > /dev/null
done

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

if ! railway status &>/dev/null; then
  echo "error: not linked to a Railway project — run 'railway link' first" >&2
  exit 1
fi

PROJECT=$(railway status | awk '/Project:/ {print $2}')
ENV=$(railway status | awk '/Environment:/ {print $2}')
echo "Project:     $PROJECT"
echo "Environment: $ENV"
echo ""

# ---------------------------------------------------------------------------
# Sync .env → Railway variables (all services receive all variables)
# ---------------------------------------------------------------------------

sync_env() {
  local env_file="$1"

  if [[ ! -f "$env_file" ]]; then
    echo "error: env file not found: $env_file" >&2
    exit 1
  fi

  echo "Reading $env_file..."

  # Parse KEY=VALUE pairs; skip blank lines and comments.
  # Strips surrounding quotes from values (both single and double).
  local pairs=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip blank lines and comments
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    # Strip leading 'export ' if present
    line="${line#export }"
    # Must contain '='
    [[ "$line" != *=* ]] && continue

    local key="${line%%=*}"
    local val="${line#*=}"

    # Strip surrounding double or single quotes
    if [[ "$val" =~ ^\"(.*)\"$ ]]; then
      val="${BASH_REMATCH[1]}"
    elif [[ "$val" =~ ^\'(.*)\'$ ]]; then
      val="${BASH_REMATCH[1]}"
    fi

    # Skip empty values — leave those unset on Railway
    [[ -z "$val" ]] && continue

    pairs+=("${key}=${val}")
  done < "$env_file"

  if [[ ${#pairs[@]} -eq 0 ]]; then
    echo "  no variables found in $env_file"
    return
  fi

  echo "  found ${#pairs[@]} variable(s) — syncing to all services..."
  echo ""

  for service in "${ALL_SERVICES[@]}"; do
    echo "  → $service"
    # Pass all pairs as separate arguments in a single call
    railway variable set --service "$service" --skip-deploys "${pairs[@]}"
  done

  echo ""
  echo "  ✓ variables synced"
  echo ""
}

if [[ -n "$ENV_FILE" ]]; then
  echo "──────────────────────────────────────"
  echo "Syncing environment variables"
  echo ""
  sync_env "$ENV_FILE"
fi

if [[ "$ENV_ONLY" == true ]]; then
  echo "──────────────────────────────────────"
  echo "Done (--env-only, skipping deploy)."
  exit 0
fi

# ---------------------------------------------------------------------------
# Create services and deploy
# ---------------------------------------------------------------------------

trap 'rm -f railway.json' EXIT

for service in "${TARGETS[@]}"; do
  cmd="$(start_command "$service")"
  echo "──────────────────────────────────────"
  echo "Service: $service"
  echo "Command: $cmd"
  echo ""

  # Create the service if it does not already exist
  add_output=$(railway add --service "$service" 2>&1 || true)
  if echo "$add_output" | grep -qi "already exists"; then
    echo "  service already exists — skipping create"
  else
    echo "  service created"
  fi

  # Write a temporary root railway.json so railway up picks up the correct
  # start command and Dockerfile path for this service.
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

  if [[ "$service" == "crash_handler" ]]; then
    domain=$(railway domain --service crash_handler 2>/dev/null | tr -d '[:space:]')
    if [[ -n "$domain" ]]; then
      echo ""
      echo "  Webhook URLs:"
      echo "    Rollbar → https://${domain}/webhook/rollbar"
      echo "    Sentry  → https://${domain}/webhook/sentry"
    fi
  fi

  rm railway.json
  echo ""
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo "──────────────────────────────────────"
echo "All deployments queued."
echo ""
echo "Monitor logs:"
for service in "${TARGETS[@]}"; do
  echo "  railway logs --service $service"
done
echo ""

# Print webhook URLs if crash_handler was deployed
for service in "${TARGETS[@]}"; do
  if [[ "$service" == "crash_handler" ]]; then
    domain=$(railway domain --service crash_handler 2>/dev/null | tr -d '[:space:]')
    if [[ -n "$domain" ]]; then
      echo "Webhook URLs:"
      echo "  Rollbar → https://${domain}/webhook/rollbar"
      echo "  Sentry  → https://${domain}/webhook/sentry"
      echo ""
    else
      echo "Webhook URLs: (domain not yet assigned — run 'railway domain --service crash_handler' once DNS is ready)"
      echo ""
    fi
    break
  fi
done

echo "Open dashboard:"
echo "  railway open"
