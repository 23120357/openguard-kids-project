#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$RemoveRuntime,
    [switch]$RemoveAgentData
)

$ErrorActionPreference = "Stop"
$ServiceName = "OpenGuardKidsAgentTest"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot = Join-Path $RepoRoot ".venv-service"
$RuntimePython = Join-Path $RuntimeRoot "Scripts\python.exe"
$AgentDataRoot = Join-Path $env:ProgramData "OpenGuardKids"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated PowerShell window (Run as administrator)."
    }
}

function Stop-OpenGuardTray {
    $trayProcessIds = @()
    try {
        $pythonProcesses = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe") -and
            $_.CommandLine -and
            $_.CommandLine.IndexOf($RuntimeRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $_.CommandLine.IndexOf("agent.tray_ui", [StringComparison]::OrdinalIgnoreCase) -ge 0
        }
        $trayProcessIds = @($pythonProcesses | Select-Object -ExpandProperty ProcessId -Unique)
    }
    catch {
        Write-Warning "Could not inspect Python command lines. Exit the OpenGuard Kids Tray manually before removing the runtime."
    }

    foreach ($processId in $trayProcessIds) {
        Write-Host "Stopping OpenGuard Kids Tray process $processId..."
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    $trayDeadline = [DateTime]::UtcNow.AddSeconds(5)
    while (
        $trayProcessIds.Count -gt 0 -and
        (Get-Process -Id $trayProcessIds -ErrorAction SilentlyContinue) -and
        [DateTime]::UtcNow -lt $trayDeadline
    ) {
        Start-Sleep -Milliseconds 100
    }
}

Assert-Administrator
Push-Location $RepoRoot
try {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        Write-Host "Stopping $ServiceName..."
        Stop-Service -Name $ServiceName -Force
        (Get-Service -Name $ServiceName).WaitForStatus(
            [System.ServiceProcess.ServiceControllerStatus]::Stopped,
            [TimeSpan]::FromSeconds(20)
        )
    }

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "Removing $ServiceName..."
        $removedWithPython = $false
        if (Test-Path -LiteralPath $RuntimePython -PathType Leaf) {
            & $RuntimePython -m agent.windows_service remove
            if ($LASTEXITCODE -eq 0) {
                $removedWithPython = $true
            }
            else {
                Write-Warning "The dedicated Python runtime is unusable; falling back to Windows sc.exe."
            }
        }
        if (-not $removedWithPython) {
            & sc.exe delete $ServiceName | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "Windows could not remove the service (exit code $LASTEXITCODE)."
            }
        }
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while ((Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        throw "The service is marked for deletion. Close Service Manager and retry after a few seconds."
    }

    Stop-OpenGuardTray

    if ($RemoveAgentData -and (Test-Path -LiteralPath $AgentDataRoot -PathType Container)) {
        $expectedDataRoot = [IO.Path]::GetFullPath((Join-Path $env:ProgramData "OpenGuardKids"))
        $resolvedDataRoot = (Resolve-Path -LiteralPath $AgentDataRoot).Path
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($resolvedDataRoot, $expectedDataRoot)) {
            throw "Refusing to remove an unexpected agent data directory: $resolvedDataRoot"
        }
        Remove-Item -LiteralPath $resolvedDataRoot -Recurse -Force
        Write-Host "Removed F1 policy, usage state, and event history. This data is not recoverable."
    }

    if ($RemoveRuntime -and (Test-Path -LiteralPath $RuntimeRoot -PathType Container)) {
        $resolvedRuntime = (Resolve-Path -LiteralPath $RuntimeRoot).Path
        if (-not $resolvedRuntime.StartsWith($RepoRoot + [IO.Path]::DirectorySeparatorChar)) {
            throw "Refusing to remove a runtime outside the repository."
        }
        try {
            Remove-Item -LiteralPath $resolvedRuntime -Recurse -Force
        }
        catch {
            throw "Could not remove .venv-service because a process is still using it. Exit the OpenGuard Kids Tray from the notification area, then run cleanup again. Original error: $($_.Exception.Message)"
        }
        Write-Host "Removed the dedicated test-service Python environment."
    }

    Write-Host "$ServiceName is stopped and removed." -ForegroundColor Green
}
finally {
    Pop-Location
}
