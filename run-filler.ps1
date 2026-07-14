<#
.SYNOPSIS
  filler 소스 실행 러너 — exe 빌드 없이 누름틀 주입 제품을 바로 띄운다.

.DESCRIPTION
  루트에서 `.\run-filler.ps1`. 패키징 없이 개발 중인 코드를 그대로 실행한다.
  exe 와 동일한 진입점(main())을 타므로 UI·로직 검증이 그대로 된다.
  test.ps1 / build.ps1 과 같은 관례로 uv 관리 환경을 쓴다.

.PARAMETER Cli
  GUI 대신 CLI 진입점 실행. 이후 인자는 그대로 CLI 로 전달된다.

.EXAMPLE
  .\run-filler.ps1                   # GUI
  .\run-filler.ps1 -Cli --help       # CLI
  .\run-filler.ps1 -Cli --template t.hwpx --data d.xlsx
#>
[CmdletBinding()]
param(
    [switch]$Cli,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# 한글 출력이 콘솔 코드페이지 무관하게 깨지지 않도록 UTF-8 강제.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$module = if ($Cli) { 'hwpxfiller.cli' } else { 'hwpxfiller.webapp' }

if (-not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) {
    Write-Error "uv 없음. 설치 후: uv sync --all-extras --group dev"
    exit 1
}

Write-Host "실행: $module  (uv/Python 3.13)" -ForegroundColor Cyan
& uv run --no-sync --extra gui python -m $module @Rest
exit $LASTEXITCODE
