# Submit one command to the elevated bridge and wait for its answer.
#
# The agent used to inline this six-line dance on every live check, and
# twice mistuned the polling window (a foreground PowerShell tool call
# times out at 120 s and gets backgrounded mid-poll). One file, one tested
# shape:
#
#   powershell -File tools\bridge-run.ps1 -Id 050-my-check `
#       -Command '& "$HOME\.venvs\pd2bot\Scripts\python.exe" -m pd2bot.dump' `
#       -TimeoutSec 300
#
# QUOTING CAVEAT (the M4 lesson, outer-hop edition): powershell.exe's own
# command line mangles nested quotes and bracket tokens, so -Command only
# survives for SIMPLE strings. Anything with embedded double quotes or
# [brackets] goes in a file instead:
#
#   powershell -File tools\bridge-run.ps1 -Id 051-x -CommandFile my-cmd.ps1
#
# The bridge itself (tools\elevated-bridge.ps1) must already be running in
# an elevated window; this script only drops the command file and reads the
# answer back. Exit codes: 0 = answer received (whatever the command's own
# exit was — that is in the output), 1 = no bridge answer in time.

param(
    [Parameter(Mandatory = $true)][string]$Id,
    [string]$Command,
    [string]$CommandFile,
    [int]$TimeoutSec = 300
)

if (-not $Command -and -not $CommandFile) {
    Write-Output "Provide -Command or -CommandFile"
    exit 1
}
if ($CommandFile) {
    if (-not (Test-Path $CommandFile)) {
        Write-Output "NO SUCH FILE: $CommandFile"
        exit 1
    }
    $Command = Get-Content $CommandFile -Raw
}

$queue = Join-Path $env:LOCALAPPDATA 'pd2bot-bridge'
if (-not (Test-Path $queue)) {
    Write-Output "NO QUEUE at $queue - is the bridge running?"
    exit 1
}

Set-Content -Encoding utf8 (Join-Path $queue "$Id.cmd.ps1") $Command
Set-Content -Encoding utf8 (Join-Path $queue "$Id.timeout") "$TimeoutSec"

$out = Join-Path $queue "$Id.out.txt"
# The bridge enforces $TimeoutSec on the command itself; we wait a little
# longer so a command that used its full budget still gets read back.
$deadline = (Get-Date).AddSeconds($TimeoutSec + 90)
while (-not (Test-Path $out) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
}

if (Test-Path $out) {
    Get-Content $out
    exit 0
}
Write-Output "TIMEOUT: no bridge answer for $Id within $($TimeoutSec + 90)s"
exit 1
