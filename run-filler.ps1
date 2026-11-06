<#
.SYNOPSIS
  소스에서 네이티브 GUI 또는 CLI를 실행한다.
.DESCRIPTION
  GUI는 봉인된 개발용 web 자산을 준비한 뒤 Rust/Tauri 창을 연다.
  CLI는 GUI 런타임 없이 같은 소스의 네이티브 CLI를 실행한다.
.EXAMPLE
  .\run-filler.ps1
  .\run-filler.ps1 -Cli --help
#>
[CmdletBinding()]
param(
    [switch]$Cli,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$priorCargoHome = $env:CARGO_HOME
$priorRustupHome = $env:RUSTUP_HOME
$local = Join-Path $root '.cache\rhwp-cargo\bin\cargo.exe'
if (Test-Path -LiteralPath $local -PathType Leaf) {
    $env:CARGO_HOME = Join-Path $root '.cache\rhwp-cargo'
    $env:RUSTUP_HOME = Join-Path $root '.cache\rhwp-rustup'
    $cargoPath = $local
} else {
    $cargo = Get-Command cargo -CommandType Application -ErrorAction SilentlyContinue
    if (-not $cargo) { throw 'Rust Cargo가 없습니다.' }
    $cargoPath = $cargo.Source
}

Push-Location $root
try {
    if ($Cli) {
        & $cargoPath run -p hwpx-desktop --bin hwpxfiller --no-default-features `
            --locked -- @Rest
    } else {
        if ($Rest.Count) { throw 'GUI 실행에는 추가 인자를 사용할 수 없습니다.' }
        & (Join-Path $root 'build-web.ps1')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $cargoPath run -p hwpx-desktop --bin documentnarmi --locked -- `
            --dev-assets (Join-Path $root 'build\web') (Join-Path $root 'examples\tutorial')
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
    $env:CARGO_HOME = $priorCargoHome
    $env:RUSTUP_HOME = $priorRustupHome
}
