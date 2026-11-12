#!/bin/bash
# Xposure one-shot dev launcher — macOS port of start.ps1.
# Boots Postgres + Qdrant (docker compose), the FastAPI backend and the
# Next.js frontend, verifying each layer and failing loudly if one is down.
# Assumes .env, backend/frontend dependencies are already installed — this
# boots services, it doesn't do first-time setup.
#
# Ports: backend 8010, frontend 3010, Postgres 5442, Qdrant 6343/6344
# (chosen to avoid colliding with the sister ComplyX project if both run on
# this machine at once — see docs/PLAN.md). Needs python3 on PATH to parse
# the /health JSON (same as ComplyX's start-demo.sh), and osascript/
# Terminal.app to open the backend and frontend windows — both standard on
# stock macOS.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8010
FRONTEND_PORT=3010

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
NC='\033[0m'

step() { printf "\n${CYAN}=== %s ===${NC}\n" "$1"; }
ok()   { printf "${GREEN}[ OK ]${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
fail() { printf "\n${RED}[FAIL]${NC} %s\n" "$1"; exit 1; }

# ── 1/4 Docker + infra (Postgres, Qdrant) ───────────────────────────────
step "1/4 Docker + infra (Postgres, Qdrant)"
docker info >/dev/null 2>&1 || fail "Docker Desktop is not running. Start it and retry."

(cd "$ROOT" && docker compose up -d) >/dev/null

pg_up=false
for _ in $(seq 1 20); do
  if (cd "$ROOT" && docker compose exec -T postgres pg_isready -U xposure) >/dev/null 2>&1; then
    pg_up=true
    break
  fi
  sleep 1
done
[ "$pg_up" = true ] || fail "Postgres did not come up on port 5442."
ok "Postgres is up (port 5442)"

qdrant_up=false
for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:6343/collections" >/dev/null 2>&1; then
    qdrant_up=true
    break
  fi
  sleep 1
done
[ "$qdrant_up" = true ] || fail "Qdrant did not come up on port 6343."
ok "Qdrant is up (port 6343)"

# ── 2/4 Backend (FastAPI) ────────────────────────────────────────────────
step "2/4 Backend (FastAPI, port $BACKEND_PORT)"
[ -f "$ROOT/.env" ] || fail "Missing .env in $ROOT (copy .env.example)."

BACKEND_SCRIPT="$ROOT/.dev-backend.sh"
cat > "$BACKEND_SCRIPT" <<EOF
#!/bin/bash
cd "$ROOT/backend"
export PYTHONUTF8=1
exec uvicorn app.main:app --port $BACKEND_PORT --host 0.0.0.0 --reload
EOF
chmod +x "$BACKEND_SCRIPT"

osascript <<APPLESCRIPT
tell application "Terminal"
    activate
    do script "bash '$BACKEND_SCRIPT'"
end tell
APPLESCRIPT

health_json=""
for _ in $(seq 1 45); do
  if health_json=$(curl -fsS "http://127.0.0.1:$BACKEND_PORT/health" 2>/dev/null); then
    break
  fi
  health_json=""
  sleep 2
done
[ -n "$health_json" ] || fail "Backend did not come up on port $BACKEND_PORT. Check the backend Terminal window for errors."

read -r ready status llm_reachable llm_base <<< "$(printf '%s' "$health_json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
llm = d.get('llm', {})
print(d.get('ready'), d.get('status', ''), llm.get('reachable'), llm.get('base_url', ''))
")"

[ "$ready" = "True" ] || fail "Backend is up but DB/Qdrant are not both reachable. Check the /health response for detail."
ok "Backend healthy (status: $status)"
[ "$llm_reachable" = "True" ] || warn "LLM ($llm_base) is unreachable — expected while LLM_BASE_URL is unset or Ollama isn't running. Diff/impact analysis calls will fail loudly, not mock, until this is fixed."

# ── 3/4 Frontend (Next.js) ───────────────────────────────────────────────
step "3/4 Frontend (Next.js, port $FRONTEND_PORT)"

FRONTEND_SCRIPT="$ROOT/.dev-frontend.sh"
cat > "$FRONTEND_SCRIPT" <<EOF
#!/bin/bash
cd "$ROOT/frontend"
exec npm run dev
EOF
chmod +x "$FRONTEND_SCRIPT"

osascript <<APPLESCRIPT
tell application "Terminal"
    activate
    do script "bash '$FRONTEND_SCRIPT'"
end tell
APPLESCRIPT

front_up=false
for _ in $(seq 1 45); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$FRONTEND_PORT" || true)
  if [ "$code" = "200" ]; then
    front_up=true
    break
  fi
  sleep 2
done
[ "$front_up" = true ] || fail "Frontend did not come up on port $FRONTEND_PORT. Check the frontend Terminal window."
ok "Frontend is up (port $FRONTEND_PORT)"

# ── 4/4 Ready ─────────────────────────────────────────────────────────────
step "4/4 Ready"
ok "Xposure is live: http://localhost:$FRONTEND_PORT"
open "http://localhost:$FRONTEND_PORT"
