import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readToml } from './read_toml.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MAP = 'tests/contracts/live-scopes.toml';
const GRAPH = 'tests/contracts/selftest-probe-graph.json';
const truthy = value => !['', '0', 'false'].includes(String(value ?? '').trim().toLowerCase());
const fields = ['description', 'paths', 'probes', 'tests'];
const plain = value => value !== null && typeof value === 'object' &&
  !Array.isArray(value);

function stringList(values, label) {
  if (!Array.isArray(values) || values.some(value => typeof value !== 'string' || !value)) {
    throw new Error(`${label} must be a list of nonempty strings`);
  }
  if (new Set(values).size !== values.length) throw new Error(`${label} contains duplicates`);
  return values;
}

export function loadScopeMap(root = ROOT) {
  const map = readToml(MAP, { cwd: root });
  return validateScopeMap(map);
}

export function validateScopeMap(map) {
  if (!plain(map) || map.version !== 1 || !plain(map.scopes) ||
      Object.keys(map).sort().join(',') !==
        ['full_only', 'no_live', 'scopes', 'shared', 'version'].join(',')) {
    throw new Error('live scope map version or scopes are invalid');
  }
  stringList(map.shared, 'shared');
  stringList(map.no_live, 'no_live');
  if (!plain(map.full_only) || Object.values(map.full_only).some(
    value => typeof value !== 'string' || !value.trim())) {
    throw new Error('full_only requires a reason per node');
  }
  for (const [name, scope] of Object.entries(map.scopes)) validateScope(name, scope);
  return map;
}

function validateScope(name, scope) {
  if (!/^[\p{ID_Start}_][\p{ID_Continue}_]*$/u.test(name) ||
      ['full', 'auto'].includes(name)) {
    throw new Error(`invalid live scope name: ${name}`);
  }
  if (!plain(scope) || Object.keys(scope).sort().join(',') !== fields.join(',')) {
    throw new Error(`invalid live scope fields: ${name}`);
  }
  if (typeof scope.description !== 'string' || !scope.description.trim()) {
    throw new Error(`missing live scope description: ${name}`);
  }
  stringList(scope.probes, `${name}.probes`);
  stringList(scope.tests, `${name}.tests`);
  stringList(scope.paths, `${name}.paths`);
  if (scope.tests.some(node => node.includes('['))) {
    throw new Error(`parameterized node in ${name}.tests`);
  }
  if (!scope.probes.length && !scope.tests.length && name !== 'journey101') {
    throw new Error(`live scope has no resource owner: ${name}`);
  }
}

export function loadProbeGraph(root = ROOT) {
  const graph = JSON.parse(readFileSync(path.join(root, GRAPH), 'utf8'));
  if (graph.version !== 1 || !Array.isArray(graph.probes)) {
    throw new Error('selftest probe graph version or probes are invalid');
  }
  return graph;
}

const matches = (name, globs) => globs.find(glob => path.matchesGlob(name, glob));

export function classifyPath(name, map) {
  const file = name.replaceAll('\\', '/');
  const shared = matches(file, map.shared);
  if (shared) return { path: file, kind: 'shared', rule: shared };
  const scopes = Object.entries(map.scopes)
    .filter(([, scope]) => matches(file, scope.paths)).map(([key]) => key);
  if (scopes.length) return { path: file, kind: 'scope', scopes };
  const noLive = matches(file, map.no_live);
  return noLive ? { path: file, kind: 'no_live', rule: noLive }
    : { path: file, kind: 'unmapped' };
}

export function decide(paths, map) {
  const verdicts = [...new Set(paths)].sort().map(name => classifyPath(name, map));
  if (!verdicts.length) return { mode: 'full', scopes: [], verdicts, reason: 'no changes' };
  if (verdicts.some(verdict => ['shared', 'unmapped'].includes(verdict.kind))) {
    return { mode: 'full', scopes: [], verdicts, reason: 'shared or unmapped change' };
  }
  const hit = new Set(verdicts.flatMap(verdict => verdict.scopes ?? []));
  const scopes = Object.keys(map.scopes).filter(name => hit.has(name));
  return { mode: scopes.length ? 'partial' : 'none', scopes, verdicts,
    reason: scopes.length ? 'local change' : 'no live change' };
}

export function probeClosure(selection, graph) {
  const planned = graph.probes.filter(probe => probe.modes.includes('full'));
  const byName = new Map(planned.map(probe => [probe.name, probe]));
  const clusters = new Set(planned.map(probe => probe.cluster));
  const stack = [];
  for (const name of selection) {
    if (byName.has(name) && clusters.has(name)) throw new Error(`ambiguous probe or cluster: ${name}`);
    if (byName.has(name)) stack.push(name);
    else if (clusters.has(name)) stack.push(...planned.filter(probe => probe.cluster === name).map(probe => probe.name));
    else throw new Error(`unknown full-mode probe or cluster: ${name}`);
  }
  const closed = new Set();
  while (stack.length) {
    const name = stack.pop();
    if (closed.has(name)) continue;
    const probe = byName.get(name);
    if (!probe) throw new Error(`unknown after dependency: ${name}`);
    closed.add(name);
    stack.push(...probe.after);
  }
  return planned.filter(probe => closed.has(probe.name)).map(probe => probe.name);
}

