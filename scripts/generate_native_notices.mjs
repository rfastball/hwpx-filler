#!/usr/bin/env node
// Generate release notices from the actual Windows Rust closure and sealed frontend chunks.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runtimePackages } from './generate_build_metadata.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ALLOWED = new Set(['MIT', 'MIT-0', 'Apache-2.0', 'BSD-3-Clause', 'Zlib',
  'Unicode-3.0', 'MPL-2.0', 'Unlicense', '0BSD', 'CC0-1.0']);
const LICENSE_FILE = /^(?:LICENSE|LICENCE|COPYING|NOTICE)(?:[.\-_]|$)/i;
const WEBVIEW2_LIB_SHA256 = '89c6b872783b8f6c3cedbff618adb42082d455c615453ae10cfc753f1e8f25d8';
const WEBVIEW2_LICENSE_SHA256 = '0af8f1b807512aae39c2ac1aa4d0cae65cabecb6fd554b8439a5162a0d6eca55';
const FAMILY_NOTICES = [
  { packages: ['alloc-stdlib@0.3.0'], commits: ['0a81fd6928ea3b33c8cd484aa4575d50ffb98012'],
    source: 'https://github.com/dropbox/rust-alloc-no-stdlib', files: [
      ['alloc-stdlib-LICENSE', 'LICENSE', 'c0c56f26d9c051cac4d200c34c84e7ae9aaa853e01a982a1df08b09931e518ae'],
    ] },
  { packages: ['rustpython-format@0.4.0', 'rustpython-literal@0.4.0'],
    commits: ['8dd2aea26778d8d6917770f8e32bea1b9cdc0ae8'],
    source: 'https://github.com/RustPython/Parser', files: [
      ['rustpython-parser-LICENSE', 'LICENSE', '0dfeb72ba967794c4ea067b6e67798aefde4fd4cdb10f1882fe1163d2652434d'],
    ] },
  { packages: ['unic-char-property@0.9.0', 'unic-char-range@0.9.0',
      'unic-common@0.9.0', 'unic-ucd-category@0.9.0', 'unic-ucd-version@0.9.0'],
    commits: ['5878605364af97a3358368a6eaef02104af2e016',
      '8a6ce83063d90b91ae2ce59eddb803edd393fca9'],
    source: 'https://github.com/open-i18n/rust-unic', files: [
      ['rust-unic-LICENSE-MIT', 'LICENSE-MIT', '23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3'],
      ['rust-unic-LICENSE-APACHE', 'LICENSE-APACHE', 'a60eea817514531668d7e00765731449fe14d059d3249e0bc93b36de45f759f2'],
    ] },
  { packages: ['webview2-com@0.39.1', 'webview2-com-sys@0.39.1'],
    commits: ['edc2caf886175ccaebe86078c9cfe1ae2a187328'],
    source: 'https://github.com/wravery/webview2-rs', files: [
      ['webview2-rs-LICENSE', 'LICENSE', '0dcf41516e608bbcb6cdc5229feb7b86fe4a643b85e7df251133c93408fdac73'],
    ] },
];
const DECLARED_NOTICES = new Map([
  ['hexf-parse@0.2.1', { commit: '4225763d744183d720f575ae96d04161b4d08ea0',
    license: 'CC0-1.0', source: 'https://github.com/lifthrasiir/hexf',
    terms: 'https://creativecommons.org/publicdomain/zero/1.0/legalcode' }],
  ['selectors@0.38.0', { commit: '572ecba2d1600e7c3d490586692a209faf703baa',
    license: 'MPL-2.0', source: 'https://github.com/servo/stylo',
    terms: 'https://www.mozilla.org/MPL/2.0/' }],
]);

function sha256File(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

function generatedNoticeHashes(root) {
  const result = [];
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile()) result.push({
        path: path.relative(root, full).split(path.sep).join('/'), sha256: sha256File(full),
      });
      else throw new Error(`Generated notice is not a regular file: ${full}`);
    }
  }
  walk(root);
  return result.sort((left, right) => left.path.localeCompare(right.path, 'en'));
}

