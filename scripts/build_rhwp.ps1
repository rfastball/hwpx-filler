$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$cache = if ($env:RHWP_BUILD_CACHE_DIR) {
    if (-not [IO.Path]::IsPathRooted($env:RHWP_BUILD_CACHE_DIR)) { throw 'RHWP_BUILD_CACHE_DIR must be absolute' }
    $env:RHWP_BUILD_CACHE_DIR
} else { Join-Path $root '.cache' }
$source = Join-Path $cache 'rhwp-upstream'
$sourceMarker = Join-Path $source '.rhwp-builder-owned'
$out = Join-Path $root 'build/rhwp/studio'
$patch = Join-Path $root 'vendor/rhwp/patches/authoring.patch'
$commit = '680111ec7bea2fe11110de18c3676ba5a1cf7847'
New-Item -ItemType Directory $cache -Force | Out-Null

if (-not (Test-Path (Join-Path $source '.git'))) {
    & git clone --filter=blob:none --no-checkout https://github.com/edwardkim/rhwp.git $source
    if ($LASTEXITCODE) { throw 'rhwp clone failed' }
    & git -C $source config core.autocrlf false
    & git -C $source sparse-checkout init --cone
    & git -C $source sparse-checkout set assets bindings crates examples npm rhwp-studio saved src tests tools
    & git -C $source checkout $commit
    if ($LASTEXITCODE) { throw 'rhwp checkout failed' }
    Set-Content -LiteralPath $sourceMarker -Value $commit -NoNewline
}
if ((& git -C $source rev-parse HEAD).Trim() -ne $commit) { throw 'rhwp source revision mismatch' }
& git -C $source config core.autocrlf false
$expectedRemote = 'https://github.com/edwardkim/rhwp.git'
if ((& git -C $source remote get-url origin).Trim() -ne $expectedRemote) { throw 'rhwp source remote mismatch' }
if (-not (Test-Path $sourceMarker) -or (Get-Content -LiteralPath $sourceMarker -Raw).Trim() -ne $commit) {
    throw 'rhwp cache checkout is not build-script-owned; use a fresh RHWP_BUILD_CACHE_DIR'
}
$ErrorActionPreference = 'Continue'
& git -C $source apply --reverse --check --quiet $patch 2>$null
$alreadyPatched = $LASTEXITCODE -eq 0
$ErrorActionPreference = 'Stop'
if (-not $alreadyPatched) {
    # This cache is ours and pinned. A changed tracked patch leaves an older
    # applied patch in place; reset only this marked checkout before reapplying.
    & git -C $source reset --hard $commit | Out-Null
    if ($LASTEXITCODE) { throw 'rhwp cache reset failed' }
    & git -C $source apply --check $patch
    if ($LASTEXITCODE) { throw 'rhwp patch does not apply to pinned source' }
    & git -C $source apply $patch
    if ($LASTEXITCODE) { throw 'rhwp patch application failed' }
}

$env:RUSTUP_HOME = Join-Path $cache 'rhwp-rustup'
$env:CARGO_HOME = Join-Path $cache 'rhwp-cargo'
New-Item -ItemType Directory $env:RUSTUP_HOME, $env:CARGO_HOME -Force | Out-Null
$env:PATH = (Join-Path $env:CARGO_HOME 'bin') + ';' + $env:PATH
$rustup = Join-Path $env:CARGO_HOME 'bin/rustup.exe'
if (-not (Test-Path $rustup)) {
    $installer = Join-Path $cache 'rustup-init.exe'
    if (-not (Test-Path $installer)) {
        Invoke-WebRequest 'https://win.rustup.rs/x86_64' -OutFile $installer
    }
    & $installer -y --no-modify-path --default-toolchain 1.93.1 --profile minimal --target wasm32-unknown-unknown
    if ($LASTEXITCODE) { throw 'local Rust install failed' }
}
$targetLib = Join-Path $env:RUSTUP_HOME 'toolchains/1.93.1-x86_64-pc-windows-msvc/lib/rustlib/wasm32-unknown-unknown/lib'
if (-not (Test-Path $targetLib)) {
    & $rustup toolchain install 1.93.1 --profile minimal --target wasm32-unknown-unknown
    if ($LASTEXITCODE) { throw 'Rust target install failed' }
}

