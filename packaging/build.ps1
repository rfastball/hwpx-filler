<#
.SYNOPSIS
  onedir 번들(웹 앱 + CLI)을 빌드하고 스모크 검증한다.

.EXAMPLE
  .\packaging\build.ps1
  .\packaging\build.ps1 -Target cli
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'filler', 'cli')]
    [string]$Target = 'all',
    [switch]$SkipCheck
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
& chcp.com 65001 *> $null

$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'
$corpus = Join-Path $root 'tests\corpus\real'
$evidenceDir = Join-Path $root (
    'build\n03-package-evidence-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + "-$PID"
)
$env:UV_CACHE_DIR = Join-Path $root '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $root '.uv-python'

if (-not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) {
    throw 'uv 없음. 먼저 uv sync --locked --all-extras --group dev --group build'
}

if ($Target -ne 'cli') {
    & (Join-Path $root 'build-web.ps1')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& uv run --no-sync python (Join-Path $PSScriptRoot 'verify_specs.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv run --no-sync python (Join-Path $root 'scripts\generate_build_metadata.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$targets = @{
    filler = @{ Spec = 'hwpx_filler_web.spec'; Dir = 'hwpx-filler-web'; Exe = 'hwpx-filler-web.exe' }
    cli    = @{ Spec = 'hwpx_cli.spec';         Dir = 'hwpx-cli';        Exe = 'hwpx-cli.exe' }
}
$plan = if ($Target -eq 'all') { @('filler', 'cli') } else { @($Target) }

function Test-BundleBoundary([string]$BundleDir) {
    # 두 타깃 모두 웹 이관 완료(#20·#23)로 Qt 미탑재 — PySide/Qt6 DLL 이 하나라도
    # 번들에 있으면 실패(재유입 차단).
    $files = Get-ChildItem $BundleDir -Recurse -File
    $unexpected = $files | Where-Object Name -Match '^(PySide|Qt6)'
    if ($unexpected) {
        throw "미사용 Qt 런타임이 번들에 남음: $($unexpected.Name -join ', ')"
    }
    $nodeRuntime = $files | Where-Object {
        $_.Name -match '^(node(\.exe)?|npm(\.cmd|\.exe)?|npx(\.cmd|\.exe)?)$' -or
        $_.FullName -match '[\\/](node_modules|frontend)([\\/]|$)'
    }
    if ($nodeRuntime) {
        throw "build-time frontend 도구/source가 번들에 남음: $($nodeRuntime.FullName -join ', ')"
    }
}

foreach ($key in $plan) {
    $item = $targets[$key]
    Write-Host "`n=== onedir 빌드: $key ===" -ForegroundColor Cyan
    & uv run --no-sync --extra gui --group build pyinstaller `
        (Join-Path $PSScriptRoot $item.Spec) --noconfirm --clean `
        --distpath $dist --workpath (Join-Path $root "build\pyinstaller-$key")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $exe = Join-Path (Join-Path $dist $item.Dir) $item.Exe
    if (-not (Test-Path $exe)) { throw "onedir exe 누락: $exe" }
    $bundleDir = Split-Path -Parent $exe
    Test-BundleBoundary $bundleDir
    if ($key -eq 'filler') {
        $bundleRoot = Join-Path $bundleDir '_internal'
        & uv run --no-sync python (Join-Path $root 'scripts\verify_packaged_web.py') `
            --repo-root $root --bundle-root $bundleRoot `
            --json-out (Join-Path $evidenceDir 'artifact-parity.json')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    if ($SkipCheck) { continue }

    if ($key -eq 'filler') {
        # build-time Node와 외부 네트워크를 제거한 환경에서 먼저 full-seal selfcheck, 이어서
        # 실제 WebView2 selftest를 수행한다. dead proxy는 loopback을 건드리지 않으면서 외부
        # HTTP(S)를 차단한다(Chromium 기본 loopback bypass).
        New-Item -ItemType Directory -Force $evidenceDir | Out-Null
        $networkControlOut = Join-Path $evidenceDir 'packaged-network-control.json'
        $selftestOut = Join-Path $evidenceDir 'packaged-selftest.json'
        $savedProcessPath = $env:Path
        $savedProductHome = $env:HWPXFILLER_HOME
        $savedSelftestOut = $env:HWPX_SELFTEST_OUT
        $savedOfflineProbe = $env:HWPX_SELFTEST_OFFLINE_PROBE
        $savedBrowserArgs = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
        try {
            $windowsRoot = $env:SystemRoot
            $env:Path = @(
                (Join-Path $windowsRoot 'System32'),
                $windowsRoot,
                (Join-Path $windowsRoot 'System32\Wbem'),
                (Join-Path $windowsRoot 'System32\WindowsPowerShell\v1.0')
            ) -join ';'
            if (Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue) {
                throw 'Node-free packaged gate PATH에서 node.exe가 발견됐습니다.'
            }

            $selfcheck = Start-Process -FilePath $exe -Wait -PassThru `
                -ArgumentList @('--selfcheck')
            if ($selfcheck.ExitCode -ne 0) {
                throw "Node-free packaged selfcheck 실패(exit $($selfcheck.ExitCode))"
            }

            # 유효한 외부 HTTPS target이 이 환경에서 실제로 도달 가능한지 먼저 양성 대조한다.
            # 같은 packaged WebView2가 proxy 없이 성공해야 뒤의 dead-proxy 실패가 DNS 우연이
            # 아니라 외부망 격리의 결과라고 말할 수 있다.
            $env:HWPXFILLER_HOME = Join-Path $evidenceDir 'home-network-control'
            $env:HWPX_SELFTEST_OUT = $networkControlOut
            $env:HWPX_SELFTEST_OFFLINE_PROBE = '1'
            [Environment]::SetEnvironmentVariable(
                'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', $null, 'Process'
            )
            $networkControl = Start-Process -FilePath $exe -Wait -PassThru `
                -ArgumentList @('--selftest')
            if ($networkControl.ExitCode -ne 0) {
                throw "packaged WebView2 외부망 양성 대조 실패(exit $($networkControl.ExitCode))"
            }
            if (-not (Test-Path -LiteralPath $networkControlOut -PathType Leaf)) {
                throw "packaged WebView2 외부망 양성 대조 증거 누락: $networkControlOut"
            }
            $networkEvidence = Get-Content -LiteralPath $networkControlOut -Raw -Encoding UTF8 |
                ConvertFrom-Json
            if (
                $networkEvidence.PSObject.Properties.Name -contains 'error' -or
                $networkEvidence.runtime.external_fetch_blocked -ne $false
            ) {
                throw (
                    'proxy 없는 packaged WebView2가 유효 외부 HTTPS target에 도달하지 못해 ' +
                    '오프라인 격리의 양성 대조를 확보할 수 없습니다.'
                )
            }

            $env:HWPXFILLER_HOME = Join-Path $evidenceDir 'home-offline'
            $env:HWPX_SELFTEST_OUT = $selftestOut
            $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = (
                '--proxy-server=127.0.0.1:9 --disable-background-networking'
            )
            $selftest = Start-Process -FilePath $exe -Wait -PassThru `
                -ArgumentList @('--selftest')
            if ($selftest.ExitCode -ne 0) {
                throw "Node-free packaged WebView2 selftest 실패(exit $($selftest.ExitCode))"
            }
            if (-not (Test-Path -LiteralPath $selftestOut -PathType Leaf)) {
                throw "packaged WebView2 selftest 증거 누락: $selftestOut"
            }
            $evidence = Get-Content -LiteralPath $selftestOut -Raw -Encoding UTF8 |
                ConvertFrom-Json
            if ($evidence.PSObject.Properties.Name -contains 'error') {
                throw "packaged WebView2 selftest probe 오류: $($evidence.error)"
            }
            $responsibilities = @(
                $evidence.PSObject.Properties.Name | Where-Object { $_ -ne 'runtime' }
            )
            if ($responsibilities.Count -ne 42) {
                throw "기존 selftest responsibility 수 불일치: $($responsibilities.Count) != 42"
            }
            $falseResponsibilities = @(
                foreach ($name in $responsibilities) {
                    $value = $evidence.PSObject.Properties[$name].Value
                    if ($value -is [bool] -and -not $value) { $name }
                }
            )
            if ($falseResponsibilities.Count -ne 0) {
                throw (
                    'packaged selftest top-level boolean false 책임이 있습니다: ' +
                    ($falseResponsibilities -join ', ')
                )
            }
            if ($evidence.url -notmatch '^http://127\.0\.0\.1:\d+/index\.html$') {
                throw "packaged WebView2 origin 불일치: $($evidence.url)"
            }
            $artifactParity = Get-Content -LiteralPath (
                Join-Path $evidenceDir 'artifact-parity.json'
            ) -Raw -Encoding UTF8 | ConvertFrom-Json
            if (
                $evidence.runtime.artifact_id -ne $artifactParity.artifact_id -or
                $evidence.runtime.tree_sha256 -ne $artifactParity.tree_sha256
            ) {
                throw 'normal/selftest/source/bundled web artifact identity가 일치하지 않습니다.'
            }
            if (
                $evidence.runtime.page_url -ne $evidence.url -or
                -not $evidence.runtime.resources_same_origin -or
                @($evidence.runtime.forbidden_resources).Count -ne 0
            ) {
                throw 'packaged WebView2에 loopback 외 resource가 로드됐습니다.'
            }
            if ($evidence.runtime.external_fetch_blocked -ne $true) {
                throw 'packaged WebView2 외부 네트워크 격리 증거가 없습니다.'
            }
            [ordered]@{
                artifact_id = $evidence.runtime.artifact_id
                tree_sha256 = $evidence.runtime.tree_sha256
                source_bundled_same_artifact = $true
                node_available_on_runtime_path = $false
                responsibility_count = $responsibilities.Count
                false_count = $falseResponsibilities.Count
                url = $evidence.url
                origin = $evidence.runtime.origin
                resource_count = @($evidence.runtime.resource_urls).Count
                resources_same_origin = $evidence.runtime.resources_same_origin
                network_control_external_fetch_succeeded = (
                    $networkEvidence.runtime.external_fetch_blocked -eq $false
                )
                offline_external_fetch_blocked = $evidence.runtime.external_fetch_blocked
            } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (
                Join-Path $evidenceDir 'validation-summary.json'
            ) -Encoding UTF8
        }
        finally {
            [Environment]::SetEnvironmentVariable('Path', $savedProcessPath, 'Process')
            [Environment]::SetEnvironmentVariable(
                'HWPXFILLER_HOME', $savedProductHome, 'Process'
            )
            [Environment]::SetEnvironmentVariable(
                'HWPX_SELFTEST_OUT', $savedSelftestOut, 'Process'
            )
            [Environment]::SetEnvironmentVariable(
                'HWPX_SELFTEST_OFFLINE_PROBE', $savedOfflineProbe, 'Process'
            )
            [Environment]::SetEnvironmentVariable(
                'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', $savedBrowserArgs, 'Process'
            )
        }
    } else {
        $template = Join-Path $corpus 'form_purchase_v1.hwpx'
        $template2 = Join-Path $corpus 'form_purchase_v2.hwpx'
        # 동적 import 경계인 템플릿 관리 명령 4개를 실제 번들에서 실행.
        & $exe schema $template --out (Join-Path $env:TEMP 'hwpx-k1-schema.json')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $exe fieldize $template
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $exe lint $template
        if ($LASTEXITCODE -notin @(0, 1)) { exit $LASTEXITCODE }
        & $exe drift $template $template2
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}

Write-Host "`nonedir 빌드·스모크 완료: $($plan -join ', ')" -ForegroundColor Green
