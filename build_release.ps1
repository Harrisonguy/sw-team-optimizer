param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Release = Join-Path $Root "release"
$UvCache = Join-Path $Root ".uv-cache"
$Uv = Get-Command uv -ErrorAction SilentlyContinue

if (-not $Uv) {
    throw "uv is required for the release build. Install it from https://docs.astral.sh/uv/."
}

Push-Location $Root
try {
$env:UV_CACHE_DIR = $UvCache
if (-not (Test-Path -LiteralPath $Python)) {
    & $Uv.Source venv $Venv --python 3.12
    if ($LASTEXITCODE -ne 0) { throw "uv failed to create the build environment." }
}

& $Uv.Source pip install --python $Python -r (Join-Path $Root "requirements_build.txt")
if ($LASTEXITCODE -ne 0) { throw "uv failed to install the release dependencies." }

if (-not $SkipTests) {
    & $Python -m unittest discover -s (Join-Path $Root "tests")
    if ($LASTEXITCODE -ne 0) { throw "The test suite failed." }
    & $Python -m compileall -q $Root
    if ($LASTEXITCODE -ne 0) { throw "Python compilation checks failed." }
}

Get-Process -Name "SWTeamOptimizer" -ErrorAction SilentlyContinue | Stop-Process -Force
& $Python -m PyInstaller --clean --noconfirm --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build") (Join-Path $Root "packaging\sw_team_optimizer.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed to create the packaged application." }

New-Item -ItemType Directory -Force -Path $Release | Out-Null
$SmokeDb = Join-Path $Release "packaged-smoke.db"
$ScreenshotDir = Join-Path $Release "screenshots"
$ImportScriptPath = Join-Path ([System.IO.Path]::GetTempPath()) "sw-optimizer-release-import.py"
New-Item -ItemType Directory -Force -Path $ScreenshotDir | Out-Null
$env:SW_OPTIMIZER_DB_PATH = $SmokeDb
$env:PYTHONPATH = $Root
$PackagedExe = Join-Path $Root "dist\SWTeamOptimizer\SWTeamOptimizer.exe"
function Invoke-PackagedApp([string[]]$Arguments) {
    $Process = Start-Process -FilePath $PackagedExe -ArgumentList $Arguments -Wait -PassThru -WindowStyle Hidden
    if ($Process.ExitCode -ne 0) {
        throw "Packaged application failed with exit code $($Process.ExitCode)."
    }
}
try {
    $ImportScript = @'
import os
from pathlib import Path
from desktop.db.importer import import_account
from src.core.account.swex_importer import import_swex_account
account = import_swex_account(Path("uuboram-17666244.json"))
import_account(account, Path(os.environ["SW_OPTIMIZER_DB_PATH"]))
'@
    Set-Content -LiteralPath $ImportScriptPath -Value $ImportScript -Encoding utf8
    & $Python $ImportScriptPath
    if ($LASTEXITCODE -ne 0) { throw "The packaged sample-account import failed." }

    Invoke-PackagedApp @("--smoke-test")

    $PageNames = @(
        "runes", "monsters", "artifacts", "rune-optimizer", "team-optimizer",
        "dungeon-builder", "sell-analysis", "analytics", "pvp-planner"
    )
    for ($Index = 0; $Index -lt $PageNames.Count; $Index++) {
        $Page = $Index + 1
        $Screenshot = Join-Path $ScreenshotDir ($PageNames[$Index] + "-1400x900.png")
        Invoke-PackagedApp @("--screenshot", $Screenshot, "--page", "$Page", "--width", "1400", "--height", "900")
        if (-not (Test-Path -LiteralPath $Screenshot)) {
            throw "Packaged screenshot failed for page $Page."
        }
    }

    foreach ($Page in @(1, 5, 6, 8, 9)) {
        $Screenshot = Join-Path $ScreenshotDir ($PageNames[$Page - 1] + "-1100x720.png")
        Invoke-PackagedApp @("--screenshot", $Screenshot, "--page", "$Page", "--width", "1100", "--height", "720")
        if (-not (Test-Path -LiteralPath $Screenshot)) {
            throw "Compact packaged screenshot failed for page $Page."
        }
    }

    $Screenshots = Get-ChildItem -LiteralPath $ScreenshotDir -Filter "*.png" |
        Where-Object { $_.Name -ne "ui-contact-sheet.png" } |
        Select-Object -ExpandProperty FullName
    & $Python (Join-Path $Root "packaging\validate_screenshots.py") @Screenshots
}
finally {
    Remove-Item Env:\SW_OPTIMIZER_DB_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ImportScriptPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $SmokeDb -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath ($SmokeDb + "-shm") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath ($SmokeDb + "-wal") -Force -ErrorAction SilentlyContinue
}

$Archive = Join-Path $Release "SWTeamOptimizer-1.0.0-win64.zip"
Compress-Archive -Path (Join-Path $Root "dist\SWTeamOptimizer\*") -DestinationPath $Archive -Force

if (-not $SkipInstaller) {
    $ProgramFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
    $CompilerCandidates = @(
        (Join-Path $ProgramFilesX86 "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    $Compiler = $CompilerCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if ($Compiler) {
        & $Compiler (Join-Path $Root "packaging\windows\installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed to build the installer." }
    }
    else {
        & (Join-Path $Root "packaging\windows\build_setup.ps1") -Archive $Archive
        if ($LASTEXITCODE -ne 0) { throw "The Windows setup build failed." }
    }
}

Write-Host "Release artifacts created in $Release"
}
finally {
    Remove-Item Env:\UV_CACHE_DIR -ErrorAction SilentlyContinue
    Pop-Location
}
