<#
  Real Windows WebView2 restart and geometry owner. Run against one sealed native bundle.
  Every launch uses a new or explicitly reused isolated app home; no user profile is read.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$EvidenceDir
)
$ErrorActionPreference = 'Stop'
$exePath = [IO.Path]::GetFullPath($Exe)
$evidencePath = [IO.Path]::GetFullPath($EvidenceDir)
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "Native GUI executable is missing: $exePath"
}
if (Test-Path -LiteralPath $evidencePath) {
    throw "Restart evidence directory must be new: $evidencePath"
}
New-Item -ItemType Directory -Path $evidencePath | Out-Null
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$darkCard = (Get-Content -LiteralPath (Join-Path $root 'frontend/design-tokens.json') `
    -Raw | ConvertFrom-Json).dark.color.card_bg
$environmentNames = @(
    'PATH', 'HWPXFILLER_HOME', 'HWPX_SELFTEST_OUT', 'HWPX_SELFTEST_PROBES',
    'HWPX_SELFTEST_SET_THEME', 'HWPX_SELFTEST_SET_FONT_SCALE',
    'HWPX_SELFTEST_GEOMETRY_ONLY', 'HWPX_SELFTEST_OFFLINE_PROBE',
    'HWPX_SELFTEST_NO_CAPABILITY', 'HWPX_SELFTEST_GLOBAL_DELTA'
)
$prior = @{}
foreach ($name in $environmentNames) {
    $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Require-Equal($Actual, $Expected, [string]$Label) {
    if ($Actual -cne $Expected) {
        throw "$Label expected '$Expected', got '$Actual'"
    }
}

function Invoke-NativeProbe([string]$Label, [string]$AppHome,
    [hashtable]$Variables) {
    foreach ($name in $environmentNames) {
        if ($name -ne 'PATH') {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
    }
    $windows = $env:SystemRoot
    $env:PATH = @((Join-Path $windows 'System32'), $windows,
        (Join-Path $windows 'System32/Wbem')) -join ';'
    $env:HWPXFILLER_HOME = $AppHome
    $output = Join-Path $evidencePath "$Label.json"
    $env:HWPX_SELFTEST_OUT = $output
    foreach ($name in $Variables.Keys) {
        [Environment]::SetEnvironmentVariable($name, [string]$Variables[$name], 'Process')
    }
    $process = Start-Process -FilePath $exePath -ArgumentList '--selftest' `
        -PassThru -WindowStyle Hidden
    # Cold60 + engine80 + native hard-stop margin60 = 200s. The harness gives
    # the process 30s more to terminate and leave a readable failure receipt.
    if (-not $process.WaitForExit(230000)) {
        Stop-Process -Id $process.Id -Force
        throw "$Label native WebView2 process exceeded its outer 230s limit"
    }
    if ($process.ExitCode -ne 0) {
        $detail = if (Test-Path -LiteralPath $output) {
            Get-Content -LiteralPath $output -Raw
        } else {
            $alerts = Join-Path $AppHome 'webapp-alerts.log'
            if (Test-Path -LiteralPath $alerts) { Get-Content -LiteralPath $alerts -Raw }
            else { 'No native receipt or durable alert was written.' }
        }
        throw "$Label native WebView2 process exited $($process.ExitCode): $detail"
    }
    if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
        throw "$Label native WebView2 receipt is missing"
    }
    $receipt = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
    if ($null -ne $receipt.error) {
        throw "$Label native WebView2 probe failed: $($receipt.error)"
    }
    return $receipt
}

function Require-Selected($Receipt, [string[]]$Names, [string]$Label) {
    Require-Equal $Receipt.selftest_selection.partial $true "$Label partial selection"
    Require-Equal ($Receipt.selftest_selection.requested -join ',') ($Names -join ',') `
        "$Label requested probes"
    $expected = @('grid_narrow', 'grid_wide', 'theme_persist')
    if ($Names -contains 'personalization_persist') { $expected += 'personalization_persist' }
    Require-Equal ($Receipt.selftest_selection.planned -join ',') ($expected -join ',') `
        "$Label dependency closure"
}

