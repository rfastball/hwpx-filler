<#
  Real WebView2 selftest capability boundary. The normal and test-enabled windows
  use the same sealed bundle; a planted global proves the detector can fail.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$EvidenceDir
)
$ErrorActionPreference = 'Stop'
$exePath = [IO.Path]::GetFullPath($Exe)
$evidencePath = [IO.Path]::GetFullPath($EvidenceDir)
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "Native GUI executable is missing: $exePath"
}
if (Test-Path -LiteralPath $evidencePath) {
    throw "Capability evidence directory must be new: $evidencePath"
}
New-Item -ItemType Directory -Path $evidencePath | Out-Null

$environmentNames = @(
    'PATH', 'HWPXFILLER_HOME', 'HWPX_SELFTEST_OUT',
    'HWPX_SELFTEST_NO_CAPABILITY', 'HWPX_SELFTEST_GLOBAL_DELTA',
    'HWPX_SELFTEST_LEAK_SENTINEL', 'HWPX_SELFTEST_PROBES',
    'HWPX_SELFTEST_SET_THEME', 'HWPX_SELFTEST_SET_FONT_SCALE',
    'HWPX_SELFTEST_GEOMETRY_ONLY', 'HWPX_SELFTEST_OFFLINE_PROBE'
)
$prior = @{}
foreach ($name in $environmentNames) {
    $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Require-Equal($Actual, $Expected, [string]$Label) {
    if ($Actual -cne $Expected) {
        throw "$Label expected '$Expected', got '$Actual'"
    }
}

function Invoke-NativeCapability([string]$Label, [hashtable]$Variables) {
    foreach ($name in $environmentNames) {
        if ($name -ne 'PATH') {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
    }
    $windows = $env:SystemRoot
    $env:PATH = @((Join-Path $windows 'System32'), $windows,
        (Join-Path $windows 'System32/Wbem')) -join ';'
    $env:HWPXFILLER_HOME = Join-Path $evidencePath "$Label-home"
    $output = Join-Path $evidencePath "$Label.json"
    $env:HWPX_SELFTEST_OUT = $output
    foreach ($name in $Variables.Keys) {
        [Environment]::SetEnvironmentVariable($name, [string]$Variables[$name], 'Process')
    }
    $process = Start-Process -FilePath $exePath -ArgumentList '--selftest' `
        -PassThru -WindowStyle Hidden
    # The native host has a 200 s absolute deadline; leave 30 s to land evidence.
    if (-not $process.WaitForExit(230000)) {
        Stop-Process -Id $process.Id -Force
        throw "$Label native WebView2 process exceeded its outer 230s limit"
    }
    if ($process.ExitCode -ne 0) {
        $detail = if (Test-Path -LiteralPath $output) {
            Get-Content -LiteralPath $output -Raw
        } else {
            $alerts = Join-Path $env:HWPXFILLER_HOME 'webapp-alerts.log'
            if (Test-Path -LiteralPath $alerts) { Get-Content -LiteralPath $alerts -Raw }
            else { 'No native receipt or durable alert was written.' }
        }
        throw "$Label native WebView2 process exited $($process.ExitCode): $detail"
    }
    if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
        throw "$Label native WebView2 receipt is missing"
    }
    $receipt = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
    if ($null -ne $receipt.error) {
        throw "$Label native WebView2 probe failed: $($receipt.error)"
    }
    return $receipt
}

try {
    $normal = Invoke-NativeCapability 'normal' @{ HWPX_SELFTEST_NO_CAPABILITY = '1' }
    Require-Equal $normal.mode 'no_capability' 'normal mode'
    $surface = $normal.non_exposure
    Require-Equal $surface.product_typeof 'object' 'product API positive control'
    Require-Equal $surface.selftest_own $false 'normal selftest own property'
    Require-Equal $surface.selftest_typeof 'undefined' 'normal selftest API'
    Require-Equal $surface.host_claim_typeof 'undefined' 'normal host claim'
    if ($surface.url_after -notmatch '\?selftest=1.*#selftest$') {
        throw "query/hash capability probe did not navigate: $($surface.url_after)"
    }
    Require-Equal $surface.selftest_own_after_query_hash $false 'query/hash own property'
    Require-Equal $surface.selftest_typeof_after_query_hash 'undefined' 'query/hash test API'
    $base = $normal.global_delta
    if ($base.total_own -le 500 -or -not $base.has_document -or -not $base.has_location) {
        throw 'normal global inventory has no live WebView positive control'
    }
    Require-Equal ($base.hwpx_namespace -join ',') '__hwpx' 'normal HWPX globals'
    Require-Equal $base.retired_present.Count 0 'retired globals'

    $sentinelName = '__hwpxLeakSentinel'
    $sentinel = Invoke-NativeCapability 'sentinel' @{
        HWPX_SELFTEST_NO_CAPABILITY = '1'
        HWPX_SELFTEST_LEAK_SENTINEL = $sentinelName
    }
    Require-Equal $sentinel.leak_sentinel $sentinelName 'planted sentinel'
    Require-Equal $sentinel.non_exposure.product_typeof 'object' 'sentinel product API'
    if ($sentinel.global_delta.hwpx_namespace -notcontains $sentinelName) {
        throw 'planted global escaped the native inventory'
    }
    if (($sentinel.global_delta.hwpx_namespace -join ',') -eq '__hwpx') {
        throw 'planted global did not break the namespace allowlist'
    }

    $enabled = Invoke-NativeCapability 'enabled' @{ HWPX_SELFTEST_GLOBAL_DELTA = '1' }
    Require-Equal $enabled.mode 'global_delta' 'capability mode'
    $testing = $enabled.global_delta
    if ($testing.total_own -le 500 -or -not $testing.has_document -or -not $testing.has_location) {
        throw 'capability global inventory has no live WebView positive control'
    }
    Require-Equal $testing.digest_without_test $base.digest 'only-test-global digest'
    Require-Equal $testing.total_own ($base.total_own + 1) 'only-test-global count'
    Require-Equal ($testing.hwpx_namespace -join ',') '__hwpx,__hwpxTest' 'enabled HWPX globals'
    if ($testing.digest -eq $testing.digest_without_test) {
        throw 'global digest did not react to the test capability'
    }
    Write-Output "Native WebView2 capability boundary: 3 launches passed; receipts=$evidencePath"
} finally {
    foreach ($name in $environmentNames) {
        if ($null -eq $prior[$name]) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $prior[$name], 'Process')
        }
    }
}
