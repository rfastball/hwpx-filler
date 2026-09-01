<#
.SYNOPSIS
  onedir 번들(웹 앱 + CLI)을 빌드하고 스모크 검증한다.

.PARAMETER WebMode
  프런트 산출물을 여기서 **만들지**(`Build`) 아니면 이미 있는 것의 봉인만 **검증할지**
  (`VerifyExisting`) 고른다. CI 는 한 run 에 생산자가 하나뿐이라 `VerifyExisting` 으로
  부른다 — 종전에는 워크플로가 프런트를 만든 뒤 이 스크립트가 같은 자리에서 또 만들었다(N-11B).

.PARAMETER ExpectWebIdentity
  생산자가 낸 identity JSON. 검증하는 산출물이 그것과 다르면 거절한다.

.PARAMETER IncludeInstaller
  설치본 사본까지 만들어 identity 를 대조한다(R5-03). 기본은 꺼짐 — 설치본은 릴리스 태그가
  소유하는 사본이고, 이 스위치는 **감사·로컬이 같은 증거를 한 명령으로 재현**하는 자리다.
  Inno Setup 6(`ISCC.exe`) 이 없으면 조용히 건너뛰지 않고 시끄럽게 실패한다.

.EXAMPLE
  .\packaging\build.ps1
  .\packaging\build.ps1 -Target cli
  .\packaging\build.ps1 -WebMode VerifyExisting -ExpectWebIdentity web-artifact-identity.json
  .\packaging\build.ps1 -Target filler -IncludeInstaller   # 네 사본 전수 대조
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'filler', 'cli')]
    [string]$Target = 'all',
    [switch]$SkipCheck,
    [ValidateSet('Build', 'VerifyExisting')]
    [string]$WebMode = 'Build',
    [string]$ExpectWebIdentity,
    [switch]$IncludeInstaller
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
& chcp.com 65001 *> $null

