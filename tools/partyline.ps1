# Toggle Partyline — the bot's in-game chat notifications — on or off.
#
#   powershell -File tools\partyline.ps1 -On
#   powershell -File tools\partyline.ps1 -Off
#   powershell -File tools\partyline.ps1          # status
#
# Works by flag file only (no elevation needed): the flag's ABSENCE means
# ON, which is the user's chosen default (M5 P6 R169). The toggle governs
# notifications; Drill Kit tests keep their chat regardless, because a
# test's OK-gate cannot function on a muted channel.

param(
    [switch]$On,
    [switch]$Off
)

$flag = Join-Path (Join-Path $env:LOCALAPPDATA 'pd2bot-bridge') 'partyline-off'

if ($On -and $Off) {
    Write-Output "Pick one of -On / -Off."
    exit 1
}
if ($On) {
    if (Test-Path $flag) { Remove-Item $flag -Force }
    Write-Output "partyline ON"
} elseif ($Off) {
    New-Item -ItemType Directory -Force -Path (Split-Path $flag) | Out-Null
    Set-Content -Encoding utf8 $flag 'partyline muted by the user'
    Write-Output "partyline OFF"
} else {
    if (Test-Path $flag) { Write-Output "partyline OFF (flag: $flag)" }
    else { Write-Output "partyline ON (default; no flag at $flag)" }
}
exit 0
