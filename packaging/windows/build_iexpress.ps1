param(
    [Parameter(Mandatory = $true)]
    [string]$Archive,

    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Release = Join-Path $Root "release"
$Stage = Join-Path $Release "iexpress-stage"
$SedPath = Join-Path $Release "sw-team-optimizer-iexpress.sed"
$WindowsRoot = $env:WINDIR
if (-not $WindowsRoot) {
    $WindowsRoot = $env:SystemRoot
}
if (-not $WindowsRoot) {
    $WindowsRoot = "C:\Windows"
}
$IExpress = Join-Path $WindowsRoot "System32\iexpress.exe"

if (-not $OutputPath) {
    $OutputPath = Join-Path $Release "SWTeamOptimizer-Setup-1.0.0.exe"
}

function Assert-UnderDirectory([string]$Path, [string]$Parent) {
    $FullPath = [System.IO.Path]::GetFullPath($Path)
    $FullParent = [System.IO.Path]::GetFullPath($Parent)
    if (-not $FullParent.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $FullParent += [System.IO.Path]::DirectorySeparatorChar
    }
    if (-not $FullPath.StartsWith($FullParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside $FullParent"
    }
}

if (-not (Test-Path -LiteralPath $Archive)) {
    throw "Portable archive does not exist: $Archive"
}
if (-not (Test-Path -LiteralPath $IExpress)) {
    throw "The built-in Windows installer tool was not found: $IExpress"
}

New-Item -ItemType Directory -Force -Path $Release | Out-Null
Assert-UnderDirectory $Stage $Release
Assert-UnderDirectory $SedPath $Release
Assert-UnderDirectory $OutputPath $Release

Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue

Copy-Item -LiteralPath $Archive -Destination (Join-Path $Stage "SWTeamOptimizer-1.0.0-win64.zip") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install.cmd") -Destination $Stage -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install.ps1") -Destination $Stage -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "uninstall.ps1") -Destination $Stage -Force

$StageForSed = $Stage
if (-not $StageForSed.EndsWith("\")) {
    $StageForSed += "\"
}

$Sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$OutputPath
FriendlyName=SW Team Optimizer 1.0.0 Setup
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1
PostInstallCmd=<None>
AdminQuietInstCmd=powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 -NoLaunch
UserQuietInstCmd=powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 -NoLaunch
SourceFiles=SourceFiles
[Strings]
FILE0=install.cmd
FILE1=install.ps1
FILE2=uninstall.ps1
FILE3=SWTeamOptimizer-1.0.0-win64.zip
[SourceFiles]
SourceFiles0=$StageForSed
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
%FILE3%=
"@

Set-Content -LiteralPath $SedPath -Value $Sed -Encoding ASCII
& $IExpress /N /Q $SedPath
for ($Attempt = 0; $Attempt -lt 120; $Attempt++) {
    if (Test-Path -LiteralPath $OutputPath) {
        break
    }
    Start-Sleep -Seconds 1
}
if (($LASTEXITCODE -ne 0) -and (-not (Test-Path -LiteralPath $OutputPath))) {
    throw "IExpress failed to build the installer."
}
if (-not (Test-Path -LiteralPath $OutputPath)) {
    throw "Installer was not created: $OutputPath"
}
if ($LASTEXITCODE -ne 0) {
    Write-Warning "IExpress returned exit code $LASTEXITCODE after creating the installer."
}

Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $SedPath -Force -ErrorAction SilentlyContinue

Write-Host "Installer created: $OutputPath"