$tools = Join-Path $cache 'rhwp-tools'
New-Item -ItemType Directory $tools -Force | Out-Null
$wasmPack = Join-Path $tools 'node_modules/.bin/wasm-pack.cmd'
if (-not (Test-Path $wasmPack)) {
    & npm install --prefix $tools --no-audit --no-fund --save-exact wasm-pack@0.15.0
    if ($LASTEXITCODE) { throw 'wasm-pack install failed' }
}
Push-Location $source
try {
    & $wasmPack build --target web --release --no-opt
    if ($LASTEXITCODE) { throw 'rhwp WASM build failed' }
} finally { Pop-Location }

$studio = Join-Path $source 'rhwp-studio'
if (-not (Test-Path (Join-Path $studio 'node_modules'))) {
    Push-Location $studio
    try { & npm ci --no-audit --no-fund; if ($LASTEXITCODE) { throw 'Studio npm ci failed' } }
    finally { Pop-Location }
}
$env:RHWP_DISABLE_EXTERNAL_WEBFONTS = '1'
$env:RHWP_EMBEDDED = '1'
# The embedded runtime uses offline font snapshots only. Strip online CDN URLs
# from its generated CanvasKit projection before Vite bundles the module.
& node (Join-Path $root 'vendor/rhwp/prepare_embedded_font_projection.mjs') $studio
if ($LASTEXITCODE) { throw 'embedded font projection failed' }
Push-Location $studio
try {
    & npm run build -- --base /rhwp/studio/
    if ($LASTEXITCODE) { throw 'Studio build failed' }
} finally { Pop-Location }

$buildRootPath = Join-Path $root 'build'
New-Item -ItemType Directory $buildRootPath -Force | Out-Null
$buildRoot = (Resolve-Path $buildRootPath).Path
if (-not $out.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Studio output escaped build root'
}
if (Test-Path $out) { Remove-Item -LiteralPath $out -Recurse -Force }
New-Item -ItemType Directory $out -Force | Out-Null
Copy-Item -Path (Join-Path $studio 'dist/*') -Destination $out -Recurse -Force
# Embedded Studio never serves upstream example documents or its standalone PWA.
$samples = Join-Path $out 'samples'
if (Test-Path $samples) { Remove-Item -LiteralPath $samples -Recurse -Force }
foreach ($name in @('manifest.webmanifest', 'registerSW.js', 'sw.js')) {
    $file = Join-Path $out $name
    if (Test-Path $file) { Remove-Item -LiteralPath $file -Force }
}
Get-ChildItem -LiteralPath $out -Filter 'workbox*.js' -File | Remove-Item -Force
$fontTarget = Join-Path $out 'fonts'
if (Test-Path $fontTarget) { Remove-Item -LiteralPath $fontTarget -Recurse -Force }
Copy-Item -Path (Join-Path $source 'assets/fonts') -Destination $fontTarget -Recurse -Force
foreach ($name in @('rhwp.js', 'rhwp.d.ts', 'rhwp_bg.wasm.d.ts')) {
    $file = Join-Path $out $name
    if (Test-Path $file) { Remove-Item -LiteralPath $file -Force }
}
foreach ($name in @('FONTS.md', 'SourceHanSerifK-OFL.txt')) {
    $file = Join-Path $fontTarget $name
    if (Test-Path $file) { Remove-Item -LiteralPath $file -Force }
}
foreach ($name in @('icon-128.png', 'icon-192.png', 'icon-512.png')) {
    $file = Join-Path $out "icons/$name"
    if (Test-Path $file) { Remove-Item -LiteralPath $file -Force }
}
Write-Host "rhwp Studio runtime ready: $out"
