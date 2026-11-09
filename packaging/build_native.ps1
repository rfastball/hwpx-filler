<#
.SYNOPSIS
  Build the native GUI and CLI into their established public bundle names.
.DESCRIPTION
  The Rust artifact verifier owns source, bundle, and notice identity. This script
  prepares the binaries and exercises the actual Windows WebView2 release boundary.
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'filler', 'cli')][string]$Target = 'all',
    [switch]$SkipCheck,
    [ValidateSet('Build', 'VerifyExisting')][string]$WebMode = 'Build',
    [string]$ExpectWebIdentity,
    [string]$EvidenceDir,
    [switch]$IncludeInstaller
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dist = Join-Path $root 'dist'
$evidence = if ($EvidenceDir) { [IO.Path]::GetFullPath($EvidenceDir) }
    else { Join-Path $root ('build/native-package-evidence-' +
        (Get-Date -Format 'yyyyMMdd-HHmmss') + "-$PID") }
$artifact = Join-Path $root 'scripts/run_web_artifact.ps1'
$oldPath = $env:PATH
$oldCargoHome = $env:CARGO_HOME
$oldRustupHome = $env:RUSTUP_HOME
$locationPushed = $false

if ($IncludeInstaller -and $Target -eq 'cli') {
    throw '-IncludeInstaller 는 GUI 번들이 있어야 합니다.'
}

