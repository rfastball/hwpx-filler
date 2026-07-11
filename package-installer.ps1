<#
.SYNOPSIS
  Inno Setup으로 제품별 사용자 설치 파일을 생성한다.
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'filler', 'diff')]
    [string]$App = 'all',
    [switch]$SkipExe
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

if (-not $SkipExe) {
    & (Join-Path $root 'build.ps1') -App $App
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$iscc = Get-Command iscc.exe -CommandType Application -ErrorAction SilentlyContinue
$isccPath = if ($iscc) { $iscc.Source } else { $null }
if (-not $isccPath) {
    $candidate = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
    if (Test-Path $candidate) { $isccPath = $candidate }
}
if (-not $isccPath) {
    Write-Error 'Inno Setup 6 ISCC.exe를 찾지 못했습니다.'
    exit 1
}

$targets = if ($App -eq 'all') { @('filler', 'diff') } else { @($App) }
foreach ($target in $targets) {
    & $isccPath (Join-Path $root "packaging\installers\hwpx-$target.iss")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Write-Host '완료 — installer-dist\ 확인.' -ForegroundColor Green
