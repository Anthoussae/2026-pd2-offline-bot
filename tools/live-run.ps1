# Launch a live bot run through the elevated bridge, from ANY working
# directory. Exists because of a silent failure (2026-08-01): a background
# shell launched `tools\bridge-run.ps1` by relative path from the wrong
# cwd, the -File parameter refused, and "the run is going" was actually
# nothing at all — no error the user could see, no input to the game.
# Absolute paths are baked here once so no caller has to get them right.
#
#   powershell -File tools\live-run.ps1                        # default run file
#   powershell -File tools\live-run.ps1 -Run runs\cold-plains-patrol.toml -Games 1 -Chicken 50
#   powershell -File tools\live-run.ps1 -Radius 120            # radius override
#   powershell -File tools\live-run.ps1 -DryRun                # assemble only, send nothing

param(
    [string]$Run = 'runs\cold-plains-patrol.toml',
    [int]$Games = 1,
    [int]$Chicken = 50,
    [int]$Radius = 0,
    [switch]$DryRun,
    [int]$TimeoutSec = 900
)

$repo = 'C:\dev\2026-pd2-bot\2026-pd2-offline-bot'
$cmd = "& `"`$HOME\.venvs\pd2bot\Scripts\python.exe`" -m pd2bot.wiring --games $Games --chicken $Chicken --run $Run"
if ($Radius -gt 0) { $cmd += " --radius $Radius" }
if ($DryRun) { $cmd += ' --dry-run' }

$id = 'live-' + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$tmp = Join-Path $env:TEMP "$id.ps1"
Set-Content -Encoding utf8 $tmp $cmd
try {
    & powershell -File (Join-Path $repo 'tools\bridge-run.ps1') -Id $id -CommandFile $tmp -TimeoutSec $TimeoutSec
    exit $LASTEXITCODE
} finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}
