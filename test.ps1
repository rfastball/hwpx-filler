<#
.SYNOPSIS
  테스트 러너 — 웹 봉인, 프런트 모듈, 저장소 계약, Rust workspace, 설치 Chrome, 실 Win32, 네이티브 실창.

.DESCRIPTION
  루트에서 `.\test.ps1` 한 줄. 순서는 web build → TOML 파서 준비 → npm test → 문구 census →
  복잡도 예산 → 문서 계약 → Rust workspace → 설치 Chrome 렌더·rhwp 왕복 → 실 Win32(ignored Rust)
  → 네이티브 WebView2 실창이다. 앞 단계가 실패하면 그 자리에서 멈춘다.

  인자는 아래 둘뿐이며 그 밖의 인자는 거절한다.
    -LiveScope auto|full|범위[,범위]  로컬 전용 부분 실창(병합 판정 아님). CI는 full 만 허용한다.
    -SkipLive                         네이티브 WebView2 실창 단계를 뺀다. 실창을 따로 소유하는
                                      호출자(릴리스 workflow 의 Quickstart 101 실주행)를 위한 것이다.

  자원 없는 로컬만 환경 변수로 명시 옵트아웃한다. CI(CI·GITHUB_ACTIONS)에서는 셋 다 거절한다.
    HWPX_SKIP_MOTION_TESTS  설치 Chrome 렌더·rhwp 왕복(tests/browser)
    HWPX_SKIP_NATIVE_TESTS  실 Win32 대화상자·클립보드·창 초점·자격 증명 저장소
    HWPX_SKIP_GUI_TESTS     네이티브 WebView2 실창

.EXAMPLE
  .\test.ps1                  # 전체
  .\test.ps1 -LiveScope auto  # 로컬 전용 부분 실창 — auto|full|범위[,범위]
  .\test.ps1 -SkipLive        # 실창 단계만 빼고 전체
#>
$ErrorActionPreference = 'Stop'

# 인자는 직접 읽는다. param() 블록은 PowerShell 의 매개변수 접두 일치(`-Live` → `-LiveScope`)와
# 이름 없는 위치 인자를 조용히 받아들이므로, 허용 목록 밖의 단어를 시끄럽게 거절하지 못한다.
# 범위 지도·CI 거절은 `scripts/live_scope_native.mjs`·`tests/contracts/live-scopes.toml` 이 진다.
$nativeScope = 'full'
$explicitNativeScope = $false
$skipLive = $false
for ($i = 0; $i -lt $args.Count; $i++) {
    $word = [string]$args[$i]
    if ($word -ieq '-LiveScope') {
        if ($explicitNativeScope) { throw '-LiveScope는 한 번만 지정합니다.' }
        if ($i + 1 -ge $args.Count) { throw '-LiveScope 값 없음: auto | full | 범위[,범위]' }
        $i++
        $scope = $args[$i]
        if ($scope -is [array]) { $scope = $scope -join ',' }
        $nativeScope = [string]$scope
        if (-not $nativeScope.Trim() -or $nativeScope.StartsWith('-')) {
            throw "-LiveScope 값이 올바르지 않습니다: '$nativeScope'"
        }
        $explicitNativeScope = $true
    } elseif ($word -ieq '-SkipLive') {
        if ($skipLive) { throw '-SkipLive는 한 번만 지정합니다.' }
        $skipLive = $true
    } else {
        throw "알 수 없는 인자: '$word' — 허용: -LiveScope <auto|full|범위[,범위]>, -SkipLive"
    }
}
function Test-Truthy([string]$value) {
    return [bool]$value -and $value.Trim().ToLowerInvariant() -notin @('', '0', 'false')
}
$inCi = (Test-Truthy $env:CI) -or (Test-Truthy $env:GITHUB_ACTIONS)
$skipMotion = Test-Truthy $env:HWPX_SKIP_MOTION_TESTS
$skipNative = Test-Truthy $env:HWPX_SKIP_NATIVE_TESTS
$skipGui = Test-Truthy $env:HWPX_SKIP_GUI_TESTS
if ($inCi) {
    foreach ($optOut in @('HWPX_SKIP_MOTION_TESTS', 'HWPX_SKIP_NATIVE_TESTS', 'HWPX_SKIP_GUI_TESTS')) {
        if (Test-Truthy ([Environment]::GetEnvironmentVariable($optOut))) {
            throw "CI에서 $optOut를 사용할 수 없습니다."
        }
    }
}
if ($skipLive -and $explicitNativeScope) { throw '-LiveScope와 -SkipLive를 함께 사용할 수 없습니다.' }
if ($skipGui) {
    if ($explicitNativeScope) { throw '-LiveScope와 HWPX_SKIP_GUI_TESTS를 함께 사용할 수 없습니다.' }
    $nativeScope = $null
}
if ($skipLive) { $nativeScope = $null }
# --- 인자·환경 판정 끝 (tests/js/live_scope_native.test.js 가 여기까지를 실행해 검사한다) ---

# 한글 테스트/메시지가 깨지지 않도록 UTF-8 강제(콘솔 코드페이지 무관).
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