try {
    $themeHome = Join-Path $evidencePath 'theme-home'
    $themeWrite = Invoke-NativeProbe 'theme-write' $themeHome `
        @{ HWPX_SELFTEST_SET_THEME = 'dark' }
    Require-Equal $themeWrite.set_result 'dark' 'theme write result'
    $stamp = (Get-Content -LiteralPath (Join-Path $themeHome 'settings.json') `
        -Raw | ConvertFrom-Json).boot_completed_runtime
    if (-not $stamp) { throw 'A completed WebView boot did not persist its runtime stamp' }
    $themeRead = Invoke-NativeProbe 'theme-read' $themeHome `
        @{ HWPX_SELFTEST_PROBES = 'theme_persist' }
    Require-Selected $themeRead @('theme_persist') 'theme restart'
    Require-Equal $themeRead.theme_persist.data_theme 'dark' 'theme after restart'
    Require-Equal $themeRead.theme_persist.a_card $darkCard 'dark card color after restart'
    Require-Equal (Get-Content -LiteralPath (Join-Path $themeHome 'settings.json') `
        -Raw | ConvertFrom-Json).boot_completed_runtime $stamp 'completed runtime stamp'

    foreach ($scale in @('large', 'larger')) {
        $fontHome = Join-Path $evidencePath "$scale-home"
        $fontWrite = Invoke-NativeProbe "$scale-write" $fontHome `
            @{ HWPX_SELFTEST_SET_FONT_SCALE = $scale }
        Require-Equal $fontWrite.set_result $scale "$scale write result"
        $settingsPath = Join-Path $fontHome 'settings.json'
        $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        $settings | Add-Member -MemberType NoteProperty -Name master_width -Value 333 -Force
        [IO.File]::WriteAllText($settingsPath, ($settings | ConvertTo-Json -Depth 20),
            (New-Object System.Text.UTF8Encoding($false)))
        $fontRead = Invoke-NativeProbe "$scale-read" $fontHome `
            @{ HWPX_SELFTEST_PROBES = 'personalization_persist' }
        Require-Selected $fontRead @('personalization_persist') "$scale restart"
        Require-Equal $fontRead.personalization_persist.font_scale $scale "$scale value"
        Require-Equal $fontRead.personalization_persist.root_px `
            $(if ($scale -eq 'large') { '20px' } else { '24px' }) "$scale root size"
        Require-Equal $fontRead.personalization_persist.master_width 333 "$scale master width"
        Require-Equal $fontRead.personalization_persist.body_overflow $false "$scale body overflow"
        Require-Equal $fontRead.grid_narrow.tabs 2 "$scale narrow tabs"
        Require-Equal $fontRead.grid_narrow.overflow $false "$scale narrow overflow"
        Require-Equal $fontRead.grid_wide.rows 2 "$scale wide rows"
        Require-Equal $fontRead.grid_wide.tool_labels_visible $true "$scale wide labels"
    }

    foreach ($mode in @('normal', 'maximized', 'offscreen')) {
        $geometryHome = Join-Path $evidencePath "$mode-home"
        New-Item -ItemType Directory -Path $geometryHome | Out-Null
        $geometry = @{ x = $(if ($mode -eq 'offscreen') { 50000 } else { 120 });
            y = 100; width = 1000; height = 700; maximized = ($mode -eq 'maximized') }
        $geometryJson = @{ window_geometry = $geometry } | ConvertTo-Json -Depth 5
        [IO.File]::WriteAllText((Join-Path $geometryHome 'settings.json'), $geometryJson,
            (New-Object System.Text.UTF8Encoding($false)))
        $view = Invoke-NativeProbe "$mode-geometry" $geometryHome `
            @{ HWPX_SELFTEST_GEOMETRY_ONLY = '1' }
        $observed = $view.window_geometry
        if ($mode -eq 'normal') {
            foreach ($name in @('x', 'y', 'width', 'height')) {
                Require-Equal $observed.$name $geometry[$name] "normal geometry $name"
            }
            Require-Equal $observed.maximized_like $false 'normal geometry maximized'
        } elseif ($mode -eq 'maximized') {
            Require-Equal $observed.maximized_like $true 'maximized geometry'
        } else {
            if ($observed.x -eq 50000) { throw 'offscreen geometry was not recovered' }
            Require-Equal $observed.width 1440 'offscreen fallback width'
            Require-Equal $observed.maximized_like $false 'offscreen fallback maximized'
        }
    }
    Write-Output "Native WebView2 restart and geometry: 9 launches passed; receipts=$evidencePath"
} finally {
    foreach ($name in $environmentNames) {
        if ($null -eq $prior[$name]) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $prior[$name], 'Process')
        }
    }
}
