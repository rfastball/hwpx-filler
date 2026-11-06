// Read repository TOML with the pinned Rust parser already used by native tooling.
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let parserExecutable;
const parsed = new Map();

function isFresh(executable) {
  const inputs = ['crates/hwpx-artifact/examples/read_toml.rs',
    'crates/hwpx-artifact/Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml'];
  return existsSync(executable) && inputs.every(name =>
    statSync(executable).mtimeMs >= statSync(path.join(root, name)).mtimeMs);
}

function cargoEnvironment() {
  const env = { ...process.env };
  const localCargo = path.join(root, '.cache/rhwp-cargo/bin/cargo.exe');
  if (existsSync(localCargo) && !env.CARGO_HOME) {
    env.CARGO_HOME = path.join(root, '.cache/rhwp-cargo');
    env.RUSTUP_HOME ??= path.join(root, '.cache/rhwp-rustup');
    env.PATH = `${path.dirname(localCargo)}${path.delimiter}${env.PATH ?? ''}`;
  }
  return env;
}

function parser() {
  if (parserExecutable) return parserExecutable;
  const env = cargoEnvironment();
  const executable = path.resolve(root, env.CARGO_TARGET_DIR ?? 'target', 'debug', 'examples',
    `read_toml${process.platform === 'win32' ? '.exe' : ''}`);
  if (isFresh(executable)) return (parserExecutable = executable);
  const result = spawnSync('cargo', [
    'build', '--quiet', '--offline', '--locked',
    '-p', 'hwpx-artifact', '--example', 'read_toml',
  ], { cwd: root, env, encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`TOML parser failed: ${result.stderr}`);
  parserExecutable = executable;
  if (!existsSync(parserExecutable)) throw new Error(`TOML parser binary missing: ${parserExecutable}`);
  return parserExecutable;
}

export function readToml(file, { cwd = root } = {}) {
  const target = path.resolve(cwd, file);
  const source = readFileSync(target, 'utf8');
  const previous = parsed.get(target);
  if (previous?.source === source) return structuredClone(previous.value);
  const value = parseTomlText(source);
  parsed.set(target, { source, value });
  return structuredClone(value);
}

export function parseTomlText(source) {
  const result = spawnSync(parser(), [], {
    cwd: root, input: source, encoding: 'utf8', maxBuffer: 4 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`TOML parser failed: ${result.stderr}`);
  return JSON.parse(result.stdout);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 3 || process.argv[2] !== '--prepare') {
    process.stderr.write('usage: node scripts/read_toml.mjs --prepare\n');
    process.exitCode = 2;
  } else {
    try { parser(); }
    catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
  }
}
