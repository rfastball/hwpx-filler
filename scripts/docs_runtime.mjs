// Declared toolchain and entrypoint facts for the generated runtime reference.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { readToml } from './read_toml.mjs';

export function environmentDeclarations(root) {
  const desktop = readToml('crates/hwpx-desktop/Cargo.toml', { cwd: root });
  const packageJson = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
  const toolchain = readToml('rust-toolchain.toml', { cwd: root }).toolchain;
  const workspace = readToml('Cargo.toml', { cwd: root }).workspace;
  const rows = [
    ['제품 버전', desktop.package.version, 'crates/hwpx-desktop/Cargo.toml'],
    ['Node pin', readFileSync(path.join(root, '.node-version'), 'utf8').trim(), '.node-version'],
    ['Node engine', packageJson.engines.node, 'package.json'],
    ['npm engine', packageJson.engines.npm, 'package.json'],
    ['package manager', packageJson.packageManager, 'package.json'],
    ['Rust pin', toolchain.channel, 'rust-toolchain.toml'],
    ['Rust components', toolchain.components.join(', '), 'rust-toolchain.toml'],
    ['Cargo workspace', workspace.members.join(', '), 'Cargo.toml'],
  ];
  return [desktop, rows];
}
