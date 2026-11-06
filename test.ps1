<#
.SYNOPSIS
  테스트 러너 — 프런트 모듈, Rust workspace, Python 품질 게이트 실행.

.DESCRIPTION
  루트에서 `.\test.ps1` 한 줄. web build → npm test → Rust → Ruff → Pyright → pytest → 네이티브 실창 순서이며,
  추가 인자는 그대로 pytest 로 넘어간다.

.EXAMPLE
  .\test.ps1                 # 전체
  .\test.ps1 -x -q           # 첫 실패에서 중단, 조용히
  .\test.ps1 -k diff         # 이름에 diff 포함만
  .\test.ps1 tests\test_engine.py
  .\test.ps1 -LiveScope auto # 로컬 전용 부분 실창(병합 판정 아님) — auto|full|범위[,범위]
#>
$ErrorActionPreference = 'Stop'

# `-LiveScope <값>` 만 여기서 읽어 native WebView 범위 실행으로 옮긴다. param() 블록을 두지
# 않는다 — PowerShell 의 매개변수 접두 일치가 pytest 의 짧은 인자(`-l` 등)를 가로챈다.
# 범위 지도·CI 거절은 `scripts/live_scope_native.mjs`·`tests/contracts/live-scopes.toml` 이 진다.
$pytestArgs = @()
$nativeScope = 'full'
$explicitNativeScope = $false
for ($i = 0; $i -lt $args.Count; $i++) {
    if ([string]$args[$i] -ieq '-LiveScope') {
        if ($explicitNativeScope) { throw '-LiveScope는 한 번만 지정합니다.' }
        if ($i + 1 -ge $args.Count) {
            [Console]::Error.WriteLine('-LiveScope 값 없음: auto | full | 범위[,범위]')
            exit 2
        }
        $i++
        $scope = $args[$i]
        if ($scope -is [array]) { $scope = $scope -join ',' }
        $nativeScope = [string]$scope
        $explicitNativeScope = $true
    } else {
        $pytestArgs += , $args[$i]
    }
}
# pytest의 경로·-k·-m 선택은 해당 선택만 검사한다. 기본 전체 호출과 -x/-q 같은
# 실행 옵션은 기존 full WebView 자원 검사를 계속 소유한다.
if (-not $explicitNativeScope) {
    foreach ($argument in $pytestArgs) {
        $word = [string]$argument
        if ($word -match '^(?:-[km](?:[^-].*)?$|--(?:keyword|markexpr)(?:=|$))' -or
            $word -match '(?:^|[\\/])tests(?:[\\/:]|$)|\.py(?:::|$)') {
            $nativeScope = $null
            break
        }
    }
}
$skipGui = $env:HWPX_SKIP_GUI_TESTS -and
    $env:HWPX_SKIP_GUI_TESTS.Trim().ToLowerInvariant() -notin @('0', 'false')
$inCi = ($env:CI -and $env:CI.Trim().ToLowerInvariant() -notin @('0', 'false')) -or
    ($env:GITHUB_ACTIONS -and $env:GITHUB_ACTIONS.Trim().ToLowerInvariant() -notin @('0', 'false'))
if ($skipGui) {
    if ($inCi) { throw 'CI에서 HWPX_SKIP_GUI_TESTS를 사용할 수 없습니다.' }
    if ($explicitNativeScope) { throw '-LiveScope와 HWPX_SKIP_GUI_TESTS를 함께 사용할 수 없습니다.' }
    $nativeScope = $null
}
if ($null -ne $nativeScope) {
    if (@($pytestArgs | Where-Object { [string]$_ -match '^(?:-m|--markexpr|--live-scope)(?:=|$)' }).Count) {
        throw '-LiveScope와 별도의 pytest live/marker 선택은 함께 쓰지 않습니다.'
    }
    $pytestArgs += '-m'
    $pytestArgs += 'not live'
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
& node scripts/read_toml.mjs --prepare
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& npm.cmd test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& node scripts/ui_copy_census.mjs --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& node scripts/complexity_budget.mjs --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& node scripts/docs_contract.mjs --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-rust.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& uv run --no-sync --all-extras --group dev ruff check src tests scripts conftest.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv run --no-sync --all-extras --group dev pyright
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv run --no-sync --all-extras --group dev pytest --basetemp=.pytest-tmp --junitxml=pytest.xml --cov --cov-report=term-missing --cov-report=xml:coverage.xml @pytestArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($null -ne $nativeScope) {
    $evidence = Join-Path $PSScriptRoot ('build/native-live-scope-' +
        (Get-Date -Format 'yyyyMMdd-HHmmss') + "-$PID")
    & (Join-Path $PSScriptRoot 'scripts/run_native_live_scope.ps1') `
        -Scope $nativeScope `
        -WebRoot (Join-Path $PSScriptRoot 'build/web') `
        -TutorialRoot (Join-Path $PSScriptRoot 'examples/tutorial') `
        -EvidenceDir $evidence
    exit $LASTEXITCODE
}
exit 0
