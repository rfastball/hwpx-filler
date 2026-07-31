<#
.SYNOPSIS
  exact Node/npm/Vite 도구로 canonical frontend 산출물을 새로 만들고 seal을 검증한다.

.DESCRIPTION
  제품 Python 코드는 웹 빌드를 수행하지 않는다. 소스 실행·테스트·패키징 러너가 이 파일을
  먼저 호출해 `frontend/ -> build/web/` 전이를 명시적으로 완주한다.
#>
[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$expectedNode = 'v24.18.1'
$expectedNpm = '11.16.0'
$expectedVite = '8.1.5'

$node = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue
$npm = Get-Command npm.cmd -CommandType Application -ErrorAction SilentlyContinue
if (-not $node -or -not $npm) {
    throw 'Node/npm 없음. .node-version의 Node 24.18.1(번들 npm 11.16.0)을 설치하세요.'
}

$nodeVersion = (& $node.Source --version).Trim()
$npmVersion = (& $npm.Source --version).Trim()
if ($nodeVersion -ne $expectedNode) {
    throw "Node 버전 불일치: actual=$nodeVersion expected=$expectedNode"
}
if ($npmVersion -ne $expectedNpm) {
    throw "npm 버전 불일치: actual=$npmVersion expected=$expectedNpm"
}

$lockPath = Join-Path $root 'package-lock.json'
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw "package-lock.json 누락: $lockPath"
}
$lockBefore = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash

Push-Location $root
try {
    if (-not $SkipInstall) {
        & $npm.Source ci
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    $viteVersionText = (& $npm.Source exec -- vite --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($viteVersionText -notmatch "(^|/)$([regex]::Escape($expectedVite))(\s|$)") {
        throw "Vite 버전 불일치: actual=$viteVersionText expected=$expectedVite"
    }

    & $npm.Source run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $npm.Source run verify:web
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

$lockAfter = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash
if ($lockAfter -ne $lockBefore) {
    throw 'npm locked install/build가 package-lock.json을 변경했습니다.'
}

$trackedBuildFiles = @(git -C $root ls-files -- 'build/web')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($trackedBuildFiles.Count -ne 0) {
    throw "generated build/web 파일이 Git에 tracked 상태입니다: $($trackedBuildFiles -join ', ')"
}

Write-Host (
    "web build/seal OK — Node $nodeVersion · npm $npmVersion · Vite $expectedVite"
) -ForegroundColor Green
