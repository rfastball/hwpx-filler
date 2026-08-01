<#
.SYNOPSIS
  canonical frontend 산출물을 만들거나(Build), 이미 있는 산출물의 봉인을 검증한다(VerifyExisting).

.DESCRIPTION
  제품 Python 코드는 웹 빌드를 수행하지 않는다. 소스 실행·테스트·패키징 러너가 이 파일을
  먼저 호출해 `frontend/ -> build/web/` 전이를 명시적으로 완주한다.

  모드는 **이름 있는 계약**이다(N-11B). 종전의 `-SkipInstall` 은 "설치만 건너뛴다"는 불리언이라
  호출자가 무엇을 얻는지 이름으로 말하지 못했고, 실제 호출자는 0명이었다.

  - `Build`          — Node/npm/Vite 핀을 확인하고 `npm ci` → `vite build` → seal → verify.
  - `VerifyExisting` — 빌드 도구를 하나도 부르지 않고 이미 있는 `build/web/` 의 봉인만
    검증한다. **Node/npm 이 없어도 된다**: 봉인 검증은 트리와 현재 checkout 을 대조할 뿐
    빌드 도구를 탐색하지 않는다. CI 소비자 job 이 이 모드로 돈다.

.PARAMETER IdentityOut
  검증된 산출물의 정체성(artifact_id·tree_sha256·source commit)을 JSON 으로 쓴다.
  생산자 job 이 이 파일을 올리고 소비자 job 이 `-ExpectIdentity` 로 되짚는다.

.PARAMETER ExpectIdentity
  주어진 생산자 identity JSON 과 다르면 거절한다 — 소비자가 내려받는 대신 **자기가 다시
  만든** 경우를 잡는다.

.EXAMPLE
  .\build-web.ps1
  .\build-web.ps1 -Mode Build -IdentityOut web-artifact-identity.json
  .\build-web.ps1 -Mode VerifyExisting -ExpectIdentity web-artifact-identity.json
#>
[CmdletBinding()]
param(
    [ValidateSet('Build', 'VerifyExisting')]
    [string]$Mode = 'Build',
    [string]$IdentityOut,
    [string]$ExpectIdentity
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$expectedNode = 'v24.18.1'
$expectedNpm = '11.16.0'
$expectedVite = '8.1.5'

# seal 검증 CLI 로 넘길 인자. 두 모드가 **같은 검증기**를 부른다 — 모드가 가르는 것은
# "도구를 부르는가"이지 "무엇을 믿는가"가 아니다.
$verifyArgs = @()
$identityPath = $IdentityOut
# CI 요약에 **무엇을 검증했는지**를 남긴다. 요약을 워크플로 여섯 자리에 복제하는 대신 여기
# 한 곳에서 낸다 — 정체성을 아는 것은 이 스크립트이고, 복제된 요약은 하나가 낡아도 조용하다.
if ($env:GITHUB_STEP_SUMMARY -and -not $identityPath) {
    $identityPath = Join-Path ([System.IO.Path]::GetTempPath()) "hwpx-web-identity-$PID.json"
}
if ($identityPath) { $verifyArgs += @('--json-out', $identityPath) }
if ($ExpectIdentity) { $verifyArgs += @('--expect-identity', $ExpectIdentity) }

if ($Mode -eq 'Build') {
    $node = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $npm = Get-Command npm.cmd -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
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
        & $npm.Source ci
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        $viteVersionText = (& $npm.Source exec -- vite --version | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if ($viteVersionText -notmatch "(^|/)$([regex]::Escape($expectedVite))(\s|$)") {
            throw "Vite 버전 불일치: actual=$viteVersionText expected=$expectedVite"
        }

        & $npm.Source run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if ($verifyArgs.Count -gt 0) {
            & $npm.Source run verify:web -- @verifyArgs
        }
        else {
            & $npm.Source run verify:web
        }
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }

    $lockAfter = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash
    if ($lockAfter -ne $lockBefore) {
        throw 'npm locked install/build가 package-lock.json을 변경했습니다.'
    }
    $summary = "web build/seal OK — Node $nodeVersion · npm $npmVersion · Vite $expectedVite"
}
else {
    # Node 를 **찾지도 않는다**. 소비자 러너에 Node 가 없는 것이 이 모드의 요점이고, 없는데도
    # 통과하는 것이 "소비자는 다시 만들지 않는다"의 실물 증거다.
    Push-Location $root
    try {
        & uv run --no-sync python (Join-Path $root 'scripts\seal_web_artifact.py') `
            --verify @verifyArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }
    $summary = 'web seal verified — 기존 build/web 재사용(빌드 도구 미호출)'
}

$trackedBuildFiles = @(git -C $root ls-files -- 'build/web')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($trackedBuildFiles.Count -ne 0) {
    throw "generated build/web 파일이 Git에 tracked 상태입니다: $($trackedBuildFiles -join ', ')"
}

if ($env:GITHUB_STEP_SUMMARY -and $identityPath -and (Test-Path -LiteralPath $identityPath)) {
    $identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
    $job = if ($env:GITHUB_JOB) { $env:GITHUB_JOB } else { 'local' }
    @(
        "### sealed web — $job ($Mode)",
        '',
        '| 항목 | 값 |',
        '|---|---|',
        "| artifact_id | ``$($identity.artifact_id)`` |",
        "| tree_sha256 | ``$($identity.tree_sha256)`` |",
        "| source commit | ``$($identity.source_commit)`` |",
        "| runner | $env:RUNNER_OS $env:RUNNER_ARCH |",
        ''
    ) | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
}

Write-Host $summary -ForegroundColor Green
