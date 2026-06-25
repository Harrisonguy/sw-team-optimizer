param(
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

$AppName = "SW Team Optimizer"
$AppVersion = "1.0.0"
$AppPublisher = "SW Optimizer"
$ProcessName = "SWTeamOptimizer"
$ExeName = "SWTeamOptimizer.exe"
$ArchiveName = "SWTeamOptimizer-1.0.0-win64.zip"

$InstallRoot = $env:LOCALAPPDATA
$InstallDir = Join-Path $InstallRoot $AppName
$StagingDir = "$InstallDir.new"
$Archive = Join-Path $PSScriptRoot $ArchiveName
$UninstallScript = Join-Path $InstallDir "uninstall.ps1"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$StartMenuShortcut = Join-Path $StartMenuDir "$AppName.lnk"
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SWTeamOptimizer"

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
    throw "Installer payload is missing: $Archive"
}

Assert-UnderDirectory $InstallDir $InstallRoot
Assert-UnderDirectory $StagingDir $InstallRoot

Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Stop-Process -Force

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Remove-Item -LiteralPath $StagingDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $StagingDir -Force

$StagedExe = Join-Path $StagingDir $ExeName
if (-not (Test-Path -LiteralPath $StagedExe)) {
    throw "Installer payload did not contain $ExeName"
}

Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
Move-Item -LiteralPath $StagingDir -Destination $InstallDir
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "uninstall.ps1") -Destination $UninstallScript -Force

$InstalledExe = Join-Path $InstallDir $ExeName
$Shell = New-Object -ComObject WScript.Shell

New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
$Shortcut = $Shell.CreateShortcut($StartMenuShortcut)
$Shortcut.TargetPath = $InstalledExe
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.IconLocation = $InstalledExe
$Shortcut.Save()

try {
    $Shortcut = $Shell.CreateShortcut($DesktopShortcut)
    $Shortcut.TargetPath = $InstalledExe
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.IconLocation = $InstalledExe
    $Shortcut.Save()
}
catch {
    Write-Warning "Desktop shortcut could not be created: $($_.Exception.Message)"
}

New-Item -Path $UninstallKey -Force | Out-Null
New-ItemProperty -Path $UninstallKey -Name "DisplayName" -Value $AppName -PropertyType String -Force | Out-Null
New-ItemProperty -Path $UninstallKey -Name "DisplayVersion" -Value $AppVersion -PropertyType String -Force | Out-Null
New-ItemProperty -Path $UninstallKey -Name "Publisher" -Value $AppPublisher -PropertyType String -Force | Out-Null
New-ItemProperty -Path $UninstallKey -Name "InstallLocation" -Value $InstallDir -PropertyType String -Force | Out-Null
New-ItemProperty -Path $UninstallKey -Name "DisplayIcon" -Value $InstalledExe -PropertyType String -Force | Out-Null
New-ItemProperty -Path $UninstallKey -Name "NoModify" -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $UninstallKey -Name "NoRepair" -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $UninstallKey -Name "UninstallString" -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$UninstallScript`"" -PropertyType String -Force | Out-Null

if (-not $NoLaunch) {
    Start-Process -FilePath $InstalledExe -WorkingDirectory $InstallDir | Out-Null
}

Write-Host "$AppName $AppVersion installed to $InstallDir"
