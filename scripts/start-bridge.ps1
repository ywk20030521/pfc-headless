<#
.SYNOPSIS
    Start one verified PFC Console instance with the in-process MCP bridge.

.DESCRIPTION
    Discovery rejects GUI executables and verifies product/Console markers.
    The engine is launched by the shared ConsoleRuntime with the official
    "--run <bootstrap.py>" arguments; stdin is never redirected.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WorkDir,
    [ValidateSet(2, 3)][int]$Dimension = 2,
    [ValidateRange(1024, 65535)][int]$Port = 9001,
    [string]$Engine
)

$ErrorActionPreference = 'Stop'
if (-not $Engine) {
    $discovered = & (Join-Path $PSScriptRoot 'discover-engine.ps1') `
        -Dimension $Dimension | ConvertFrom-Json
    if (-not $discovered) { throw "No verified PFC${Dimension}D Console build was found." }
    $Engine = @($discovered)[-1].executable_path
}

$engineItem = Get-Item -LiteralPath $Engine
$python = Join-Path $engineItem.DirectoryName 'python310\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Engine-local Python not found: $python"
}

& $python (Join-Path $PSScriptRoot 'console_cli.py') start `
    --workdir $WorkDir `
    --dimension $Dimension `
    --port $Port `
    --engine $Engine
if ($LASTEXITCODE -ne 0) {
    throw "Console start failed with exit code $LASTEXITCODE"
}

