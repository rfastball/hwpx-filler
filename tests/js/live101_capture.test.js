import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { CAPTURE_POINTS } from '../../scripts/live101_native/legacy.mjs';
import { publishCapture } from '../../scripts/publish_101_screenshots.mjs';

const png = Buffer.from('89504e470d0a1a0a', 'hex');
const names = CAPTURE_POINTS.map((name, index) =>
  `${String(index + 1).padStart(2, '0')}-${name}.png`);

test('native capture publishes only a complete set and restores the previous set on rename failure', async () => {
  const base = path.resolve('.cache');
  await mkdir(base, { recursive: true });
  const fixture = await mkdtemp(path.join(base, 'capture-owner-'));
  try {
    const evidence = path.join(fixture, 'evidence');
    const pixels = path.join(evidence, 'pixels');
    const target = path.join(fixture, 'img');
    await mkdir(pixels, { recursive: true });
    await mkdir(target);
    for (const name of names) {
      await writeFile(path.join(pixels, name), png);
      await writeFile(path.join(target, name), Buffer.from('old'));
    }
    const report = { phase: 'legacy', mode: 'capture', hwpx_generated: 3,
      shots: [...CAPTURE_POINTS], verdict: { ok: true }, teardown: { graceful: true } };
    await writeFile(path.join(evidence, 'check-report.json'), JSON.stringify(report));

    await rm(path.join(pixels, names[0]));
    await assert.rejects(publishCapture(evidence, target), /set differs/);
    assert.equal((await readFile(path.join(target, names[0]))).toString(), 'old');
    await writeFile(path.join(pixels, names[0]), png);

    await assert.rejects(publishCapture(evidence, target, {
      rename: async (from, to) => {
        if (path.basename(from).startsWith('.img-capture-')) throw new Error('new rename failed');
        await rename(from, to);
      },
    }), /new rename failed/);
    assert.deepEqual((await readdir(target)).sort(), [...names].sort());
    assert.equal((await readFile(path.join(target, names[0]))).toString(), 'old');

    const result = await publishCapture(evidence, target);
    assert.equal(result.shots, 13);
    assert.deepEqual((await readdir(target)).sort(), [...names].sort());
    assert.deepEqual(await readFile(path.join(target, names[0])), png);
    assert.deepEqual((await readdir(fixture)).sort(), ['evidence', 'img']);
  } finally {
    // The unique fixture was created below the workspace cache and owns every child.
    if (path.dirname(fixture) !== base || !path.basename(fixture).startsWith('capture-owner-')) {
      throw new Error(`unsafe capture fixture cleanup: ${fixture}`);
    }
    await rm(fixture, { recursive: true, force: true });
  }
});

test('native shutter names, committed PNGs, and Quickstart references have one ordered set', async () => {
  const root = path.resolve('examples/quickstart-101');
  const committed = (await readdir(path.join(root, 'img'))).sort();
  const readme = await readFile(path.join(root, 'README.md'), 'utf8');
  const referenced = [...readme.matchAll(/img\/(\d{2}-[a-z-]+\.png)/g)]
    .map(match => match[1]);
  assert.deepEqual(committed, [...names].sort());
  assert.deepEqual(referenced, names);
});