function Remove-GeneratedBundle([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    $boundary = [IO.Path]::GetFullPath($dist).TrimEnd('\') + '\'
    if (-not $absolute.StartsWith($boundary, [StringComparison]::OrdinalIgnoreCase)) {
        throw "배포 폴더가 dist 밖입니다: $absolute"
    }
    if (Test-Path -LiteralPath $absolute) {
        foreach ($candidate in @($dist, $absolute)) {
            $item = Get-Item -LiteralPath $candidate
            if (-not ($item -is [IO.DirectoryInfo]) -or
                ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "배포 경로의 링크·비폴더를 거절합니다: $candidate"
            }
        }
        $links = @(Get-ChildItem -LiteralPath $absolute -Recurse -Force |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
        if ($links.Count) { throw "배포 폴더의 링크를 거절합니다: $($links[0].FullName)" }
        Remove-Item -LiteralPath $absolute -Recurse -Force
    }
}

function Invoke-RuntimePath([scriptblock]$Action, [string]$HomeName = 'isolated-home') {
    $priorPath = $env:PATH
    $priorHome = $env:HWPXFILLER_HOME
    try {
        $win = $env:SystemRoot
        $env:PATH = @((Join-Path $win 'System32'), $win,
            (Join-Path $win 'System32/Wbem')) -join ';'
        foreach ($name in @('node.exe', 'python.exe', 'uv.exe')) {
            if (Get-Command $name -CommandType Application -ErrorAction SilentlyContinue) {
                throw "배포 런타임 PATH에서 빌드 도구가 발견됐습니다: $name"
            }
        }
        $env:HWPXFILLER_HOME = Join-Path $evidence $HomeName
        & $Action
    } finally {
        $env:PATH = $priorPath
        $env:HWPXFILLER_HOME = $priorHome
    }
}

# `$HOME` 은 PowerShell 자동 변수(읽기 전용)라 홈 폴더 변수는 다른 이름을 쓴다.
function Seed-AuthoringCorpus([string]$HomeRoot) {
    $templates = Join-Path $HomeRoot 'templates'
    New-Item -ItemType Directory -Path $templates -Force | Out-Null
    $hashes = @{}
    foreach ($name in @(
        'bid_notice_limited_under100m.hwpx', 'filled_notice_marine.hwpx'
    )) {
        $source = Join-Path $root "tests/corpus/real/$name"
        $item = Get-Item -LiteralPath $source -ErrorAction Stop
        if (-not ($item -is [IO.FileInfo]) -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "HWPX selftest corpus 원본이 일반 파일이 아닙니다: $source"
        }
        $target = Join-Path $templates $name
        if (Test-Path -LiteralPath $target) { throw "selftest 홈이 비어 있지 않습니다: $target" }
        $hashes[$name] = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        Copy-Item -LiteralPath $source -Destination $target
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $hashes[$name]) {
            throw "HWPX selftest corpus 사본이 원본과 다릅니다: $name"
        }
    }
    return $hashes
}

function Test-NativeWebView([string]$Exe, [string]$Identity, [string]$Label) {
    $output = Join-Path $evidence "$Label-selftest.json"
    $selftestHome = Join-Path $evidence "$Label-home"
    $sourceHashes = Seed-AuthoringCorpus $selftestHome
    $oldOutput = $env:HWPX_SELFTEST_OUT
    $oldProbe = $env:HWPX_SELFTEST_OFFLINE_PROBE
    $hadSelection = Test-Path Env:HWPX_SELFTEST_PROBES
    $oldSelection = $env:HWPX_SELFTEST_PROBES
    try {
        $env:HWPX_SELFTEST_OUT = $output
        $env:HWPX_SELFTEST_OFFLINE_PROBE = '1'
        Remove-Item Env:HWPX_SELFTEST_PROBES -ErrorAction SilentlyContinue
        $processExitCode = Invoke-RuntimePath {
            $process = Start-Process -FilePath $Exe -ArgumentList '--selftest' `
                -PassThru -WindowStyle Hidden
            # The product owns the 200 s cold-boot + engine + cleanup deadline.
            # The outer runner gives that process 30 s to write its refusal receipt.
            if (-not $process.WaitForExit(230000)) {
                Stop-Process -Id $process.Id -Force
                throw "$Label WebView2 selftest 시간 초과"
            }
            $process.ExitCode
        } "$Label-home"
    } finally {
        $env:HWPX_SELFTEST_OUT = $oldOutput
        $env:HWPX_SELFTEST_OFFLINE_PROBE = $oldProbe
        if ($hadSelection) { $env:HWPX_SELFTEST_PROBES = $oldSelection }
        else { Remove-Item Env:HWPX_SELFTEST_PROBES -ErrorAction SilentlyContinue }
    }
    if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
        throw "$Label WebView2 selftest 증거가 없습니다."
    }
    foreach ($name in $sourceHashes.Keys) {
        $source = Join-Path $root "tests/corpus/real/$name"
        $copy = Join-Path $selftestHome "templates/$name"
        foreach ($file in @($source, $copy)) {
            if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $sourceHashes[$name]) {
                throw "$Label HWPX selftest 원본 또는 사본이 변경됐습니다: $file"
            }
        }
    }
    & node (Join-Path $root 'scripts/verify_native_selftest.mjs') $output $Identity
    if ($LASTEXITCODE -ne 0) { throw "$Label WebView2 selftest 증거가 계약과 다릅니다." }
    if ($processExitCode -ne 0) {
        throw "$Label WebView2 selftest 실패(exit $processExitCode)"
    }
}

function Test-Bundle([string]$Bundle, [string]$Label) {
    $receipt = Join-Path $evidence "$Label.json"
    & $artifact --repo-root $root --bundle-root $Bundle --json-out $receipt
    if ($LASTEXITCODE -ne 0) { throw "$Label 웹·고지 identity 검증 실패" }
    return $receipt
}

function Test-InstalledBundle {
    $iscc = & (Join-Path $PSScriptRoot 'Find-Iscc.ps1')
    if (-not $iscc) { throw '-IncludeInstaller 에 필요한 Inno Setup 6 ISCC.exe가 없습니다.' }
    $productKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
        '{A08D764C-A28D-4E7E-A8E9-E391E11A5A8C}_is1'
    if (Test-Path -LiteralPath $productKey) {
        throw '기존 문서나르미 설치가 있어 같은 AppId의 무인 설치·제거를 거절합니다.'
    }
    & $iscc (Join-Path $PSScriptRoot 'installers/hwpx-filler.iss')
    if ($LASTEXITCODE -ne 0) { throw '설치본 컴파일 실패' }
    $metadata = Get-Content (Join-Path $root 'build/version/build-metadata.json') `
        -Raw -Encoding UTF8 | ConvertFrom-Json
    $setup = Get-Item -LiteralPath (Join-Path $root (
        "installer-dist/HWPX-Filler-$($metadata.version)-Setup.exe")) `
        -ErrorAction SilentlyContinue
    if (-not $setup) { throw '설치본 산출물이 없습니다.' }
    $installed = Join-Path $evidence 'installed'
    $log = Join-Path $evidence 'install.log'
    $process = Start-Process -FilePath $setup.FullName -Wait -PassThru `
        -WindowStyle Hidden `
        -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            "/LOG=`"$log`"", "/DIR=`"$installed`"")
    if ($process.ExitCode -ne 0) { throw "설치본 무인 설치 실패(exit $($process.ExitCode))" }
    try {
        $identity = Test-Bundle $installed 'installed'
        Test-NativeWebView (Join-Path $installed 'hwpx-filler-web.exe') $identity 'installed'
    } finally {
        $uninstall = Join-Path $installed 'unins000.exe'
        if (Test-Path -LiteralPath $uninstall) {
            $removed = Start-Process -FilePath $uninstall -Wait -PassThru `
                -WindowStyle Hidden `
                -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
            if ($removed.ExitCode -ne 0) { throw '임시 설치본 제거 실패' }
        }
    }
}

if (Test-Path -LiteralPath $evidence) {
    throw "기존 증거 폴더를 재사용하지 않습니다: $evidence"
}
New-Item -ItemType Directory -Path $evidence, $dist -Force | Out-Null
try {
    Push-Location $root
    $locationPushed = $true
    # 저장소 지역 toolchain 이 있으면 그것을 쓴다 — 고지 생성기(`cargo metadata --offline`)를
    # 포함한 Node 도구가 같은 규칙으로 CARGO_HOME 을 고르므로, 빌드가 받은 의존을 그대로 본다.
    $local = Join-Path $root '.cache/rhwp-cargo/bin/cargo.exe'
    if (-not $env:CARGO_HOME -and (Test-Path -LiteralPath $local -PathType Leaf)) {
        $env:CARGO_HOME = Join-Path $root '.cache/rhwp-cargo'
        $env:RUSTUP_HOME = Join-Path $root '.cache/rhwp-rustup'
        $env:PATH = (Split-Path -Parent $local) + ';' + $env:PATH
        $cargoPath = $local
    } else {
        $cargo = Get-Command cargo.exe -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $cargo) { throw 'Cargo가 없습니다. rust-toolchain.toml의 도구 체인을 먼저 준비하세요.' }
        $cargoPath = $cargo.Source
    }
    # 빌드 메타데이터(TOML 파서)·고지 생성기는 --offline 으로 Cargo 를 부른다 — 깨끗한 러너에서도
    # 돌도록 같은 toolchain 에 잠금 의존을 먼저 받아 둔다.
    & $cargoPath fetch --locked
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    if (-not $SkipCheck) {
        & (Join-Path $root 'test.ps1')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    if ($Target -ne 'cli') {
        $webArgs = @{ Mode = $WebMode }
        if ($ExpectWebIdentity) { $webArgs.ExpectIdentity = $ExpectWebIdentity }
        & (Join-Path $root 'build-web.ps1') @webArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    if ($Target -ne 'cli') {
        & node (Join-Path $root 'scripts/generate_build_metadata.mjs') --require-web
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    if ($Target -ne 'filler') {
        & node (Join-Path $root 'scripts/generate_build_metadata.mjs') `
            --out (Join-Path $root 'build/version-cli') --no-web `
            'CLI bundle has no web data'
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    $binaryRoot = if ($env:CARGO_TARGET_DIR) { Join-Path $env:CARGO_TARGET_DIR 'release' }
        else { Join-Path $root 'target/release' }
    if ($Target -ne 'cli') {
        & $cargoPath build -p hwpx-desktop --bin documentnarmi --release --locked
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $notices = Join-Path $evidence 'notices'
        & node (Join-Path $root 'scripts/generate_native_notices.mjs') `
            --web-root (Join-Path $root 'build/web') --out $notices
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $gui = Join-Path $dist 'hwpx-filler-web'
        Remove-GeneratedBundle $gui
        & (Join-Path $PSScriptRoot 'assemble_native.ps1') -SourceRoot $root `
            -OutputDir $gui -GuiExe (Join-Path $binaryRoot 'documentnarmi.exe') `
            -NoticeRoot $notices -EvidenceDir $evidence
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Test-NativeWebView (Join-Path $gui 'hwpx-filler-web.exe') `
            (Join-Path $evidence 'dist.json') 'dist'
        if ($IncludeInstaller) { Test-InstalledBundle }
    }
    if ($Target -ne 'filler') {
        & $cargoPath build -p hwpx-desktop --bin hwpxfiller --no-default-features `
            --release --locked
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $cli = Join-Path $dist 'hwpx-cli'
        Remove-GeneratedBundle $cli
        New-Item -ItemType Directory -Path $cli | Out-Null
        Copy-Item -LiteralPath (Join-Path $binaryRoot 'hwpxfiller.exe') `
            -Destination (Join-Path $cli 'hwpx-cli.exe')
        $cliNotices = Join-Path $evidence 'cli-notices'
        & node (Join-Path $root 'scripts/generate_native_notices.mjs') `
            --cli-out $cliNotices
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Copy-Item -LiteralPath (Join-Path $root 'LICENSE') -Destination $cli
        Copy-Item -LiteralPath (Join-Path $root 'build/version-cli/build-metadata.json') `
            -Destination $cli
        Copy-Item -LiteralPath (Join-Path $cliNotices 'THIRD_PARTY_NOTICES') `
            -Destination $cli
        Copy-Item -LiteralPath (Join-Path $cliNotices 'native-notices.json') `
            -Destination $cli
        Copy-Item -LiteralPath (Join-Path $cliNotices 'licenses') `
            -Destination $cli -Recurse
        & node (Join-Path $root 'scripts/verify_cli_bundle.mjs') $root $cli
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Invoke-RuntimePath {
            & (Join-Path $cli 'hwpx-cli.exe') --help | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'CLI 도움말 스모크 실패' }
        }
    }
    Write-Host "native bundle complete: $Target"
} finally {
    if ($locationPushed) { Pop-Location }
    $env:PATH = $oldPath
    $env:CARGO_HOME = $oldCargoHome
    $env:RUSTUP_HOME = $oldRustupHome
}
