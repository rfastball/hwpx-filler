#!/usr/bin/env node
// Verify the independent no-web CLI release copy and its complete notice tree.
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { lstatSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const sha256 = file => createHash('sha256').update(readFileSync(file)).digest('hex');
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);

function filesUnder(root) {
  const rootStat = lstatSync(root);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
    throw new Error('CLI bundle root is not a regular directory');
  }
  const result = [];
  function walk(folder) {
    for (const name of readdirSync(folder)) {
      const full = path.join(folder, name);
      const stat = lstatSync(full);
      if (stat.isSymbolicLink()) throw new Error(`CLI link refused: ${full}`);
      if (stat.isDirectory()) walk(full);
      else if (stat.isFile()) result.push(path.relative(root, full).split(path.sep).join('/'));
      else throw new Error(`CLI non-file refused: ${full}`);
    }
  }
  walk(root);
  return result.sort();
}

function verifyMetadata(root, manifest, metadata) {
  const lockHash = sha256(path.join(root, 'Cargo.lock'));
  const version = readFileSync(path.join(root, 'crates/hwpx-desktop/Cargo.toml'), 'utf8')
    .match(/^version\s*=\s*"([^"]+)"/m)?.[1];
  const rust = readFileSync(path.join(root, 'rust-toolchain.toml'), 'utf8')
    .match(/^channel\s*=\s*"([^"]+)"/m)?.[1];
  const commitResult = spawnSync('git', ['rev-parse', 'HEAD'],
    { cwd: root, encoding: 'utf8' });
  const commit = commitResult.status === 0 ? commitResult.stdout.trim() : null;
  if (!version || !rust || !/^[a-f0-9]{40}(?:[a-f0-9]{24})?$/.test(commit ?? '')) {
    throw new Error('CLI source version, toolchain, or commit is unavailable');
  }
  for (const [observed, expected] of [
    [manifest.schema_version, 1], [manifest.kind, 'cli'],
    [manifest.cargo_lock_sha256, lockHash],
    [metadata.cargo_lock_sha256, lockHash],
    [metadata.web?.present, false], [metadata.version, version],
    [metadata.rust, rust], [metadata.commit, commit],
  ]) {
    if (observed !== expected) throw new Error('CLI bundle metadata or lock identity differs');
  }
  verifyManifestShape(manifest, metadata);
  return lockHash;
}

function verifyManifestShape(manifest, metadata) {
  if (typeof metadata.web?.reason !== 'string' || !metadata.web.reason ||
      !Array.isArray(manifest.files) || !Number.isSafeInteger(manifest.rust_crates) ||
      manifest.rust_crates < 1) throw new Error('CLI bundle metadata or lock identity differs');
}

function validNoticePath(item) {
  return typeof item.path === 'string' &&
    /^(?:licenses\/rust\/[A-Za-z0-9._/-]+|THIRD_PARTY_NOTICES)$/.test(item.path) &&
    !item.path.split('/').some(part => part === '..' || part === '.' || part === '') &&
    /^[a-f0-9]{64}$/.test(item.sha256);
}

export function verifyCliBundle(root, bundle) {
  const actual = filesUnder(bundle);
  const manifest = JSON.parse(readFileSync(path.join(bundle, 'native-notices.json')));
  const metadata = JSON.parse(readFileSync(path.join(bundle, 'build-metadata.json')));
  const lockHash = verifyMetadata(root, manifest, metadata);
  function verifyNotices() {
    const notices = manifest.files.map(item => {
    if (!validNoticePath(item)) {
      throw new Error('CLI notice manifest entry is invalid');
    }
    const full = path.resolve(bundle, item.path);
    const boundary = `${path.resolve(bundle)}${path.sep}`;
    if (!full.toLowerCase().startsWith(boundary.toLowerCase()) ||
        !lstatSync(full).isFile() || lstatSync(full).isSymbolicLink() ||
        sha256(full) !== item.sha256) {
      throw new Error(`CLI notice bytes differ: ${item.path}`);
    }
    return item.path;
    }).sort();
    return notices;
  }
  const notices = verifyNotices();
  const expected = [...notices, 'native-notices.json', 'build-metadata.json',
    'LICENSE', 'hwpx-cli.exe'].sort();
  if (!same(actual, expected)) throw new Error('CLI bundle file closure differs');
  return { cargo_lock_sha256: lockHash, rust_crates: manifest.rust_crates };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length !== 4) throw new Error('usage: verify_cli_bundle.mjs ROOT BUNDLE');
    const result = verifyCliBundle(path.resolve(process.argv[2]), path.resolve(process.argv[3]));
    process.stdout.write(`CLI bundle verified: ${result.rust_crates} Rust crates\n`);
  } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
