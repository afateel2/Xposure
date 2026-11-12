# Xposure one-shot dev launcher.
# Boots Postgres + Qdrant (docker compose), the FastAPI backend and the
# Next.js frontend, verifying each layer and failing loudly if one is down.
# Assumes .env, backend/frontend dependencies (`make install` equivalent)
# are already in place — this boots services, it doesn't do first-time setup.
#
# Ports: backend 8010, frontend 3010, Postgres 5442, Qdrant 6343/6344
# (chosen to avoid colliding with the sister ComplyX project if both run on
# this machine at once — see docs/PLAN.md).

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$BackendPort = 8010
$FrontendPort = 3010

function Fail($msg) { Write-Host "`n[FAIL] $msg" -ForegroundColor Red; exit 1 }
function Ok($msg) { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

Step "1/4 Docker + infra (Postgres, Qdrant)"
try { docker info *> $null } catch { Fail "Docker Desktop is not running. Start it and retry." }
Push-Location $Root
docker compose up -d | Out-Null
Pop-Location

$pgUp = $false
foreach ($i in 1..20) {
    docker compose exec -T postgres pg_isready -U xposure *> $null
    if ($LASTEXITCODE -eq 0) { $pgUp = $true; break }
    Start-Sleep 1
}
if (-not $pgUp) { Fail "Postgres did not come up on port 5442." }
Ok "Postgres is up (port 5442)"

$qdrantUp = $false
foreach ($i in 1..20) {
    try {
        $null = Invoke-RestMethod "http://127.0.0.1:6343/collections" -TimeoutSec 2
        $qdrantUp = $true; break
    } catch { Start-Sleep 1 }
}
if (-not $qdrantUp) { Fail "Qdrant did not come up on port 6343." }
Ok "Qdrant is up (port 6343)"

Step "2/4 Backend (FastAPI, port $BackendPort)"
if (-not (Test-Path "$Root\.env")) { Fail "Missing .env in $Root (copy .env.example)." }
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$Root\backend'; `$env:PYTHONUTF8='1'; py -3 -m uvicorn app.main:app --port $BackendPort --host 0.0.0.0 --reload"
$health = $null
foreach ($i in 1..45) {
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$BackendPort/health" -TimeoutSec 2
        break
    } catch { Start-Sleep 2 }
}
if (-not $health) { Fail "Backend did not come up on port $BackendPort. Check the backend window for errors." }
if (-not $health.ready) { Fail "Backend is up but DB/Qdrant are not both reachable. Check the /health response for detail." }
Ok "Backend healthy (status: $($health.status))"
if (-not $health.llm.reachable) {
    Write-Host "[WARN] LLM ($($health.llm.base_url)) is unreachable — expected while LLM_BASE_URL is unset or Ollama isn't running. Diff/impact analysis calls will fail loudly, not mock, until this is fixed." -ForegroundColor Yellow
}

Step "3/4 Frontend (Next.js, port $FrontendPort)"
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$Root\frontend'; npm run dev"
$frontUp = $false
foreach ($i in 1..45) {
    try {
        $resp = Invoke-WebRequest "http://127.0.0.1:$FrontendPort" -TimeoutSec 2 -UseBasicParsing
        if ($resp.StatusCode -eq 200) { $frontUp = $true; break }
    } catch { Start-Sleep 2 }
}
if (-not $frontUp) { Fail "Frontend did not come up on port $FrontendPort. Check the frontend window." }
Ok "Frontend is up (port $FrontendPort)"

Step "4/4 Ready"
Ok "Xposure is live: http://localhost:$FrontendPort"
Start-Process "http://localhost:$FrontendPort"