# 설치본 사본은 filler 번들에서만 나온다. `-Target cli` 와 함께 받으면 스위치가 조용히
# 무시된 채 exit 0 이 나고, 그 조합으로 감사를 돌린 사람은 **설치본을 세지 않은 초록**을
# 증거로 들게 된다(Codex P2). 요청한 사본을 못 낼 조합은 일 시작 전에 거절한다.
if ($IncludeInstaller -and $Target -eq 'cli') {
    throw (
        '-IncludeInstaller 는 filler 번들이 있어야 합니다 — `-Target cli` 와 함께 쓸 수 ' +
        '없습니다. 설치본 사본을 세지 않은 채 초록을 내지 않습니다.'
    )
}

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
    # 해시테이블 splat 이다 — 배열 splat 은 요소를 **위치 인자**로 넘겨 `-Mode` 자체가
    # $Mode 의 값이 된다(실측: ValidateSet 이 "-Mode" 를 거절).
    $webArgs = @{ Mode = $WebMode }
    if ($ExpectWebIdentity) { $webArgs['ExpectIdentity'] = $ExpectWebIdentity }
    & (Join-Path $root 'build-web.ps1') @webArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& uv run --no-sync python (Join-Path $PSScriptRoot 'verify_specs.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# 프런트를 싣는지는 **빌드 계획**이 정한다 — 생성기가 디스크를 보고 추측하게 두지 않는다.
# cli 전용 빌드는 앞선 filler 빌드가 남긴 유효한 build/web 이 그대로 있어도 부재를 기록해야
# 한다. hwpx_cli.spec 은 datas=[] 라 실제로 아무것도 안 싣기 때문이다(#383 리뷰).
# (uv 는 native 명령이라 배열 splat 이 곧 위치 인자다.)
$metadataArgs = @((Join-Path $root 'scripts\generate_build_metadata.py'))
if ($Target -eq 'cli') {
    $metadataArgs += @('--no-web', 'cli-only build (hwpx_cli.spec bundles no web data)')
} else {
    $metadataArgs += '--require-web'
}
& uv run --no-sync python @metadataArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$targets = @{
    filler = @{ Spec = 'hwpx_filler_web.spec'; Dir = 'hwpx-filler-web'; Exe = 'hwpx-filler-web.exe' }
    cli    = @{ Spec = 'hwpx_cli.spec';         Dir = 'hwpx-cli';        Exe = 'hwpx-cli.exe' }
}
$plan = if ($Target -eq 'all') { @('filler', 'cli') } else { @($Target) }

function Set-NodeFreePath {
    # Node-free 국면의 **단일 정의**. 종전에는 filler 분기 안에만 있어서 CLI 스모크는 러너의
    # 앰비언트 PATH 로 돌았다 — CI 에서 우연히 Node 가 없었을 뿐 그것을 세는 단언이 없었다
    # (「집합 하나를 넓히고 형제를 안 넓힌다」). 호출자가 자기 PATH 를 저장·복원한다.
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
}

function Invoke-InstalledCopy([string]$EvidencePath) {
    # 설치본 사본(R5-03). 릴리스 태그가 소유하는 국면을 **감사·로컬이 한 명령으로 재현**하는
    # 자리다. 부재는 조용한 스킵이 아니다 — 이 함수는 `-IncludeInstaller` 를 켠 호출자만
    # 부르고, 그 선언이 곧 "설치본까지 세겠다"이므로 도구가 없으면 시끄럽게 죽는다.
    $isccPath = & (Join-Path $PSScriptRoot 'Find-Iscc.ps1')
    if (-not $isccPath) {
        throw (
            '-IncludeInstaller 를 켰지만 Inno Setup 6 ISCC.exe 를 찾지 못했습니다 — ' +
            '설치본 사본을 세지 않은 채 통과시키지 않습니다.'
        )
    }

    # 이 .iss 는 **출하 AppId** 를 쓴다. 같은 AppId 가 이미 등록돼 있으면 무인 설치가 그
    # 등록을 이 임시 폴더로 갈아치우고, 뒤이은 제거가 사용자의 **진짜 설치**를 고아로 만든다.
    # 감사·개발자 기기에서 문서나르미를 실제로 쓰고 있을 수 있으므로 먼저 거절한다.
    $productKey = (
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
        '{A08D764C-A28D-4E7E-A8E9-E391E11A5A8C}_is1'
    )
    if (Test-Path -LiteralPath $productKey) {
        throw (
            '이 기기에 문서나르미가 이미 설치돼 있습니다 — -IncludeInstaller 는 같은 AppId 로 ' +
            '설치·제거하므로 기존 등록을 망가뜨립니다. 먼저 제거하고 다시 실행하세요: ' +
            $productKey
        )
    }

    & $isccPath (Join-Path $root 'packaging\installers\hwpx-filler.iss')
    if ($LASTEXITCODE -ne 0) { throw "설치본 컴파일 실패(exit $LASTEXITCODE)" }
    $setup = Get-ChildItem (Join-Path $root 'installer-dist\HWPX-Filler-*-Setup.exe') `
            -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $setup) { throw '설치본 산출물을 찾지 못했습니다: installer-dist' }

    $installDir = Join-Path $evidenceDir 'installed'
    $installLog = Join-Path $evidenceDir 'installed-install.log'
    # 경로에 공백이 있으면 배열 인자는 두 토큰으로 갈라진다 — 따옴표를 직접 싣는다.
    $install = Start-Process -FilePath $setup.FullName -Wait -PassThru -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
        "/LOG=`"$installLog`"", "/DIR=`"$installDir`""
    )
    if ($install.ExitCode -ne 0) {
        throw "설치본 무인 설치 실패(exit $($install.ExitCode)) — 로그: $installLog"
    }
    try {
        # 설치본이 무엇을 실었는지는 **제거하기 전에만** 물을 수 있다. 이 순서가 계약이다.
        & uv run --no-sync python (Join-Path $root 'scripts\verify_packaged_web.py') `
            --repo-root $root --bundle-root (Join-Path $installDir '_internal') `
            --json-out $EvidencePath
        if ($LASTEXITCODE -ne 0) { throw 'installed web artifact identity 불일치' }
        Test-BundleBoundary $installDir
        # 릴리스 태그 쪽 설치본 스모크와 **같은 것**을 묻는다 — 한쪽만 selfcheck 하고 다른
        # 쪽만 번들 경계를 보면, 이름이 같고 강도가 다른 두 증거가 된다.
        $installedCheck = Start-Process -Wait -PassThru -ArgumentList @('--selfcheck') `
            -FilePath (Join-Path $installDir 'hwpx-filler-web.exe')
        if ($installedCheck.ExitCode -ne 0) {
            throw "설치본 selfcheck 실패(exit $($installedCheck.ExitCode))"
        }
    }
    finally {
        # 정리 실패로 **앞선 실패를 덮지 않는다** — finally 에서 던지면 진짜 원인이 사라진다.
        # 대신 남은 것을 이름으로 말한다(사용자 기기에 등록된 앱이 남는 상태라 침묵은 금물).
        $uninstaller = Join-Path $installDir 'unins000.exe'
        if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
            $uninstall = Start-Process -FilePath $uninstaller -Wait -PassThru `
                -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
            if ($uninstall.ExitCode -ne 0) {
                Write-Warning (
                    "설치본 제거가 실패했습니다(exit $($uninstall.ExitCode)) — " +
                    "직접 제거하세요: $uninstaller"
                )
            }
        } else {
            Write-Warning "설치본 제거기를 찾지 못했습니다 — 남은 설치: $installDir"
        }
    }
}

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

