import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { decide, loadProbeGraph, loadScopeMap, probeClosure, resolveScope,
  validateScopeMap, verifySelectionReceipt } from '../../scripts/live_scope_native.mjs';

test('local runner preserves full native coverage with execution options and rejects CI opt-out', () => {
  // Execute the real argument/environment selection before any build or window starts.
  const runner = readFileSync(new URL('../../test.ps1', import.meta.url), 'utf8').replace(/^\uFEFF/u, '');
  const boundary = runner.indexOf('$uv = Get-Command');
  assert.ok(boundary > 0);
  const cases = [
    { args: [], scope: 'full' },
    { args: ['-x', '-q'], scope: 'full' },
    { args: ['--durations', '10', '--maxfail', '2'], scope: 'full' },
    { args: ['tests/selected_case.py'], scope: null },
    { args: ['-k', 'engine'], scope: null },
    { args: ['-kengine'], scope: null },
    { args: ['-m', 'not live'], scope: null },
    { args: ['-LiveScope', 'settings'], scope: 'settings' },
    { args: [], skip: '1', scope: null },
    { args: [], skip: '0', scope: 'full' },
    { args: [], skip: '1', ci: '1', error: true },
    { args: ['-LiveScope', 'full'], skip: '1', error: true },
  ];
  const input = JSON.stringify(cases).replaceAll("'", "''");
  const script = `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$cases = ConvertFrom-Json '${input}'
$results = foreach ($case in $cases) {
  $env:HWPX_SKIP_GUI_TESTS = $case.skip
  $env:CI = $case.ci
  $env:GITHUB_ACTIONS = $null
  $caseArgs = @($case.args)
  try {
    & {
${runner.slice(0, boundary)}
      @{ scope = $nativeScope; error = $false }
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
    if (!expected.error) assert.equal(observed[index].scope, expected.scope, JSON.stringify(expected));
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
  malformed.scopes.job.tests = ['tests/foo.py::test_bar[param]'];
  assert.throws(() => validateScopeMap(malformed), /parameterized node/);
  malformed.scopes.job.tests = [];
  malformed.scopes.job.unknown = true;
  assert.throws(() => validateScopeMap(malformed), /invalid live scope fields/);

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
