<#
.SYNOPSIS
  Run the native 101 capture and publish only a complete set of thirteen screenshots.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$EvidenceDir
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$binary = [IO.Path]::GetFullPath($Exe)
$evidence = [IO.Path]::GetFullPath($EvidenceDir)
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
    throw "native 101 캡처 실행 파일이 없습니다: $binary"
}
if (Test-Path -LiteralPath $evidence) {
    throw "native 101 캡처 증거 폴더를 재사용하지 않습니다: $evidence"
}
$locationPushed = $false
try {
    Push-Location $root
    $locationPushed = $true
    & node (Join-Path $root 'scripts/live101_native/run.mjs') capture `
        --exe $binary --evidence $evidence
    if ($LASTEXITCODE -ne 0) { throw "native 101 캡처 완주 실패: $evidence" }
    & node (Join-Path $root 'scripts/publish_101_screenshots.mjs') $evidence
    if ($LASTEXITCODE -ne 0) { throw "native 101 캡처 그림 게시 실패: $evidence" }
} finally {
    if ($locationPushed) { Pop-Location }
}
