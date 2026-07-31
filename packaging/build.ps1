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
if (-not $env:UV_CACHE_DIR) {
    $env:UV_CACHE_DIR = Join-Path $root '.uv-cache'
}
if (-not $env:UV_PYTHON_INSTALL_DIR) {
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $root '.uv-python'
}

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
        $proxyReadyOut = Join-Path $evidenceDir 'network-control-proxy-ready.json'
        $proxyHitOut = Join-Path $evidenceDir 'network-control-proxy-hit.json'
        $proxyProcess = $null
        $savedProcessPath = $env:Path
        $savedProductHome = $env:HWPXFILLER_HOME
        $savedSelftestOut = $env:HWPX_SELFTEST_OUT
        $savedOfflineProbe = $env:HWPX_SELFTEST_OFFLINE_PROBE
        $savedBrowserArgs = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
        $webViewPolicyPath = (
            'HKLM:\SOFTWARE\Policies\Microsoft\Edge\WebView2\' +
            'AdditionalBrowserArguments'
        )
        $webViewPolicyName = [System.IO.Path]::GetFileName($exe)
        $webViewPolicyKeyCreated = $false
        $webViewPolicyValueCreated = $false
        $principal = [Security.Principal.WindowsPrincipal]::new(
            [Security.Principal.WindowsIdentity]::GetCurrent()
        )
        $isElevated = $principal.IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator
        )
        $networkIsolationMechanism = if ($isElevated) {
            'hklm-app-policy'
        } else {
            'process-environment'
        }
        try {
            if ($isElevated) {
                # WebView2 intentionally ignores WEBVIEW2_* environment overrides for a
                # high-integrity host. Its documented HKLM policy lookup accepts the compiled
                # executable name as AppId, so scope the temporary override to this packaged
                # selftest executable. Never replace a machine policy owned by the host.
                $webViewPolicyKeyCreated = -not (
                    Test-Path -LiteralPath $webViewPolicyPath -PathType Container
                )
                if ($webViewPolicyKeyCreated) {
                    New-Item -Path $webViewPolicyPath -Force | Out-Null
                }
                $policyKey = Get-Item -LiteralPath $webViewPolicyPath
                if ($policyKey.GetValueNames() -contains $webViewPolicyName) {
                    throw (
                        '기존 WebView2 AdditionalBrowserArguments machine policy와 ' +
                        "충돌합니다: $webViewPolicyName"
                    )
                }
                New-ItemProperty -LiteralPath $webViewPolicyPath `
                    -Name $webViewPolicyName -PropertyType String -Value '' |
                    Out-Null
                $webViewPolicyValueCreated = $true
            }
            $setWebViewNetworkArguments = {
                param([string]$Arguments)

                $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = $Arguments
                if ($isElevated) {
                    Set-ItemProperty -LiteralPath $webViewPolicyPath `
                        -Name $webViewPolicyName -Value $Arguments
                    $policyValue = (
                        Get-Item -LiteralPath $webViewPolicyPath
                    ).GetValue($webViewPolicyName)
                    if ($policyValue -ne $Arguments) {
                        throw (
                            'WebView2 machine policy readback이 요청한 browser arguments와 ' +
                            '일치하지 않습니다.'
                        )
                    }
                }
            }
            $pythonExe = Join-Path $root '.venv\Scripts\python.exe'
            $proxyScript = Join-Path $root 'scripts\selftest_http_proxy.py'
            if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
                throw "network control Python 누락: $pythonExe"
            }
            $proxyProcess = Start-Process -FilePath $pythonExe -WindowStyle Hidden -PassThru `
                -ArgumentList @(
                    "`"$proxyScript`"",
                    '--ready-file', "`"$proxyReadyOut`"",
                    '--hit-file', "`"$proxyHitOut`""
                )
            $proxyDeadline = (Get-Date).AddSeconds(10)
            while (-not (Test-Path -LiteralPath $proxyReadyOut -PathType Leaf)) {
                if ($proxyProcess.HasExited) {
                    throw "network control proxy가 준비 전에 종료했습니다(exit $($proxyProcess.ExitCode))"
                }
                if ((Get-Date) -ge $proxyDeadline) {
                    throw 'network control proxy 준비 시간이 초과됐습니다.'
                }
                Start-Sleep -Milliseconds 50
            }
            $proxyInfo = Get-Content -LiteralPath $proxyReadyOut -Raw -Encoding UTF8 |
                ConvertFrom-Json
            $proxyPort = 0
            $proxyPortValid = [int]::TryParse([string]$proxyInfo.port, [ref]$proxyPort)
            if (
                $proxyInfo.host -ne '127.0.0.1' -or
                -not $proxyPortValid -or
                $proxyPort -le 0
            ) {
                throw "network control proxy endpoint가 잘못됐습니다: $($proxyInfo | ConvertTo-Json -Compress)"
            }

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
            $artifactParity = Get-Content -LiteralPath (
                Join-Path $evidenceDir 'artifact-parity.json'
            ) -Raw -Encoding UTF8 | ConvertFrom-Json

            # 유효한 외부 HTTP target을 deterministic loopback control proxy로 먼저 성공시킨다.
            # proxy가 요청을 실제로 관측해야 뒤의 같은-target dead-proxy 실패가 DNS/CI egress
            # 우연이 아니라 외부망 격리의 결과라고 말할 수 있다.
            $env:HWPXFILLER_HOME = Join-Path $evidenceDir 'home-network-control'
            $env:HWPX_SELFTEST_OUT = $networkControlOut
            $env:HWPX_SELFTEST_OFFLINE_PROBE = '1'
            & $setWebViewNetworkArguments (
                "--proxy-server=http://127.0.0.1:$proxyPort"
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
                $networkEvidence.runtime.external_fetch_completed -ne $true -or
                $networkEvidence.runtime.external_fetch_succeeded -ne $true -or
                $networkEvidence.runtime.external_fetch_blocked -ne $false -or
                $networkEvidence.runtime.external_fetch_error -ne 'external fetch succeeded'
            ) {
                throw (
                    'control proxy를 통한 packaged WebView2 외부 HTTP probe가 성공하지 않아 ' +
                    '오프라인 격리의 양성 대조를 확보할 수 없습니다.'
                )
            }
            if (
                $networkEvidence.url -notmatch '^http://127\.0\.0\.1:\d+/index\.html$' -or
                $networkEvidence.runtime.page_url -ne $networkEvidence.url -or
                -not $networkEvidence.runtime.resources_same_origin -or
                @($networkEvidence.runtime.forbidden_resources).Count -ne 0 -or
                $networkEvidence.runtime.artifact_id -ne $artifactParity.artifact_id -or
                $networkEvidence.runtime.tree_sha256 -ne $artifactParity.tree_sha256
            ) {
                throw 'network control WebView2의 loopback origin 또는 artifact identity가 다릅니다.'
            }
            if (-not (Test-Path -LiteralPath $proxyHitOut -PathType Leaf)) {
                throw 'network control proxy가 WebView2 외부 HTTP 요청을 관측하지 못했습니다.'
            }
            $proxyHit = Get-Content -LiteralPath $proxyHitOut -Raw -Encoding UTF8 |
                ConvertFrom-Json
            if (
                $proxyHit.method -ne 'GET' -or
                $proxyHit.host -ne 'example.com' -or
                $proxyHit.target -ne 'http://example.com/__n03_network_control__'
            ) {
                throw "network control proxy 관측값이 잘못됐습니다: $($proxyHit | ConvertTo-Json -Compress)"
            }
            Stop-Process -Id $proxyProcess.Id -Force
            $proxyProcess.WaitForExit()
            $proxyProcess = $null
            $deadProxyConfirmed = $false
            $deadProxyCheck = [System.Net.Sockets.TcpClient]::new()
            try {
                $deadProxyCheck.Connect('127.0.0.1', $proxyPort)
            }
            catch {
                $deadProxyConfirmed = $true
            }
            finally {
                $deadProxyCheck.Dispose()
            }
            if (-not $deadProxyConfirmed) {
                throw "종료한 network control proxy port가 여전히 열려 있습니다: $proxyPort"
            }

            $env:HWPXFILLER_HOME = Join-Path $evidenceDir 'home-offline'
            $env:HWPX_SELFTEST_OUT = $selftestOut
            & $setWebViewNetworkArguments (
                "--proxy-server=127.0.0.1:$proxyPort --disable-background-networking"
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
            if (
                $evidence.runtime.external_fetch_completed -ne $true -or
                $evidence.runtime.external_fetch_succeeded -ne $false -or
                $evidence.runtime.external_fetch_blocked -ne $true -or
                $evidence.runtime.external_fetch_error -eq 'external fetch succeeded' -or
                $evidence.runtime.external_fetch_error -eq 'offline probe timed out'
            ) {
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
                network_control_external_fetch_completed = (
                    $networkEvidence.runtime.external_fetch_completed
                )
                network_control_external_fetch_succeeded = (
                    $networkEvidence.runtime.external_fetch_succeeded
                )
                network_control_proxy_observed = $true
                network_control_target = $proxyHit.target
                network_isolation_mechanism = $networkIsolationMechanism
                dead_proxy_port = $proxyPort
                offline_external_fetch_blocked = $evidence.runtime.external_fetch_blocked
            } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (
                Join-Path $evidenceDir 'validation-summary.json'
            ) -Encoding UTF8
        }
        finally {
            try {
                if ($null -ne $proxyProcess -and -not $proxyProcess.HasExited) {
                    Stop-Process -Id $proxyProcess.Id -Force
                    $proxyProcess.WaitForExit()
                }
            }
            finally {
                try {
                    if ($webViewPolicyValueCreated) {
                        Remove-ItemProperty -LiteralPath $webViewPolicyPath `
                            -Name $webViewPolicyName -ErrorAction Stop
                        $policyKey = Get-Item -LiteralPath $webViewPolicyPath
                        if ($policyKey.GetValueNames() -contains $webViewPolicyName) {
                            throw (
                                '임시 WebView2 machine policy value cleanup을 확인하지 못했습니다: ' +
                                $webViewPolicyName
                            )
                        }
                    }
                    if (
                        $webViewPolicyKeyCreated -and
                        (Test-Path -LiteralPath $webViewPolicyPath -PathType Container)
                    ) {
                        $policyKey = Get-Item -LiteralPath $webViewPolicyPath
                        if (
                            $policyKey.GetValueNames().Count -eq 0 -and
                            $policyKey.SubKeyCount -eq 0
                        ) {
                            Remove-Item -LiteralPath $webViewPolicyPath `
                                -Force -ErrorAction Stop
                            if (Test-Path -LiteralPath $webViewPolicyPath) {
                                throw '임시 WebView2 machine policy key cleanup을 확인하지 못했습니다.'
                            }
                        } else {
                            throw (
                                '임시 WebView2 machine policy key에 예상 밖 값 또는 ' +
                                'subkey가 생겨 안전하게 제거할 수 없습니다.'
                            )
                        }
                    }
                }
                finally {
                    [Environment]::SetEnvironmentVariable(
                        'Path', $savedProcessPath, 'Process'
                    )
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
                        'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS',
                        $savedBrowserArgs,
                        'Process'
                    )
                }
            }
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
