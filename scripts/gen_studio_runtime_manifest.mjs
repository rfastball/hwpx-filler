/** Regenerate or verify the tracked Studio runtime pin from build/rhwp/studio. */
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function filesUnder(root, directory = root) {
  const files = [];
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    const link = lstatSync(path);
    const info = link.isSymbolicLink() ? statSync(path) : link;
    if (info.isDirectory() && !link.isSymbolicLink()) {
      files.push(...filesUnder(root, path));
    } else if (info.isFile()) {
      files.push(path);
    }
  }
  return files;
}

export function buildManifest(outputDir, sourceCommit) {
  const files = filesUnder(outputDir).map(path => {
    const part = relative(outputDir, path).split(sep).join('/');
    if (part.toLowerCase().endsWith('.map')) {
      throw new Error(`source map must not ship with the Studio runtime: ${part}`);
    }
    const bytes = readFileSync(path);
    return {
      path: `studio/${part}`,
      size: bytes.length,
      sha256: createHash('sha256').update(bytes).digest('hex'),
    };
  }).sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  if (!files.some(item => item.path === 'studio/index.html')) {
    throw new Error(`Studio output has no index.html: ${outputDir}`);
  }
  return { schema: 1, source_commit: sourceCommit, files };
}

export function run({ root = ROOT, check = false, log = console.log, error = console.error } = {}) {
  const outputDir = join(root, 'build', 'rhwp', 'studio');
  const source = join(root, 'vendor', 'rhwp', 'source.json');
  const target = join(root, 'vendor', 'rhwp', 'studio-runtime.json');
  if (!existsSync(outputDir)) {
    error(`Studio output missing; run scripts/build_rhwp.ps1 first: ${outputDir}`);
    return 1;
  }
  const commit = JSON.parse(readFileSync(source, 'utf8')).commit;
  if (typeof commit !== 'string' || !/^[0-9a-f]{40}$/i.test(commit)) {
    throw new Error(`${source} has no valid commit`);
  }
  const manifest = buildManifest(outputDir, commit);
  if (check) {
    let existing;
    try {
      existing = JSON.parse(readFileSync(target, 'utf8'));
    } catch (cause) {
      error(`${target} unreadable: ${cause}`);
      return 1;
    }
    if (!isDeepStrictEqual(existing, manifest)) {
      error(`${target} differs from ${outputDir}`);
      return 1;
    }
    log(`${target} matches ${manifest.files.length} files`);
    return 0;
  }
  writeFileSync(target, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  log(`wrote ${target} (${manifest.files.length} files)`);
  return 0;
}

export function main(args = process.argv.slice(2), options = {}) {
  if (args.length === 1 && args[0] === '--help') {
    (options.log ?? console.log)('usage: node scripts/gen_studio_runtime_manifest.mjs [--check]');
    return 0;
  }
  if (args.length > 1 || (args.length === 1 && args[0] !== '--check')) {
    (options.error ?? console.error)('usage: node scripts/gen_studio_runtime_manifest.mjs [--check]');
    return 1;
  }
  try {
    return run({ ...options, check: args[0] === '--check' });
  } catch (cause) {
    (options.error ?? console.error)(cause.message);
    return 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}
