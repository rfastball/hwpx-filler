<#
.SYNOPSIS
  패키징 러너 — PyInstaller 로 exe 빌드 + --selfcheck 스모크.

.DESCRIPTION
  루트에서 `.\build.ps1`. 기본은 두 제품 모두 빌드하고 각각 헤드리스 selfcheck 를
  돌린다(패키징 산출물 검증). selfcheck 가 FAIL 이면 종료코드 비0.

.PARAMETER App
  filler | diff | all(기본).

.PARAMETER SkipCheck
  빌드만, selfcheck 생략.

.EXAMPLE
  .\build.ps1                 # 둘 다 빌드 + 검증
  .\build.ps1 -App filler     # filler exe 만
  .\build.ps1 -App diff -SkipCheck
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'filler', 'diff')]
    [string]$App = 'all',
    [switch]$SkipCheck
)
$ErrorActionPreference = 'Stop'
# 한글 selfcheck 출력이 깨지지 않도록 UTF-8 강제.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$root = $PSScriptRoot
$dist = Join-Path $root 'dist'
$corpus = Join-Path $root 'tests\corpus\real'

if (-not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) {
    Write-Error "uv 없음. 설치 후: uv sync --all-extras --group build"
    exit 1
}

& uv run --no-sync --group build python (Join-Path $root 'scripts\generate_build_metadata.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# (제품키) = spec, exe 이름, selfcheck 인자
$targets = @{
    filler = @{
        Spec  = 'packaging\hwpx_filler.spec'
        Exe   = 'hwpx-filler.exe'
        Check = @('--selfcheck')
    }
    diff = @{
        Spec  = 'packaging\hwpx_diff.spec'
        Exe   = 'hwpx-diff.exe'
        Check = @('--selfcheck',
                  (Join-Path $corpus 'spec_revision_2025.hwpx'),
                  (Join-Path $corpus 'spec_revision_2026.hwpx'))
    }
}

$plan = if ($App -eq 'all') { @('filler', 'diff') } else { @($App) }
$failed = @()

foreach ($key in $plan) {
    $t = $targets[$key]
    Write-Host "`n=== 빌드: $key ($($t.Spec)) ===" -ForegroundColor Cyan
    & uv run --no-sync --extra gui --group build pyinstaller (Join-Path $root $t.Spec) --noconfirm
    if ($LASTEXITCODE -ne 0) {
        Write-Error "빌드 실패: $key"
        exit 1
    }

    if ($SkipCheck) { continue }

    $exe = Join-Path $dist $t.Exe
    Write-Host "--- selfcheck: $($t.Exe) ---" -ForegroundColor Cyan
    $out = & $exe @($t.Check) 2>&1
    $code = $LASTEXITCODE
    Write-Host $out
    if ($code -ne 0) {
        Write-Host "FAIL: $($t.Exe) selfcheck (exit $code)" -ForegroundColor Red
        $failed += $key
    } else {
        Write-Host "OK: $($t.Exe)" -ForegroundColor Green
    }
}

if ($failed.Count -gt 0) {
    Write-Host "`nselfcheck 실패: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "`n완료 — dist\ 확인." -ForegroundColor Green
exit 0
