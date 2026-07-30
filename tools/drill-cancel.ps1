# Cancel a running live drill without killing the bridge.
#
# The bridge runs one elevated child at a time, and the agent's shell is not
# elevated, so "stop this test" used to mean waiting out the drill's
# timeouts or Ctrl+C-ing the bridge and restarting it (R79). Drills now
# check for this file at every wait and abort within a tick.
#
#   powershell -File tools\drill-cancel.ps1          # request a cancel
#   powershell -File tools\drill-cancel.ps1 -Clear   # withdraw the request
#
# The next drill process clears a stale request on its first run, so a
# forgotten cancel cannot silently kill tomorrow's testing. Within a single
# suite the cancel is sticky on purpose: stopping means stopping, not
# skipping to the next test.

param([switch]$Clear)

$file = Join-Path (Join-Path $env:LOCALAPPDATA 'pd2bot-bridge') 'drill-cancel'

if ($Clear) {
    if (Test-Path $file) {
        Remove-Item $file -Force
        Write-Output "cancel request withdrawn"
    } else {
        Write-Output "no cancel request outstanding"
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path (Split-Path $file) | Out-Null
Set-Content -Encoding utf8 $file 'cancel'
Write-Output "cancel requested — the running drill will abort at its next wait"
