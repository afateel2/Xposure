# Stops the Xposure dev backend/frontend cleanly, including orphaned
# uvicorn --reload workers and orphaned Next.js dev server children.
#
# Why this exists, part 1: `netstat`'s port-owner PID can be stale on this
# machine — Stop-Process against it sometimes reports success while the
# real process (a multiprocessing.spawn_main worker orphaned when its
# uvicorn --reload reloader parent was killed without it) keeps running
# and keeps serving stale config (measured directly at least twice while
# building this project — see docs/PLAN.md). Walking the real process
# tree via Get-CimInstance and killing every match, parents and orphaned
# children alike, is what actually works.
#
# `next dev`'s own process tree has the identical shape: killing the
# top-level `npm run dev` (or `next dev`) process leaves its actual
# listener child running and still bound to the port. That child's
# command line is next/dist/server/lib/start-server.js, NOT a literal
# "next-server" substring — the first version of this script matched
# "next-server" and missed it, confirmed live (port 3010 stayed
# EADDRINUSE after both TaskStop and this script's first pattern
# reported success). Matching "start-server" and "npm-cli.js run dev"
# too closes that gap.
#
# Why this exists, part 2 (found 2026-09-16, worse than part 1): a
# uvicorn --reload worker orphaned across MULTIPLE restart cycles can end
# up with a command line that mentions neither "uvicorn" nor anything else
# recognizable — on Windows its re-exec through multiprocessing.spawn_main
# looks like `python.exe -c "from multiprocessing.spawn import spawn_main;
# spawn_main(...)" --multiprocessing-fork`, which no content-based pattern
# will ever match (a live, correctly-configured worker has the exact same
# command line shape, so "match spawn_main" would kill good workers too).
# Measured directly: a genuinely fresh `uvicorn --reload` process started,
# logged "Uvicorn running on 0.0.0.0:8010" and "Application startup
# complete", and passed its own /health check — while an old orphaned
# spawn_main worker from a PRIOR session was silently still bound to the
# same port underneath it, and every curl request kept reaching the old
# one, missing routes added since. Windows let both processes claim the
# port without either raising "address already in use". The distinguishing
# fact isn't the command line at all — it's that the orphan's PARENT
# process no longer exists. That's what pass 2 below checks, and pass 3
# is a final belt-and-suspenders: whatever the OS says currently owns
# ports 8010/3010 gets killed too, no matter what its command line says,
# since "confirm the health check passed" turned out not to be enough to
# trust that a fresh server is the one actually answering requests.
#
# Safe to run anytime, even if nothing is up.

$ErrorActionPreference = "SilentlyContinue"
$DEV_PORTS = 8010, 3010
$COMMAND_PATTERN = 'uvicorn|next dev|next-server|start-server|npm-cli\.js run dev'

function Get-AppProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'node.exe'"
}

$killedAny = $false

# Pass 1: known dev-server command lines (the common, expected case).
$named = Get-AppProcesses | Where-Object { $_.CommandLine -match $COMMAND_PATTERN }
foreach ($p in $named) {
    Write-Host "Stopping PID $($p.ProcessId) (matched pattern): $($p.CommandLine)"
    Stop-Process -Id $p.ProcessId -Force
    $killedAny = $true
}

# Pass 2: orphans by parentage, regardless of command line — catches
# generic-looking multiprocessing/worker children whose own command line
# gives no hint they belong to this project, the same shape a
# multi-generation-orphaned uvicorn worker has (see the docstring above).
$allApp = Get-AppProcesses
foreach ($p in $allApp) {
    if ($p.ProcessId -in $named.ProcessId) { continue }
    $parentAlive = Get-Process -Id $p.ParentProcessId -ErrorAction SilentlyContinue
    if (-not $parentAlive) {
        Write-Host "Stopping PID $($p.ProcessId) (orphaned, parent $($p.ParentProcessId) is gone): $($p.CommandLine)"
        Stop-Process -Id $p.ProcessId -Force
        $killedAny = $true
    }
}

Start-Sleep -Seconds 1

# Pass 3: whoever the OS says owns the dev ports right now, no exceptions.
# This is the actual ground truth this script cares about — a process
# that answers on 8010/3010 but wasn't caught by passes 1-2 is exactly
# the failure mode that motivated adding this pass.
foreach ($port in $DEV_PORTS) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerPid in $owners) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid" -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping PID $ownerPid (owns port $port): $($proc.CommandLine)"
            Stop-Process -Id $ownerPid -Force
            $killedAny = $true
        }
    }
}

if (-not $killedAny) {
    Write-Host "Nothing running."
    exit 0
}

Start-Sleep -Seconds 1

$stillNamed = Get-AppProcesses | Where-Object { $_.CommandLine -match $COMMAND_PATTERN }
$stillOnPorts = $DEV_PORTS | ForEach-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue }
if ($stillNamed -or $stillOnPorts) {
    Write-Host "WARNING: still running after kill attempt:"
    if ($stillNamed) { $stillNamed | Select-Object ProcessId, CommandLine | Format-Table -AutoSize -Wrap }
    if ($stillOnPorts) { $stillOnPorts | Select-Object LocalPort, OwningProcess | Format-Table -AutoSize }
} else {
    Write-Host "All stopped."
}
