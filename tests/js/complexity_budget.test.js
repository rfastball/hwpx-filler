import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { judge, renderLedger, tightened } from '../../scripts/complexity_budget.mjs';
import { targetExecutable } from '../../scripts/measure_rust_complexity.mjs';
import { parseTomlText } from '../../scripts/read_toml.mjs';

test('Rust and JS complexity cannot escape a closed ledger', () => {
  const absoluteTarget = process.platform === 'win32' ? 'C:\\native-target' : '/native-target';
  assert.equal(targetExecutable(absoluteTarget).startsWith(absoluteTarget), true);
  const unit = (path, qual, value) => ({ path, qual, kind: 'function',
    metrics: { function_complexity: value }, detail: [] });
  const baseline = { schema: 'complexity-budget/v1', budget: {
    'frontend/src/old.js::render': { function_complexity: 12 },
  } };
  const current = structuredClone(baseline);
  const units = [unit('frontend/src/old.js', 'render', 12),
    unit('crates/hwpx-core/src/new.rs', 'dispatch', 11)];
  assert.deepEqual(judge(units, current, baseline), [
    'crates/hwpx-core/src/new.rs::dispatch — function_complexity 11 > 10: split responsibility',
  ]);
  current.budget['frontend/src/old.js::render'].function_complexity = 13;
  assert.ok(judge(units, current, baseline).some(message => message.includes('raised frozen budget')));
  assert.ok(judge([], baseline, baseline).some(message => message.includes('stale frozen entry')));
  const inline = { ...unit('crates/hwpx-core/src/new.rs', 'tests.huge', 21), tier: 'test' };
  assert.deepEqual(judge([inline], { schema: 'complexity-budget/v1', budget: {} },
    { schema: 'complexity-budget/v1', budget: {} }), [
    'crates/hwpx-core/src/new.rs::tests.huge — function_complexity 21 > 20: split responsibility',
  ]);
  const old = { schema: 'complexity-budget/v1', budget: {
    'crates/hwpx-core/src/old.rs::large': { function_complexity: 19 },
    'src/legacy.py::large': { function_complexity: 16 },
  } };
  const lower = tightened([unit('crates/hwpx-core/src/old.rs', 'large', 12)], old,
    { pythonExists: rel => rel === 'src/legacy.py' });
  assert.equal(lower.budget['crates/hwpx-core/src/old.rs::large'].function_complexity, 12);
  assert.equal(lower.budget['src/legacy.py::large'].function_complexity, 16);
  assert.match(renderLedger(lower, '# existing header\n'), /function_complexity = 12/u);
  assert.deepEqual(tightened([], old).budget, {});
  for (const name of ['frontend/src/selftest/probes/a.js', 'tests/js/a.js', 'tests/browser/a.mjs', 'crates/example/tests/a.rs']) {
    assert.deepEqual(judge([unit(name, 'probe', 11)],
      { schema: 'complexity-budget/v1', budget: {} }), []);
  }
  assert.match(judge([unit('scripts/tool.mjs', 'run', 11)],
    { schema: 'complexity-budget/v1', budget: {} }).join('\n'), /split responsibility/u);
});