function Test-WheelDistribution {
    $work = Join-Path $root "build\wheel-smoke-$PID"
    New-Item -ItemType Directory -Force $work | Out-Null
    New-Item -ItemType Directory -Force $evidenceDir | Out-Null
    try {
        & uv build --wheel --out-dir $work
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $wheels = @(Get-ChildItem -LiteralPath $work -Filter '*.whl')
        if ($wheels.Count -ne 1) {
            throw "wheel 산출물은 정확히 하나여야 합니다: $($wheels.Count)"
        }
        $wheel = $wheels[0]

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [System.IO.Compression.ZipFile]::OpenRead($wheel.FullName)
        try {
            $entries = @($archive.Entries | ForEach-Object FullName)
        }
        finally {
            $archive.Dispose()
        }
        $legacy = @($entries | Where-Object { $_ -like 'hwpxfiller/core/*' })
        if ($legacy.Count -ne 0) {
            throw "wheel에 퇴역 hwpxfiller/core 경로가 있습니다: $($legacy -join ', ')"
        }
        $required = @(
            'hwpxcore/package.py',
            'hwpxfiller/domain/validation.py',
            'hwpxfiller/external/atomic.py',
            'hwpxfiller/external/hwpx_package_io.py',
            'hwpxfiller/external/text_registry.py',
            'hwpxfiller/host/motw.py',
            'hwpxfiller/host/native/single_instance.py'
        )
        $missing = @($required | Where-Object { $_ -notin $entries })
        if ($missing.Count -ne 0) {
            throw "wheel에 canonical runtime module이 없습니다: $($missing -join ', ')"
        }

        $savedPythonUtf8 = $env:PYTHONUTF8
        $savedPythonIoEncoding = $env:PYTHONIOENCODING
        try {
            # wheel console script는 frozen wrapper 없이도 cp949 초기 stream을 UTF-8로 바꿔야 한다.
            $env:PYTHONUTF8 = '0'
            $env:PYTHONIOENCODING = 'cp949'
            & uv run --quiet --isolated --no-project --with $wheel.FullName -- hwpxfiller --help
            if ($LASTEXITCODE -ne 0) { throw "clean wheel CLI --help 실패(exit $LASTEXITCODE)" }
        }
        finally {
            [Environment]::SetEnvironmentVariable('PYTHONUTF8', $savedPythonUtf8, 'Process')
            [Environment]::SetEnvironmentVariable(
                'PYTHONIOENCODING', $savedPythonIoEncoding, 'Process'
            )
        }

        $smoke = (
            "import importlib, importlib.metadata, importlib.util; " +
            "mods=('hwpxcore','hwpxcore.package','hwpxfiller','hwpxfiller.domain.job'," +
            "'hwpxfiller.domain.validation','hwpxfiller.external.atomic'," +
            "'hwpxfiller.external.hwpx_package_io','hwpxfiller.external.job_store'," +
            "'hwpxfiller.external.text_registry','hwpxfiller.host.locations'," +
            "'hwpxfiller.host.motw','hwpxfiller.host.native.dialogs'); " +
            "[importlib.import_module(m) for m in mods]; " +
            "eps={(e.group,e.name,e.value) for e in importlib.metadata.entry_points() " +
            "if e.name in {'hwpxfiller','hwpx-filler-web'}}; " +
            "assert ('console_scripts','hwpxfiller','hwpxfiller.cli:main') in eps; " +
            "assert ('gui_scripts','hwpx-filler-web','hwpxfiller.webapp.app:main') in eps; " +
            "assert importlib.util.find_spec('hwpxfiller.core') is None"
        )
        & uv run --quiet --isolated --no-project --with $wheel.FullName -- python -I -c $smoke
        if ($LASTEXITCODE -ne 0) { throw "clean wheel canonical import smoke 실패(exit $LASTEXITCODE)" }

        [ordered]@{
            wheel = $wheel.Name
            entry_count = $entries.Count
            legacy_core_count = $legacy.Count
            required_modules = $required
            cli_help = $true
            canonical_import_smoke = $true
        } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (
            Join-Path $evidenceDir 'wheel-summary.json'
        ) -Encoding UTF8
    }
    finally {
        if (Test-Path -LiteralPath $work) {
            Remove-Item -LiteralPath $work -Recurse -Force
        }
    }
}

