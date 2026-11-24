<#
.SYNOPSIS
    Discover verified PFC2D/PFC3D Console executables.
#>
[CmdletBinding()]
param(
    [ValidateSet(2, 3)][int]$Dimension = 2,
    [string[]]$Root
)

$ErrorActionPreference = 'Stop'
if (-not $Root) {
    $Root = @(
        'D:\Itasca',
        'C:\Itasca',
        (Join-Path $env:ProgramFiles 'Itasca')
    ) | Where-Object { Test-Path -LiteralPath $_ }
}

# [Text.Encoding]::Latin1 only exists on .NET 5+ (PowerShell 7+).  Windows
# PowerShell 5.1 runs on .NET Framework where it evaluates to $null, causing
# "Cannot call a method on a null-valued expression".  GetEncoding(28591) is
# the ISO-8859-1 / Latin-1 code page available on every .NET runtime.
$Latin1 = [Text.Encoding]::GetEncoding(28591)

$candidates = @()
foreach ($base in $Root) {
    Get-ChildItem -LiteralPath $base -Recurse -File -Filter '*.exe' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "pfc$Dimension`d.*console" -and $_.Name -notmatch 'gui' } |
        ForEach-Object { $candidates += $_ }
}

$results = @()
$rejected = @()
foreach ($candidate in $candidates) {
    try {
        $bytes = [IO.File]::ReadAllBytes($candidate.FullName)
        $text = $Latin1.GetString($bytes)
        if ($text.Contains("PFC${Dimension}D") -and $text.Contains('Console Terminal')) {
            $results += [pscustomobject]@{
                engine_type = "PFC${Dimension}D_CONSOLE"
                dimension = $Dimension
                executable_path = $candidate.FullName
                size_bytes = $candidate.Length
                sha256 = (Get-FileHash -LiteralPath $candidate.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                identity_basis = 'product and console markers inside executable'
            }
        } else {
            $rejected += [pscustomobject]@{ path = $candidate.FullName; reason = 'missing product/console markers' }
        }
    } catch {
        $rejected += [pscustomobject]@{ path = $candidate.FullName; reason = $_.Exception.Message }
    }
}
if (-not $results) {
    if ($candidates.Count -gt 0) {
        $detail = $candidates.Count
        throw "Found ${detail} candidate(s) named like PFC${Dimension}D Console, but none passed identity verification. Rejected: $($rejected | ConvertTo-Json -Compress -Depth 3)"
    }
    throw "No verified PFC${Dimension}D Console executable was found under: $($Root -join '; '). This is a discovery failure, not a script crash."
}
$results | ConvertTo-Json -Depth 4

