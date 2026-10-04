#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [string]$DeviceName = $env:COMPUTERNAME,
    [string]$PythonExecutable = "",
    [switch]$AllowInsecureHttp,
    [switch]$ElevatedPhase
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$ServiceName = "OpenGuardKidsAgentTest"
$RuntimePython = Join-Path $RepoRoot ".venv-service\Scripts\python.exe"

$parsedServerUri = $null
if (-not [Uri]::TryCreate($ServerUrl, [UriKind]::Absolute, [ref]$parsedServerUri)) {
    throw "ServerUrl must be an absolute HTTP(S) URL."
}
$serverUri = $parsedServerUri
if ($serverUri.Scheme -notin @("http", "https") -or -not $serverUri.Host -or $serverUri.UserInfo -or $serverUri.AbsolutePath -ne "/" -or $serverUri.Query -or $serverUri.Fragment) {
    throw "ServerUrl must be the HTTP(S) server origin, without credentials or a path."
}
if ($serverUri.Scheme -eq "http" -and $serverUri.Host -notin @("127.0.0.1", "localhost", "::1") -and -not $AllowInsecureHttp) {
    throw "HTTP to another computer exposes device credentials. Use HTTPS or explicitly pass -AllowInsecureHttp for a trusted lab network."
}
if ([string]::IsNullOrWhiteSpace($DeviceName) -or $DeviceName.Length -gt 80) {
    throw "DeviceName must have 1 to 80 characters."
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    if ($ElevatedPhase) { throw "Administrator approval was not granted." }
    $quote = { param([string]$value) "'" + $value.Replace("'", "''") + "'" }
    $stage = "& $(& $quote $PSCommandPath) -ElevatedPhase -ServerUrl $(& $quote $ServerUrl) -DeviceName $(& $quote $DeviceName) -PythonExecutable $(& $quote $PythonExecutable)"
    if ($AllowInsecureHttp) { $stage += " -AllowInsecureHttp" }
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($stage))
    $shell = (Get-Process -Id $PID).Path
    Write-Host "Accept the UAC prompt. The first install may take several minutes while dependencies are installed."
    $process = Start-Process -FilePath $shell -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encoded
    ) -Verb RunAs -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Agent installation failed or UAC was cancelled (exit $($process.ExitCode)). Re-run in an Administrator PowerShell window to see the detailed error."
    }
    Write-Host "Service is ready. Opening the Tray pairing screen." -ForegroundColor Green
    & (Join-Path $PSScriptRoot "Start-OGKTray.ps1") -Restart -Open
    Start-Sleep -Seconds 3
    if ((Get-Service -Name $ServiceName).Status -ne "Running") {
        throw "The agent service stopped after Tray startup. Check the OpenGuardKidsAgentTest events in Windows Event Viewer."
    }
    & $RuntimePython -m agent.windows_service ping
    if ($LASTEXITCODE -ne 0) {
        throw "The agent service did not respond after Tray startup."
    }
    return
}

Push-Location $RepoRoot
try {
    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $existing) {
        $install = Join-Path $PSScriptRoot "Install-OGKTestService.ps1"
        $options = @{ SkipStart = $true; PythonExecutable = $PythonExecutable }
        & $install @options
    }
    if (-not $env:ProgramData) { throw "ProgramData is unavailable." }
    $dataRoot = Join-Path $env:ProgramData "OpenGuardKids"
    if (-not (Test-Path -LiteralPath $dataRoot -PathType Container)) {
        throw "The service data directory was not created."
    }
    $bootstrapPath = Join-Path $dataRoot "bootstrap.json"
    $remoteConfig = Join-Path $dataRoot "remote-config.json"
    if (-not (Test-Path -LiteralPath $remoteConfig -PathType Leaf)) {
        $bootstrap = @{
            server_url = $ServerUrl.TrimEnd("/")
            device_name = $DeviceName
            allow_insecure_http = [bool]$AllowInsecureHttp
        } | ConvertTo-Json
        [IO.File]::WriteAllText($bootstrapPath, $bootstrap, [Text.UTF8Encoding]::new($false))
    }
    Set-Service -Name $ServiceName -StartupType Automatic
    if ((Get-Service -Name $ServiceName).Status -eq "Running" -and $existing) {
        Restart-Service -Name $ServiceName -Force
    }
    else {
        Start-Service -Name $ServiceName
    }
    (Get-Service -Name $ServiceName).WaitForStatus(
        [System.ServiceProcess.ServiceControllerStatus]::Running,
        [TimeSpan]::FromSeconds(20)
    )
    & $RuntimePython -m agent.windows_service ping
    if ($LASTEXITCODE -ne 0) { throw "The service started but the named pipe did not respond." }
    Write-Host "Service is ready. The Tray UI will ask for the pairing code." -ForegroundColor Green
}
finally {
    Pop-Location
}

if (-not $ElevatedPhase) {
    & (Join-Path $PSScriptRoot "Start-OGKTray.ps1") -Restart -Open
    Start-Sleep -Seconds 3
    if ((Get-Service -Name $ServiceName).Status -ne "Running") {
        throw "The agent service stopped after Tray startup. Check the OpenGuardKidsAgentTest events in Windows Event Viewer."
    }
    & $RuntimePython -m agent.windows_service ping
    if ($LASTEXITCODE -ne 0) {
        throw "The agent service did not respond after Tray startup."
    }
}
