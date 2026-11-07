import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { NativeSurface } from '../../scripts/live101_native/surface.mjs';
import { BOOT_MS, HARD_STOP_MS, OUTER_MS, SURFACE_MS,
  hardStopReport } from '../../scripts/live101_native/run_budget.mjs';

test('native live101 hard stop precedes its outer deadline and leaves a failed receipt', () => {
  assert.equal(BOOT_MS, 75_000);
  assert.equal(SURFACE_MS, 600_000);
  assert.equal(HARD_STOP_MS, 690_000);
  assert.equal(OUTER_MS, 735_000);
  assert.ok(HARD_STOP_MS < OUTER_MS);
  const receipt = hardStopReport({ phase: 'journey', mode: 'check', home: 'isolated',
    previous: { observations: { reached: true }, documents: [{ name: 'partial' }],
      hwpx_generated: 1 }, shots: ['first'], elapsedMs: HARD_STOP_MS });
  assert.equal(receipt.verdict.ok, false);
  assert.match(receipt.error, /hard stop/);
  assert.equal(receipt.deadline_ms, HARD_STOP_MS);
  assert.equal(receipt.hwpx_generated, 1);
  assert.deepEqual(receipt.shots, ['first']);
});

test('native surface distinguishes a missing control, an unsatisfied control, and an expired journey', async () => {
  const page = { evaluate: async expression => expression.includes('document.querySelector')
    ? true : { ready: false, alert: null } };
  const surface = new NativeSurface(page, 3000);
  await assert.rejects(surface.wait('false', 'missing', { timeoutMs: 1, requires: ['#absent'] }),
    /native step timed out: missing/);
  page.evaluate = async expression => expression.includes('document.querySelector')
    ? false : { ready: false, alert: null };
  await assert.rejects(surface.wait('false', 'missing', { timeoutMs: 1, requires: ['#absent'] }),
    /missing native surface #absent at missing/);
  page.evaluate = async () => ({ ready: false, alert: 'unexpected dialog' });
  await assert.rejects(surface.wait('false', 'alert', { timeoutMs: 1000 }),
    /native alert during alert: unexpected dialog/);
  surface.deadline = Date.now() - 1;
  await assert.rejects(surface.wait('false', 'expired'),
    /live101 journey budget ended before expired/);
});

test('native runner preserves a dirty home and writes a finite missing-GUI report', async () => {
  const cache = path.resolve('.cache');
  await mkdir(cache, { recursive: true });
  const fixture = await mkdtemp(path.join(cache, 'live101-negative-'));
  try {
    const home = path.join(fixture, 'home');
    const evidence = path.join(fixture, 'evidence');
    const jobs = path.join(home, 'jobs');
    await mkdir(jobs, { recursive: true });
    const sentinel = path.join(jobs, 'existing.job.json');
    await writeFile(sentinel, 'user document bytes');
    const child = spawnSync(process.execPath, [
      path.resolve('scripts/live101_native/run.mjs'), 'check',
      '--exe', path.join(fixture, 'no-exe.exe'), '--home', home,
      '--evidence', evidence,
    ], { encoding: 'utf8', timeout: 5000 });
    assert.equal(child.status, 1, child.stderr);
    const report = JSON.parse(await readFile(path.join(evidence, 'check-report.json'), 'utf8'));
    assert.equal(report.verdict.ok, false);
    assert.match(report.error, /live101 home contains practice state: jobs/);
    assert.equal(await readFile(sentinel, 'utf8'), 'user document bytes');

    const cleanHome = path.join(fixture, 'clean-home');
    const cleanEvidence = path.join(fixture, 'clean-evidence');
    const failedChild = spawnSync(process.execPath, [
      path.resolve('scripts/live101_native/run.mjs'), 'check',
      '--exe', path.join(fixture, 'no-exe.exe'), '--home', cleanHome,
      '--evidence', cleanEvidence,
    ], { encoding: 'utf8', timeout: 5000 });
    assert.equal(failedChild.status, 1, failedChild.stderr);
    const failedReport = JSON.parse(await readFile(path.join(cleanEvidence, 'check-report.json'), 'utf8'));
    assert.equal(failedReport.verdict.ok, false);
    assert.match(failedReport.error, /native GUI did not spawn/);
    assert.equal(failedReport.hwpx_generated, 0);
  } finally {
    if (path.dirname(fixture) !== cache || !path.basename(fixture).startsWith('live101-negative-')) {
      throw new Error(`unsafe native live fixture cleanup: ${fixture}`);
    }
    await rm(fixture, { recursive: true, force: true });
  }
});
