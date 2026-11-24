<#
.SYNOPSIS
    Safely stop a registered PFC Console instance.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WorkDir,
    [ValidateSet(2, 3)][int]$Dimension = 2,
    [ValidateRange(1024, 65535)][int]$Port = 9001,
    [string]$SaveName,
    [switch]$AllowUnsaved
)

$ErrorActionPreference = 'Stop'
$statePath = Join-Path $WorkDir '.pfc-console\runtime.json'
if (-not (Test-Path -LiteralPath $statePath)) {
    throw "No registered runtime state: $statePath"
}
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$python = Join-Path (Split-Path -Parent $state.engine) 'python310\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Engine-local Python not found: $python"
}

$arguments = @(
    (Join-Path $PSScriptRoot 'console_cli.py'),
    'stop',
    '--workdir', $WorkDir,
    '--dimension', "$Dimension",
    '--port', "$Port",
    '--engine', $state.engine
)
if ($SaveName) { $arguments += @('--save-name', $SaveName) }
if ($AllowUnsaved) { $arguments += '--allow-unsaved' }

& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Safe stop failed with exit code $LASTEXITCODE"
}

