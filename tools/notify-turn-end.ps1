# Fired by the Claude Code Stop hook when the agent finishes a terminal
# turn: queue a best-effort "your turn" line into the PD2 client via the
# elevated bridge. FIRE AND FORGET — this script never waits for the
# bridge's answer, because the hook runs on the terminal's critical path
# and a notification is never worth a stall there.
#
# Everything conditional happens on the elevated side
# (pd2bot.partyline --notify): the toggle, the freshness stamp, in-game /
# foreground / no-panel. This side only refuses to queue when it can see
# the outcome from here — partyline muted, or no bridge queue at all —
# so a dead bridge costs nothing and a muted channel queues nothing.

$queue = Join-Path $env:LOCALAPPDATA 'pd2bot-bridge'
if (-not (Test-Path $queue)) { exit 0 }                          # no bridge ever ran here
if (Test-Path (Join-Path $queue 'partyline-off')) { exit 0 }     # muted: don't even queue

# Housekeeping: notifications are the one high-frequency command class,
# so their audit artifacts get a shorter retention than the bridge's
# default keep-everything. A day is plenty to debug a misfire.
Get-ChildItem $queue -Filter 'notify-*' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-24) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$epoch = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$stamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$id = "notify-$epoch"
# --stamp lets the elevated side drop this if it sat in the queue too
# long (the bridge is single-file; a long test in front of us would
# otherwise turn into a burst of stale "your turn" messages afterwards).
$cmd = "& `"`$HOME\.venvs\pd2bot\Scripts\python.exe`" -m pd2bot.partyline --notify `"done - your turn`" --stamp $stamp"
Set-Content -Encoding utf8 (Join-Path $queue "$id.timeout") "30"
Set-Content -Encoding utf8 (Join-Path $queue "$id.cmd.ps1") $cmd
exit 0
