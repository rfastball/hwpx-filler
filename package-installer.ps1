<#
.SYNOPSIS
  Inno Setup으로 제품별 사용자 설치 파일을 생성한다.
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'filler')]
    [string]$App = 'all',
    [switch]$SkipExe
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

if (-not $SkipExe) {
    & (Join-Path $root 'build.ps1') -App $App
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$isccPath = & (Join-Path $root 'packaging\Find-Iscc.ps1')
if (-not $isccPath) {
    Write-Error 'Inno Setup 6 ISCC.exe를 찾지 못했습니다.'
    exit 1
}

$targets = if ($App -eq 'all') { @('filler') } else { @($App) }
foreach ($target in $targets) {
    & $isccPath (Join-Path $root "packaging\installers\hwpx-$target.iss")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Write-Host '완료 — installer-dist\ 확인.' -ForegroundColor Green
