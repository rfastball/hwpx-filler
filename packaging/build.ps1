<#
.SYNOPSIS
  Compatibility entry point for the native Windows bundles.
.DESCRIPTION
  Preserves the public build.ps1 options while build_native.ps1 owns the build,
  WebView2 selftest, notices, and shipped-copy verification.
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'filler', 'cli')][string]$Target = 'all',
    [switch]$SkipCheck,
    [ValidateSet('Build', 'VerifyExisting')][string]$WebMode = 'Build',
    [string]$ExpectWebIdentity,
    [string]$EvidenceDir,
    [switch]$IncludeInstaller
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'build_native.ps1') @PSBoundParameters
exit $LASTEXITCODE