# 저장소 지역 Rust toolchain(test-rust.ps1 과 같은 규칙)을 호출 동안만 쓴다 — 사용자 세션 PATH 를 남기지 않는다.
# 인자는 문자열 배열 하나로 받는다: 함수 호출의 맨 `--` 는 PowerShell 이 매개변수 끝 표지로 삼켜
# cargo 에 닿지 않는다(`-- --ignored` 가 `--ignored` 로 바뀐다).
function Invoke-Cargo([string[]]$CargoArgs) {
    $priorPath = $env:PATH
    $priorCargoHome = $env:CARGO_HOME
    $priorRustupHome = $env:RUSTUP_HOME
    try {
        $cachedCargo = Join-Path $PSScriptRoot '.cache\rhwp-cargo\bin\cargo.exe'
        if (Test-Path -LiteralPath $cachedCargo -PathType Leaf) {
            $env:CARGO_HOME = Join-Path $PSScriptRoot '.cache\rhwp-cargo'
            $env:RUSTUP_HOME = Join-Path $PSScriptRoot '.cache\rhwp-rustup'
            $env:PATH = (Split-Path $cachedCargo) + ';' + $env:PATH
        }
        # 출력은 콘솔로 보내고 stdout 줄은 $script:cargoOutput 에 남긴다 — 반환값은 종료 코드 하나다.
        & cargo @CargoArgs | Tee-Object -Variable captured | Out-Host
        $code = $LASTEXITCODE
        $script:cargoOutput = @($captured)
        return $code
    } finally {
        $env:PATH = $priorPath
        $env:CARGO_HOME = $priorCargoHome
        $env:RUSTUP_HOME = $priorRustupHome
    }
}

Push-Location $PSScriptRoot
try {
    # TOML 파서 준비와 npm test 의 bridge descriptor 는 --offline 으로 짓는다 — 깨끗한 체크아웃
    # (릴리스 러너 포함)에서도 돌도록 workspace 잠금 의존을 먼저 받아 둔다.
    $code = Invoke-Cargo ('fetch --locked' -split ' ')
    if ($code -ne 0) { exit $code }
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

    # 설치 Chrome 렌더 기하·rhwp 왕복 — 방금 봉인·검증한 build/web 을 읽는다(Chrome 렌더 증거, WebView2 아님).
    if ($skipMotion) {
        Write-Warning 'HWPX_SKIP_MOTION_TESTS: 설치 Chrome 렌더·rhwp 왕복 검사(tests/browser)를 실행하지 않았습니다.'
    } else {
        $code = Invoke-Cargo ('build --locked -p hwpx-filler --example browser_fixture' -split ' ')
        if ($code -ne 0) { exit $code }
        $env:HWPX_WEB_ARTIFACT_ROOT = Join-Path $PSScriptRoot 'build/web'
        $env:HWPX_BROWSER_FIXTURE_BIN = Join-Path $PSScriptRoot 'target/debug/examples/browser_fixture.exe'
        try {
            & node --test --test-concurrency=1 'tests/browser/*.test.js'
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        } finally {
            Remove-Item Env:HWPX_WEB_ARTIFACT_ROOT, Env:HWPX_BROWSER_FIXTURE_BIN -ErrorAction SilentlyContinue
        }
    }

    # 실 Win32 — 데스크톱 세션·OLE 아파트·클립보드·자격 증명 저장소가 있어야 도는 ignored Rust 테스트.
    # 이름 목록은 CI windows-native 와 같고 tests/js/quality_workflow.test.js 가 소스의 #[ignore] 집합과 대조한다.
    if ($skipNative) {
        Write-Warning 'HWPX_SKIP_NATIVE_TESTS: 실 Win32 대화상자·클립보드·창 초점·자격 증명 검사를 실행하지 않았습니다.'
    } else {
        $code = Invoke-Cargo (('test -p hwpx-desktop --lib --locked -- --ignored --exact' -split ' ') + @(
            'dialogs::win::positive_tests::windows_sta_dialog_result_and_pidl_allocator_round_trip',
            'single_instance::tests::windows_clipboard_and_visible_focus_round_trip',
            'nara_secret_store::tests::windows_credential_store_round_trip'))
        if ($code -ne 0) { exit $code }
        # 이름이 어긋나면 libtest 는 0개를 돌리고 성공한다 — 실행 수를 직접 확인한다.
        if (-not ($script:cargoOutput -match '^test result: ok\. 3 passed;')) {
            throw '실 Win32 ignored 테스트 3개가 모두 실행되지 않았습니다.'
        }
    }
} finally {
    Pop-Location
}

if ($null -eq $nativeScope) {
    if ($skipLive) {
        Write-Warning '-SkipLive: 네이티브 WebView2 실창 단계를 실행하지 않았습니다 — 호출자가 실창을 따로 소유해야 합니다.'
    } elseif ($skipGui) {
        Write-Warning 'HWPX_SKIP_GUI_TESTS: 네이티브 WebView2 실창 단계를 실행하지 않았습니다.'
    }
    exit 0
}
$evidence = Join-Path $PSScriptRoot ('build/native-live-scope-' +
    (Get-Date -Format 'yyyyMMdd-HHmmss') + "-$PID")
& (Join-Path $PSScriptRoot 'scripts/run_native_live_scope.ps1') `
    -Scope $nativeScope `
    -WebRoot (Join-Path $PSScriptRoot 'build/web') `
    -TutorialRoot (Join-Path $PSScriptRoot 'examples/tutorial') `
    -EvidenceDir $evidence
exit $LASTEXITCODE