function Test-PyInstallerArchive([string]$ExePath, [string]$Key) {
    $lines = @(
        & uv run --no-sync --group build pyi-archive_viewer -r -b $ExePath 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller archive inspection 실패($Key, exit $LASTEXITCODE)"
    }
    $legacy = @($lines | Where-Object { $_ -match 'hwpxfiller\.core(?:\.|$)' })
    if ($legacy.Count -ne 0) {
        throw "$Key bundle에 퇴역 hwpxfiller.core module이 있습니다: $($legacy -join ', ')"
    }
    $required = @(
        'hwpxfiller.domain.validation',
        'hwpxfiller.external.atomic',
        'hwpxfiller.external.hwpx_package_io'
    )
    if ($Key -eq 'filler') {
        $required += @(
            'hwpxfiller.external.job_store',
            'hwpxfiller.external.text_registry',
            'hwpxfiller.host.locations',
            'hwpxfiller.host.motw',
            'hwpxfiller.host.native.dialogs',
            'hwpxfiller.host.native.single_instance'
        )
    }
    $missing = @(
        $required | Where-Object {
            $module = [regex]::Escape($_)
            -not ($lines -match "(^|\s)$module($|\s)")
        }
    )
    if ($missing.Count -ne 0) {
        throw "$Key bundle에 canonical runtime module이 없습니다: $($missing -join ', ')"
    }
    [ordered]@{
        target = $Key
        archive_line_count = $lines.Count
        legacy_core_count = $legacy.Count
        required_modules = $required
    } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (
        Join-Path $evidenceDir "archive-$Key-summary.json"
    ) -Encoding UTF8
}

