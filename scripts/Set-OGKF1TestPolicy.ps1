#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateRange(1, 1440)][int]$WeekdayMinutes = 3,
    [ValidateRange(1, 1440)][int]$WeekendMinutes = 3,
    [ValidateSet("AllowAll", "BlockCurrentSlot")][string]$ScheduleMode = "AllowAll",
    [switch]$Disable,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$ServiceName = "OpenGuardKidsAgentTest"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot = Join-Path $RepoRoot ".venv-service"
$AgentDataRoot = Join-Path $env:ProgramData "OpenGuardKids"
$PolicyPath = Join-Path $AgentDataRoot "f1-policy.json"
$RemoteConfigPath = Join-Path $AgentDataRoot "remote-config.json"
$TrayRefreshEventName = "Global\OpenGuardKids.Tray.Refresh.v1"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated PowerShell window (Run as administrator)."
    }
}

function Get-OpenGuardTrayProcessIds {
    try {
        return @(
            Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
                $_.Name -in @("python.exe", "pythonw.exe") -and
                $_.CommandLine -and
                $_.CommandLine.IndexOf($RuntimeRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $_.CommandLine.IndexOf("agent.tray_ui", [StringComparison]::OrdinalIgnoreCase) -ge 0
            } | Select-Object -ExpandProperty ProcessId -Unique
        )
    }
    catch {
        Write-Warning "Could not inspect existing Tray processes: $($_.Exception.Message)"
        return @()
    }
}

Assert-Administrator
if (Test-Path -LiteralPath $RemoteConfigPath -PathType Leaf) {
    throw "This agent is enrolled for remote F4 policy. Change policy in the dashboard, or clean agent data before returning to local F1 test policy."
}
$existingTrayProcessIds = @(Get-OpenGuardTrayProcessIds)
if (-not $env:ProgramData) {
    throw "ProgramData is unavailable; refusing to choose an F1 data directory."
}
New-Item -ItemType Directory -Path $AgentDataRoot -Force | Out-Null

$version = [DateTime]::UtcNow.Ticks
if (Test-Path -LiteralPath $PolicyPath -PathType Leaf) {
    try {
        $current = Get-Content -LiteralPath $PolicyPath -Raw | ConvertFrom-Json
        $previousVersion = [long]$current.version
        if ($previousVersion -ge $version) {
            $version = $previousVersion + 1
        }
    }
    catch {
        Write-Warning "The previous policy was invalid; replacing it with a fresh version."
    }
}

$schedule = @()
for ($day = 0; $day -lt 7; $day++) {
    $schedule += (("1" * 48) -join "")
}
if ($ScheduleMode -eq "BlockCurrentSlot") {
    $now = Get-Date
    $mondayIndex = ([int]$now.DayOfWeek + 6) % 7
    $slot = $now.Hour * 2 + [int]($now.Minute -ge 30)
    $row = $schedule[$mondayIndex].ToCharArray()
    $row[$slot] = "0"
    $schedule[$mondayIndex] = -join $row
}

$policy = [ordered]@{
    version = $version
    enabled = -not $Disable
    weekday_minutes = $WeekdayMinutes
    weekend_minutes = $WeekendMinutes
    schedule = $schedule
    warnings_minutes = @(10, 5, 1)
    grace_seconds = 60
    idle_threshold_seconds = 300
}
$policyJson = $policy | ConvertTo-Json -Depth 4
$temporaryPolicy = Join-Path $AgentDataRoot "f1-policy.json.tmp"
[IO.File]::WriteAllText($temporaryPolicy, $policyJson, [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporaryPolicy -Destination $PolicyPath -Force
& icacls.exe $AgentDataRoot /inheritance:r /grant:r `
    "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Could not restrict the OpenGuard Kids data directory ACL."
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($service -and -not $NoRestart) {
    Restart-Service -Name $ServiceName -Force
    (Get-Service -Name $ServiceName).WaitForStatus(
        [System.ServiceProcess.ServiceControllerStatus]::Running,
        [TimeSpan]::FromSeconds(20)
    )
}

if ($service -and -not $NoRestart) {
    try {
        $refreshEvent = [Threading.EventWaitHandle]::OpenExisting($TrayRefreshEventName)
        try {
            $refreshEvent.Set() | Out-Null
        }
        finally {
            $refreshEvent.Dispose()
        }
    }
    catch [Threading.WaitHandleCannotBeOpenedException] {
        if ($existingTrayProcessIds.Count -gt 0) {
            Write-Warning "The running Tray is from an older build and cannot be refreshed directly. Restart that Tray once."
        }
    }
}

Write-Host "F1 test policy version $version written to $PolicyPath" -ForegroundColor Green
Write-Host "Enabled: $(-not $Disable); weekday/weekend quota: $WeekdayMinutes/$WeekendMinutes minutes"
Write-Host "Schedule mode: $ScheduleMode"
if (-not $service) {
    Write-Host "The service is not installed. The policy will load when it is next installed."
}
elseif ($NoRestart) {
    Write-Host "The Service was not restarted. The new allocation will load on its next restart."
}
elseif ($existingTrayProcessIds.Count -gt 0) {
    $liveTrayProcessIds = @(
        $existingTrayProcessIds | Where-Object {
            Get-Process -Id $_ -ErrorAction SilentlyContinue
        }
    )
    if ($liveTrayProcessIds.Count -gt 0) {
        Write-Host "Existing Tray detected; no new Tray was started. Its clock is resetting to the full allocation." -ForegroundColor Green
    }
    else {
        Write-Warning "The existing Tray exited while the policy was updated. Start it again with .\scripts\Start-OGKTray.ps1 -Open"
    }
}
else {
    Write-Host "No existing Tray was detected. Start one with: & .\scripts\Start-OGKTray.ps1 -Open"
}
