<#
.SYNOPSIS
  Run the shipped Quickstart 101 journey and same-home restart in real WebView2.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$EvidenceDir,
    [string]$WebRoot,
    [string]$TutorialRoot
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$binary = [IO.Path]::GetFullPath($Exe)
$evidence = [IO.Path]::GetFullPath($EvidenceDir)
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
    throw "native live101 실행 파일이 없습니다: $binary"
}
if (Test-Path -LiteralPath $evidence) {
    throw "native live101 증거 폴더를 재사용하지 않습니다: $evidence"
}
if (-not (Get-Command node -CommandType Application -ErrorAction SilentlyContinue)) {
    throw 'native live101 드라이버에 필요한 Node가 없습니다.'
}
if ([bool]$WebRoot -ne [bool]$TutorialRoot) {
    throw 'native live101 개발 자산은 WEB과 TUTORIAL을 함께 지정해야 합니다.'
}
$budgetPath = Join-Path $root 'scripts/live101_native/run_budget.json'
$budget = Get-Content -LiteralPath $budgetPath -Raw -Encoding UTF8 | ConvertFrom-Json
$budgetFields = @('boot_ms', 'surface_ms', 'hard_stop_margin_ms', 'cleanup_ms', 'parent_slack_ms')
$outerMs = 0L
foreach ($field in $budgetFields) {
    $value = $budget.$field
    if ($null -eq $value -or ($value -isnot [int] -and $value -isnot [long]) -or $value -le 0) {
        throw "native live101 budget is invalid: $field"
    }
    $outerMs += [long]$value
}
if ($outerMs -gt [int]::MaxValue) { throw 'native live101 outer budget exceeds WaitForExit range' }
$nodeExe = (Get-Command node -CommandType Application -ErrorAction Stop |
    Select-Object -First 1).Source
$hadSelection = Test-Path Env:HWPX_SELFTEST_PROBES
$oldSelection = $env:HWPX_SELFTEST_PROBES
$locationPushed = $false
try {
    Remove-Item Env:HWPX_SELFTEST_PROBES -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $evidence | Out-Null
    $liveHome = Join-Path $evidence 'home'
    $driver = Join-Path $root 'scripts/live101_native/run.mjs'
    Push-Location $root
    $locationPushed = $true
    foreach ($phase in @('journey', 'restart')) {
        $phaseEvidence = Join-Path $evidence $phase
        $driverArgs = @($driver, 'check', '--exe', $binary, '--home', $liveHome,
            '--evidence', $phaseEvidence, '--phase', $phase)
        if ($WebRoot) {
            $driverArgs += @('--dev-assets', [IO.Path]::GetFullPath($WebRoot),
                [IO.Path]::GetFullPath($TutorialRoot))
        }
        New-Item -ItemType Directory -Path $phaseEvidence | Out-Null
        foreach ($arg in $driverArgs) {
            if ($arg.Contains('"') -or $arg.EndsWith('\')) {
                throw "native live101 argument cannot be quoted safely: $arg"
            }
        }
        $arguments = ($driverArgs | ForEach-Object { '"' + $_ + '"' }) -join ' '
        $start = New-Object System.Diagnostics.ProcessStartInfo
        $start.FileName = $nodeExe
        $start.Arguments = $arguments
        $start.WorkingDirectory = $root
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $start
        try {
            if (-not $process.Start()) { throw "native live101 $phase process did not start" }
            if (-not $process.WaitForExit([int]$outerMs)) {
                & taskkill.exe /PID $process.Id /T /F | Out-Null
                $failure = Join-Path $phaseEvidence 'check-report.json'
                if (-not (Test-Path -LiteralPath $failure -PathType Leaf)) {
                    $outerReport = @{ phase = $phase; verdict = @{ ok = $false;
                        failures = @('native live101 outer deadline exceeded') };
                        error = 'native live101 outer deadline exceeded';
                        outer_deadline_ms = $outerMs; teardown = @{ graceful = $false } } |
                        ConvertTo-Json -Depth 5
                    [IO.File]::WriteAllText($failure, $outerReport,
                        (New-Object System.Text.UTF8Encoding($false)))
                }
                throw "native live101 $phase exceeded outer ${outerMs}ms: $phaseEvidence"
            }
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) {
                $failure = Join-Path $phaseEvidence 'check-report.json'
                $detail = if (Test-Path -LiteralPath $failure -PathType Leaf) {
                    (Get-Content -LiteralPath $failure -Raw -Encoding UTF8 | ConvertFrom-Json).error
                } else { 'no check-report.json' }
                throw "native live101 $phase failed(exit $($process.ExitCode)): $detail"
            }
        } finally {
            $process.Dispose()
        }
        $report = Join-Path $phaseEvidence 'check-report.json'
        if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {
            throw "native live101 $phase 보고서가 없습니다: $report"
        }
        $result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($result.phase -ne $phase -or $result.verdict.ok -ne $true -or
            $result.teardown.graceful -ne $true) {
            throw "native live101 $phase 보고서가 완주·정상 종료를 증명하지 못합니다: $report"
        }
    }
} finally {
    if ($locationPushed) { Pop-Location }
    if ($hadSelection) { $env:HWPX_SELFTEST_PROBES = $oldSelection }
    else { Remove-Item Env:HWPX_SELFTEST_PROBES -ErrorAction SilentlyContinue }
}