test('frozen budgets require fresh justified overrides and tightening never raises them', () => {
  const ident = 'crates/example/src/lib.rs::Big';
  const ledger = value => ({ schema: 'complexity-budget/v1', budget: {
    [ident]: { class_methods: value },
  } });
  const units = value => [{ path: 'crates/example/src/lib.rs', qual: 'Big', kind: 'class',
    metrics: { class_methods: value }, detail: [] }];
  const base = ledger(30);
  const fresh = { value: 31, override: '#1234', reason: '책임 분리 전 단계' };
  assert.deepEqual(judge(units(30), base), []);
  assert.match(judge(units(30), ledger(31)).join('\n'), /bootstrap/u);
  assert.match(judge(units(30), ledger(31), base).join('\n'), /raised/u);
  assert.deepEqual(judge(units(30), ledger(fresh), base), []);
  for (const invalid of [
    { ...fresh, reason: '' }, { ...fresh, override: 'TODO' },
  ]) assert.match(judge(units(30), ledger(invalid), base).join('\n'), /raised/u);
  assert.match(judge(units(30), ledger(fresh), ledger({ ...fresh, value: 30 })).join('\n'), /raised/u);
  assert.match(judge(units(35), ledger(40), ledger(40)).join('\n'), /ratchet lags/u);
  assert.deepEqual(judge(units(36), ledger(40), ledger(40)), []);
  assert.deepEqual(tightened(units(35), ledger(40)), ledger(35));
  assert.deepEqual(tightened(units(45), ledger(40)), ledger(40));
  assert.deepEqual(tightened(units(20), ledger(40)).budget, {});
  const quoted = ledger({ ...fresh, reason: '따옴표 " 와 한글' });
  assert.deepEqual(parseTomlText(renderLedger(quoted, '# preserved header')), quoted);
  assert.throws(() => renderLedger({ schema: 'complexity-budget/v1',
    budget: { [ident]: { lines: 3 } } }, '# header'), /invalid/u);
  const duplicate = [
    { path: 'frontend/a.ts', qual: 'render', metrics: { function_complexity: 12, function_statements: 36 } },
    { path: 'frontend/a.ts', qual: 'render', metrics: { function_complexity: 9, function_statements: 55 } },
  ];
  const maxima = { schema: 'complexity-budget/v1', budget: { 'frontend/a.ts::render': {
    function_complexity: 12, function_statements: 55,
  } } };
  assert.deepEqual(judge(duplicate, maxima, maxima), []);
});

test('JS measurement separates callbacks, ignores formatting, and refuses broken syntax', () => {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const cache = path.join(root, '.cache');
  mkdirSync(cache, { recursive: true });
  const fixture = mkdtempSync(path.join(cache, 'complexity-axes-'));
  assert.ok(path.resolve(fixture).startsWith(path.resolve(cache) + path.sep));
  const source = `"use strict";
/** Documentation is not a statement. */
export class Panel { open() { return 1; } close = () => { this.x = 0; }; }
export function route(a, b) {
  if (a && b) { return a ?? b; }
  for (const item of a) { item.go(); }
  test("named callback", () => { if (a) b(); });
  return a ? 1 : 2;
}`;
  const component = count => `export function Component({ a, b, c }) {
    return h("div", { className: a ? "on" : "off" },
    ${Array.from({ length: count }, (_, i) =>
    `h("button", { onClick: () => { if (a === ${i}) b(); if (b) a(); if (c) c(); } }),`).join('\n')}
    h("input", { onKeyDown(event) { if (event.key === "x" && a) b(); } }), c && h("span"));
  }`;
  const files = {
    'plain.ts': source,
    'joined.tsx': source.replace(/\/\*.*?\*\//gu, '').replaceAll('\n', ' '),
    'one.ts': component(1), 'many.tsx': component(12), 'broken.ts': 'function (',
  };
  const measure = names => spawnSync(process.execPath, ['scripts/complexity_axes.mjs'], {
    cwd: root, input: JSON.stringify({ root: fixture, files: names }), encoding: 'utf8',
  });
  try {
    for (const [name, body] of Object.entries(files)) writeFileSync(path.join(fixture, name), body);
    const measured = measure(Object.keys(files).filter(name => name !== 'broken.ts'));
    assert.equal(measured.status, 0, measured.stderr);
    const units = JSON.parse(measured.stdout);
    const axes = name => units.filter(unit => unit.path === name).map(({ qual, metrics }) => ({ qual, metrics }));
    assert.deepEqual(axes('plain.ts'), axes('joined.tsx'));
    const metric = qual => axes('plain.ts').find(unit => unit.qual === qual).metrics;
    assert.deepEqual(metric('Panel'), { class_methods: 2 });
    assert.deepEqual(metric('route'), { function_complexity: 6, function_statements: 6 });
    assert.deepEqual(metric('route.test("named callback")'), { function_complexity: 2, function_statements: 2 });
    for (const [name, count] of [['one.ts', 1], ['many.tsx', 12]]) {
      const handlers = axes(name).filter(unit => unit.qual === 'Component.onClick');
      assert.equal(handlers.length, count);
      assert.ok(handlers.every(unit => unit.metrics.function_complexity === 4));
      assert.deepEqual(axes(name).find(unit => unit.qual === 'Component').metrics,
        { function_complexity: 3, function_statements: 1 });
    }
    const broken = measure(['broken.ts']);
    assert.notEqual(broken.status, 0);
    assert.match(broken.stderr, /broken\.ts.*파싱 실패/u);
  } finally { rmSync(fixture, { recursive: true, force: true }); }
});
