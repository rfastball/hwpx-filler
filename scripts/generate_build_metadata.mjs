#!/usr/bin/env node
// Describe the exact native build plan and its verified web artifact.
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readToml } from './read_toml.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (root, name) => readFileSync(path.join(root, name), 'utf8');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

export function numericVersion(version) {
  const head = /^\d+(?:\.\d+)*/.exec(version)?.[0];
  if (!head) throw new Error(`버전에서 숫자 부분을 찾을 수 없습니다: ${version}`);
  const parts = head.split('.').map(Number);
  if (parts.length > 4 || parts.some(part => !Number.isSafeInteger(part) || part > 65535)) {
    throw new Error(`Windows 버전은 0..65535 숫자 4개 이하여야 합니다: ${version}`);
  }
  return [...parts, 0, 0, 0, 0].slice(0, 4).join('.');
}

export function vendorPackageName(region) {
  const tail = region.split('node_modules/').at(-1);
  const parts = tail.split('/');
  return parts[0].startsWith('@') ? `${parts[0]}/${parts[1]}` : parts[0];
}

export function runtimePackages(root, artifactRoot) {
  const names = new Set();
  const walk = directory => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile() && entry.name.endsWith('.js')) {
        const text = readFileSync(full, 'utf8');
        for (const match of text.matchAll(/^\/\/#region node_modules\/([^\r\n]+?)\r?$/gm)) {
          names.add(vendorPackageName(`node_modules/${match[1]}`));
        }
      }
    }
  };
  walk(artifactRoot);
  if (!names.size) throw new Error('출하 번들에서 런타임 패키지 경계를 하나도 찾지 못했습니다.');
  const locked = JSON.parse(read(root, 'package-lock.json')).packages;
  return Object.fromEntries([...names].sort().map(name => {
    const version = locked?.[`node_modules/${name}`]?.version;
    if (!version) throw new Error(`출하 런타임 패키지의 lock 항목을 찾지 못했습니다: ${name}`);
    return [name, version];
  }));
}

function verifiedIdentity(root) {
  const tempRoot = path.join(root, '.cache');
  mkdirSync(tempRoot, { recursive: true });
  const temp = mkdtempSync(path.join(tempRoot, 'native-metadata-'));
  try {
    const output = path.join(temp, 'identity.json');
    const shell = process.platform === 'win32' ? 'powershell.exe' : 'pwsh';
    const result = spawnSync(shell, ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
      path.join(root, 'scripts/run_web_artifact.ps1'), '-Verify', '--repo-root', root,
      '--json-out', output], { cwd: root, encoding: 'utf8', maxBuffer: 1024 * 1024 });
    if (result.error || result.status !== 0 || !existsSync(output)) {
      throw new Error(`sealed web artifact 를 요구했지만 검증에 실패했습니다: ${result.stderr || result.error}`);
    }
    return JSON.parse(readFileSync(output, 'utf8'));
  } finally { rmSync(temp, { recursive: true, force: true }); }
}

export function webMetadata(root, plan, verify = verifiedIdentity) {
  if (plan.kind === 'no-web') return { present: false, reason: plan.reason };
  const identity = verify(root);
  const seal = JSON.parse(read(root, 'build/web/web-artifact-seal.json'));
  if (identity.artifact_id !== seal.artifact_id ||
      identity.tree_sha256 !== seal.output?.tree_sha256 ||
      identity.source_commit !== seal.source?.commit) {
    throw new Error('sealed web identity 가 검증기와 seal 사이에서 달라졌습니다.');
  }
  return {
    present: true,
    artifact_id: identity.artifact_id,
    tree_sha256: identity.tree_sha256,
    source_commit: identity.source_commit,
    package_lock_sha256: seal.package_lock.sha256,
    toolchain: seal.toolchain,
    runtime_packages: runtimePackages(root, path.join(root, 'build/web')),
  };
}

export function parseArgs(args) {
  const state = { out: path.join(ROOT, 'build/version'), plan: undefined };
  for (let at = 0; at < args.length; at++) {
    at = parseOption(args, at, state);
  }
  if (!state.plan || (state.plan.kind === 'no-web' && !state.plan.reason.trim())) {
    throw new Error('--require-web 또는 사유가 있는 --no-web 이 필요합니다.');
  }
  return state;
}

function parseOption(args, at, state) {
  const flag = args[at];
  if (flag === '--out') {
    state.out = path.resolve(requiredValue(args, at, flag));
    return at + 1;
  }
  if (flag === '--require-web' && !state.plan) {
    state.plan = { kind: 'require-web' };
    return at;
  }
  if (flag === '--no-web' && !state.plan) {
    state.plan = { kind: 'no-web', reason: requiredValue(args, at, flag) };
    return at + 1;
  }
  throw new Error('usage: generate_build_metadata.mjs [--out DIR] (--require-web | --no-web REASON)');
}

function requiredValue(args, at, flag) {
  const value = args[at + 1];
  if (!value || value.startsWith('--')) throw new Error(`${flag} 값이 필요합니다.`);
  return value;
}

export function generate(root, out, plan, verify = verifiedIdentity) {
  const version = readToml('crates/hwpx-desktop/Cargo.toml', { cwd: root }).package.version;
  const rust = readToml('rust-toolchain.toml', { cwd: root }).toolchain.channel;
  const commit = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' });
  if (commit.error || commit.status !== 0 || !/^[a-f0-9]{40}\s*$/.test(commit.stdout)) {
    throw new Error('Git source commit 을 확인할 수 없습니다.');
  }
  const metadata = {
    version,
    commit: commit.stdout.trim(),
    rust,
    cargo_lock_sha256: hash(readFileSync(path.join(root, 'Cargo.lock'))),
    web: webMetadata(root, plan, verify),
  };
  const windowsVersion = numericVersion(version);
  mkdirSync(out, { recursive: true });
  writeFileSync(path.join(out, 'version.iss'),
    `#define AppVersion "${version}"\n#define AppVersionInfo "${windowsVersion}"\n`, 'utf8');
  writeFileSync(path.join(out, 'build-metadata.json'), `${JSON.stringify(metadata, null, 2)}\n`, 'utf8');
  return metadata;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const { out, plan } = parseArgs(process.argv.slice(2));
    const metadata = generate(ROOT, out, plan);
    process.stdout.write(`build metadata: ${metadata.version} -> ${out}\n`);
  } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