function nativeComponents(root, crates, metadata) {
  const webview = crates.find(item => item.name === 'webview2-com-sys');
  let sdk;
  if (webview) {
    if (webview.version !== '0.39.1') throw new Error('WebView2 binding version needs review');
    const archive = path.join(path.dirname(webview.manifest_path), 'x64/WebView2LoaderStatic.lib');
    const notice = path.join(root, 'packaging/Microsoft-WebView2-SDK-LICENSE.txt');
    if (sha256File(archive) !== WEBVIEW2_LIB_SHA256 ||
        sha256File(notice) !== WEBVIEW2_LICENSE_SHA256) {
      throw new Error('WebView2 SDK binary or license differs from verified NuGet 1.0.3800.47');
    }
    sdk = { notice, archive };
  }
  const sqlite = crates.find(item => item.name === 'libsqlite3-sys');
  let sqliteSource;
  if (sqlite) {
    const node = metadata.resolve.nodes.find(item => item.id === sqlite.id);
    if (!node?.features.includes('bundled')) {
      throw new Error('SQLite native notice must be reviewed for non-bundled build');
    }
    const source = path.join(path.dirname(sqlite.manifest_path), 'sqlite3/sqlite3.c');
    const version = readFileSync(source, 'utf8').match(/^#define SQLITE_VERSION\s+"([^"]+)"/m)?.[1];
    if (!version) throw new Error('Bundled SQLite source version missing');
    sqliteSource = { version, sha256: sha256File(source) };
  }
  return { sdk, sqliteSource };
}

function cargoEnvironment(root) {
  const env = { ...process.env };
  const local = path.join(root, '.cache/rhwp-cargo/bin/cargo.exe');
  if (existsSync(local) && !env.CARGO_HOME) {
    env.CARGO_HOME = path.join(root, '.cache/rhwp-cargo');
    env.RUSTUP_HOME ??= path.join(root, '.cache/rhwp-rustup');
    env.PATH = `${path.dirname(local)}${path.delimiter}${env.PATH ?? ''}`;
  }
  return env;
}

export function cargoMetadata(root = ROOT, noDefaultFeatures = false) {
  const result = spawnSync('cargo', ['metadata', '--format-version', '1', '--offline',
    '--locked', '--filter-platform', 'x86_64-pc-windows-msvc',
    ...(noDefaultFeatures ? ['--no-default-features'] : [])],
  { cwd: root, env: cargoEnvironment(root), encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  if (result.error || result.status !== 0) {
    throw new Error(`Cargo.lock dependency inventory failed: ${result.stderr || result.error}`);
  }
  return JSON.parse(result.stdout);
}

export function runtimeCrates(metadata) {
  const root = metadata.packages.find(item => item.name === 'hwpx-desktop');
  if (!root) throw new Error('hwpx-desktop package missing from Cargo metadata');
  const nodes = new Map(metadata.resolve.nodes.map(node => [node.id, node]));
  const packagesById = new Map(metadata.packages.map(item => [item.id, item]));
  const seen = new Set();
  function visit(id) {
    if (seen.has(id)) return;
    seen.add(id);
    const node = nodes.get(id);
    if (!node) throw new Error(`Cargo resolve node missing: ${id}`);
    for (const edge of node.deps) {
      const dependency = packagesById.get(edge.pkg);
      if (!dependency) throw new Error(`Cargo package missing: ${edge.pkg}`);
      // Proc macros and their dependencies execute during the build, not in the app.
      const procMacro = dependency.targets?.some(target => target.kind.includes('proc-macro'));
      if (edge.dep_kinds.some(kind => kind.kind === null) && !procMacro) visit(edge.pkg);
    }
  }
  visit(root.id);
  const packages = metadata.packages.filter(item => seen.has(item.id) &&
    item.source?.startsWith('registry+'));
  if (!packages.length) throw new Error('Windows Rust runtime closure is empty');
  const compare = (left, right) => left < right ? -1 : left > right ? 1 : 0;
  return packages.sort((left, right) => compare(left.name, right.name) ||
    compare(left.version, right.version));
}

function assertLicense(item) {
  const names = item.license?.match(/[A-Za-z0-9.-]+/g) ?? [];
  const ids = names.filter(name => name !== 'AND' && name !== 'OR');
  if (!ids.length || ids.some(name => !ALLOWED.has(name))) {
    throw new Error(`Rust license requires review: ${item.name}@${item.version}: ${item.license}`);
  }
  if (!/^[a-z0-9_-]+$/.test(item.name) || !/^\d+[\w.+-]*$/.test(item.version)) {
    throw new Error(`Unsafe crate identity: ${item.name}@${item.version}`);
  }
}

function noticeFiles(item, root) {
  const directory = path.dirname(item.manifest_path);
  const files = readdirSync(directory).filter(name => LICENSE_FILE.test(name) &&
    lstatSync(path.join(directory, name)).isFile());
  if (files.length) return files.map(name => ({ from: path.join(directory, name), name,
    origin: `https://crates.io/crates/${item.name}/${item.version}` }));
  return upstreamNoticeFiles(item, root, directory);
}

function upstreamNoticeFiles(item, root, directory) {
  const identity = `${item.name}@${item.version}`;
  const family = FAMILY_NOTICES.find(group => group.packages.includes(identity));
  const declared = DECLARED_NOTICES.get(identity);
  if (!family && !declared) throw new Error(`Rust package notice missing: ${identity}`);
  const commit = JSON.parse(readFileSync(path.join(directory, '.cargo_vcs_info.json'), 'utf8')).git.sha1;
  if (family) return familyNoticeFiles(identity, family, root, commit);
  return [declaredNoticeFile(item, declared, directory, commit)];
}

function familyNoticeFiles(identity, family, root, commit) {
  if (!family.commits.includes(commit)) throw new Error(`Upstream notice commit changed: ${identity}`);
  return family.files.map(([sourceName, name, digest]) => {
    const from = path.join(root, 'packaging/native-notice-sources', sourceName);
    if (sha256File(from) !== digest) throw new Error(`Upstream notice bytes changed: ${identity}`);
    return { from, name, origin: `${family.source}/tree/${commit}` };
  });
}

function declaredNoticeFile(item, declared, directory, commit) {
  const identity = `${item.name}@${item.version}`;
  if (commit !== declared.commit || item.license !== declared.license) {
    throw new Error(`Declared upstream license changed: ${identity}`);
  }
  const header = item.name === 'selectors'
    ? readFileSync(path.join(directory, 'lib.rs'), 'utf8').split('\n').slice(0, 3).join('\n')
    : '';
  if (item.name === 'selectors' && !header.includes('Mozilla Public')) {
    throw new Error(`Selectors source license header changed: ${identity}`);
  }
  return { name: 'DECLARATION.txt', origin: `${declared.source}/tree/${commit}`,
    text: `${identity}\n${item.license} declared in the published Cargo.toml.\n` +
      `Upstream revision: ${declared.source}/tree/${commit}\n` +
      `License terms: ${declared.terms}\n${header}\n` };
}

function safeCell(value) {
  return String(value ?? '').replaceAll('|', '\\|').replaceAll(/[\r\n]+/g, ' ');
}

function copyNpmNotices(root, out, name) {
  const parts = name.split('/');
  if (parts.some(part => part === '.' || part === '..') ||
    !/^(@[a-z0-9._-]+\/)?[a-z0-9._-]+$/.test(name)) {
    throw new Error(`Unsafe npm package name: ${name}`);
  }
  const source = path.join(root, 'node_modules', name);
  if (!lstatSync(source).isDirectory()) throw new Error(`npm package is not a directory: ${name}`);
  const files = readdirSync(source).filter(file => LICENSE_FILE.test(file) &&
    lstatSync(path.join(source, file)).isFile());
  if (!files.length) throw new Error(`npm license file missing: ${name}`);
  const destination = path.join(out, 'licenses/npm', name);
  mkdirSync(destination, { recursive: true });
  for (const file of files) copyFileSync(path.join(source, file), path.join(destination, file));
}

function writeCrateNotices(prepared, out, lines) {
  mkdirSync(path.join(out, 'licenses/rust'), { recursive: true });
  for (const [item, files] of prepared) {
    const destination = path.join(out, 'licenses/rust', `${item.name}-${item.version}`);
    mkdirSync(destination);
    for (const file of files) {
      const target = path.join(destination, file.name);
      if (file.from) copyFileSync(file.from, target);
      else writeFileSync(target, file.text, 'utf8');
    }
    const authors = item.authors.join(', ');
    const source = `https://crates.io/crates/${item.name}/${item.version}`;
    lines.push(`| ${safeCell(item.name)} | ${safeCell(item.version)} | ${safeCell(item.license)}` +
      ` | ${safeCell(authors)} | ${safeCell(source)} | ${safeCell(item.repository)}` +
      ` | ${safeCell(files[0].origin)} |`);
  }
}

function writeNpmNotices(root, frontend, npmLock, out, lines) {
  for (const [name, version] of Object.entries(frontend)) {
    const license = npmLock[`node_modules/${name}`]?.license;
    if (!license) throw new Error(`npm license missing: ${name}@${version}`);
    copyNpmNotices(root, out, name);
    lines.push(`| ${safeCell(name)} | ${safeCell(version)} | ${safeCell(license)} |`);
  }
}

export function generateNotices(root, web, out, metadata = cargoMetadata(root)) {
  if (existsSync(out)) throw new Error(`Refusing existing notice directory: ${out}`);
  const crates = runtimeCrates(metadata);
  const native = nativeComponents(root, crates, metadata);
  const prepared = crates.map(item => {
    assertLicense(item);
    return [item, noticeFiles(item, root)];
  });
  const frontend = runtimePackages(root, web);
  const npmLock = JSON.parse(readFileSync(path.join(root, 'package-lock.json'), 'utf8')).packages;
  const lines = [
    '# 제3자 고지 (Third-Party Notices)', '',
    '문서나르미 Windows 출하본의 Rust/Tauri 링크 의존성은 Cargo.lock의',
    'x86_64-pc-windows-msvc normal 의존성에서 빌드 시 실행되는 proc macro를 제외해 유도했다.',
    '웹 런타임은 봉인된 JS 청크에서 유도했다.',
    '각 Rust 크레이트의 원문 고지는 `licenses/rust/`, npm 패키지의 원문은',
    '`licenses/npm/`에 동봉한다.', '',
    '## Rust/Tauri 런타임 의존성', '',
    '| 크레이트 | 버전 | 라이선스 | 저자 | 고정 배포판 | 원천 저장소 | 고지 원천 |',
    '| --- | --- | --- | --- | --- | --- | --- |',
  ];
  writeCrateNotices(prepared, out, lines);
  if (native.sdk) {
    mkdirSync(path.join(out, 'licenses/microsoft'), { recursive: true });
    copyFileSync(native.sdk.notice, path.join(out, 'licenses/microsoft/WebView2-SDK-LICENSE.txt'));
    lines.push('', '### 정적 링크된 Microsoft WebView2 SDK', '',
      '`webview2-com-sys 0.39.1`의 x64 `WebView2LoaderStatic.lib`는',
      'Microsoft.Web.WebView2 1.0.3800.47 NuGet 원본과 SHA-256이 일치한다.',
      '원본: https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3800.47',
      `SHA-256: \`${WEBVIEW2_LIB_SHA256}\`.`,
      'SDK 원문 고지: `licenses/microsoft/WebView2-SDK-LICENSE.txt`.', '');
  }
  if (native.sqliteSource) {
    lines.push('', '### 정적 링크된 SQLite', '',
      `\`libsqlite3-sys\`의 bundled SQLite ${native.sqliteSource.version} 소스를 링크한다.`,
      `소스 SHA-256: \`${native.sqliteSource.sha256}\`.`,
      'SQLite 원천은 공개영역이다: https://www.sqlite.org/copyright.html',
      'Rust 바인딩의 MIT 고지는 위 크레이트 표와 `licenses/rust/`에 있다.', '');
  }
  lines.push('', '## React/Node 웹 런타임 의존성', '',
    '| 패키지 | 버전 | 라이선스 |', '| --- | --- | --- |');
  writeNpmNotices(root, frontend, npmLock, out, lines);
  lines.push('', '## rhwp 렌더러·글꼴', '',
    'rhwp Studio JS/WASM의 원천은 `vendor/rhwp/source.json`에 고정한다.',
    '원문과 전이 의존성 고지는 `licenses/rhwp/LICENSE.txt`,',
    '`licenses/rhwp/THIRD_PARTY_LICENSES.txt`, `licenses/rhwp/FONTS.txt`,',
    '`licenses/rhwp/SourceHanSerifK-OFL.txt`,',
    '`licenses/rhwp/canvaskit-wasm-LICENSE.txt`에 동봉한다.',
    '앱 글꼴 고지는 `licenses/pretendard/OFL.txt`에 동봉한다.', '',
    '### 출하 글꼴 파일', '');
  const studio = JSON.parse(readFileSync(path.join(root, 'vendor/rhwp/studio-runtime.json'), 'utf8'));
  const fonts = studio.files.map(file => file.path).filter(name => name.startsWith('studio/fonts/'))
    .map(name => path.basename(name));
  const appFonts = readdirSync(path.join(root, 'frontend/fonts')).filter(name => name.endsWith('.woff2'));
  if (!fonts.length || !appFonts.length) throw new Error('Shipped font inventory is empty');
  for (const name of [...new Set([...fonts, ...appFonts])].sort()) lines.push(`- \`${name}\``);
  lines.push('', 'Latin Modern Math의 GUST Font License는 LaTeX Project Public License',
    '1.3c 이상 조건을 따른다. 출처: https://tug.org/fonts/licenses/GUST-FONT-LICENSE.txt', '',
    '```text',
    '% This is version 1.0, dated 22 June 2009, of the GUST Font License.',
    '% (GUST is the Polish TeX Users Group, http://www.gust.org.pl)',
    '%',
    '% For the most recent version of this license see',
    '% http://www.gust.org.pl/fonts/licenses/GUST-FONT-LICENSE.txt',
    '% or',
    '% http://tug.org/fonts/licenses/GUST-FONT-LICENSE.txt',
    '%',
    '% This work may be distributed and/or modified under the conditions',
    '% of the LaTeX Project Public License, either version 1.3c of this',
    '% license or (at your option) any later version.',
    '%',
    '% Please also observe the following clause:',
    '% 1) it is requested, but not legally required, that derived works be',
    '%    distributed only after changing the names of the fonts comprising this',
    '%    work and given in an accompanying "manifest", and that the',
    '%    files comprising the Work, as listed in the manifest, also be given',
    '%    new names. Any exceptions to this request are also given in the',
    '%    manifest.',
    '%',
    '%    We recommend the manifest be given in a separate file named',
    '%    MANIFEST-<fontid>.txt, where <fontid> is some unique identification',
    '%    of the font family. If a separate "readme" file accompanies the Work,',
    '%    we recommend a name of the form README-<fontid>.txt.',
    '%',
    '% The latest version of the LaTeX Project Public License is in',
    '% http://www.latex-project.org/lppl.txt and version 1.3c or later',
    '% is part of all distributions of LaTeX version 2006/05/20 or later.',
    '```', '',
    '## 이식한 소스', '',
    '`crates/hwpx-filler/src/field_induction_labels.rs`의 낱말 목록·정규식은',
    'kordoc v4.16.1 (commit 878b7009a97a1e7d0f37e304ad2046b6d7916818)에서',
    '옮겼다. 원천: https://github.com/chrisryugj/kordoc',
    'MIT License, Copyright (c) 2026 chrisryugj.',
    '원문 고지는 `licenses/rust/kordoc-LICENSE.txt`에 동봉한다.', '',
    '## 프로젝트 라이선스', '', '동봉 `LICENSE`를 따른다.', '');
  const kordocNotice = readFileSync(path.join(root, 'packaging/kordoc-LICENSE.txt'), 'utf8');
  if (!kordocNotice.startsWith('MIT License\n')) {
    throw new Error('kordoc source attribution notice missing');
  }
  writeFileSync(path.join(out, 'licenses/rust/kordoc-LICENSE.txt'), kordocNotice, 'utf8');
  writeFileSync(path.join(out, 'THIRD_PARTY_NOTICES'), `${lines.join('\n')}\n`, 'utf8');
  const seal = JSON.parse(readFileSync(path.join(web, 'web-artifact-seal.json'), 'utf8'));
  if (!/^[a-f0-9]{64}$/.test(seal.artifact_id) ||
      !/^[a-f0-9]{64}$/.test(seal.output?.tree_sha256)) {
    throw new Error('Sealed web identity is missing from notice input');
  }
  const lockHash = createHash('sha256').update(readFileSync(path.join(root, 'Cargo.lock')))
    .digest('hex');
  writeFileSync(path.join(out, 'native-notices.json'), `${JSON.stringify({
    schema_version: 1, cargo_lock_sha256: lockHash, artifact_id: seal.artifact_id,
    tree_sha256: seal.output.tree_sha256,
    rust_crates: crates.length, npm_packages: Object.keys(frontend).length,
    files: generatedNoticeHashes(out),
  }, null, 2)}\n`, 'utf8');
  return { rust: crates.length, npm: Object.keys(frontend).length };
}

export function generateCliNotices(root, out, metadata = cargoMetadata(root, true)) {
  if (existsSync(out)) throw new Error(`Refusing existing notice directory: ${out}`);
  const crates = runtimeCrates(metadata);
  if (crates.some(item => item.name === 'tauri' || item.name === 'webview2-com-sys')) {
    throw new Error('CLI no-default-features closure unexpectedly includes GUI runtime');
  }
  const native = nativeComponents(root, crates, metadata);
  const prepared = crates.map(item => {
    assertLicense(item);
    return [item, noticeFiles(item, root)];
  });
  mkdirSync(out, { recursive: true });
  const lines = [
    '# CLI 제3자 고지 (Third-Party Notices)', '',
    'Windows CLI의 Cargo.lock no-default-features normal 링크 의존성에서',
    '빌드 시 실행되는 proc macro를 제외해 유도했다.',
    '각 크레이트의 고지는 `licenses/rust/`에 동봉한다.', '',
    '| 크레이트 | 버전 | 라이선스 | 저자 | 고정 배포판 | 원천 저장소 | 고지 원천 |',
    '| --- | --- | --- | --- | --- | --- | --- |',
  ];
  writeCrateNotices(prepared, out, lines);
  if (native.sqliteSource) {
    lines.push('', '## 정적 링크된 SQLite', '',
      `SQLite ${native.sqliteSource.version} 소스 SHA-256: ${native.sqliteSource.sha256}.`,
      '원천 공개영역: https://www.sqlite.org/copyright.html', '');
  }
  const kordocNotice = readFileSync(path.join(root, 'packaging/kordoc-LICENSE.txt'), 'utf8');
  if (!kordocNotice.startsWith('MIT License\n')) {
    throw new Error('kordoc source attribution notice missing');
  }
  writeFileSync(path.join(out, 'licenses/rust/kordoc-LICENSE.txt'), kordocNotice);
  lines.push('', '## 이식한 소스', '',
    'kordoc v4.16.1, commit 878b7009a97a1e7d0f37e304ad2046b6d7916818.',
    '원천: https://github.com/chrisryugj/kordoc',
    '원문: `licenses/rust/kordoc-LICENSE.txt`.', '');
  writeFileSync(path.join(out, 'THIRD_PARTY_NOTICES'), `${lines.join('\n')}\n`);
  const lockHash = sha256File(path.join(root, 'Cargo.lock'));
  writeFileSync(path.join(out, 'native-notices.json'), `${JSON.stringify({
    schema_version: 1, kind: 'cli', cargo_lock_sha256: lockHash,
    rust_crates: crates.length, files: generatedNoticeHashes(out),
  }, null, 2)}\n`);
  return { rust: crates.length };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const cli = process.argv.length === 4 && process.argv[2] === '--cli-out';
    const gui = process.argv.length === 6 && process.argv[2] === '--web-root' &&
      process.argv[4] === '--out';
    if (!cli && !gui) {
      throw new Error('usage: generate_native_notices.mjs --web-root PATH --out DIR | --cli-out DIR');
    }
    const result = cli
      ? generateCliNotices(ROOT, path.resolve(process.argv[3]))
      : generateNotices(ROOT, path.resolve(process.argv[3]), path.resolve(process.argv[5]));
    process.stdout.write(`native notices: ${result.rust} Rust crates, ${result.npm ?? 0} npm packages\n`);
  } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
