# Launch a live bot run through the elevated bridge, from ANY working
# directory. Exists because of a silent failure (2026-08-01): a background
# shell launched `tools\bridge-run.ps1` by relative path from the wrong
# cwd, the -File parameter refused, and "the run is going" was actually
# nothing at all — no error the user could see, no input to the game.
# Absolute paths are baked here once so no caller has to get them right.
#
# Since 2026-08-07 a run is GUARDED: a separate chicken-watchdog process
# runs beside the bot and presses ESC if vitals cross, so a wedged bot
# cannot starve the chicken (docs/reviews/2026-08-07-chicken-starvation-death/).
# That sequence lives in `tools\guarded-run.ps1` and NOT here, because it
# must run elevated — this script does not, only the command it queues
# does. A watchdog started from here would die on its first memory read.
#
#   powershell -File tools\live-run.ps1                        # default run file
#   powershell -File tools\live-run.ps1 -Run runs\countess.toml -Games 1 -Chicken 50
#   powershell -File tools\live-run.ps1 -Radius 120            # radius override
#   powershell -File tools\live-run.ps1 -DryRun                # assemble only, send nothing
#   powershell -File tools\live-run.ps1 -NoWatchdog            # deliberate, and say why

param(
    [string]$Run = 'runs\cold-plains-patrol.toml',
    [int]$Games = 1,
    # 0 = use the class config's number (35 since the Stage D decision,
    # 2026-08-03). The staged-acceptance 50 was always an override.
    [int]$Chicken = 0,
    [int]$Radius = 0,
    [switch]$DryRun,
    # Runs without the watchdog. Deliberately awkward to reach and never
    # the default: a safety layer that is routinely switched off is worse
    # than none, because everyone assumes it is on.
    [switch]$NoWatchdog,
    # Watchdog life threshold; 0 = five points under the bot's own, read
    # from the same class config so the two numbers cannot drift.
    [int]$WatchdogThreshold = 0,
    [int]$TimeoutSec = 900
)

$repo = 'C:\dev\2026-pd2-bot\2026-pd2-offline-bot'

if ($DryRun) {
    # A dry run assembles the wiring and sends nothing, so it needs no
    # watchdog and must not be blocked by one.
    $cmd = "& `"`$HOME\.venvs\pd2bot\Scripts\python.exe`" -m pd2bot.wiring --games $Games --run $Run --dry-run"
    if ($Chicken -gt 0) { $cmd += " --chicken $Chicken" }
    if ($Radius -gt 0) { $cmd += " --radius $Radius" }
} else {
    $guarded = Join-Path $repo 'tools\guarded-run.ps1'
    $cmd = "& powershell -NoProfile -File `"$guarded`" -Run `"$Run`" -Games $Games -Chicken $Chicken -Radius $Radius -WatchdogThreshold $WatchdogThreshold"
    if ($NoWatchdog) { $cmd += ' -NoWatchdog' }
}

$id = 'live-' + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$tmp = Join-Path $env:TEMP "$id.ps1"
Set-Content -Encoding utf8 $tmp $cmd
try {
    & powershell -File (Join-Path $repo 'tools\bridge-run.ps1') -Id $id -CommandFile $tmp -TimeoutSec $TimeoutSec
    exit $LASTEXITCODE
} finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}
