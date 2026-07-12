<#
.SYNOPSIS
  패키징 러너 — packaging\build.ps1(K1 onedir canonical)로 위임하는 얇은 래퍼.

.DESCRIPTION
  루트에서 `.\build.ps1`. K1 onedir 전환 후 실제 빌드·검증(spec 계약 검사,
  빌드 메타데이터, onedir 빌드, 번들 경계 검사, selfcheck·GUI 기동 스모크)은
  packaging\build.ps1 이 소유한다. 이 래퍼는 기존 진입점 관례(-App,
  release.yml·package-installer.ps1 호출부)만 보존한다.
  산출물은 onedir: dist\hwpx-filler\hwpx-filler.exe, dist\hwpx-diff\hwpx-diff.exe.

.PARAMETER App
  filler | diff | all(기본; filler+diff).
  CLI 번들은 이 래퍼 범위 밖 — `.\packaging\build.ps1 -Target cli`.

.PARAMETER SkipCheck
  빌드만, 스모크 생략.

.EXAMPLE
  .\build.ps1                 # 둘 다 빌드 + 검증
  .\build.ps1 -App filler     # filler 번들만
  .\build.ps1 -App diff -SkipCheck
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'filler', 'diff')]
    [string]$App = 'all',
    [switch]$SkipCheck
)
$ErrorActionPreference = 'Stop'

$plan = if ($App -eq 'all') { @('filler', 'diff') } else { @($App) }
foreach ($key in $plan) {
    & (Join-Path $PSScriptRoot 'packaging\build.ps1') -Target $key -SkipCheck:$SkipCheck
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Write-Host "`n완료 — dist\<제품>\ 확인." -ForegroundColor Green
exit 0
