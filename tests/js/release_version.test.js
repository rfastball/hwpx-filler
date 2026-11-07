import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { checkReleaseVersion, isPrerelease } from '../../scripts/check_release_version.mjs';

test('release tag requires the exact desktop and Tauri version', () => {
  const base = path.resolve('.cache');
  mkdirSync(base, { recursive: true });
  const root = mkdtempSync(path.join(base, 'release-version-'));
  try {
    const desktop = path.join(root, 'crates/hwpx-desktop');
    mkdirSync(desktop, { recursive: true });
    writeFileSync(path.join(desktop, 'Cargo.toml'), '[package]\nname = "hwpx-desktop"\nversion = "0.15.0"\n');
    writeFileSync(path.join(desktop, 'tauri.conf.json'), '{"version":"0.15.0"}');
    assert.equal(checkReleaseVersion('v0.15.0', root), '0.15.0');
    assert.throws(() => checkReleaseVersion('v0.15.1', root), /does not match/);
    writeFileSync(path.join(desktop, 'tauri.conf.json'), '{"version":"0.15.1"}');
    assert.throws(() => checkReleaseVersion('v0.15.0', root), /Tauri version/);
    writeFileSync(path.join(desktop, 'tauri.conf.json'), '{"version":"0.15.0"}');
    writeFileSync(path.join(desktop, 'Cargo.toml'), '[package]\nversion = "0.15.0"\nversion = "0.15.0"\n');
    assert.throws(() => checkReleaseVersion('v0.15.0', root), /정확히 하나/);
    for (const version of ['0.15.0', '0.15.0-post1', '0.15.0+rc1']) {
      assert.equal(isPrerelease(version), false, version);
    }
    for (const version of ['0.15.0rc1', '0.15.0-rc1', '0.15.0.rc1', '0.15.0_rc1', '0.15.0-rc.1', '0.15.0.dev2']) {
      assert.equal(isPrerelease(version), true, version);
    }
    assert.throws(() => isPrerelease('0.15.0-unknown'), /지원하지 않는/);
  } finally {
    if (!root.startsWith(`${base}${path.sep}`)) throw new Error('test cleanup escaped workspace cache');
    rmSync(root, { recursive: true, force: true });
  }
});
