<#
.SYNOPSIS
  테스트 러너 — 프런트 모듈과 Python 품질 게이트 실행.

.DESCRIPTION
  루트에서 `.\test.ps1` 한 줄. web build → npm test → Ruff → Pyright → pytest 순서이며,
  추가 인자는 그대로 pytest 로 넘어간다.

.EXAMPLE
  .\test.ps1                 # 전체
  .\test.ps1 -x -q           # 첫 실패에서 중단, 조용히
  .\test.ps1 -k diff         # 이름에 diff 포함만
  .\test.ps1 tests\test_engine.py
  .\test.ps1 -LiveScope auto # 로컬 전용 부분 실창(병합 판정 아님) — auto|full|범위[,범위]
#>
$ErrorActionPreference = 'Stop'

# `-LiveScope <값>` 만 여기서 읽어 pytest `--live-scope=<값>` 으로 옮긴다. param() 블록을 두지
# 않는다 — PowerShell 의 매개변수 접두 일치가 pytest 의 짧은 인자(`-l` 등)를 가로챈다.
# 범위 지도·CI 거절은 `scripts/live_scope.py`·`tests/contracts/live-scopes.toml` 이 진다.
$pytestArgs = @()
for ($i = 0; $i -lt $args.Count; $i++) {
    if ([string]$args[$i] -ieq '-LiveScope') {
        if ($i + 1 -ge $args.Count) {
            [Console]::Error.WriteLine('-LiveScope 값 없음: auto | full | 범위[,범위]')
            exit 2
        }
        $i++
        $scope = $args[$i]
        if ($scope -is [array]) { $scope = $scope -join ',' }
        $pytestArgs += "--live-scope=$scope"
    } else {
        $pytestArgs += , $args[$i]
    }
}
$uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Error "uv 없음. https://docs.astral.sh/uv/ 에서 설치 후: uv sync --all-extras --group dev --group build"
    exit 1
}

# 한글 테스트/메시지가 깨지지 않도록 UTF-8 강제(콘솔 코드페이지 무관).
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

& (Join-Path $PSScriptRoot 'build-web.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& npm.cmd test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& uv run --no-sync --all-extras --group dev ruff check src tests scripts conftest.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv run --no-sync --all-extras --group dev pyright
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv run --no-sync --all-extras --group dev pytest --basetemp=.pytest-tmp --junitxml=pytest.xml --cov --cov-report=term-missing --cov-report=xml:coverage.xml @pytestArgs
exit $LASTEXITCODE
