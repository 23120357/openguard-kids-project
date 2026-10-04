#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Open,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot = Join-Path $RepoRoot ".venv-service"
$Pythonw = Join-Path $RepoRoot ".venv-service\Scripts\pythonw.exe"
$Python = Join-Path $RepoRoot ".venv-service\Scripts\python.exe"
$TrayShowEventName = "Global\OpenGuardKids.Tray.Show.v1"

if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
    throw "The dedicated runtime is missing. Run Install-OGKTestService.ps1 first."
}

if ($Restart) {
    $trayProcesses = @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe") -and
            $_.CommandLine -and
            $_.CommandLine.IndexOf($RuntimeRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $_.CommandLine.IndexOf("agent.tray_ui", [StringComparison]::OrdinalIgnoreCase) -ge 0
        } | Select-Object -ExpandProperty ProcessId -Unique
    )
    foreach ($trayProcessId in $trayProcesses) {
        Stop-Process -Id $trayProcessId -Force
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while ($trayProcesses.Count -gt 0 -and [DateTime]::UtcNow -lt $deadline) {
        if (-not (Get-Process -Id $trayProcesses -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 100
    }
    if ($trayProcesses.Count -gt 0 -and (Get-Process -Id $trayProcesses -ErrorAction SilentlyContinue)) {
        throw "The previous Tray UI is still running. Close it before starting a new version."
    }
}

try {
    $showEvent = [Threading.EventWaitHandle]::OpenExisting($TrayShowEventName)
    try {
        $showEvent.Set() | Out-Null
        Write-Host "The existing OpenGuard Kids Tray window was opened."
        return
    }
    finally {
        $showEvent.Dispose()
    }
}
catch [Threading.WaitHandleCannotBeOpenedException] {
    # No singleton-aware Tray is currently running. Start the first instance below.
}

$legacyTrayProcessIds = @()
try {
    $legacyTrayProcessIds = @(
        Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe") -and
            $_.CommandLine -and
            $_.CommandLine.IndexOf($RuntimeRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $_.CommandLine.IndexOf("agent.tray_ui", [StringComparison]::OrdinalIgnoreCase) -ge 0
        } | Select-Object -ExpandProperty ProcessId -Unique
    )
}
catch {
    Write-Verbose "Could not inspect legacy Tray processes: $($_.Exception.Message)"
}
if ($legacyTrayProcessIds.Count -gt 0) {
    throw "An older Tray instance is already running but does not support window activation. Exit it from its notification icon once, then run this command again. No duplicate was started."
}

$arguments = @("-m", "agent.tray_ui")
if ($Open) {
    $arguments += "--open"
}
Start-Process -FilePath $Pythonw -ArgumentList $arguments -WorkingDirectory $RepoRoot -WindowStyle Hidden
Write-Host "OpenGuard Kids Tray UI started. Future starts will open this same window."
