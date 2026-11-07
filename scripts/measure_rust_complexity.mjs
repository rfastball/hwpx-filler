// Parse every owned Rust source with the pinned syn AST helper.
import { spawnSync } from 'node:child_process';
import { existsSync, globSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const inputs = [
  'crates/hwpx-artifact/examples/complexity_axes.rs',
  'crates/hwpx-artifact/Cargo.toml',
  'Cargo.lock',
  'rust-toolchain.toml',
];

function cargoEnvironment() {
  const env = { ...process.env };
  const localCargo = path.join(root, '.cache/rhwp-cargo/bin/cargo.exe');
  if (existsSync(localCargo) && !env.CARGO_HOME) {
    env.CARGO_HOME = path.join(root, '.cache/rhwp-cargo');
    env.RUSTUP_HOME ??= path.join(root, '.cache/rhwp-rustup');
    env.PATH = path.dirname(localCargo) + path.delimiter + (env.PATH ?? '');
  }
  return env;
}

export function targetExecutable(targetDir = 'target') {
  return path.resolve(root, targetDir, 'debug', 'examples',
    'complexity_axes' + (process.platform === 'win32' ? '.exe' : ''));
}

function executable(env) {
  const binary = targetExecutable(env.CARGO_TARGET_DIR ?? 'target');
  if (existsSync(binary) && inputs.every(name =>
    statSync(binary).mtimeMs >= statSync(path.join(root, name)).mtimeMs)) return binary;
  const build = spawnSync('cargo', [
    'build', '--quiet', '--offline', '--locked', '-p', 'hwpx-artifact',
    '--example', 'complexity_axes',
  ], { cwd: root, env, encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
  if (build.error) throw build.error;
  if (build.status !== 0) throw new Error('Rust AST helper build failed:\n' + build.stderr);
  if (!existsSync(binary)) throw new Error('Rust AST helper missing: ' + binary);
  return binary;
}

export function rustFiles() {
  const files = [
    ...globSync('crates/*/src/**/*.rs', { cwd: root }),
    ...globSync('crates/*/build.rs', { cwd: root }),
    ...globSync('crates/*/examples/**/*.rs', { cwd: root }),
    ...globSync('crates/*/tests/**/*.rs', { cwd: root }),
  ].map(name => name.replaceAll('\\', '/')).sort();
  if (!files.length) throw new Error('no Rust sources found');
  return files;
}

export function measureRust() {
  const env = cargoEnvironment();
  const result = spawnSync(executable(env), [], {
    cwd: root,
    env,
    input: JSON.stringify({ root, files: rustFiles() }),
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error('Rust AST measurement failed:\n' + result.stderr);
  return JSON.parse(result.stdout);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 2) {
    process.stderr.write('usage: node scripts/measure_rust_complexity.mjs\n');
    process.exitCode = 2;
  } else {
    try { process.stdout.write(JSON.stringify(measureRust()) + '\n'); }
    catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 1; }
  }
}
