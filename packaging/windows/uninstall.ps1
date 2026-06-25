$ErrorActionPreference = "Stop"

$AppName = "SW Team Optimizer"
$ProcessName = "SWTeamOptimizer"
$InstallRoot = $env:LOCALAPPDATA
$InstallDir = Join-Path $InstallRoot $AppName
$StartMenuShortcut = Join-Path (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs") "$AppName.lnk"
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SWTeamOptimizer"

function Assert-UnderDirectory([string]$Path, [string]$Parent) {
    $FullPath = [System.IO.Path]::GetFullPath($Path)
    $FullParent = [System.IO.Path]::GetFullPath($Parent)
    if (-not $FullParent.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $FullParent += [System.IO.Path]::DirectorySeparatorChar
    }
    if (-not $FullPath.StartsWith($FullParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside $FullParent"
    }
}

Assert-UnderDirectory $InstallDir $InstallRoot

Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -LiteralPath $StartMenuShortcut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $DesktopShortcut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $InstallDir) {
    $Command = "ping 127.0.0.1 -n 3 > nul & rmdir /s /q `"$InstallDir`""
    Start-Process -FilePath "cmd.exe" -ArgumentList "/d", "/c", $Command -WorkingDirectory $env:TEMP -WindowStyle Hidden | Out-Null
}

Write-Host "$AppName was uninstalled."
