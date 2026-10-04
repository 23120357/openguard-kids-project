#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PythonExecutable = "",
    [switch]$SkipBootstrap,
    [switch]$SkipStart
)

$ErrorActionPreference = "Stop"
$ServiceName = "OpenGuardKidsAgentTest"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot = Join-Path $RepoRoot ".venv-service"
$RuntimePython = Join-Path $RuntimeRoot "Scripts\python.exe"
$AgentDataRoot = Join-Path $env:ProgramData "OpenGuardKids"
$PolicyPath = Join-Path $AgentDataRoot "f1-policy.json"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated PowerShell window (Run as administrator)."
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
    }
}

function New-ServiceRuntime {
    if ($PythonExecutable) {
        if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
            throw "Python executable not found: $PythonExecutable"
        }
        $resolvedPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
        if ($resolvedPython.IndexOf("\WindowsApps\", [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "Microsoft Store WindowsApps Python cannot host a LocalSystem service. Pass a real Python installation."
        }
        Invoke-Checked $resolvedPython -m venv $RuntimeRoot
        return
    }

    $codexPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $codexPython -PathType Leaf) {
        Invoke-Checked $codexPython -m venv $RuntimeRoot
        return
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3.11 -m venv $RuntimeRoot
        if ($LASTEXITCODE -ne 0) {
            Invoke-Checked $launcher.Source -3 -m venv $RuntimeRoot
        }
        return
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        if ($python.Source.IndexOf("\WindowsApps\", [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "Only a Microsoft Store WindowsApps Python alias was found. Pass -PythonExecutable with a real Python installation."
        }
        Invoke-Checked $python.Source -m venv $RuntimeRoot
        return
    }
    throw "Python 3.11 or newer was not found. Pass -PythonExecutable with a full path."
}

function Assert-ServiceRuntimeBase {
    $configurationPath = Join-Path $RuntimeRoot "pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $configurationPath -PathType Leaf)) {
        throw "The service runtime configuration is missing: $configurationPath"
    }
    $configuration = Get-Content -LiteralPath $configurationPath -Raw
    if ($configuration.IndexOf("\WindowsApps\", [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "The service runtime uses Microsoft Store WindowsApps Python, which LocalSystem cannot execute. Remove the runtime and pass -PythonExecutable with a real Python installation."
    }
    Invoke-Checked $RuntimePython -c "import sys; assert sys.version_info >= (3, 11); print(sys.executable)"
}

function Initialize-PyWin32ServiceHost {
    # The SCM starts virtual-environment executables with a minimal PATH. Keep the
    # runtime and pywin32 DLLs in the environment root so portable Python behaves
    # the same as a machine-wide Python installation.
    $basePrefix = (& $RuntimePython -c "import sys; print(sys.base_prefix)").Trim()
    $versionTag = (& $RuntimePython -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')").Trim()
    $runtimeDlls = @("python$versionTag.dll", "python3.dll")
    foreach ($dll in $runtimeDlls) {
        $source = Join-Path $basePrefix $dll
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $RuntimeRoot $dll) -Force
        }
    }
    foreach ($dll in @("pywintypes$versionTag.dll", "pythoncom$versionTag.dll")) {
        $source = Join-Path $RuntimeRoot "Lib\site-packages\pywin32_system32\$dll"
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required pywin32 service DLL not found: $source"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $RuntimeRoot $dll) -Force
    }
}

Assert-Administrator
Push-Location $RepoRoot
try {
    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existing) {
        throw "Service $ServiceName already exists. Run Cleanup-OGKTestService.ps1 first."
    }

    if (-not (Test-Path -LiteralPath $RuntimePython -PathType Leaf)) {
        if ($SkipBootstrap) {
            throw "The dedicated runtime does not exist at $RuntimePython. Remove -SkipBootstrap."
        }
        Write-Host "Creating dedicated test-service Python environment..."
        New-ServiceRuntime
    }

    Assert-ServiceRuntimeBase

    if (-not $SkipBootstrap) {
        Write-Host "Installing the tested project dependencies into the dedicated runtime..."
        Invoke-Checked $RuntimePython -m pip install --disable-pip-version-check -r requirements.txt
    }

    Invoke-Checked $RuntimePython -c "import pywintypes, win32serviceutil, win32pipe, pystray, PIL, websocket, websockets"
    Initialize-PyWin32ServiceHost

    if (-not $env:ProgramData) {
        throw "ProgramData is unavailable; refusing to choose an F1 data directory."
    }
    New-Item -ItemType Directory -Path $AgentDataRoot -Force | Out-Null
    & icacls.exe $AgentDataRoot /inheritance:r /grant:r `
        "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not restrict the OpenGuard Kids data directory ACL."
    }
    if (-not (Test-Path -LiteralPath $PolicyPath -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot "agent\f1_policy.default.json") `
            -Destination $PolicyPath
    }

    Write-Host "Registering $ServiceName as a real Windows service..."
    Invoke-Checked $RuntimePython -m agent.windows_service install
    Set-Service -Name $ServiceName -StartupType Manual

    if (-not $SkipStart) {
        Start-Service -Name $ServiceName
        (Get-Service -Name $ServiceName).WaitForStatus(
            [System.ServiceProcess.ServiceControllerStatus]::Running,
            [TimeSpan]::FromSeconds(20)
        )
        Invoke-Checked $RuntimePython -m agent.windows_service ping
    }

    Write-Host ""
    Write-Host "OpenGuard Kids test service is installed." -ForegroundColor Green
    Write-Host "Service name: $ServiceName"
    Write-Host "Startup type: Manual"
    Write-Host "F1 is installed in the safe disabled state. Configure an explicit lab policy with:"
    Write-Host "  & .\scripts\Set-OGKF1TestPolicy.ps1"
    Write-Host "Run the visible Tray UI as the normal signed-in user:"
    Write-Host "  & .\scripts\Start-OGKTray.ps1"
    Write-Host "When finished, remove the test service with:"
    Write-Host "  & .\scripts\Cleanup-OGKTestService.ps1"
}
catch {
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        Write-Warning "Installation was incomplete. Run Cleanup-OGKTestService.ps1 before retrying."
    }
    throw
}
finally {
    Pop-Location
}
