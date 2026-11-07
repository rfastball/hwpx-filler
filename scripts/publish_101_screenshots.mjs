import { randomBytes } from 'node:crypto';
import { constants } from 'node:fs';
import { copyFile, lstat, mkdir, readFile, readdir, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CAPTURE_POINTS } from './live101_native/legacy.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TARGET = path.join(ROOT, 'examples/quickstart-101/img');
const expected = CAPTURE_POINTS.map((name, index) =>
  `${String(index + 1).padStart(2, '0')}-${name}.png`);

async function namesAndTypes(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  if (entries.some(entry => !entry.isFile())) {
    throw new Error(`capture contains a non-file entry: ${directory}`);
  }
  const names = entries.map(entry => entry.name).sort();
  if (JSON.stringify(names) !== JSON.stringify([...expected].sort())) {
    throw new Error(`capture image set differs: ${directory}`);
  }
  return names;
}

async function normalDirectory(directory) {
  const info = await lstat(directory);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new Error(`capture path is not a normal directory: ${directory}`);
  }
}

async function normalPng(file) {
  const info = await lstat(file);
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new Error(`capture image is not a normal file: ${file}`);
  }
  const bytes = await readFile(file);
  if (bytes.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') {
    throw new Error(`capture image is not PNG: ${file}`);
  }
  return bytes;
}

async function ownedCleanup(directory, parent, prefix) {
  if (path.dirname(directory) !== parent || !path.basename(directory).startsWith(prefix)) {
    throw new Error(`capture cleanup path escaped its parent: ${directory}`);
  }
  await normalDirectory(directory);
  await rm(directory, { recursive: true });
}

async function verifyReceipt(source) {
  const report = JSON.parse(await readFile(path.join(source, 'check-report.json'), 'utf8'));
  if (report.phase !== 'legacy' || report.mode !== 'capture' ||
      report.verdict?.ok !== true || report.teardown?.graceful !== true ||
      report.hwpx_generated !== 3 ||
      JSON.stringify(report.shots) !== JSON.stringify(CAPTURE_POINTS)) {
    throw new Error('capture report does not prove a complete native 101 run');
  }
  const pixels = path.join(source, 'pixels');
  await normalDirectory(pixels);
  await namesAndTypes(pixels);
  return pixels;
}

async function previousCapture(destination) {
  let present = false;
  try {
    await normalDirectory(destination);
    await namesAndTypes(destination);
    present = true;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  return present;
}

async function stageCapture(pixels, staged) {
  await mkdir(staged);
  for (const name of expected) {
    await normalPng(path.join(pixels, name));
    await copyFile(path.join(pixels, name), path.join(staged, name), constants.COPYFILE_EXCL);
  }
}

async function replaceCapture({ destination, parent, staged, backup, hasPrevious, renamePath }) {
  let backedUp = false;
  if (hasPrevious) {
    await renamePath(destination, backup);
    backedUp = true;
  }
  try {
    await renamePath(staged, destination);
  } catch (error) {
    if (backedUp) await renamePath(backup, destination);
    throw error;
  }
  if (backedUp) {
    try {
      await ownedCleanup(backup, parent, '.img-previous-');
    } catch (error) {
      process.stderr.write(`previous capture cleanup failed: ${backup}: ${error.message}\n`);
    }
  }
}

export async function publishCapture(evidence, target = TARGET, operations = {}) {
  const source = path.resolve(evidence);
  const destination = path.resolve(target);
  const parent = path.dirname(destination);
  const pixels = await verifyReceipt(source);
  await normalDirectory(parent);
  const hasPrevious = await previousCapture(destination);
  const nonce = randomBytes(12).toString('hex');
  const staged = path.join(parent, `.img-capture-${nonce}`);
  const backup = path.join(parent, `.img-previous-${nonce}`);
  try {
    await stageCapture(pixels, staged);
    await replaceCapture({ destination, parent, staged, backup, hasPrevious,
      renamePath: operations.rename ?? rename });
  } finally {
    try {
      await ownedCleanup(staged, parent, '.img-capture-');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
  return { target: destination, shots: expected.length };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 3) {
    throw new Error('usage: node scripts/publish_101_screenshots.mjs EVIDENCE_DIR');
  }
  const published = await publishCapture(process.argv[2]);
  process.stdout.write(`${published.shots} screenshots published to ${published.target}\n`);
}
