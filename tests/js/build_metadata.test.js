import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { generate, parseArgs, runtimePackages, vendorPackageName, webMetadata } from '../../scripts/generate_build_metadata.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const fixtureRoot = () => {
  const cache = path.join(root, '.cache');
  mkdirSync(cache, { recursive: true });
  return cache;
};

test('declared build plan controls native metadata and cannot be guessed from a stale web tree', () => {
  assert.throws(() => parseArgs([]), /--require-web.*--no-web/);
  assert.throws(() => parseArgs(['--require-web', '--no-web', 'x']), /usage:/);
  assert.throws(() => parseArgs(['--no-web', '   ']), /사유/);
  assert.throws(() => parseArgs(['--out', '--require-web']), /값이 필요/);
  assert.throws(() => parseArgs(['--unknown', '--no-web', 'x']), /usage:/);
  const fixture = mkdtempSync(path.join(fixtureRoot(), 'native-metadata-owner-'));
  try {
    const out = path.join(fixture, 'output');
    const metadata = generate(root, out, { kind: 'no-web', reason: 'cli-only build' });
    assert.deepEqual(metadata.web, { present: false, reason: 'cli-only build' });
    assert.equal(metadata.cargo_lock_sha256, digest(readFileSync(path.join(root, 'Cargo.lock'))));
    assert.match(readFileSync(path.join(out, 'version.iss'), 'utf8'), /#define AppVersionInfo "0\.15\.0\.0"/);
    assert.deepEqual(JSON.parse(readFileSync(path.join(out, 'build-metadata.json'), 'utf8')), metadata);
  } finally {
    rmSync(fixture, { recursive: true, force: true });
  }
});

test('required seal and shipped lazy chunks stay explicit', () => {
  assert.throws(() => webMetadata(root, { kind: 'require-web' }, () => {
    throw new Error('missing seal');
  }), /missing seal/);
  const fixture = mkdtempSync(path.join(fixtureRoot(), 'native-runtime-owner-'));
  try {
    const assets = path.join(fixture, 'assets');
    mkdirSync(assets);
    writeFileSync(path.join(assets, 'main.js'), '//#region node_modules/react/index.js\r\n');
    writeFileSync(path.join(assets, 'lazy.js'), '//#region node_modules/scheduler/index.js\n');
    assert.deepEqual(Object.keys(runtimePackages(root, fixture)), ['react', 'scheduler']);
    assert.equal(vendorPackageName('react-dom/node_modules/@scope/pkg/index.js'), '@scope/pkg');
    writeFileSync(path.join(assets, 'lazy.js'), '//#region node_modules/ghost-lib/index.js\n');
    assert.throws(() => runtimePackages(root, fixture), /lock 항목을 찾지 못했습니다: ghost-lib/);
    writeFileSync(path.join(assets, 'main.js'), 'const loaded = true;\n');
    writeFileSync(path.join(assets, 'lazy.js'), 'const lazy = true;\n');
    assert.throws(() => runtimePackages(root, fixture), /경계를 하나도 찾지 못했습니다/);
  } finally {
    rmSync(fixture, { recursive: true, force: true });
  }
});