function git(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' });
  if (result.error || result.status !== 0) {
    throw new Error(`git ${args.join(' ')} failed: ${result.stderr ?? result.error}`);
  }
  return result.stdout;
}

export function changedFiles(root = ROOT, base = 'origin/master') {
  const ancestor = git(root, ['merge-base', 'HEAD', base]).trim();
  const tracked = git(root, ['diff', '--name-only', '--no-renames', ancestor]).split(/\r?\n/);
  const untracked = git(root, ['ls-files', '--others', '--exclude-standard']).split(/\r?\n/);
  return [...new Set([...tracked, ...untracked].filter(Boolean))].sort();
}

function explicitNames(choice, map) {
  const names = choice.split(',').map(name => name.trim());
  if (names.some(name => !name || ['full', 'auto'].includes(name)) ||
      new Set(names).size !== names.length) throw new Error(`invalid live scope: ${choice}`);
  const unknown = names.filter(name => !Object.hasOwn(map.scopes, name));
  if (unknown.length) throw new Error(`unknown live scope: ${unknown.join(', ')}`);
  return names;
}

function autoDecision(changed, map) {
  try { return decide(changed ?? changedFiles(), map); }
  catch (error) { return { mode: 'full', scopes: [], reason: `git unavailable: ${error.message}` }; }
}

function scopedSelection(choice, names, decision, map, graph) {
  const mode = decision?.mode ?? 'partial';
  if (mode !== 'partial') return { requested: choice, mode, scopes: [], probes: [],
    closure: [], runJourney: mode === 'full', decision };
  const probes = [...new Set(names.flatMap(name => map.scopes[name].probes))];
  const closure = probes.length ? probeClosure(probes, graph) : [];
  return { requested: choice, mode, scopes: names, probes, closure,
    runJourney: names.includes('journey101'), decision };
}

function assertSafeSelection(choice, environ) {
  if (choice !== 'full' && (truthy(environ.CI) || truthy(environ.GITHUB_ACTIONS))) {
    throw new Error('partial live scope is forbidden in CI');
  }
  if (truthy(environ.HWPX_SELFTEST_PROBES)) {
    throw new Error('HWPX_SELFTEST_PROBES is owned by the live runner');
  }
}

export function resolveScope(requested = 'full', options = {}) {
  const choice = String(requested || 'full').trim();
  assertSafeSelection(choice, options.environ ?? process.env);
  if (choice === 'full') return { requested: choice, mode: 'full', scopes: [],
    probes: [], closure: [], runJourney: true };
  const map = options.map ?? loadScopeMap();
  const graph = options.graph ?? loadProbeGraph();
  const decision = choice === 'auto' ? autoDecision(options.changed, map) : null;
  const names = decision?.scopes ?? explicitNames(choice, map);
  return scopedSelection(choice, names, decision, map, graph);
}

function assertSelectionEcho(selection, receipt) {
  const marker = receipt.selftest_selection;
  if (!plain(marker) || marker.partial !== true ||
      JSON.stringify(marker.requested) !== JSON.stringify(selection.probes) ||
      !Array.isArray(marker.planned) ||
      marker.planned.length !== selection.closure.length ||
      JSON.stringify([...marker.planned].sort()) !==
        JSON.stringify([...selection.closure].sort())) {
    throw new Error('partial WebView selection echo differs from requested closure');
  }
}

export function verifySelectionReceipt(selection, receipt, graph) {
  if (selection.mode !== 'partial' || !selection.probes.length) {
    throw new Error('a partial probe selection is required');
  }
  if (!plain(receipt) || Object.hasOwn(receipt, 'error')) {
    throw new Error(`partial WebView receipt failed: ${receipt?.error ?? 'not an object'}`);
  }
  assertSelectionEcho(selection, receipt);
  const planned = new Set(selection.closure);
  const keys = [...new Set(graph.probes.filter(probe => planned.has(probe.name))
    .flatMap(probe => probe.keys))].sort();
  const observed = Object.keys(receipt).filter(key => key !== 'selftest_selection').sort();
  if (JSON.stringify(observed) !== JSON.stringify(keys)) {
    throw new Error('partial WebView receipt keys differ from selected probe closure');
  }
  return keys.length;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv[2] === '--verify') {
      if (process.argv.length !== 5) throw new Error('usage: live_scope_native.mjs --verify SELECTION RECEIPT');
      const selection = JSON.parse(readFileSync(process.argv[3], 'utf8'));
      const receipt = JSON.parse(readFileSync(process.argv[4], 'utf8'));
      const count = verifySelectionReceipt(selection, receipt, loadProbeGraph());
      process.stdout.write(`partial native WebView receipt verified: ${count} keys\n`);
    } else {
      if (process.argv.length > 3) throw new Error('usage: live_scope_native.mjs [auto|full|scope[,scope]]');
      process.stdout.write(`${JSON.stringify(resolveScope(process.argv[2] ?? 'auto'), null, 2)}\n`);
    }
  } catch (error) { process.stderr.write(`${error.stack ?? error}\n`); process.exitCode = 1; }
}
