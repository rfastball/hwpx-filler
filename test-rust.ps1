<#
.SYNOPSIS
  Rust workspace formatting, lint, and tests.
#>
$ErrorActionPreference = 'Stop'
$priorPath = $env:PATH
$priorCargoHome = $env:CARGO_HOME
$priorRustupHome = $env:RUSTUP_HOME
$locationPushed = $false
$code = 1
try {
    $cachedCargo = Join-Path $PSScriptRoot '.cache\rhwp-cargo\bin\cargo.exe'
    if (Test-Path -LiteralPath $cachedCargo -PathType Leaf) {
        $env:CARGO_HOME = Join-Path $PSScriptRoot '.cache\rhwp-cargo'
        $env:RUSTUP_HOME = Join-Path $PSScriptRoot '.cache\rhwp-rustup'
        $env:PATH = (Split-Path $cachedCargo) + ';' + $env:PATH
    }
    if (-not (Get-Command cargo -CommandType Application -ErrorAction SilentlyContinue)) {
        throw 'cargo 없음. rust-toolchain.toml의 Rust toolchain을 준비하세요.'
    }

    Push-Location $PSScriptRoot
    $locationPushed = $true
    & cargo fmt --all --check
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        & cargo clippy --workspace --all-targets --locked -- -D warnings
        $code = $LASTEXITCODE
    }
    if ($code -eq 0) {
        & cargo test --workspace --all-targets --locked
        $code = $LASTEXITCODE
    }
    if ($code -eq 0) {
        & cargo check -p hwpx-desktop --bin hwpxfiller --no-default-features --locked
        $code = $LASTEXITCODE
    }
} finally {
    if ($locationPushed) { Pop-Location }
    $env:PATH = $priorPath
    $env:CARGO_HOME = $priorCargoHome
    $env:RUSTUP_HOME = $priorRustupHome
}
exit $code
