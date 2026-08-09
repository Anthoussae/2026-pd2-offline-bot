# Run the bot with its chicken watchdog beside it. RUNS ELEVATED.
#
# Why this file exists separately from live-run.ps1: the watchdog needs
# Administrator rights for both halves of its job (reading the client's
# memory, and sending ESC past UIPI), and it must be a SEPARATE PROCESS
# from the bot so a wedged bot cannot starve it. live-run.ps1 itself runs
# unelevated — only the command it queues is elevated — so a watchdog
# started there would have died on its first memory read. Found
# 2026-08-07 while preparing the M6 P5 battery, before it could waste a
# live run.
#
# The bridge executes exactly one command at a time, so the watchdog
# cannot be a queue entry of its own (it would hold the queue for the
# whole run). Instead the whole guarded sequence is one entry: start the
# watchdog detached, wait for it to prove itself alive, run the bot,
# then kill the watchdog tree and verify it died.
#
#   powershell -File tools\guarded-run.ps1 -Run runs\countess.toml -Games 1 -Chicken 50

param(
    [string]$Run = 'runs\cold-plains-patrol.toml',
    [int]$Games = 1,
    [int]$Chicken = 0,
    [int]$Radius = 0,
    # 0 = five points under the bot's own, from the same class config.
    [int]$WatchdogThreshold = 0,
    [switch]$NoWatchdog
)

$ErrorActionPreference = 'Continue'
$repo = 'C:\dev\2026-pd2-bot\2026-pd2-offline-bot'
$python = "$HOME\.venvs\pd2bot\Scripts\python.exe"
$bridgeDir = Join-Path $env:LOCALAPPDATA 'pd2bot-bridge'
$latch = Join-Path $bridgeDir 'watchdog-latch'
$heartbeat = Join-Path $bridgeDir 'watchdog-heartbeat'

function Test-HeartbeatFresh {
    if (-not (Test-Path $heartbeat)) { return $false }
    $age = ((Get-Date) - (Get-Item $heartbeat).LastWriteTime).TotalSeconds
    return $age -le 3
}

$watchdog = $null
try {
    if (-not $NoWatchdog) {
        # A latch left by a previous run would disarm this one before it
        # started - the drill-cancel stickiness lesson, applied.
        Remove-Item $latch -Force -ErrorAction SilentlyContinue

        $dogArgs = @('-u', '-m', 'pd2bot.watchdog')
        if ($WatchdogThreshold -gt 0) { $dogArgs += @('--threshold', "$WatchdogThreshold") }
        # Capture its output. On 2026-08-08 the watchdog died 16 s into a
        # run and left NO evidence, because its window went with it —
        # the failure had to be re-derived from the bot's side. `-u` is
        # unbuffered, so a crash cannot swallow the last lines.
        $logDir = Join-Path $repo 'logs'
        if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
        $script:watchdogLog = Join-Path $logDir ("watchdog-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
        $watchdog = Start-Process -FilePath $python -ArgumentList $dogArgs `
            -WorkingDirectory $repo -PassThru -WindowStyle Minimized `
            -RedirectStandardOutput $script:watchdogLog `
            -RedirectStandardError ($script:watchdogLog -replace '\.log$', '.err.log')
        Write-Output "watchdog starting (pid $($watchdog.Id)), log: $script:watchdogLog"

        # Prove it is alive rather than assume it: it has to open the
        # client's memory before it can guard anything, and that is
        # exactly the step that fails when rights are wrong.
        $deadline = (Get-Date).AddSeconds(15)
        while ((Get-Date) -lt $deadline -and -not (Test-HeartbeatFresh)) {
            if ($watchdog.HasExited) {
                Write-Error "the watchdog exited immediately (code $($watchdog.ExitCode)) - NOT launching the run"
                exit 1
            }
            Start-Sleep -Milliseconds 300
        }
        if (-not (Test-HeartbeatFresh)) {
            Write-Error 'the watchdog never wrote a heartbeat - NOT launching the run'
            exit 1
        }
        Write-Output 'watchdog ARMED (heartbeat confirmed)'
    }

    $botArgs = @('-m', 'pd2bot.wiring', '--games', "$Games", '--run', $Run)
    if ($Chicken -gt 0) { $botArgs += @('--chicken', "$Chicken") }
    if ($Radius -gt 0) { $botArgs += @('--radius', "$Radius") }
    if (-not $NoWatchdog) { $botArgs += '--require-watchdog' }

    Write-Output "launching: python $($botArgs -join ' ')"
    & $python @botArgs
    $code = $LASTEXITCODE
    Write-Output "bot exited with code $code"
    exit $code
} finally {
    if ($null -ne $watchdog) {
        # Crash or hang? The distinction decides where to look, and
        # without it both look identical from the bot's side (a stale
        # heartbeat). Reported before the kill, or the kill answers it.
        if ($watchdog.HasExited) {
            Write-Warning "the watchdog had ALREADY EXITED (code $($watchdog.ExitCode)) - it did not survive the run"
        } else {
            Write-Output 'watchdog process was still alive at the end'
        }
        # /T because the pid we hold is a LAUNCHER SHIM, not the watchdog:
        # the venv's python.exe re-execs (measured 2026-08-07 - a latch
        # written by pid 25084 from a process started as 21200). Killing
        # only the shim can orphan a live watchdog, and an orphaned
        # watchdog is one that can press ESC into a later, unrelated game.
        & taskkill /PID $watchdog.Id /T /F 2>&1 | Out-Null
        Start-Sleep -Seconds 4
        if (Test-HeartbeatFresh) {
            Write-Warning 'the watchdog may STILL BE RUNNING - check for stray python processes'
        } else {
            Write-Output 'watchdog stopped'
        }
    }
    # The latch is deliberately NOT cleared here: if the watchdog fired,
    # the operator needs to find the evidence. The next launch clears it.
}
