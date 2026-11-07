<#
.SYNOPSIS
  Local-only native WebView scope over a sealed GUI bundle or source release build.
#>
[CmdletBinding()]
param(
    [string]$Scope = 'auto',
    [string]$Exe,
    [string]$WebRoot,
    [string]$TutorialRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceDir
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$evidence = [IO.Path]::GetFullPath($EvidenceDir)
if (Test-Path -LiteralPath $evidence) { throw "native scope evidence directory must be new: $evidence" }
foreach ($name in @('HWPX_SELFTEST_SET_THEME', 'HWPX_SELFTEST_SET_FONT_SCALE',
                   'HWPX_SELFTEST_GEOMETRY_ONLY', 'HWPX_SELFTEST_NO_CAPABILITY',
                   'HWPX_SELFTEST_GLOBAL_DELTA')) {
    if ([Environment]::GetEnvironmentVariable($name, 'Process')) {
        throw "native live scope cannot run with $name preset"
    }
}
$selector = Join-Path $root 'scripts/live_scope_native.mjs'
$selectionText = & node $selector $Scope
if ($LASTEXITCODE -ne 0) { throw "native live scope selection failed(exit $LASTEXITCODE)" }
$selection = ($selectionText -join "`n") | ConvertFrom-Json
New-Item -ItemType Directory -Path $evidence | Out-Null
$selectionPath = Join-Path $evidence 'selection.json'
[IO.File]::WriteAllText($selectionPath, ($selectionText -join "`n"),
    (New-Object System.Text.UTF8Encoding($false)))
if ($selection.mode -eq 'none') { return }
if (($WebRoot -and $Exe) -or ([bool]$WebRoot -ne [bool]$TutorialRoot)) {
    throw 'native scope needs either EXE or the WEB/TUTORIAL source pair'
}

if ($WebRoot) {
    $web = [IO.Path]::GetFullPath($WebRoot)
    $tutorial = [IO.Path]::GetFullPath($TutorialRoot)
    $sourceRepo = Split-Path (Split-Path $web)
    $expectedWeb = [IO.Path]::GetFullPath((Join-Path $sourceRepo 'build/web'))
    if ($web -ine $expectedWeb) {
        throw "native source web must be the repository build/web: $web"
    }
    $sourceSeal = Join-Path $web 'web-artifact-seal.json'
    if (-not (Test-Path -LiteralPath $sourceSeal -PathType Leaf)) {
        throw "native source web seal is missing: $sourceSeal"
    }
    if (-not (Test-Path -LiteralPath $tutorial -PathType Container)) {
        throw "native tutorial assets are missing: $tutorial"
    }
    $priorCargoHome = $env:CARGO_HOME
    $priorRustupHome = $env:RUSTUP_HOME
    $localCargo = Join-Path $root '.cache/rhwp-cargo/bin/cargo.exe'
    try {
        if (Test-Path -LiteralPath $localCargo -PathType Leaf) {
            $env:CARGO_HOME = Join-Path $root '.cache/rhwp-cargo'
            $env:RUSTUP_HOME = Join-Path $root '.cache/rhwp-rustup'
            $cargoPath = $localCargo
        } else {
            $cargoPath = (Get-Command cargo -CommandType Application -ErrorAction Stop).Source
        }
        Push-Location $root
        try {
            & $cargoPath run --quiet --locked -p hwpx-artifact -- --verify --repo-root $sourceRepo
            if ($LASTEXITCODE -ne 0) { throw "native source web verification failed(exit $LASTEXITCODE)" }
            & $cargoPath build --release -p hwpx-desktop --bin documentnarmi --locked
            if ($LASTEXITCODE -ne 0) { throw "native release GUI build failed(exit $LASTEXITCODE)" }
        } finally { Pop-Location }
    } finally {
        $env:CARGO_HOME = $priorCargoHome
        $env:RUSTUP_HOME = $priorRustupHome
    }
    $target = if ($env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR } else { Join-Path $root 'target' }
    if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path $root $target }
    $builtBinary = [IO.Path]::GetFullPath((Join-Path $target 'release/documentnarmi.exe'))
    if (-not (Test-Path -LiteralPath $builtBinary -PathType Leaf)) {
        throw "native release GUI executable is missing: $builtBinary"
    }
    $localBundle = Join-Path $evidence 'native-bundle'
    New-Item -ItemType Directory -Path $localBundle | Out-Null
    Copy-Item -LiteralPath $builtBinary -Destination (Join-Path $localBundle 'documentnarmi.exe')
    Copy-Item -LiteralPath $web -Destination (Join-Path $localBundle 'web') -Recurse
    New-Item -ItemType Directory -Path (Join-Path $localBundle 'examples') | Out-Null
    Copy-Item -LiteralPath $tutorial -Destination (Join-Path $localBundle 'examples/tutorial') -Recurse
    $binary = Join-Path $localBundle 'documentnarmi.exe'
    $sealPath = Join-Path $localBundle 'web/web-artifact-seal.json'
    $assetArgs = @()
} else {
    if (-not $Exe) { throw 'native scope requires a sealed GUI executable or source web assets' }
    $binary = [IO.Path]::GetFullPath($Exe)
    $assetArgs = @()
    $sealPath = Join-Path (Split-Path $binary) 'web/web-artifact-seal.json'
    $sourceSeal = Join-Path $root 'build/web/web-artifact-seal.json'
    if (-not (Test-Path -LiteralPath $sourceSeal -PathType Leaf) -or
        -not (Test-Path -LiteralPath $sealPath -PathType Leaf)) {
        throw 'native live scope needs current built web and a sealed GUI bundle'
    }
    $sourceIdentity = Get-Content -LiteralPath $sourceSeal -Raw -Encoding UTF8 | ConvertFrom-Json
    $bundleIdentity = Get-Content -LiteralPath $sealPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($sourceIdentity.artifact_id -cne $bundleIdentity.artifact_id -or
        $sourceIdentity.output.tree_sha256 -cne $bundleIdentity.output.tree_sha256) {
        throw 'native live scope GUI bundle differs from the current built web artifact'
    }
}
if (-not (Test-Path -LiteralPath $binary -PathType Leaf) -or
    -not (Test-Path -LiteralPath $sealPath -PathType Leaf)) {
    throw "native GUI executable or seal is missing: $binary / $sealPath"
}
$bundleIdentity = Get-Content -LiteralPath $sealPath -Raw -Encoding UTF8 | ConvertFrom-Json

