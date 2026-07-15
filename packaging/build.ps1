<#
.SYNOPSIS
  K1 onedir 번들(앱 A·B + CLI)을 빌드하고 스모크 검증한다.

.EXAMPLE
  .\packaging\build.ps1
  .\packaging\build.ps1 -Target cli
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'filler', 'diff', 'cli')]
    [string]$Target = 'all',
    [switch]$SkipCheck
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
& chcp.com 65001 *> $null

$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'
$corpus = Join-Path $root 'tests\corpus\real'
$env:UV_CACHE_DIR = Join-Path $root '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $root '.uv-python'

if (-not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) {
    throw 'uv 없음. 먼저 uv sync --locked --all-extras --group dev --group build'
}

& uv run --no-sync python (Join-Path $PSScriptRoot 'verify_specs.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv run --no-sync python (Join-Path $root 'scripts\generate_build_metadata.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$targets = @{
    filler = @{ Spec = 'hwpx_filler.spec'; Dir = 'hwpx-filler'; Exe = 'hwpx-filler.exe' }
    diff   = @{ Spec = 'hwpx_diff.spec';   Dir = 'hwpx-diff';   Exe = 'hwpx-diff.exe' }
    cli    = @{ Spec = 'hwpx_cli.spec';    Dir = 'hwpx-cli';    Exe = 'hwpx-cli.exe' }
}
$plan = if ($Target -eq 'all') { @('filler', 'diff', 'cli') } else { @($Target) }

function Test-GuiStart([string]$ExePath) {
    $previous = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = 'offscreen'
    try {
        $process = Start-Process -FilePath $ExePath -PassThru -WindowStyle Hidden
        Start-Sleep -Seconds 3
        $process.Refresh()
        if ($process.HasExited) {
            throw "GUI 조기 종료(exit $($process.ExitCode)): $ExePath"
        }
        Stop-Process -Id $process.Id -Force
        Write-Host "GUI 기동: OK ($ExePath)" -ForegroundColor Green
    } finally {
        $env:QT_QPA_PLATFORM = $previous
    }
}

function Test-BundleBoundary([string]$Key, [string]$BundleDir) {
    $files = Get-ChildItem $BundleDir -Recurse -File
    if ($Key -eq 'cli' -or $Key -eq 'diff') {
        # cli·diff(웹 이관, #22)는 Qt 미탑재 — PySide/Qt6 DLL 이 하나라도 있으면 실패.
        $unexpected = $files | Where-Object Name -Match '^(PySide|Qt6)'
    } else {
        $unexpected = $files | Where-Object Name -Match `
            '^(Qt6(Qml|Quick|Pdf|Network|OpenGL|VirtualKeyboard)|opengl32sw|qtvirtualkeyboardplugin|qpdf\.dll)'
    }
    if ($unexpected) {
        throw "미사용 런타임이 번들에 남음: $($unexpected.Name -join ', ')"
    }
}

foreach ($key in $plan) {
    $item = $targets[$key]
    Write-Host "`n=== onedir 빌드: $key ===" -ForegroundColor Cyan
    & uv run --no-sync --extra gui --group build pyinstaller `
        (Join-Path $PSScriptRoot $item.Spec) --noconfirm --clean `
        --distpath $dist --workpath (Join-Path $root "build\pyinstaller-$key")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $exe = Join-Path (Join-Path $dist $item.Dir) $item.Exe
    if (-not (Test-Path $exe)) { throw "onedir exe 누락: $exe" }
    Test-BundleBoundary $key (Split-Path -Parent $exe)
    if ($SkipCheck) { continue }

    if ($key -eq 'filler') {
        & $exe --selfcheck
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Test-GuiStart $exe
    } elseif ($key -eq 'diff') {
        # diff 는 #22 로 웹(pywebview) 이관됨 — Qt offscreen 기동(Test-GuiStart)은 무의미하다.
        # 헤드리스 --selfcheck 가 브리지·컨트롤러·비교 엔진·번들 web-diff/ 를 스모크한다.
        & $exe --selfcheck `
            (Join-Path $corpus 'spec_revision_2025.hwpx') `
            (Join-Path $corpus 'spec_revision_2026.hwpx')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } else {
        $template = Join-Path $corpus 'form_purchase_v1.hwpx'
        $template2 = Join-Path $corpus 'form_purchase_v2.hwpx'
        # 동적 import 경계인 템플릿 관리 명령 4개를 실제 번들에서 실행.
        & $exe schema $template --out (Join-Path $env:TEMP 'hwpx-k1-schema.json')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $exe fieldize $template
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $exe lint $template
        if ($LASTEXITCODE -notin @(0, 1)) { exit $LASTEXITCODE }
        & $exe drift $template $template2
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}

Write-Host "`nK1 onedir 빌드·스모크 완료: $($plan -join ', ')" -ForegroundColor Green
