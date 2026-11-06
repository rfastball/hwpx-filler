// Closed complexity budget for owned JavaScript and Rust source during Python retirement.
import { spawnSync } from 'node:child_process';
import { existsSync, globSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseTomlText, readToml } from './read_toml.mjs';
import { measureRust } from './measure_rust_complexity.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ledgerPath = 'tests/contracts/complexity-budget.toml';
const metrics = ['module_statements', 'class_methods', 'function_complexity', 'function_statements'];
const ceilings = {
  production: { module_statements: 300, class_methods: 20, function_complexity: 10, function_statements: 50 },
  test: { module_statements: 800, class_methods: 60, function_complexity: 20, function_statements: 120 },
};
const excluded = ['frontend/vendor/', 'tests/js/fixtures/', 'tests/fixtures/', 'tests/corpus/'];

function git(...args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`git ${args[0]} failed: ${result.stderr.trim()}`);
  return result.stdout.trimEnd();
}

function jsFiles() {
  const paths = new Set();
  for (const pattern of ['frontend/**/*.{js,mjs,ts,tsx}', 'tests/**/*.{js,mjs,ts,tsx}',
    'scripts/**/*.{js,mjs,ts,tsx}', '*.{js,mjs,ts,tsx}']) {
    for (const name of globSync(pattern, { cwd: root })) {
      const rel = name.replaceAll('\\', '/');
      if (!excluded.some(prefix => rel.startsWith(prefix))) paths.add(rel);
    }
  }
  if (!paths.size) throw new Error('no JavaScript or TypeScript source found');
  return [...paths].sort();
}