if (-not $SkipCheck) { Test-WheelDistribution }

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
    if (-not $SkipCheck) { Test-PyInstallerArchive $exe $key }
    if ($key -eq 'filler') {
        $bundleRoot = Join-Path $bundleDir '_internal'
        & uv run --no-sync python (Join-Path $root 'scripts\verify_packaged_web.py') `
            --repo-root $root --bundle-root $bundleRoot `
            --json-out (Join-Path $evidenceDir 'artifact-parity.json')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        # 사용자가 실제로 여는 것은 dist\ 가 아니라 portable zip 을 푼 결과다. 종전에 이
        # 왕복은 **태그 push 에서만** 검증됐다 — 압축·해제가 트리를 바꿔도(포장 도구마다
        # 제 hidden/dot 경로 정책이 있다) 병합 시점엔 아무도 몰랐다. 비용이 초 단위라
        # 매 병합으로 당긴다.
        # 왕복 작업물(zip·해제 트리)은 evidence 밖에 둔다 — 각 45MB 라 CI 증거 업로드에
        # 들어가면 부피만 90MB 늘고, 판정에 쓰이는 것은 옆의 parity JSON 하나다.
        $portableWork = Join-Path $root 'build\portable-roundtrip'
        if (Test-Path -LiteralPath $portableWork) {
            Remove-Item -LiteralPath $portableWork -Recurse -Force
        }
        New-Item -ItemType Directory -Force $portableWork | Out-Null
        New-Item -ItemType Directory -Force $evidenceDir | Out-Null
        $portableZip = Join-Path $portableWork 'portable.zip'
        $portableRoot = Join-Path $portableWork 'expanded'
        Compress-Archive -Path (Join-Path $bundleDir '*') -DestinationPath $portableZip
        Expand-Archive -Path $portableZip -DestinationPath $portableRoot -Force
        & uv run --no-sync python (Join-Path $root 'scripts\verify_packaged_web.py') `
            --repo-root $root --bundle-root (Join-Path $portableRoot '_internal') `
            --json-out (Join-Path $evidenceDir 'portable-parity.json')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        $reconcileArgs = @(
            (Join-Path $root 'scripts\reconcile_shipped_copies.py'),
            '--build-metadata', (Join-Path $root 'build\version\build-metadata.json'),
            '--copy', ('dist=' + (Join-Path $evidenceDir 'artifact-parity.json')),
            '--copy', ('portable=' + (Join-Path $evidenceDir 'portable-parity.json'))
        )
        $expectedCopies = 'source,dist,portable'
        if ($IncludeInstaller) {
            $installedParity = Join-Path $evidenceDir 'installed-parity.json'
            Invoke-InstalledCopy -EvidencePath $installedParity
            $reconcileArgs += @('--copy', ('installed=' + $installedParity))
            $expectedCopies = 'source,dist,installed,portable'
        }
        $reconcileArgs += @(
            '--expect', $expectedCopies,
            '--json-out', (Join-Path $evidenceDir 'shipped-copies.json')
        )
        & uv run --no-sync python @reconcileArgs
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
        $savedSelfcheckOut = $env:HWPX_SELFCHECK_OUT
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

            Set-NodeFreePath

            $artifactParity = Get-Content -LiteralPath (
                Join-Path $evidenceDir 'artifact-parity.json'
            ) -Raw -Encoding UTF8 | ConvertFrom-Json

            # `--selfcheck` 국면의 **in-process** identity 를 듣는다(R5-03). 이 인자는 제품
            # `main()` 을 부르지 않는다 — 엔트리 래퍼가 가로채 헤드리스 스모크로 보낸다. 그래서
            # 여기서 얻는 것은 「정상 실행의 증거」가 아니라 **창을 열지 않는 별개 프로세스가
            # 같은 sealed 산출물을 fail-closed 로 해석했다**는 증거다(제품 진입점이 해석한
            # identity 는 아래 `--selftest` 증거의 runtime.artifact_id 가 이미 진다).
            # 종전에는 ExitCode 만 읽어 이 프로세스가 무엇을 실었는지 아무도 묻지 않았다.
            # 창 앱이라 stdout 은 리디렉션해야 잡힌다.
            # 증거는 **제품이 파일로 쓴다**. 초판은 stdout 을 리디렉션해 읽었는데, 이 exe 는
            # `console=False` 라 stdout 이 붙는 자리가 환경마다 다르다 — 로컬에서 즉시 끝난
            # 같은 호출이 CI 에서 13분 매달렸다(run 31229199482). selftest 가 이미
            # `HWPX_SELFTEST_OUT` 으로 피해 가던 축이라 같은 형태로 맞춘다.
            $env:HWPX_SELFCHECK_OUT = Join-Path $evidenceDir 'packaged-selfcheck.json'
            if (Test-Path -LiteralPath $env:HWPX_SELFCHECK_OUT -PathType Leaf) {
                Remove-Item -LiteralPath $env:HWPX_SELFCHECK_OUT -Force
            }
            $selfcheck = Start-Process -FilePath $exe -Wait -PassThru `
                -ArgumentList @('--selfcheck')
            if ($selfcheck.ExitCode -ne 0) {
                throw "Node-free packaged selfcheck 실패(exit $($selfcheck.ExitCode))"
            }
            # 판정은 Python 판별기가 소유한다 — 음성 대조가 붙는 유일한 자리다
            # (`classify_webview_evidence.py` 와 같은 이유). 러너는 호출과 배선만 진다.
            $selfcheckIdentityOut = Join-Path $evidenceDir 'packaged-selfcheck-identity.json'
            & $pythonExe (Join-Path $root 'scripts\assert_selfcheck_identity.py') `
                --selfcheck-evidence $env:HWPX_SELFCHECK_OUT `
                --expect-identity (Join-Path $evidenceDir 'artifact-parity.json') `
                --json-out $selfcheckIdentityOut
            if ($LASTEXITCODE -ne 0) {
                throw 'packaged --selfcheck 국면의 web artifact identity 대조에 실패했습니다.'
            }
            $selfcheckIdentity = Get-Content -LiteralPath $selfcheckIdentityOut -Raw -Encoding UTF8 |
                ConvertFrom-Json

            # 유효한 외부 HTTP target을 deterministic loopback control proxy로 먼저 성공시킨다.
            # proxy가 요청을 실제로 관측해야 뒤의 같은-target dead-proxy 실패가 DNS/CI egress
            # 우연이 아니라 외부망 격리의 결과라고 말할 수 있다.
            $env:HWPXFILLER_HOME = Join-Path $evidenceDir 'home-network-control'
            $env:HWPX_SELFTEST_OUT = $networkControlOut
            $env:HWPX_SELFTEST_OFFLINE_PROBE = '1'
            & $setWebViewNetworkArguments (
                "--proxy-server=http://127.0.0.1:$proxyPort"
            )
            # 콜드 부팅 실패(환경)만 유한 재시도한다(#477). 판별은 Python 판별기가 소유하고
            # (scripts\classify_webview_evidence.py — 음성 대조가 붙는 유일한 자리), 제품
            # 증거가 있는 실패는 어떤 경우에도 재시도되지 않는다 — quality.yml 의 「제품
            # 단언은 재시도하지 않는다」 계약을 이 분류가 보존한다. 시도마다 홈·증거·proxy
            # 관측 잔재를 지운다: 앞 시도의 잔재가 이번 시도의 양성 대조를 오염시키면
            # proxy_observed 가 부팅 없이 참이 되는 길이 열린다.
            $classifyScript = Join-Path $root 'scripts\classify_webview_evidence.py'
            $bootRetryLimit = 3
            $bootFlakeErrors = @()
            for ($bootAttempt = 1; $bootAttempt -le $bootRetryLimit; $bootAttempt++) {
                foreach ($stale in @($networkControlOut, $proxyHitOut)) {
                    if (Test-Path -LiteralPath $stale -PathType Leaf) {
                        Remove-Item -LiteralPath $stale -Force
                    }
                }
                if (Test-Path -LiteralPath $env:HWPXFILLER_HOME -PathType Container) {
                    Remove-Item -LiteralPath $env:HWPXFILLER_HOME -Recurse -Force
                }
                $networkControlStartedAt = Get-Date
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
                if (-not ($networkEvidence.PSObject.Properties.Name -contains 'error')) {
                    break
                }
                & $pythonExe $classifyScript $networkControlOut | Write-Host
                if ($LASTEXITCODE -ne 0) {
                    # 제품 증거가 있거나 환경 서명 밖이거나 판정 불능 — 재시도 없이 아래 본
                    # 검증이 종전 문장으로 시끄럽게 던진다.
                    break
                }
                $bootFlakeErrors += [string]$networkEvidence.error
                $flakeLine = 'webview_boot_flake attempt={0}/{1} error={2}' -f `
                    $bootAttempt, $bootRetryLimit, $networkEvidence.error
                Write-Host $flakeLine
                if ($bootAttempt -eq $bootRetryLimit) {
                    throw (
                        "packaged WebView2 콜드 부팅이 환경 판정으로 $bootRetryLimit" +
                        '회 연속 실패했습니다 — 임계 도달은 조용한 재시도가 아니라 그 자체가 ' +
                        '결함으로 올라갑니다(#477). 시도별 오류: ' +
                        ($bootFlakeErrors -join ' | ')
                    )
                }
            }
            $proxyObserved = Test-Path -LiteralPath $proxyHitOut -PathType Leaf
            $proxyHitDiagnostic = $null
            $proxyHitParseFailed = $false
            if ($proxyObserved) {
                try {
                    $proxyHitDiagnostic = Get-Content -LiteralPath $proxyHitOut -Raw -Encoding UTF8 |
                        ConvertFrom-Json
                }
                catch {
                    # 아래 본 검증은 같은 파일을 다시 읽어 원래 오류를 그대로 내야 한다. 여기서는
                    # 진단 출력 자체가 주 실패를 가리지 않도록 파싱 실패 여부만 기록한다.
                    $proxyHitParseFailed = $true
                }
            }
            $policyBrowserArguments = $null
            if ($isElevated) {
                $policyBrowserArguments = (
                    Get-Item -LiteralPath $webViewPolicyPath
                ).GetValue($webViewPolicyName)
            }
            $proxyProcessExited = $proxyProcess.HasExited
            $proxyProcessExitCode = $null
            if ($proxyProcessExited) {
                $proxyProcessExitCode = $proxyProcess.ExitCode
            }
            $networkControlDiagnostics = [ordered]@{
                network_isolation_mechanism = $networkIsolationMechanism
                elevated = $isElevated
                app_id = $webViewPolicyName
                environment_browser_arguments = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
                policy_browser_arguments = $policyBrowserArguments
                control_elapsed_ms = [int]((Get-Date) - $networkControlStartedAt).TotalMilliseconds
                control_exit_code = $networkControl.ExitCode
                boot_flake_attempts = $bootAttempt
                boot_flake_errors = $bootFlakeErrors
                evidence_error_present = (
                    $networkEvidence.PSObject.Properties.Name -contains 'error'
                )
                evidence_error = $networkEvidence.error
                external_fetch_completed = $networkEvidence.runtime.external_fetch_completed
                external_fetch_succeeded = $networkEvidence.runtime.external_fetch_succeeded
                external_fetch_blocked = $networkEvidence.runtime.external_fetch_blocked
                external_fetch_error = $networkEvidence.runtime.external_fetch_error
                proxy_observed = $proxyObserved
                proxy_hit_parse_failed = $proxyHitParseFailed
                proxy_method = $proxyHitDiagnostic.method
                proxy_host = $proxyHitDiagnostic.host
                proxy_target = $proxyHitDiagnostic.target
                proxy_process_exited = $proxyProcessExited
                proxy_process_exit_code = $proxyProcessExitCode
            }
            Write-Host (
                'network_control_diagnostics=' +
                ($networkControlDiagnostics | ConvertTo-Json -Compress)
            )
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
            if ($responsibilities.Count -ne 43) {
                throw "기존 selftest responsibility 수 불일치: $($responsibilities.Count) != 43"
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
            # React 실런타임 마커(R2-04 · #408) — 동결 exe 오프라인 국면에서 React 가 실제로
            # 커밋했고 store 신호가 서 있다는 형상 단언. 값의 크기(0/양수)는 module selftest
            # result 소유라 여기서 겸하지 않는다.
            $reactRuntime = $evidence.react_runtime
            if ($null -eq $reactRuntime) {
                throw 'packaged selftest 에 react_runtime 증거가 없습니다.'
            }
            # 형 가드가 먼저다 — PS 5.1 의 배열 LHS `-ne`/`-notmatch` 는 필터라 ["1"] 같은
            # 배열이, 스칼라 강제 변환은 숫자 1 이 값 비교를 조용히 통과한다(L16 실증).
            if (
                -not ($reactRuntime.mounted -is [string]) -or
                $reactRuntime.mounted -ne '1' -or
                -not ($reactRuntime.store_rev -is [string]) -or
                $reactRuntime.store_rev -notmatch '^[0-9]+$' -or
                -not ($reactRuntime.roots -is [int] -or $reactRuntime.roots -is [long]) -or
                $reactRuntime.roots -ne 1
            ) {
                throw (
                    'packaged WebView2 의 React 실런타임 마커가 계약과 다릅니다: ' +
                    ($reactRuntime | ConvertTo-Json -Compress)
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
                # 창을 열지 않는 `--selfcheck` 프로세스가 해석한 값. 아래 selftest 국면의
                # runtime.artifact_id 와 **다른 프로세스**의 증거라 같은 자리에 나란히 둔다.
                selfcheck_artifact_id = $selfcheckIdentity.selfcheck_artifact_id
                selfcheck_tree_sha256 = $selfcheckIdentity.selfcheck_tree_sha256
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
                        'HWPX_SELFCHECK_OUT', $savedSelfcheckOut, 'Process'
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
        # CLI 스모크도 Node-free 국면 안에서 돈다. 종전에는 filler 분기가 PATH 를 복원한 뒤
        # 앰비언트 PATH 로 돌았고, CI 에서 Node 가 없던 것은 그 잡이 setup-node 를 안 하기
        # 때문이지 이 게이트가 그것을 세서가 아니었다 — 우연한 참은 계약이 아니다.
        $savedCliPath = $env:Path
        try {
            Set-NodeFreePath
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
        finally {
            [Environment]::SetEnvironmentVariable('Path', $savedCliPath, 'Process')
        }
    }
}

Write-Host "`nonedir 빌드·스모크 완료: $($plan -join ', ')" -ForegroundColor Green
