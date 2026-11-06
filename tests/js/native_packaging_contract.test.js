import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { encodeIco, icoSizes, tierFor } from '../../scripts/render_document_narmi_branding.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = name => readFileSync(path.join(root, name), 'utf8');

test('PowerShell sources remain UTF-8 in Windows PowerShell 5.1', () => {
  const result = spawnSync('git', ['ls-files', '--cached', '--others', '--exclude-standard',
    '-z', '--', '*.ps1', '*.psm1', '*.psd1'], { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  const files = [...new Set(result.stdout.split('\0').filter(Boolean))];
  assert.ok(files.includes('test.ps1'));
  const bom = Buffer.from([0xef, 0xbb, 0xbf]);
  const decoder = new TextDecoder('utf-8', { fatal: true });
  const failures = files.flatMap(file => {
    const bytes = readFileSync(path.join(root, file));
    if (!bytes.subarray(0, 3).equals(bom)) return [`${file}: UTF-8 BOM missing`];
    try { decoder.decode(bytes.subarray(3)); return []; }
    catch { return [`${file}: invalid UTF-8`]; }
  });
  assert.deepEqual(failures, []);
});

test('native icon keeps each size-specific SVG raster in its own ICO frame', () => {
  const hash = bytes => createHash('sha256').update(bytes).digest('hex');
  const manifest = JSON.parse(read('assets/branding/branding-manifest.json'));
  assert.equal(manifest.generator_sha256, hash(read('scripts/render_document_narmi_branding.mjs').replace(/\r\n?/gu, '\n')));
  for (const [file, digest] of Object.entries(manifest.inputs)) {
    assert.equal(hash(read(file).replace(/\r\n?/gu, '\n')), digest, file);
  }
  for (const [file, digest] of Object.entries(manifest.files)) {
    assert.equal(hash(readFileSync(path.join(root, file))), digest, file);
  }
  const source = readFileSync(path.join(root, 'packaging/hwpx-filler.ico'));
  assert.equal(source.readUInt16LE(0), 0);
  assert.equal(source.readUInt16LE(2), 1);
  assert.equal(source.readUInt16LE(4), 7);
  const frames = icoSizes.map((size, at) => {
    const entry = 6 + at * 16;
    assert.equal(source[entry] || 256, size);
    assert.equal(source[entry + 1] || 256, size);
    const offset = source.readUInt32LE(entry + 12), length = source.readUInt32LE(entry + 8);
    assert.ok(offset >= 118 && offset + length <= source.length);
    return source.subarray(offset, offset + length);
  });
  const result = encodeIco(frames);
  let offset = 118;
  frames.forEach((frame, at) => {
    const entry = 6 + at * 16;
    assert.equal(result.readUInt32LE(entry + 12), offset);
    assert.equal(result.readUInt32LE(entry + 8), frame.length);
    assert.equal(result.readUInt16LE(entry + 4), 1);
    assert.equal(result.readUInt16LE(entry + 6), 32);
    assert.deepEqual(result.subarray(offset, offset + frame.length), frame);
    offset += frame.length;
  });
  assert.equal(offset, result.length);
  assert.deepEqual(icoSizes.map(tierFor), ['micro', 'micro', 'small', 'full', 'full', 'full', 'full']
    .map(tier => 'document-narmi-mark-' + tier));
  assert.throws(() => encodeIco(frames.slice(1)), /seven/u);
  assert.throws(() => encodeIco([...frames].reverse()), /invalid 16px/u);
  assert.throws(() => encodeIco([Buffer.alloc(33), ...frames.slice(1)]), /invalid 16px/u);
});

test('public build command rejects an installer without a GUI before building', () => {
  const publicBuild = read('packaging/build.ps1');
  assert.match(publicBuild, /build_native\.ps1/u);
  assert.match(publicBuild, /@PSBoundParameters/u);
  const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy',
    'Bypass', '-File',
    path.join(root, 'packaging/build.ps1'), '-Target', 'cli', '-IncludeInstaller'],
  { cwd: root, encoding: 'utf8', timeout: 120000 });
  if (result.error) throw result.error;
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /-IncludeInstaller/u);
});

test('native installer keeps the one AppId and limits silent upgrade deletion', () => {
  const build = read('packaging/build_native.ps1');
  const iss = read('packaging/installers/hwpx-filler.iss');
  const finder = read('packaging/Find-Iscc.ps1');
  const install = read('package-installer.ps1');
  assert.match(finder, /LOCALAPPDATA/u);
  assert.match(finder, /ProgramFiles\(x86\)/u);
  assert.match(finder, /Get-Command iscc\.exe/u);
  assert.match(build, /Find-Iscc\.ps1/u);
  assert.match(install, /Find-Iscc\.ps1/u);
  const ids = [iss.match(/^AppId=\{\{([\da-f-]{36})\}/imu)?.[1],
    iss.match(/Uninstall\\\{([\da-f-]{36})\}_is1/iu)?.[1],
    build.match(/\{([\da-f-]{36})\}_is1/iu)?.[1]];
  assert.ok(ids.every(Boolean));
  assert.equal(new Set(ids.map(id => id.toUpperCase())).size, 1);
  const wipe = iss.slice(iss.indexOf('function WipeSelected(): Boolean;'));
  assert.match(wipe.slice(0, wipe.indexOf('end;')), /not WizardSilent\(\)[\s\S]*IsUpgrade\(\)/u);
  assert.match(iss, /mbConfirmation, MB_YESNO or MB_DEFBUTTON2/u);
  assert.match(iss, /DelTree\(DataHomeDir\(\)/u);
  const section = iss.split('[InstallDelete]')[1]?.split(/\n\[/u)[0] ?? '';
  for (const name of ['web', 'licenses\\rust', 'licenses\\npm', 'licenses\\microsoft']) {
    assert.ok(section.includes(`Type: filesandordirs; Name: "{app}\\${name}"`), name);
  }
  assert.doesNotMatch(section, /Name: "\{app\}"/u);
  assert.doesNotMatch(section, /Check:|Tasks:|Components:|Languages:/u);
});
