<#
.SYNOPSIS
  Assemble one Python-free Windows onedir copy from built Rust binaries and a sealed web source.
.DESCRIPTION
  Refuses an existing destination. The Rust web verifier owns source/bundle identity, and the
  packaged GUI owns the windowless native selfcheck. This script only copies declared resources.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceRoot,
    [Parameter(Mandatory)][string]$OutputDir,
    [Parameter(Mandatory)][string]$GuiExe,
    [string]$EvidenceDir,
    [Parameter(Mandatory)][string]$NoticeRoot
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = (Resolve-Path -LiteralPath $SourceRoot).Path
$gui = (Resolve-Path -LiteralPath $GuiExe).Path
$destination = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $destination) {
    throw "기존 배포 폴더를 덮어쓰지 않습니다: $destination"
}
$sealedSource = [IO.Path]::GetFullPath((Join-Path $source 'build\web'))
if ($destination.StartsWith(($sealedSource.TrimEnd('\') + '\'),
        [StringComparison]::OrdinalIgnoreCase)) {
    throw '배포 폴더는 봉인된 web 원천의 하위일 수 없습니다.'
}
if (-not $EvidenceDir) { $EvidenceDir = Join-Path $repo 'build\native-package-evidence' }
$evidence = [IO.Path]::GetFullPath($EvidenceDir)
$checker = Join-Path $repo 'scripts\run_web_artifact.ps1'

function Copy-DeclaredFile([string]$From, [string]$To) {
    $item = Get-Item -LiteralPath $From -ErrorAction Stop
    if (-not ($item -is [IO.FileInfo]) -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "일반 파일이 아닌 배포 원본을 거절합니다: $From"
    }
    Copy-Item -LiteralPath $From -Destination $To
}

& $checker -Verify --repo-root $source --json-out (Join-Path $evidence 'source.json')
if ($LASTEXITCODE -ne 0) { throw '원천 웹 산출물 봉인 검증 실패' }
$sourceIdentity = Get-Content -LiteralPath (Join-Path $evidence 'source.json') -Raw -Encoding UTF8 |
    ConvertFrom-Json
$nativeNotices = (Resolve-Path -LiteralPath $NoticeRoot).Path
$noticeIdentity = Get-Content -LiteralPath (
    Join-Path $nativeNotices 'native-notices.json'
) -Raw -Encoding UTF8 | ConvertFrom-Json
$lockHash = (Get-FileHash -LiteralPath (Join-Path $source 'Cargo.lock') `
    -Algorithm SHA256).Hash.ToLowerInvariant()
if ($noticeIdentity.cargo_lock_sha256 -ne $lockHash -or
    $noticeIdentity.artifact_id -ne $sourceIdentity.artifact_id -or
    $noticeIdentity.tree_sha256 -ne $sourceIdentity.tree_sha256) {
    throw '네이티브 고지가 Cargo.lock 또는 봉인 웹 산출물과 다릅니다.'
}

New-Item -ItemType Directory -Path $destination | Out-Null
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
Copy-DeclaredFile $gui (Join-Path $destination 'hwpx-filler-web.exe')
Copy-Item -LiteralPath (Join-Path $source 'build\web') `
    -Destination (Join-Path $destination 'web') -Recurse

$tutorial = Join-Path $destination 'examples\tutorial'
New-Item -ItemType Directory -Path $tutorial -Force | Out-Null
$originals = @(
    '물품 구매입찰 공고.hwpx',
    '낙찰자 선정 및 계약체결 안내.txt',
    '계약방법 결정 및 구매추진 안내.txt',
    '공고목록.xlsx'
)
foreach ($name in $originals) {
    Copy-DeclaredFile (Join-Path $source "examples\tutorial\$name") `
        (Join-Path $tutorial $name)
}

$notices = @{
    'LICENSE' = 'LICENSE'
    'vendor/rhwp/LICENSE.txt' = 'licenses/rhwp/LICENSE.txt'
    'vendor/rhwp/THIRD_PARTY_LICENSES.txt' = 'licenses/rhwp/THIRD_PARTY_LICENSES.txt'
    'vendor/rhwp/FONTS.txt' = 'licenses/rhwp/FONTS.txt'
    'vendor/rhwp/SourceHanSerifK-OFL.txt' = 'licenses/rhwp/SourceHanSerifK-OFL.txt'
    'vendor/rhwp/canvaskit-wasm-LICENSE.txt' = 'licenses/rhwp/canvaskit-wasm-LICENSE.txt'
    'frontend/fonts/OFL.txt' = 'licenses/pretendard/OFL.txt'
}
foreach ($entry in $notices.GetEnumerator()) {
    $target = Join-Path $destination $entry.Value
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-DeclaredFile (Join-Path $source $entry.Key) $target
}
Copy-DeclaredFile (Join-Path $nativeNotices 'native-notices.json') `
    (Join-Path $destination 'native-notices.json')
Copy-DeclaredFile (Join-Path $nativeNotices 'THIRD_PARTY_NOTICES') `
    (Join-Path $destination 'THIRD_PARTY_NOTICES')
Copy-Item -LiteralPath (Join-Path $nativeNotices 'licenses\rust') `
    -Destination (Join-Path $destination 'licenses\rust') -Recurse
Copy-Item -LiteralPath (Join-Path $nativeNotices 'licenses\npm') `
    -Destination (Join-Path $destination 'licenses\npm') -Recurse
Copy-Item -LiteralPath (Join-Path $nativeNotices 'licenses\microsoft') `
    -Destination (Join-Path $destination 'licenses\microsoft') -Recurse

& $checker --repo-root $source --bundle-root $destination `
    --json-out (Join-Path $evidence 'dist.json')
if ($LASTEXITCODE -ne 0) { throw '원천/네이티브 배포본 웹 identity 불일치' }

$oldPath = $env:PATH
$oldEvidence = $env:HWPX_SELFCHECK_OUT
try {
    $windowsRoot = $env:SystemRoot
    $env:PATH = @(
        (Join-Path $windowsRoot 'System32'), $windowsRoot,
        (Join-Path $windowsRoot 'System32\Wbem')
    ) -join ';'
    foreach ($command in @('node.exe', 'python.exe', 'uv.exe')) {
        if (Get-Command $command -CommandType Application -ErrorAction SilentlyContinue) {
            throw "배포 selfcheck PATH에 build/runtime 도구가 남았습니다: $command"
        }
    }
    $env:HWPX_SELFCHECK_OUT = Join-Path $evidence 'selfcheck.json'
    $check = Start-Process -FilePath (Join-Path $destination 'hwpx-filler-web.exe') `
        -ArgumentList @('--selfcheck') -WindowStyle Hidden -Wait -PassThru
    if ($check.ExitCode -ne 0) { throw "배포 selfcheck 실패(exit $($check.ExitCode))" }
} finally {
    $env:PATH = $oldPath
    $env:HWPX_SELFCHECK_OUT = $oldEvidence
}
& $checker --selfcheck-evidence (Join-Path $evidence 'selfcheck.json') `
    --expect-identity (Join-Path $evidence 'dist.json') `
    --json-out (Join-Path $evidence 'selfcheck-identity.json')
if ($LASTEXITCODE -ne 0) { throw '배포 selfcheck identity 불일치' }
Write-Host "native bundle: $destination"
