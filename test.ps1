<#
.SYNOPSIS
  테스트 러너 — venv 의 pytest 로 tests/ 수집·실행.

.DESCRIPTION
  루트에서 `.\test.ps1` 한 줄. 추가 인자는 그대로 pytest 로 넘어간다.

.EXAMPLE
  .\test.ps1                 # 전체
  .\test.ps1 -x -q           # 첫 실패에서 중단, 조용히
  .\test.ps1 -k diff         # 이름에 diff 포함만
  .\test.ps1 tests\test_engine.py
#>
$ErrorActionPreference = 'Stop'
$uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Error "uv 없음. https://docs.astral.sh/uv/ 에서 설치 후: uv sync --all-extras --group dev --group build"
    exit 1
}

# 한글 테스트/메시지가 깨지지 않도록 UTF-8 강제(콘솔 코드페이지 무관).
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

& uv run --no-sync --all-extras --group dev ruff check src tests conftest.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv run --no-sync --all-extras --group dev pyright
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv run --no-sync --all-extras --group dev pytest --basetemp=.pytest-tmp --junitxml=pytest.xml --cov --cov-report=term-missing --cov-report=xml:coverage.xml @args
exit $LASTEXITCODE
