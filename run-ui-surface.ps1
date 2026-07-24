<#
.SYNOPSIS
  기존 UI와 백지 UI 랩을 같은 백엔드로 번갈아 실행한다.

.EXAMPLE
  .\run-ui-surface.ps1 -Surface Lab -Variant blank -Scenario blank
  .\run-ui-surface.ps1 -Surface Legacy
#>
[CmdletBinding()]
param(
    [ValidateSet('Lab', 'Legacy')]
    [string]$Surface = 'Lab',
    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
    [string]$Variant = 'blank',
    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
    [string]$Scenario = 'blank',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$webRoot = Join-Path $root 'web'
$scenarioFile = $null
$labHome = $null

if ($Surface -eq 'Lab') {
    $manifestPath = Join-Path $root 'web-minimal\variants.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $entry = $manifest.variants | Where-Object { $_.id -eq $Variant } | Select-Object -First 1
    if ($null -eq $entry) {
        $known = ($manifest.variants.id -join ', ')
        throw "Unknown UI variant '$Variant'. Available: $known"
    }
    $webRoot = Join-Path (Join-Path $root 'web-minimal') $entry.path
    $scenarioFile = Join-Path $root "web-minimal\scenarios\$Scenario.json"
    if (-not (Test-Path -LiteralPath $scenarioFile -PathType Leaf)) {
        throw "Unknown comparison scenario '$Scenario': $scenarioFile"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $webRoot 'index.html') -PathType Leaf)) {
        throw "UI variant '$Variant' has no index.html: $webRoot"
    }
    $labHome = Join-Path $root ".ui-lab-home\$Variant\$Scenario"
}

if (-not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) {
    Write-Error 'uv is unavailable. Run: uv sync --all-extras --group dev'
    exit 1
}

$oldWebDir = $env:HWPXFILLER_WEB_DIR
$oldHome = $env:HWPXFILLER_HOME
$oldVariant = $env:HWPXFILLER_UI_VARIANT
$oldScenario = $env:HWPXFILLER_UI_SCENARIO
$oldScenarioFile = $env:HWPXFILLER_UI_SCENARIO_FILE
try {
    $env:HWPXFILLER_WEB_DIR = $webRoot
    if ($Surface -eq 'Lab') {
        # 빈 랩의 창 위치·향후 시연 데이터가 기존 사용자 상태와 섞이지 않게 한다.
        $env:HWPXFILLER_HOME = $labHome
        # 향후 시연 하네스가 소비할 예약 seam. 현재 백지 시안은 읽지 않는다.
        $env:HWPXFILLER_UI_VARIANT = $Variant
        $env:HWPXFILLER_UI_SCENARIO = $Scenario
        $env:HWPXFILLER_UI_SCENARIO_FILE = $scenarioFile
    }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

    $selection = if ($Surface -eq 'Lab') { "$Variant / $Scenario" } else { 'current product' }
    Write-Host "UI surface: $Surface ($selection)" -ForegroundColor Cyan
    Write-Host "Web assets: $webRoot" -ForegroundColor DarkGray
    if ($ValidateOnly) {
        Write-Host 'Path validation complete; the app was not started.' -ForegroundColor Green
        return
    }
    & uv run --no-sync --extra gui python -m hwpxfiller.webapp
    exit $LASTEXITCODE
}
finally {
    $env:HWPXFILLER_WEB_DIR = $oldWebDir
    $env:HWPXFILLER_HOME = $oldHome
    $env:HWPXFILLER_UI_VARIANT = $oldVariant
    $env:HWPXFILLER_UI_SCENARIO = $oldScenario
    $env:HWPXFILLER_UI_SCENARIO_FILE = $oldScenarioFile
}
