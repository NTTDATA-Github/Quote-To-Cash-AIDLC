#!/usr/bin/env bash
# Start or stop the local stack: Postgres, Floci, Odoo, then migrate, seed,
# api, worker, the reseller mock, AdminOps, and (when erp-agent-service/.env exists) the coding agent.
#   bash scripts/local.sh up
#   bash scripts/local.sh down
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://portal:portal@127.0.0.1:5432/portal}"
export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://127.0.0.1:4566}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export APP_PROFILE=postgres
export ERP_ADAPTER_MODE="${ERP_ADAPTER_MODE:-real}"
export RECONCILE_INTERVAL_SECONDS="${RECONCILE_INTERVAL_SECONDS:-30}"
export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}"
# Local-only: every ERP this stack talks to (Odoo, the NetSuite mock, anything an
# operator registers while testing) is on localhost, which GenericErpProbe's SSRF guard
# correctly refuses for a real deployment. staging/production never set this.
export ERP_PROBE_ALLOW_PRIVATE_ADDRESSES="${ERP_PROBE_ALLOW_PRIVATE_ADDRESSES:-true}"

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

stop_pid() {
  local pid="$1"
  kill "$pid" 2>/dev/null || true
}

# Git Bash's $! is an MSYS-space id, not the real Windows PID netstat/tasklist use — it
# often doesn't correspond to any actual process, so pid-file-based kill silently kills
# nothing and every `up` leaks the previous run's api/worker/etc. processes (confirmed:
# they keep serving with whatever Cognito pool/env they started with, which is exactly
# why a stack rebuild didn't fix stale "Not authenticated" errors). Kill by command-line
# match instead — exact, since each service's module/script name is distinctive.
stop_bg() {
  if [[ -n "${MSYSTEM:-}" ]]; then
    powershell.exe -NoProfile -Command \
      "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'uvicorn src\.api\.app|src\.worker\.main|scripts\.dev_webhook_receiver|scripts\.mock_netsuite|uvicorn service\.app|service\.worker|vite|npm.*run dev' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
      >/dev/null 2>&1 || true
    rm -f .local/*.pid
    return 0
  fi
  local f pid
  for f in .local/*.pid; do
    [[ -f "$f" ]] || continue
    pid="$(cat "$f")"
    stop_pid "$pid"
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

# Floci's bedrock-runtime returns a stub. The mapping worker calls real Bedrock with
# the same bearer token the coding agent keeps in its .env.
load_bedrock_token() {
  if [[ -n "${AWS_BEARER_TOKEN_BEDROCK:-}" || ! -f erp-agent-service/.env ]]; then
    return 0
  fi
  AWS_BEARER_TOKEN_BEDROCK="$("$PY" - <<'PY'
from pathlib import Path
for line in Path("erp-agent-service/.env").read_text(encoding="utf-8").splitlines():
    if line.startswith("AWS_BEARER_TOKEN_BEDROCK="):
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        print(value, end="")
        break
PY
)"
  export AWS_BEARER_TOKEN_BEDROCK
}

# The agent's .env (sqlite job db, Bedrock bearer token) must win over the portal
# DATABASE_URL, dummy AWS keys, and Floci endpoint exported above. load_dotenv does not override.
start_agent() {
  local name="$1"
  shift
  (
    cd erp-agent-service
    unset DATABASE_URL AWS_ENDPOINT_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    "$@"
  ) >".local/${name}.log" 2>&1 &
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
  docker compose up -d
  wait_for "Postgres" 60 docker compose exec -T postgres pg_isready -U portal
  wait_for "Floci" 60 curl -sf http://127.0.0.1:4566/_floci/health
  # First Odoo boot installs modules (base,contacts,sale_management,stock,sale_stock),
  # which takes a few minutes — give it longer than the other, near-instant services.
  wait_for "Odoo" 150 curl -sf http://127.0.0.1:8069/web/login
  "$PY" -m alembic upgrade head
  "$PY" -m scripts.messaging_bootstrap
  "$PY" -m scripts.seed_demo
  "$PY" -m scripts.seed_netsuite
  "$PY" -m scripts.seed_cognito
  set -a
  # shellcheck disable=SC1091
  source .local/cognito.env
  set +a
  # Restart the app processes every up so they load the env this run just wrote.
  stop_bg
  load_bedrock_token
  start_bg api "$PY" -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
  start_bg worker "$PY" -m src.worker.main
  # Same value seed_demo stores for whep_local_demo. Override only together with that secret.
  start_bg reseller-mock "$PY" -m scripts.dev_webhook_receiver --port 8090 --secret "${WEBHOOK_RECEIVER_SECRET:-whsec_local_dev}"
  # NetSuite SuiteTalk REST service on :8075 (self-hosted instance for this environment).
  start_bg netsuite "$PY" -m scripts.mock_netsuite --port 8075
  if [[ -d ui/node_modules ]]; then
    start_bg ui npm --prefix ui run dev -- --host 127.0.0.1 --port 5173
  else
    echo "UI dependencies are not installed. From ui/: npm install"
  fi
  if [[ -f erp-agent-service/.env ]] && "$PY" -c "import dotenv" >/dev/null 2>&1; then
    start_agent agent-api "$PY_ABS" -m uvicorn service.app:app --host 127.0.0.1 --port 8002
    start_agent agent-worker "$PY_ABS" -m service.worker
  elif [[ -f erp-agent-service/.env ]]; then
    echo "Agent dependencies are not installed. pip install -r erp-agent-service/requirements.txt"
  else
    echo "erp-agent-service/.env is missing. Copy erp-agent-service/.env.example to start the coding agent."
  fi
  if ! wait_for "API" 60 curl -sf http://127.0.0.1:8000/livez; then
    echo "api failed. Last log lines:" >&2
    tail -n 40 .local/api.log >&2 || true
    exit 1
  fi
  if [[ -f .local/agent-api.pid ]] && ! wait_for "Agent API" 60 curl -sf http://127.0.0.1:8002/livez; then
    echo "agent api failed. Last log lines:" >&2
    tail -n 40 .local/agent-api.log >&2 || true
    exit 1
  fi
  cat <<'EOF'

Local stack is up.
  AdminOps                       http://localhost:5173
                                 http://127.0.0.1:5173
  API liveness                   http://127.0.0.1:8000/livez
  API readiness                  http://127.0.0.1:8000/readyz
  Reseller GraphQL               http://127.0.0.1:8000/graphql/reseller
  Operator GraphQL               http://127.0.0.1:8000/graphql/operator
  Odoo                           http://localhost:8069
  App database (Adminer)         http://localhost:8088
  Odoo webhook (demo secret)     http://127.0.0.1:8000/erp/webhook/conn_odoo_local/odoo-webhook-demo
  Floci                          http://localhost:4566
  Floci health                   http://localhost:4566/_floci/health
  Floci console                  http://localhost:4566/_floci/ui
  Adapter agent                  http://127.0.0.1:8002/livez
  Reseller mock                  http://127.0.0.1:8090/hooks
  NetSuite (SuiteTalk REST)      http://127.0.0.1:8075
  NetSuite triggers (Swagger)    http://127.0.0.1:8075/docs

Sign in to AdminOps as demo-operator / DemoPass123!. Odoo is admin / admin.
The seeded order is PO-48213 for Acme Retail, read from Odoo for that partner (the demo binding).
A sticky Odoo banner about the push service is the browser refusing desktop notifications. Dismiss it.
Stop with: bash scripts/local.sh down
EOF
}

down() {
  stop_bg
  docker compose stop
  echo "Stopped. Data is kept. Start again with: bash scripts/local.sh up"
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  *)
    echo "usage: bash scripts/local.sh up|down" >&2
    exit 1
    ;;
esac
