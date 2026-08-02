# Elevated command bridge for pd2bot live checks.
#
# Why this exists: the PD2 client runs as Administrator, and Windows blocks
# both memory reads (OpenProcess) and synthetic input (UIPI) from any
# lower-privilege process. Every live check therefore needs elevation, and
# before this bridge every one of them was a human round trip: the agent
# wrote a command, the user alt-tabbed, pasted, and copied output back
# (instruction log R3-R25). The bridge collapses that loop: the user starts
# THIS script once in a Run-as-administrator window (R31/R32), and the agent
# then drives live checks by dropping command files into a queue directory
# that this loop executes and answers.
#
# Protocol (one file pair per command, processed strictly one at a time,
# oldest name first):
#   <id>.cmd.ps1     the command, written by the agent; executed in a fresh
#                    child powershell (-NoProfile) with cwd = the repo root
#   <id>.timeout     optional sidecar: integer seconds (default 300)
#   <id>.out.txt     the answer: exit code + stdout + stderr (written
#                    atomically: composed as .out.tmp, then renamed)
#   <id>.done.ps1    the executed command, renamed, kept as the audit trail
#   stop             create this file (or press Ctrl+C) to end the bridge
#
# Trust model (user decision, R31): while this loop runs, anything that can
# write to the queue directory executes as Administrator. That is the point
# - sole-user machine, and the agent's commands still appear in the app's
# normal tool flow. Every command is also echoed here before it runs, so
# this window doubles as a live audit log. Stale *.cmd.ps1 files found at
# startup are quarantined (renamed *.stale), never executed.

param(
    [string]$QueueDir = (Join-Path $env:LOCALAPPDATA 'pd2bot-bridge'),
    [string]$WorkDir = 'C:\dev\2026-pd2-bot\2026-pd2-offline-bot',
    [int]$DefaultTimeoutSec = 300
)

$ErrorActionPreference = 'Continue'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: not elevated. Start this from a Run-as-administrator window.' -ForegroundColor Red
    exit 1
}

# Single instance, enforced with a named mutex. Necessary since the bridge
# auto-starts at logon (scheduled task, M5 P6 R169): a manual start on top
# of the task's instance would give TWO loops racing on one queue — each
# command grabbed by whichever polls first, answers interleaved, and the
# audit trail split across two windows. Global\ scope so it holds across
# sessions; the mutex dies with the process, so a crashed bridge never
# blocks the next one.
$script:bridgeMutex = New-Object System.Threading.Mutex($false, 'Global\pd2bot-elevated-bridge')
if (-not $script:bridgeMutex.WaitOne(0)) {
    Write-Host 'Another bridge is already running; this one is not needed.' -ForegroundColor Yellow
    exit 0
}

New-Item -ItemType Directory -Force -Path $QueueDir | Out-Null
Set-Location $WorkDir

# Never execute commands left over from an earlier run.
Get-ChildItem $QueueDir -Filter '*.cmd.ps1' | ForEach-Object {
    Rename-Item $_.FullName ($_.FullName + '.stale') -Force
    Write-Host ("quarantined stale command: " + $_.Name) -ForegroundColor Yellow
}

Write-Host 'pd2bot elevated bridge is running.' -ForegroundColor Green
Write-Host ("  queue : " + $QueueDir)
Write-Host ("  cwd   : " + $WorkDir)
Write-Host ("  stop  : Ctrl+C here, or create a file named 'stop' in the queue")
Write-Host ''

while ($true) {
    $stopFile = Join-Path $QueueDir 'stop'
    if (Test-Path $stopFile) {
        Remove-Item $stopFile -Force
        Write-Host 'Stop requested - bridge exiting.'
        break
    }

    $cmd = Get-ChildItem $QueueDir -Filter '*.cmd.ps1' |
        Sort-Object Name | Select-Object -First 1
    if ($null -eq $cmd) {
        Start-Sleep -Milliseconds 500
        continue
    }

    $id = $cmd.Name -replace '\.cmd\.ps1$', ''
    $timeoutSec = $DefaultTimeoutSec
    $timeoutFile = Join-Path $QueueDir ($id + '.timeout')
    if (Test-Path $timeoutFile) {
        try { $timeoutSec = [int]((Get-Content $timeoutFile -Raw).Trim()) } catch {}
    }

    Write-Host ('=' * 66)
    Write-Host ("[{0}] {1}  (timeout {2}s)" -f (Get-Date -Format 'HH:mm:ss'), $cmd.Name, $timeoutSec) -ForegroundColor Cyan
    Get-Content $cmd.FullName | ForEach-Object { Write-Host ('    ' + $_) }

    $stdoutFile = Join-Path $QueueDir ($id + '.stdout.tmp')
    $stderrFile = Join-Path $QueueDir ($id + '.stderr.tmp')
    $exitFile = Join-Path $QueueDir ($id + '.exit.tmp')
    $outTmp = Join-Path $QueueDir ($id + '.out.tmp')
    $outFinal = Join-Path $QueueDir ($id + '.out.txt')

    # PS 5.1's Start-Process -PassThru never reliably exposes ExitCode
    # (verified empirically), so the exit code travels in-band instead: a
    # wrapper shell runs the command file as a grandchild and writes
    # $LASTEXITCODE to a sidecar file.
    $wrapper = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$($cmd.FullName)`"; " +
        "Set-Content -Path `"$exitFile`" -Value `$LASTEXITCODE"
    $proc = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoProfile', '-Command', $wrapper) `
        -WorkingDirectory $WorkDir -NoNewWindow -PassThru `
        -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile

    $finished = $proc.WaitForExit($timeoutSec * 1000)
    if ($finished) {
        $exit = 'UNKNOWN'
        try { $exit = ((Get-Content $exitFile -Raw -ErrorAction Stop).Trim()) } catch {}
    } else {
        # Kill the whole tree: the wrapper started a grandchild powershell,
        # which may itself have started python.
        & taskkill.exe /PID $proc.Id /T /F | Out-Null
        $exit = 'TIMEOUT'
    }
    Remove-Item $exitFile -Force -ErrorAction SilentlyContinue

    $stdout = ''
    $stderr = ''
    try { $stdout = (Get-Content $stdoutFile -Raw -ErrorAction Stop) } catch {}
    try { $stderr = (Get-Content $stderrFile -Raw -ErrorAction Stop) } catch {}
    Remove-Item $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue

    $body = "exit: $exit`r`n--- stdout ---`r`n$stdout`r`n--- stderr ---`r`n$stderr"
    Set-Content -Path $outTmp -Value $body -Encoding utf8
    Move-Item $outTmp $outFinal -Force

    Write-Host $body
    Rename-Item $cmd.FullName ($id + '.done.ps1') -Force
    Remove-Item $timeoutFile -Force -ErrorAction SilentlyContinue
}
