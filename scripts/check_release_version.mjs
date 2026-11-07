/** Validate one release tag against the desktop package and its bundle version. */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function sectionVersion(source, section) {
  let current = '';
  const found = [];
  for (const raw of source.replace(/^\uFEFF/, '').split(/\r?\n/)) {
    const line = raw.trim();
    const header = /^\[([^\]]+)\]$/.exec(line);
    if (header) {
      current = header[1];
      continue;
    }
    if (current !== section || !/^version\s*=/.test(line)) continue;
    const value = /^version\s*=\s*"([^"\r\n]+)"\s*(?:#.*)?$/.exec(line);
    if (!value) throw new Error(`${section}.version 형식이 올바르지 않습니다`);
    found.push(value[1]);
  }
  if (found.length !== 1) throw new Error(`${section}.version 선언이 정확히 하나여야 합니다`);
  return found[0];
}

export function checkReleaseVersion(tag, root = ROOT) {
  if (typeof tag !== 'string' || !tag) throw new Error('release tag가 필요합니다');
  const cargo = sectionVersion(readFileSync(path.join(root, 'crates/hwpx-desktop/Cargo.toml'), 'utf8'), 'package');
  const tauri = JSON.parse(readFileSync(path.join(root, 'crates/hwpx-desktop/tauri.conf.json'), 'utf8')).version;
  if (tauri !== cargo) throw new Error(`Tauri version ${JSON.stringify(tauri)} 이 desktop package ${JSON.stringify(cargo)} 와 다릅니다`);
  const expected = `v${cargo}`;
  if (tag !== expected) throw new Error(`tag ${JSON.stringify(tag)} does not match project version ${JSON.stringify(expected)}`);
  return cargo;
}

export function isPrerelease(version) {
  // Cargo release versions use the PEP 440 release/pre/post/dev subset accepted
  // by the former packaging.version gate. Local labels do not affect this flag.
  const match = /^(?:\d+!)?\d+(?:\.\d+)*(?:[-_.]?(?:a|alpha|b|beta|rc|c|pre|preview)[-_.]?\d*)?(?:[-_.]?(?:post|rev|r)[-_.]?\d*)?(?:[-_.]?dev[-_.]?\d*)?(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?$/i.exec(version);
  if (!match) throw new Error(`지원하지 않는 release version: ${JSON.stringify(version)}`);
  const publicVersion = version.split('+', 1)[0];
  return /(?:^|\d)[-_.]?(?:a|alpha|b|beta|rc|c|pre|preview|dev)[-_.]?\d*(?=$|[-_.])/i.test(publicVersion);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length === 3) console.log(`release version: ${checkReleaseVersion(process.argv[2])}`);
    else if (process.argv.length === 4 && process.argv[2] === '--prerelease') {
      console.log(String(isPrerelease(checkReleaseVersion(process.argv[3]))));
    } else throw new Error('사용법: node scripts/check_release_version.mjs [--prerelease] vX.Y.Z');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
  }
}
