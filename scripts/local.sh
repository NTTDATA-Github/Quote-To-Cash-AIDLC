#!/usr/bin/env bash
# Start or stop the local demo: Odoo (Docker), the API in the memory profile, the seed, the
# reseller and NetSuite mocks, AdminOps, and the coding agent when erp-agent-service/.env exists.
#   bash scripts/local.sh up
#   bash scripts/local.sh down
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

export APP_PROFILE=memory
export ERP_ADAPTER_MODE="${ERP_ADAPTER_MODE:-real}"
export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}"
export ODOO_WEBHOOK_SECRET="${ODOO_WEBHOOK_SECRET:-odoo-webhook-demo}"
export NETSUITE_WEBHOOK_SECRET="${NETSUITE_WEBHOOK_SECRET:-ns-webhook-demo}"
# Local-only: the ERPs this stack talks to are on localhost, which GenericErpProbe's SSRF
# guard refuses for a real deployment. Staging and production never set this.
export ERP_PROBE_ALLOW_PRIVATE_ADDRESSES="${ERP_PROBE_ALLOW_PRIVATE_ADDRESSES:-true}"
# Keycloak runs in docker-compose. "localhost" must match the issuer in the tokens the
# browser gets, so the API and the UI both use it.
KEYCLOAK_REALM_URL="http://localhost:8080/realms/o2c"
export KEYCLOAK_ISSUER="$KEYCLOAK_REALM_URL"
export KEYCLOAK_CLIENT_ID="o2c-portal"

if [[ -x .venv/Scripts/python.exe ]]; then
  PY=".venv/Scripts/python.exe"
elif [[ -x .venv/bin/python ]]; then
  PY=".venv/bin/python"
else
  echo "No virtualenv. Create one with: python -m venv .venv && .venv/Scripts/python -m pip install -e \".[dev]\""
  exit 1
fi
# Absolute so the agent can cd into its own directory and still find this interpreter.
if command -v cygpath >/dev/null 2>&1; then
  PY_ABS="$(cygpath -w "$ROOT/$PY")"
else
  PY_ABS="$ROOT/$PY"
fi

mkdir -p .local

stop_bg() {
  # Git Bash's $! is not the Windows PID, so kill by command-line match instead.
  if [[ -n "${MSYSTEM:-}" ]]; then
    powershell.exe -NoProfile -Command \
      "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'uvicorn src\.api\.app|scripts\.dev_webhook_receiver|scripts\.mock_netsuite|uvicorn service\.app|service\.worker|vite|npm.*run dev' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
      >/dev/null 2>&1 || true
    rm -f .local/*.pid
    return 0
  fi
  local f pid
  for f in .local/*.pid; do
    [[ -f "$f" ]] || continue
    pid="$(cat "$f")"
    kill "$pid" 2>/dev/null || true
    rm -f "$f"
  done
}

start_bg() {
  local name="$1"
  shift
  "$@" >".local/${name}.log" 2>&1 &
  echo $! >".local/${name}.pid"
  echo "$name started (log: .local/${name}.log)"
}

wait_for() {
  local label="$1"
  local tries="${2:-60}"
  shift 2
  local i
  for i in $(seq 1 "$tries"); do
    if "$@" >/dev/null 2>&1; then
      echo "$label is up"
      return 0
    fi
    sleep 2
  done
  echo "$label did not become ready" >&2
  return 1
}

up() {
  docker compose up -d odoo-db odoo keycloak
  wait_for "Keycloak" 120 curl -sf "$KEYCLOAK_REALM_URL/.well-known/openid-configuration"
  # First Odoo boot installs modules, which takes a few minutes.
  wait_for "Odoo" 150 curl -sf http://127.0.0.1:8069/web/login

  stop_bg
  start_bg api "$PY" -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
  wait_for "API" 60 curl -sf http://127.0.0.1:8000/livez

  # Seeds the in-memory API process, so it must run after every API start.
  "$PY" -m scripts.seed_demo

  start_bg reseller-mock "$PY" -m scripts.dev_webhook_receiver --port 8090 \
    --secret "$(cat .local/reseller-secret)"
  start_bg netsuite "$PY" -m scripts.mock_netsuite --port 8075
  if [[ -d ui/node_modules ]]; then
    VITE_KEYCLOAK_ISSUER_URL="$KEYCLOAK_REALM_URL" VITE_KEYCLOAK_CLIENT_ID="$KEYCLOAK_CLIENT_ID" \
      start_bg ui npm --prefix ui run dev -- --host 127.0.0.1 --port 5173
  else
    echo "UI dependencies are not installed. From ui/: npm install"
  fi
  if [[ -f erp-agent-service/.env ]] && "$PY" -c "import dotenv" >/dev/null 2>&1; then
    (cd erp-agent-service && start_bg agent-api "$PY_ABS" -m uvicorn service.app:app --host 127.0.0.1 --port 8002)
    (cd erp-agent-service && start_bg agent-worker "$PY_ABS" -m service.worker)
  elif [[ -f erp-agent-service/.env ]]; then
    echo "Agent dependencies are not installed. pip install -r erp-agent-service/requirements.txt"
  else
    echo "erp-agent-service/.env is missing. Copy erp-agent-service/.env.example to start the coding agent."
  fi

  cat <<'EOF'

Local demo is up.
  AdminOps                       http://127.0.0.1:5173
  API liveness                   http://127.0.0.1:8000/livez
  Reseller GraphQL               http://127.0.0.1:8000/graphql/reseller
  Operator GraphQL               http://127.0.0.1:8000/graphql/operator
  Keycloak                       http://localhost:8080  (admin / admin)
  Odoo                           http://localhost:8069  (admin / admin)
  Reseller mock                  http://127.0.0.1:8090/hooks
  NetSuite (SuiteTalk REST)      http://127.0.0.1:8075
  NetSuite triggers (Swagger)    http://127.0.0.1:8075/docs
  Adapter agent                  http://127.0.0.1:8002/livez

The seed prints the Odoo webhook URL above. Sign in to AdminOps as operator1 / operator1.
Data lives in the API process. Restarting `up` reseeds it.
Stop with: bash scripts/local.sh down
EOF
}

down() {
  stop_bg
  docker compose stop
  echo "Stopped. Start again with: bash scripts/local.sh up"
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  *)
    echo "usage: bash scripts/local.sh up|down" >&2
    exit 1
    ;;
esac
