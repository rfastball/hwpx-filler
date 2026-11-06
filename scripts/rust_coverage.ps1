<#
.SYNOPSIS
  Rust workspace LLVM line/branch coverage against the exact-package floors.
.DESCRIPTION
  Builds and runs `cargo test --workspace --all-targets --locked` (the test-rust.ps1 test set)
  with `-C instrument-coverage` in a separate target directory, merges the raw profiles with the
  pinned toolchain's llvm-tools, exports production-only per-file coverage JSON, and enforces
  tests/contracts/package-coverage-floors.toml with the check_rust_coverage example.

  Branch coverage (`-Zcoverage-options=branch`) and the `coverage(off)` attribute that excludes
  `#[cfg(test)]` modules (`--cfg coverage_nightly`) are unstable compiler options, so the
  instrumented build alone runs the pinned stable compiler with RUSTC_BOOTSTRAP=1.
  Normal builds, clippy and the checker itself never see these flags.

  Exit codes: 0 all floors met; 1 a floor is missed; 2 the evidence or inventory is invalid;
  any other non-zero code is a missing tool or a failing/failed-to-build test.
#>
param(
    # Markdown summary of the gate (CI appends it to the step summary).
    [string]$MarkdownOutput = 'target/coverage/package-coverage.md',
    # Production-only llvm-cov export JSON that the checker reads.
    [string]$JsonOutput = 'target/coverage/llvm-coverage.json'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$saved = @{}
foreach ($name in 'PATH', 'CARGO_HOME', 'RUSTUP_HOME', 'CARGO_TARGET_DIR', 'RUSTFLAGS', 'RUSTC_BOOTSTRAP', 'LLVM_PROFILE_FILE', 'CARGO_INCREMENTAL') {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$locationPushed = $false
$code = 1

function Restore-Environment {
    foreach ($entry in $saved.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }
}

function Resolve-RepoPath([string]$path) {
    if ([IO.Path]::IsPathRooted($path)) { return $path }
    return [IO.Path]::GetFullPath((Join-Path $repo $path))
}

try {
    $cachedCargo = Join-Path $repo '.cache\rhwp-cargo\bin\cargo.exe'
    if (Test-Path -LiteralPath $cachedCargo -PathType Leaf) {
        $env:CARGO_HOME = Join-Path $repo '.cache\rhwp-cargo'
        $env:RUSTUP_HOME = Join-Path $repo '.cache\rhwp-rustup'
        $env:PATH = (Split-Path $cachedCargo) + ';' + $env:PATH
    }
    if (-not (Get-Command cargo -CommandType Application -ErrorAction SilentlyContinue)) {
        throw 'cargo 없음. rust-toolchain.toml의 Rust toolchain을 준비하세요.'
    }
    Push-Location $repo
    $locationPushed = $true

    # The toolchain file pins the compiler and requires the llvm-tools component.
    $sysroot = (& rustc --print sysroot)
    if ($LASTEXITCODE -ne 0 -or -not $sysroot) { throw 'rustc --print sysroot 실패' }
    $hostLine = (& rustc -vV) | Where-Object { $_ -like 'host: *' }
    if (-not $hostLine) { throw 'rustc -vV 에 host 줄이 없습니다' }
    $hostTriple = $hostLine.Substring(6).Trim()
    $llvmBin = Join-Path $sysroot "lib\rustlib\$hostTriple\bin"
    $profdata = Join-Path $llvmBin 'llvm-profdata.exe'
    $llvmCov = Join-Path $llvmBin 'llvm-cov.exe'
    foreach ($tool in $profdata, $llvmCov) {
        if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
            throw "LLVM 도구 없음: $tool. rust-toolchain.toml 의 llvm-tools component 를 설치하세요 (rustup component add llvm-tools)."
        }
    }

    $coverageTarget = Join-Path $repo 'target\coverage'
    $profileDir = Join-Path $coverageTarget 'profraw'
    $mergedProfile = Join-Path $coverageTarget 'coverage.profdata'
    $jsonPath = Resolve-RepoPath $JsonOutput
    $markdownPath = Resolve-RepoPath $MarkdownOutput
    # Stale profiles from an earlier run would count code this run never executed.
    if (Test-Path -LiteralPath $profileDir) { Remove-Item -LiteralPath $profileDir -Recurse -Force }
    foreach ($stale in $mergedProfile, $jsonPath, $markdownPath) {
        if (Test-Path -LiteralPath $stale) { Remove-Item -LiteralPath $stale -Force }
    }
    New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
    foreach ($output in $jsonPath, $markdownPath) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null
    }

    $env:CARGO_TARGET_DIR = $coverageTarget
    $env:RUSTFLAGS = '-C instrument-coverage -Z coverage-options=branch --cfg coverage_nightly'
    $env:RUSTC_BOOTSTRAP = '1'
    $env:CARGO_INCREMENTAL = '0'
    $env:LLVM_PROFILE_FILE = Join-Path $profileDir '%p-%m.profraw'

    $started = Get-Date
    & cargo test --workspace --all-targets --locked
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE; throw "instrumented cargo test 실패 (exit $LASTEXITCODE)" }

    # Every executable the test set built (test harnesses, bins they spawn, examples) carries
    # coverage mapping; the same command with --no-run rebuilds nothing and lists them.
    $objects = [Collections.Generic.List[string]]::new()
    $messages = & cargo test --workspace --all-targets --locked --no-run --message-format=json
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE; throw "cargo test --no-run 실패 (exit $LASTEXITCODE)" }
    foreach ($line in $messages) {
        if (-not $line.StartsWith('{')) { continue }
        $message = $line | ConvertFrom-Json
        if ($message.reason -eq 'compiler-artifact' -and $message.executable -and -not $objects.Contains($message.executable)) {
            $objects.Add($message.executable)
        }
    }
    if ($objects.Count -eq 0) { throw '계측된 실행 파일이 없습니다' }

    $profiles = @(Get-ChildItem -LiteralPath $profileDir -Filter '*.profraw' -File)
    if ($profiles.Count -eq 0) { throw "프로파일 없음: $profileDir" }
    $profileList = Join-Path $coverageTarget 'profraw-inputs.txt'
    [IO.File]::WriteAllLines($profileList, [string[]]($profiles | ForEach-Object FullName))
    & $profdata merge -sparse "--input-files=$profileList" -o $mergedProfile
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE; throw "llvm-profdata merge 실패 (exit $LASTEXITCODE)" }

    # Production-only: dependency and std sources, integration tests, examples, benches and build
    # scripts are excluded here; `#[cfg(test)]` modules are excluded at compile time by
    # `#[cfg_attr(coverage_nightly, coverage(off))]`. The checker rejects any other crates/ file
    # that is not in its exact source inventory.
    $exportArgs = @(
        'export', '-format=text', '-summary-only', "-instr-profile=$mergedProfile",
        '-ignore-filename-regex=[\\/](registry[\\/]src|git[\\/]checkouts)[\\/]',
        '-ignore-filename-regex=^[\\/]?rustc[\\/]',
        '-ignore-filename-regex=[\\/]crates[\\/][^\\/]+[\\/](tests|examples|benches)[\\/]',
        '-ignore-filename-regex=[\\/]build\.rs$',
        $objects[0]
    )
    foreach ($object in ($objects | Select-Object -Skip 1)) { $exportArgs += "-object=$object" }
    $json = & $llvmCov @exportArgs
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE; throw "llvm-cov export 실패 (exit $LASTEXITCODE)" }
    [IO.File]::WriteAllText($jsonPath, ($json -join "`n"), [Text.UTF8Encoding]::new($false))
    $elapsed = (Get-Date) - $started
    Write-Host ("instrumented test + export: {0:mm\:ss}" -f $elapsed)

    # The checker is an ordinary build: drop every coverage setting first.
    Restore-Environment
    if (Test-Path -LiteralPath $cachedCargo -PathType Leaf) {
        $env:CARGO_HOME = Join-Path $repo '.cache\rhwp-cargo'
        $env:RUSTUP_HOME = Join-Path $repo '.cache\rhwp-rustup'
        $env:PATH = (Split-Path $cachedCargo) + ';' + $env:PATH
    }
    & cargo run --locked -p hwpx-desktop --no-default-features --example check_rust_coverage -- `
        tests/contracts/package-coverage-floors.toml $jsonPath --markdown-output $markdownPath
    $code = $LASTEXITCODE
} catch {
    Write-Host "Rust coverage: $_" -ForegroundColor Red
    if ($code -eq 0) { $code = 1 }
} finally {
    if ($locationPushed) { Pop-Location }
    Restore-Environment
}
exit $code
