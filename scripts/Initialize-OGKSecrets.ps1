#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$EnvPath = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path '.env'),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path '.env.example') -Destination $EnvPath
}

function New-RandomBase64Url([int]$ByteCount) {
    $bytes = [byte[]]::new($ByteCount)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

$lines = [Collections.Generic.List[string]](Get-Content -LiteralPath $EnvPath)
foreach ($name in @('OGK_POLICY_SIGNING_KEY', 'OGK_DATA_ENCRYPTION_KEY')) {
    $index = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^$([Regex]::Escape($name))=") { $index = $i; break }
    }
    if (-not $Force -and $index -ge 0 -and $lines[$index].Length -gt ($name.Length + 1)) {
        continue
    }
    $value = New-RandomBase64Url 32
    if ($index -ge 0) { $lines[$index] = "$name=$value" }
    else { $lines.Add("$name=$value") }
}
[IO.File]::WriteAllLines($EnvPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Host "Generated local signing and AES-256 keys in $EnvPath" -ForegroundColor Green