if ($selection.mode -ne 'none' -and
    ($selection.mode -eq 'full' -or @($selection.probes).Count -gt 0)) {
    $appHome = Join-Path $evidence 'app-home'
    $templates = Join-Path $appHome 'templates'
    New-Item -ItemType Directory -Path $templates | Out-Null
    $hashes = @{}
    foreach ($name in @('bid_notice_limited_under100m.hwpx', 'filled_notice_marine.hwpx')) {
        $source = Join-Path $root "tests/corpus/real/$name"
        $item = Get-Item -LiteralPath $source -ErrorAction Stop
        if (-not ($item -is [IO.FileInfo]) -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "native selftest corpus source is not a regular file: $source"
        }
        $hashes[$name] = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        Copy-Item -LiteralPath $source -Destination (Join-Path $templates $name)
    }
    $prior = @{}
    foreach ($name in @('HWPXFILLER_HOME', 'HWPX_SELFTEST_OUT',
                       'HWPX_SELFTEST_PROBES', 'HWPX_SELFTEST_OFFLINE_PROBE')) {
        $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    $receipt = Join-Path $evidence 'selftest.json'
    try {
        $env:HWPXFILLER_HOME = $appHome
        $env:HWPX_SELFTEST_OUT = $receipt
        $env:HWPX_SELFTEST_OFFLINE_PROBE = '1'
        if ($selection.mode -eq 'partial') { $env:HWPX_SELFTEST_PROBES = @($selection.probes) -join ',' }
        else { Remove-Item Env:HWPX_SELFTEST_PROBES -ErrorAction SilentlyContinue }
        $process = Start-Process -FilePath $binary -ArgumentList (@('--selftest') + $assetArgs) `
            -PassThru -WindowStyle Hidden
        if (-not $process.WaitForExit(230000)) {
            Stop-Process -Id $process.Id -Force
            throw 'native scoped WebView2 selftest exceeded the outer 230s limit'
        }
        if ($process.ExitCode -ne 0) {
            $detail = if (Test-Path -LiteralPath $receipt) {
                Get-Content -LiteralPath $receipt -Raw -Encoding UTF8
            } else { 'no receipt' }
            throw "native scoped WebView2 selftest failed(exit $($process.ExitCode)): $detail"
        }
    } finally {
        foreach ($name in $prior.Keys) {
            [Environment]::SetEnvironmentVariable($name, $prior[$name], 'Process')
        }
    }
    if (-not (Test-Path -LiteralPath $receipt -PathType Leaf)) { throw 'native scope receipt missing' }
    foreach ($name in $hashes.Keys) {
        foreach ($file in @((Join-Path $root "tests/corpus/real/$name"),
                           (Join-Path $templates $name))) {
            if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $hashes[$name]) {
                throw "native selftest corpus changed: $file"
            }
        }
    }
    if ($selection.mode -eq 'full') {
        $identity = Join-Path $evidence 'identity.json'
        $identityJson = @{ artifact_id = $bundleIdentity.artifact_id;
                           tree_sha256 = $bundleIdentity.output.tree_sha256 } | ConvertTo-Json -Compress
        [IO.File]::WriteAllText($identity, $identityJson,
            (New-Object System.Text.UTF8Encoding($false)))
        & node (Join-Path $root 'scripts/verify_native_selftest.mjs') $receipt $identity
    } else {
        & node $selector --verify $selectionPath $receipt
    }
    if ($LASTEXITCODE -ne 0) { throw 'native scoped receipt does not match the selected contract' }
}
if ($selection.runJourney) {
    $journeyArgs = @{ Exe = $binary; EvidenceDir = (Join-Path $evidence 'live101') }
    & (Join-Path $root 'scripts/run_native_live101.ps1') @journeyArgs
    if ($LASTEXITCODE -ne 0) { throw 'native live101 journey/restart failed' }
}
