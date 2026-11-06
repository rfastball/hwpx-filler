<#
.SYNOPSIS
  Run the Rust web artifact sealer or its Python-free existing-artifact verifier.
#>
param([switch]$Verify)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$priorPath = $env:PATH
$priorCargoHome = $env:CARGO_HOME
$priorRustupHome = $env:RUSTUP_HOME
$locationPushed = $false
$code = 1
try {
    $cachedCargo = Join-Path $root '.cache\rhwp-cargo\bin\cargo.exe'
    $cargoCommand = Get-Command cargo -CommandType Application -ErrorAction SilentlyContinue
    if ((-not $cargoCommand -or $cargoCommand.Source -ieq $cachedCargo) -and
        (Test-Path -LiteralPath $cachedCargo -PathType Leaf)) {
        $env:CARGO_HOME = Join-Path $root '.cache\rhwp-cargo'
        $env:RUSTUP_HOME = Join-Path $root '.cache\rhwp-rustup'
        if (-not $cargoCommand) {
            $env:PATH = (Split-Path $cachedCargo) + ';' + $env:PATH
        }
    }
    if (-not (Get-Command cargo -CommandType Application -ErrorAction SilentlyContinue)) {
        throw 'cargo 없음. rust-toolchain.toml의 Rust toolchain을 준비하세요.'
    }
    $artifactArgs = @()
    if ($Verify) { $artifactArgs += '--verify' }
    $artifactArgs += $args
    Push-Location $root
    $locationPushed = $true
    & cargo run --quiet --locked -p hwpx-artifact -- @artifactArgs
    $code = $LASTEXITCODE
}
finally {
    if ($locationPushed) { Pop-Location }
    $env:PATH = $priorPath
    $env:CARGO_HOME = $priorCargoHome
    $env:RUSTUP_HOME = $priorRustupHome
}
exit $code