function measureJs(files) {
  const result = spawnSync(process.execPath, ['scripts/complexity_axes.mjs'], {
    cwd: root, input: JSON.stringify({ root, files }), encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`JavaScript AST measurement failed: ${result.stderr}`);
  return JSON.parse(result.stdout);
}

function tier(rel) {
  return rel.startsWith('tests/') || rel.startsWith('frontend/src/selftest/')
    || /^crates\/[^/]+\/tests\//u.test(rel) ? 'test' : 'production';
}

function merge(units) {
  const found = new Map();
  for (const unit of units) {
    const ident = unit.path + (unit.qual ? `::${unit.qual}` : '');
    for (const [metric, value] of Object.entries(unit.metrics)) {
      if (!metrics.includes(metric) || !Number.isSafeInteger(value) || value < 0)
        throw new Error(`invalid complexity reading: ${ident}.${metric}`);
      const key = `${ident}\0${metric}`;
      found.set(key, Math.max(found.get(key) ?? 0, value));
    }
  }
  return found;
}

function entries(document) {
  if (document.schema !== 'complexity-budget/v1' || !document.budget || typeof document.budget !== 'object')
    throw new Error('complexity ledger schema is invalid');
  const result = new Map();
  for (const [ident, values] of Object.entries(document.budget)) {
    for (const [metric, raw] of Object.entries(values)) {
      const entry = Number.isSafeInteger(raw) ? { value: raw } : raw;
      if (!metrics.includes(metric) || !Number.isSafeInteger(entry?.value) || entry.value < 0)
        throw new Error(`invalid complexity ledger entry: ${ident}.${metric}`);
      result.set(`${ident}\0${metric}`, entry);
    }
  }
  return result;
}

function baseEntries() {
  const base = git('merge-base', 'HEAD', 'origin/master').trim();
  const spec = `${base}:${ledgerPath}`;
  const present = spawnSync('git', ['cat-file', '-e', spec], { cwd: root });
  if (present.error) throw present.error;
  if (present.status !== 0) return null;
  return parseTomlText(git('show', spec));
}

function bootstrapLedger(now, found) {
  return [...now].filter(([key, entry]) =>
    found.get(key) !== entry.value || entry.override !== undefined)
    .map(([key]) => `${key.replace('\0', ' — ')}: bootstrap budget differs from measurement`);
}

function freshOverride(entry, original) {
  return typeof entry.override === 'string' && /^#\d+$/u.test(entry.override)
    && typeof entry.reason === 'string' && entry.reason.trim()
    && (!original || original.override !== entry.override);
}

function closedLedger(now, before, found) {
  if (!before) return bootstrapLedger(now, found);
  const problems = [];
  for (const [key, entry] of now) {
    const original = before.get(key);
    if (original && entry.value <= original.value) continue;
    if (!freshOverride(entry, original))
      problems.push(`${key.replace('\0', ' — ')}: new or raised frozen budget`);
  }
  return problems;
}

function readingProblems(found, now, unitTiers) {
  const problems = [];
  for (const [key, value] of found) {
    const [ident, metric] = key.split('\0');
    const rel = ident.split('::')[0];
    const ceiling = ceilings[unitTiers.get(ident) ?? tier(rel)][metric];
    const frozen = now.get(key)?.value;
    const limit = frozen ?? ceiling;
    if (value > limit) problems.push(`${ident} — ${metric} ${value} > ${limit}: split responsibility`);
    if (frozen !== undefined && value <= ceiling)
      problems.push(`${ident} — ${metric}: stale frozen entry inside ceiling`);
    else if (frozen !== undefined && value < frozen * 0.9)
      problems.push(`${ident} — ${metric}: frozen ratchet lags ${value} < ${frozen}×0.9`);
  }
  return problems;
}

function staleProblems(found, now, pythonExists) {
  const problems = [];
  for (const key of now.keys()) {
    if (found.has(key)) continue;
    const rel = key.split('\0')[0].split('::')[0];
    if (rel.endsWith('.py') && pythonExists(rel)) continue;
    problems.push(`${key.replace('\0', ' — ')}: stale frozen entry`);
  }
  return problems;
}

function explicitTiers(units) {
  return new Map(units.filter(unit => unit.tier).map(unit => [
    unit.path + (unit.qual ? `::${unit.qual}` : ''), unit.tier,
  ]));
}

export function judge(units, ledger, base = null, { pythonExists = () => false } = {}) {
  const found = merge(units);
  const unitTiers = explicitTiers(units);
  const now = entries(ledger);
  const problems = closedLedger(now, base && entries(base), found);
  problems.push(...readingProblems(found, now, unitTiers), ...staleProblems(found, now, pythonExists));
  return problems;
}

function tightenValue(raw, current, ceiling, retainMissing) {
  if (current === undefined && retainMissing) return raw;
  if (current === undefined || current <= ceiling) return undefined;
  const entry = typeof raw === 'number' ? raw : raw.value;
  if (current >= entry) return raw;
  return typeof raw === 'number' ? current : { ...raw, value: current };
}

export function tightened(units, ledger, { pythonExists = () => false } = {}) {
  const found = merge(units);
  const unitTiers = explicitTiers(units);
  const next = structuredClone(ledger);
  entries(next); // reject malformed source before writing anything
  for (const [ident, values] of Object.entries(next.budget)) {
    const rel = ident.split('::')[0];
    for (const [metric, raw] of Object.entries(values)) {
      const key = `${ident}\0${metric}`;
      const current = found.get(key);
      const value = tightenValue(raw, current, ceilings[unitTiers.get(ident) ?? tier(rel)][metric],
        rel.endsWith('.py') && pythonExists(rel));
      if (value === undefined) delete values[metric];
      else values[metric] = value;
    }
    if (!Object.keys(values).length) delete next.budget[ident];
  }
  return next;
}

export function renderLedger(document, header) {
  entries(document);
  const lines = [header.trimEnd(), '', 'schema = "complexity-budget/v1"'];
  for (const ident of Object.keys(document.budget).sort()) {
    lines.push('', `[budget.${JSON.stringify(ident)}]`);
    for (const metric of metrics) {
      const raw = document.budget[ident][metric];
      if (raw === undefined) continue;
      const value = typeof raw === 'number' ? String(raw) : `{ value = ${raw.value}`
        + (raw.override === undefined ? '' : `, override = ${JSON.stringify(raw.override)}`)
        + (raw.reason === undefined ? '' : `, reason = ${JSON.stringify(raw.reason)}`) + ' }';
      lines.push(`${metric} = ${value}`);
    }
  }
  return lines.join('\n') + '\n';
}

function survey() {
  const files = jsFiles();
  return { files, units: [...measureJs(files), ...measureRust()] };
}

export function checkRepository() {
  const { files, units } = survey();
  const ledger = readToml(ledgerPath);
  const before = baseEntries();
  const problems = judge(units, ledger, before,
    { pythonExists: rel => existsSync(path.join(root, rel)) });
  return { files: files.length, rust: units.filter(unit => unit.path.endsWith('.rs')).length, problems };
}

function tightenRepository() {
  const { units } = survey();
  const file = path.join(root, ledgerPath);
  const source = readFileSync(file, 'utf8');
  const ledger = readToml(ledgerPath);
  const before = Object.keys(ledger.budget).length;
  const next = tightened(units, ledger, { pythonExists: rel => existsSync(path.join(root, rel)) });
  const header = source.slice(0, source.indexOf('schema ='));
  if (!header || !source.includes('schema =')) throw new Error('complexity ledger header missing');
  writeFileSync(file, renderLedger(next, header), 'utf8');
  return { removed: before - Object.keys(next.budget).length, remaining: Object.keys(next.budget).length };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 3 || !['--check', '--tighten'].includes(process.argv[2])) {
    process.stderr.write('usage: node scripts/complexity_budget.mjs --check|--tighten\n');
    process.exitCode = 2;
  } else {
    try {
      if (process.argv[2] === '--tighten') {
        const result = tightenRepository();
        process.stdout.write(`complexity budget tightened: removed ${result.removed}, remaining ${result.remaining}\n`);
      } else {
        const result = checkRepository();
        if (result.problems.length) {
        process.stderr.write(`complexity budget: ${result.problems.length} violations\n`
          + result.problems.slice(0, 40).join('\n') + '\n');
        process.exitCode = 1;
        } else {
        process.stdout.write(`complexity budget: ${result.files} JS/TS files, ${result.rust} Rust units passed\n`);
        }
      }
    } catch (error) {
      process.stderr.write(`${error.message}\n`);
      process.exitCode = 1;
    }
  }
}
