import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { decide, loadProbeGraph, loadScopeMap, probeClosure, resolveScope,
  validateScopeMap, verifySelectionReceipt } from '../../scripts/live_scope_native.mjs';

test('local runner accepts only its declared arguments and rejects CI opt-outs', () => {
  // Execute the real argument/environment selection before any build or window starts.
  const runner = readFileSync(new URL('../../test.ps1', import.meta.url), 'utf8').replace(/^\uFEFF/u, '');
  const boundary = runner.indexOf('# --- 인자·환경 판정 끝');
  assert.ok(boundary > 0);
  const cases = [
    { args: [], scope: 'full', motion: false, native: false },
    { args: ['-LiveScope', 'settings'], scope: 'settings' },
    { args: ['-livescope', 'job,data'], scope: 'job,data' },
    { args: ['-SkipLive'], scope: null },
    { args: ['-SkipLive'], ci: '1', scope: null },
    { args: ['-LiveScope', 'full'], ci: '1', scope: 'full' },
    { args: ['-SkipLive', '-LiveScope', 'auto'], error: true },
    { args: ['-SkipLive', '-SkipLive'], error: true },
    { args: ['-LiveScope', 'job', '-LiveScope', 'data'], error: true },
    { args: ['-LiveScope'], error: true },
    { args: ['-LiveScope', '-SkipLive'], error: true },
    { args: ['-x'], error: true },
    { args: ['-m', 'not live'], error: true },
    { args: ['tests/selected_case.rs'], error: true },
    { args: ['-Live', 'auto'], error: true },
    { args: [], skip: '1', scope: null },
    { args: [], skip: '0', scope: 'full' },
    { args: [], skip: '1', ci: '1', error: true },
    { args: ['-LiveScope', 'full'], skip: '1', error: true },
    { args: [], motion: '1', scope: 'full', skipMotion: true },
    { args: [], motion: '1', ci: '1', error: true },
    { args: [], native: '1', scope: 'full', skipNative: true },
    { args: [], native: '1', ci: '1', error: true },
    { args: [], native: 'false', ci: '1', scope: 'full', skipNative: false },
  ];
  const input = JSON.stringify(cases).replaceAll("'", "''");
  const script = `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$cases = ConvertFrom-Json '${input}'
$results = foreach ($case in $cases) {
  $env:HWPX_SKIP_GUI_TESTS = $case.skip
  $env:HWPX_SKIP_MOTION_TESTS = $case.motion
  $env:HWPX_SKIP_NATIVE_TESTS = $case.native
  $env:CI = $case.ci
  $env:GITHUB_ACTIONS = $null
  $caseArgs = @($case.args)
  try {
    & {
${runner.slice(0, boundary)}
      @{ scope = $nativeScope; motion = $skipMotion; native = $skipNative; error = $false }
    } @caseArgs
  } catch { @{ scope = $null; error = $true; detail = $_.ToString() } }
}
ConvertTo-Json -InputObject @($results) -Compress`;
  const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive',
    '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')],
  { encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.stderr);
  const observed = JSON.parse(result.stdout);
  assert.equal(observed.length, cases.length);
  for (const [index, expected] of cases.entries()) {
    assert.equal(observed[index].error, !!expected.error,
      JSON.stringify({ expected, observed: observed[index] }));
    if (expected.error) continue;
    assert.equal(observed[index].scope, expected.scope, JSON.stringify(expected));
    if ('skipMotion' in expected) assert.equal(observed[index].motion, expected.skipMotion, JSON.stringify(expected));
    if ('skipNative' in expected) assert.equal(observed[index].native, expected.skipNative, JSON.stringify(expected));
  }
});

test('native local scope keeps full fallback, probe closure, and CI refusal', () => {
  const map = loadScopeMap();
  const graph = loadProbeGraph();
  assert.deepEqual(decide(['frontend/src/screens/job_read.ts', 'docs/workflow.md'], map).scopes,
    ['job']);
  assert.equal(decide(['frontend/src/shell/app.ts'], map).mode, 'full');
  assert.equal(decide(['docs/workflow.md'], map).mode, 'none');
  assert.equal(decide([], map).mode, 'full');
  const closure = probeClosure(['data_picker'], graph);
  for (const name of ['data_picker', 'job_editmode', 'milestone_h_wave1', 'job_data_first']) {
    assert.ok(closure.includes(name));
  }
  assert.ok(!closure.includes('react_runtime'));
  assert.ok(!probeClosure(['E'], graph).includes('window_geometry'));
  assert.throws(() => probeClosure(['window_geometry'], graph), /unknown full-mode probe/);

  const partial = resolveScope('auto', { map, graph, environ: {},
    changed: ['frontend/src/screens/job_read.ts'] });
  assert.equal(partial.mode, 'partial');
  assert.deepEqual(partial.scopes, ['job']);
  assert.equal(partial.runJourney, false);
  assert.equal(resolveScope('journey101', { map, graph, environ: {} }).runJourney, true);
  for (const choice of ['job,job', 'job,full', 'auto,job', 'no_such_scope']) {
    assert.throws(() => resolveScope(choice, { map, graph, environ: {} }));
  }
  assert.throws(() => resolveScope('job', { map, graph, environ: { CI: 'true' } }), /CI/);
  assert.throws(() => resolveScope('full', { map, graph,
    environ: { HWPX_SELFTEST_PROBES: 'job_mirror' } }), /HWPX_SELFTEST_PROBES/);
  assert.equal(resolveScope('full', { map, graph, environ: { CI: 'true' } }).mode, 'full');
  const malformed = structuredClone(map);
  malformed.scopes.job.tests = [];
  assert.throws(() => validateScopeMap(malformed), /invalid live scope fields/);
  delete malformed.scopes.job.tests;
  malformed.scopes.job.probes = [];
  assert.throws(() => validateScopeMap(malformed), /no resource owner/);
  assert.throws(() => validateScopeMap({ ...structuredClone(map), version: 1 }), /version/);

  // 낡은 glob(지운 구현의 경로)은 조용히 아무것도 고르지 않는다 — 소유 경로는 실제 추적 파일을 가리켜야 한다.
  const tracked = spawnSync('git', ['ls-files'], { encoding: 'utf8', cwd: new URL('../../', import.meta.url) });
  assert.equal(tracked.status, 0, tracked.stderr);
  const files = tracked.stdout.split(/\r?\n/u).filter(Boolean);
  const owned = [['shared', map.shared],
    ...Object.entries(map.scopes).map(([name, scope]) => [`scopes.${name}.paths`, scope.paths])];
  for (const [label, globs] of owned) {
    for (const glob of globs) {
      assert.ok(files.some(file => path.matchesGlob(file, glob)), `${label}: ${glob} matches no tracked file`);
    }
  }

  const selected = resolveScope('settings', { map, graph, environ: {} });
  const included = new Set(selected.closure);
  const keys = [...new Set(graph.probes.filter(probe => included.has(probe.name))
    .flatMap(probe => probe.keys))];
  const receipt = Object.fromEntries(keys.map(key => [key, {}]));
  receipt.selftest_selection = { partial: true,
    requested: [...selected.probes], planned: [...selected.closure].reverse() };
  assert.equal(verifySelectionReceipt(selected, receipt, graph), keys.length);
  delete receipt[keys[0]];
  assert.throws(() => verifySelectionReceipt(selected, receipt, graph), /receipt keys/);
  receipt[keys[0]] = {};
  receipt.selftest_selection.planned.pop();
  assert.throws(() => verifySelectionReceipt(selected, receipt, graph), /selection echo/);
});
