import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, cpSync, existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { generateCliNotices, generateNotices, runtimeCrates } from '../../scripts/generate_native_notices.mjs';
import { verifyCliBundle } from '../../scripts/verify_cli_bundle.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

test('pinned rhwp notice sources and shipped font inventory are present', () => {
  const source = JSON.parse(readFileSync(path.join(repo, 'vendor/rhwp/source.json'), 'utf8'));
  const runtime = JSON.parse(readFileSync(path.join(repo, 'vendor/rhwp/studio-runtime.json'), 'utf8'));
  assert.equal(runtime.source_commit, source.commit);
  for (const relative of [source.licenseFile, source.thirdPartyLicenses,
    ...source.fontNotices, ...source.bundledNpmLicenses]) {
    assert.ok(existsSync(path.join(repo, relative)), relative);
  }
  assert.match(readFileSync(path.join(repo, source.thirdPartyLicenses), 'utf8'),
    /^# Third-Party Licenses/);
  const studioPaths = runtime.files.map(file => file.path);
  assert.ok(studioPaths.some(file => /\/canvaskit-[^/]+\.wasm$/.test(file)));
  assert.ok(studioPaths.some(file => /\/rhwp_bg-[^/]+\.wasm$/.test(file)));
  assert.ok(studioPaths.some(file => file.startsWith('studio/fonts/') && file.endsWith('.woff2')));
  assert.ok(readdirSync(path.join(repo, 'frontend/fonts')).some(file => file.endsWith('.woff2')));
});

test('native notice closure follows only shipped normal edges and refuses unknown licenses', () => {
  const temp = mkdtempSync(path.join(repo, '.cache', 'native-notices-owner-'));
  try {
    const crate = path.join(temp, 'registry', 'example-1.0.0');
    const web = path.join(temp, 'web');
    mkdirSync(crate, { recursive: true });
    mkdirSync(web);
    writeFileSync(path.join(crate, 'Cargo.toml'), '[package]\nname="example"\n');
    writeFileSync(path.join(crate, 'LICENSE-MIT'), 'Copyright Example\nMIT License\n');
    writeFileSync(path.join(web, 'entry.js'), '//#region node_modules/react/index.js\r\n');
    writeFileSync(path.join(web, 'web-artifact-seal.json'), JSON.stringify({
      artifact_id: 'a'.repeat(64), output: { tree_sha256: 'b'.repeat(64) },
    }));
    copyFileSync(path.join(repo, 'Cargo.lock'), path.join(temp, 'Cargo.lock'));
    writeFileSync(path.join(temp, 'package-lock.json'), JSON.stringify({ packages: {
      'node_modules/react': { version: '19.2.8', license: 'MIT' },
    } }));
    mkdirSync(path.join(temp, 'node_modules/react'), { recursive: true });
    writeFileSync(path.join(temp, 'node_modules/react/LICENSE'), 'Copyright React\nMIT License\n');
    mkdirSync(path.join(temp, 'vendor/rhwp'), { recursive: true });
    writeFileSync(path.join(temp, 'vendor/rhwp/studio-runtime.json'),
      JSON.stringify({ files: [{ path: 'studio/fonts/Example.woff2' }] }));
    mkdirSync(path.join(temp, 'frontend/fonts'), { recursive: true });
    writeFileSync(path.join(temp, 'frontend/fonts/App.woff2'), 'font');
    mkdirSync(path.join(temp, 'packaging'), { recursive: true });
    writeFileSync(path.join(temp, 'packaging/kordoc-LICENSE.txt'), 'MIT License\n');
    const pkg = { id: 'registry-example', name: 'example', version: '1.0.0',
      source: 'registry+https://index.crates.io/', license: 'MIT', authors: ['Example'],
      repository: 'https://example.test/source', manifest_path: path.join(crate, 'Cargo.toml') };
    const metadata = { packages: [{ id: 'desktop', name: 'hwpx-desktop' }, pkg,
      { ...pkg, id: 'build-only', name: 'build-only' },
      { ...pkg, id: 'macro', name: 'macro', targets: [{ kind: ['proc-macro'] }] },
      { ...pkg, id: 'macro-helper', name: 'macro-helper' }], resolve: { nodes: [
      { id: 'desktop', deps: [
        { pkg: pkg.id, dep_kinds: [{ kind: null }] },
        { pkg: 'build-only', dep_kinds: [{ kind: 'build' }] },
        { pkg: 'macro', dep_kinds: [{ kind: null }] },
      ] },
      { id: pkg.id, deps: [] }, { id: 'build-only', deps: [] },
      { id: 'macro', deps: [{ pkg: 'macro-helper', dep_kinds: [{ kind: null }] }] },
      { id: 'macro-helper', deps: [] },
    ] } };
    assert.deepEqual(runtimeCrates(metadata).map(item => item.name), ['example']);
    const output = path.join(temp, 'output');
    assert.deepEqual(generateNotices(temp, web, output, metadata), { rust: 1, npm: 1 });
    const text = readFileSync(path.join(output, 'THIRD_PARTY_NOTICES'), 'utf8');
    assert.match(text, /example \| 1\.0\.0 \| MIT/);
    assert.doesNotMatch(text, /build-only/);
    assert.match(text, /react \| 19\.2\.8 \| MIT/);
    assert.match(text, /`Example\.woff2`/);
    assert.match(text, /`App\.woff2`/);
    assert.equal(readFileSync(path.join(output, 'licenses/rust/example-1.0.0/LICENSE-MIT'), 'utf8'),
      'Copyright Example\nMIT License\n');
    assert.equal(readFileSync(path.join(output, 'licenses/npm/react/LICENSE'), 'utf8'),
      'Copyright React\nMIT License\n');
    const noticeManifest = JSON.parse(readFileSync(path.join(output, 'native-notices.json'), 'utf8'));
    assert.equal(noticeManifest.artifact_id, 'a'.repeat(64));
    assert.equal(noticeManifest.schema_version, 1);
    assert.ok(noticeManifest.files.some(file => file.path ===
      'licenses/rust/example-1.0.0/LICENSE-MIT'));
    assert.throws(() => generateNotices(temp, web, path.join(temp, 'unknown'),
      { ...metadata, packages: metadata.packages.map(item => item.id === pkg.id
        ? { ...item, license: 'GPL-3.0-only' } : item) }),
    /requires review/);

    const familyDir = path.join(temp, 'registry/alloc-stdlib-0.3.0');
    const upstreamDir = path.join(temp, 'packaging/native-notice-sources');
    mkdirSync(familyDir);
    mkdirSync(upstreamDir, { recursive: true });
    writeFileSync(path.join(familyDir, 'Cargo.toml'), '[package]\nname="alloc-stdlib"\n');
    const revision = '0a81fd6928ea3b33c8cd484aa4575d50ffb98012';
    writeFileSync(path.join(familyDir, '.cargo_vcs_info.json'),
      JSON.stringify({ git: { sha1: revision } }));
    copyFileSync(path.join(repo, 'packaging/native-notice-sources/alloc-stdlib-LICENSE'),
      path.join(upstreamDir, 'alloc-stdlib-LICENSE'));
    const family = { ...pkg, name: 'alloc-stdlib', version: '0.3.0',
      license: 'BSD-3-Clause', manifest_path: path.join(familyDir, 'Cargo.toml') };
    const familyMetadata = { ...metadata, packages: metadata.packages.map(item =>
      item.id === pkg.id ? family : item) };
    const familyOut = path.join(temp, 'family');
    generateNotices(temp, web, familyOut, familyMetadata);
    assert.equal(readFileSync(path.join(familyOut, 'licenses/rust/alloc-stdlib-0.3.0/LICENSE'), 'utf8'),
      readFileSync(path.join(upstreamDir, 'alloc-stdlib-LICENSE'), 'utf8'));
    assert.match(readFileSync(path.join(familyOut, 'THIRD_PARTY_NOTICES'), 'utf8'),
      /dropbox\/rust-alloc-no-stdlib\/tree\/0a81fd69/);
    const cliOut = path.join(temp, 'cli');
    assert.deepEqual(generateCliNotices(temp, cliOut, metadata), { rust: 1 });
    const cliManifest = JSON.parse(readFileSync(path.join(cliOut, 'native-notices.json'), 'utf8'));
    assert.equal(cliManifest.kind, 'cli');
    assert.equal(cliManifest.rust_crates, 1);
    assert.equal(cliManifest.artifact_id, undefined);
    assert.match(readFileSync(path.join(cliOut, 'THIRD_PARTY_NOTICES'), 'utf8'),
      /example \| 1\.0\.0 \| MIT/);
    const bundle = path.join(temp, 'cli-bundle');
    mkdirSync(bundle);
    cpSync(path.join(cliOut, 'licenses'), path.join(bundle, 'licenses'), { recursive: true });
    for (const name of ['native-notices.json', 'THIRD_PARTY_NOTICES']) {
      copyFileSync(path.join(cliOut, name), path.join(bundle, name));
    }
    writeFileSync(path.join(bundle, 'LICENSE'), 'app license');
    writeFileSync(path.join(bundle, 'hwpx-cli.exe'), 'native binary');
    writeFileSync(path.join(bundle, 'build-metadata.json'), JSON.stringify({
      cargo_lock_sha256: cliManifest.cargo_lock_sha256,
      version: readFileSync(path.join(repo, 'crates/hwpx-desktop/Cargo.toml'), 'utf8')
        .match(/^version\s*=\s*"([^"]+)"/m)[1],
      rust: readFileSync(path.join(repo, 'rust-toolchain.toml'), 'utf8')
        .match(/^channel\s*=\s*"([^"]+)"/m)[1],
      commit: spawnSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).stdout.trim(),
      web: { present: false, reason: 'CLI bundle has no web data' },
    }));
    assert.equal(verifyCliBundle(repo, bundle).rust_crates, 1);
    writeFileSync(path.join(bundle, 'licenses/rust/example-1.0.0/LICENSE-MIT'), 'mutated');
    assert.throws(() => verifyCliBundle(repo, bundle), /CLI notice bytes differ/);
    writeFileSync(path.join(bundle, 'native-notices.json'), JSON.stringify({
      ...cliManifest,
      files: [{ path: 'licenses/rust/..\\..\\outside', sha256: '0'.repeat(64) }],
    }));
    assert.throws(() => verifyCliBundle(repo, bundle), /CLI notice manifest entry is invalid/);
    writeFileSync(path.join(familyDir, '.cargo_vcs_info.json'),
      JSON.stringify({ git: { sha1: 'wrong' } }));
    assert.throws(() => generateNotices(temp, web, path.join(temp, 'stale-family'), familyMetadata),
      /commit changed/);
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});
