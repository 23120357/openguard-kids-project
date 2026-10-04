#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern("^[A-Za-z2-9]{8}$")][string]$Code,
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [string]$DeviceName = "Windows lab device",
    [string]$PolicySigningKey = ""
)

$ErrorActionPreference = "Stop"
$ServiceName = "OpenGuardKidsAgentTest"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$RuntimePython = Join-Path $RepoRoot ".venv-service\Scripts\python.exe"
$ConfigPath = Join-Path $env:ProgramData "OpenGuardKids\remote-config.json"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window (Run as administrator)."
}
if (-not (Test-Path -LiteralPath $RuntimePython -PathType Leaf)) {
    throw "Install the test service first so its Python runtime exists."
}

Push-Location $RepoRoot
try {
    $arguments = @(
        "-m", "agent.remote_sync", "--config", $ConfigPath,
        "--server", $ServerUrl, "--code", $Code, "--name", $DeviceName
    )
    if ($PolicySigningKey) {
        $arguments += @("--signing-key", $PolicySigningKey)
    }
    & $RuntimePython @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Agent enrollment failed with exit code $LASTEXITCODE."
    }
    Restart-Service -Name $ServiceName -Force
    (Get-Service -Name $ServiceName).WaitForStatus(
        [System.ServiceProcess.ServiceControllerStatus]::Running,
        [TimeSpan]::FromSeconds(20)
    )
    & $RuntimePython -m agent.windows_service ping
    if ($LASTEXITCODE -ne 0) {
        throw "The service restarted but its named-pipe check failed."
    }
    Write-Host "The Windows service is enrolled and remote sync is active." -ForegroundColor Green
}
finally {
    Pop-Location
}
