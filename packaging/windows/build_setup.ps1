param(
    [Parameter(Mandatory = $true)]
    [string]$Archive,

    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Release = Join-Path $Root "release"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Bootstrap = Join-Path $PSScriptRoot "setup_bootstrap.py"
$WorkPath = Join-Path $Root "build\setup-installer"
$SpecPath = Join-Path $Root "SWTeamOptimizer-Setup-1.0.0.spec"

if (-not $OutputPath) {
    $OutputPath = Join-Path $Release "SWTeamOptimizer-Setup-1.0.0.exe"
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Build Python was not found: $Python"
}
if (-not (Test-Path -LiteralPath $Bootstrap)) {
    throw "Setup bootstrap was not found: $Bootstrap"
}
if (-not (Test-Path -LiteralPath $Archive)) {
    throw "Portable archive does not exist: $Archive"
}

New-Item -ItemType Directory -Force -Path $Release | Out-Null
Get-Process -Name "SWTeamOptimizer-Setup-1.0.0" -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $WorkPath -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $SpecPath -Force -ErrorAction SilentlyContinue

$ArchiveData = "$Archive;."
$InstallData = "$(Join-Path $PSScriptRoot "install.ps1");."
$UninstallData = "$(Join-Path $PSScriptRoot "uninstall.ps1");."

& $Python -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --noconsole `
    --name "SWTeamOptimizer-Setup-1.0.0" `
    --distpath $Release `
    --workpath $WorkPath `
    --add-data $ArchiveData `
    --add-data $InstallData `
    --add-data $UninstallData `
    $Bootstrap
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed to build the setup executable."
}
if (-not (Test-Path -LiteralPath $OutputPath)) {
    throw "Setup executable was not created: $OutputPath"
}

Remove-Item -LiteralPath $SpecPath -Force -ErrorAction SilentlyContinue
Write-Host "Installer created: $OutputPath"
