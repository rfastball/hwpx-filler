import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, globSync, readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { parseAst } from 'vite';
import config from '../../vite.config.mjs';
import { readToml } from '../../scripts/read_toml.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = name => readFileSync(path.join(root, name), 'utf8');
const packageJson = JSON.parse(read('package.json'));
const relative = value => path.relative(root, value).replaceAll('\\', '/');
const inRoot = (file, allowed) => allowed.some(entry => file === entry || file.startsWith(`${entry}/`));

const sourceLang = file => file.endsWith('.tsx') ? 'tsx' : /\.[mc]?ts$/u.test(file) ? 'ts' : 'js';
const literal = node => node?.type === 'Literal' && typeof node.value === 'string' ? node.value : null;

function frontendImports(file, source) {
  const syntax = parseAst(source, { lang: sourceLang(file) });
  // `/// <reference types>` 도 vendor 타입을 끌어들이는 의존 간선이다.
  const imports = [...source.matchAll(/^\s*\/\/\/\s*<reference\s+types\s*=\s*["']([^"']+)["']\s*\/>/gmu)]
    .map(match => match[1]);
  const visit = node => {
    if (['ImportDeclaration', 'ExportNamedDeclaration', 'ExportAllDeclaration'].includes(node.type)
      && typeof node.source?.value === 'string') imports.push(node.source.value);
    if (node.type === 'TSImportEqualsDeclaration' && node.moduleReference?.type === 'TSExternalModuleReference')
      imports.push(literal(node.moduleReference.expression));
    const required = node.type === 'CallExpression' && (node.callee?.name === 'require'
      || node.callee?.type === 'MemberExpression' && !node.callee.computed
        && node.callee.object?.name === 'module' && node.callee.property?.name === 'require');
    if (node.type === 'ImportExpression' || required) {
      // 문자열 literal 이 아닌 지정자는 정적으로 판정할 수 없으므로 통과가 아니라 거절이다.
      const specifier = literal(node.type === 'ImportExpression' ? node.source : node.arguments?.[0]);
      assert.ok(specifier !== null && (node.type === 'ImportExpression' || node.arguments.length === 1),
        `${file}: dynamic import()/require() specifier must be a string literal`);
      imports.push(specifier);
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(child => child?.type && visit(child));
      else if (value?.type) visit(value);
    }
  };
  visit(syntax);
  return imports;
}

function declaredOwner(file, symbol) {
  const syntax = parseAst(read(file), { lang: 'ts' });
  let found = false;
  const visit = node => {
    if (['FunctionDeclaration', 'ClassDeclaration', 'VariableDeclarator'].includes(node.type)
      && node.id?.name === symbol || node.type === 'Property' && node.key?.name === symbol
      && node.method) found = true;
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(child => child?.type && visit(child));
      else if (value?.type) visit(value);
    }
  };
  visit(syntax);
  return found;
}

function resolveFrontendImport(file, specifier, sources) {
  const target = specifier.startsWith('.')
    ? path.posix.normalize(path.posix.join(path.posix.dirname(file), specifier))
    : specifier.startsWith('/src/') || specifier.startsWith('/js/') ? specifier.slice(1) : null;
  if (!target || target.startsWith('../')) return null;
  return [target, `${target}.ts`, `${target}.tsx`, `${target}.js`, `${target}.mjs`,
    `${target}/index.ts`, `${target}/index.js`].find(candidate => sources.has(candidate)) ?? null;
}

function vendorScan(sources, approved) {
  const edges = new Map();
  const provenance = new Set();
  const violations = [];
  for (const [file, source] of sources) {
    const internal = [];
    for (const specifier of frontendImports(file, source)) {
      const target = resolveFrontendImport(file, specifier, sources);
      if (target) {
        internal.push(target);
      } else if (!specifier.startsWith('.') && !specifier.startsWith('/')) {
        const dependency = specifier.startsWith('@') ? specifier.split('/').slice(0, 2).join('/')
          : specifier.split('/')[0];
        const owner = approved.get(dependency);
        if (!owner || !inRoot(`frontend/${file}`, owner)) violations.push(`${file} -> ${specifier}`);
        provenance.add(file);
      }
    }
    edges.set(file, internal);
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const [file, targets] of edges) {
      if (!provenance.has(file) && targets.some(target => provenance.has(target))) {
        provenance.add(file);
        changed = true;
      }
    }
  }
  violations.push(...[...provenance].filter(file => file.startsWith('src/contract/'))
    .map(file => `${file} -> vendor adapter`));
  return violations.sort();
}

const retainedCodecs = new Set([
  'src/domain/canonical_execution_encoding.ts',
  'src/domain/slot_selection.ts',
]);
const semanticSymbols = new Set([
  'canonicalExecutionBytes', 'canonicalExecutionDigest', 'canonicalizeSelectionSet',
  'digestSelectionSet', 'semanticSelectionEqual', 'validateSelectionSet',
  'declaredSelectionDigest',
]);
function semanticAuthorityViolations(sources) {
  const violations = [];
  for (const [file, source] of sources) {
    if (retainedCodecs.has(file)) continue;
    for (const specifier of frontendImports(file, source)) {
      const target = resolveFrontendImport(file, specifier, sources);
      if (target?.startsWith('src/domain/')) violations.push(`${file} -> ${target}`);
    }
    const ast = parseAst(source, { lang: file.endsWith('.tsx') ? 'tsx' : file.endsWith('.ts') ? 'ts' : 'js' });
    const found = new Set();
    const visit = node => {
      if (node.type === 'Identifier' && semanticSymbols.has(node.name)) found.add(node.name);
      if (node.type === 'MemberExpression' && (node.property?.name === 'subtle'
        || node.computed && node.property?.value === 'subtle')
        && (node.object?.name === 'crypto' || node.object?.property?.name === 'crypto')) {
        found.add('crypto.subtle');
      }
      for (const value of Object.values(node)) {
        if (Array.isArray(value)) value.forEach(child => child?.type && visit(child));
        else if (value?.type) visit(value);
      }
    };
    visit(ast);
    violations.push(...[...found].sort().map(symbol => `${file} -> ${symbol}`));
  }
  return violations.sort();
}

test('frontend dependencies and toolchain declarations have exact matching locks', () => {
  const lock = JSON.parse(read('package-lock.json'));
  const owners = JSON.parse(read('tests/static_closure_contract.json')).dev_dependency_owners;
  assert.deepEqual(Object.keys(packageJson.devDependencies).sort(), Object.keys(owners).sort());
  assert.ok(Object.values(owners).every(owner => typeof owner === 'string' && owner.trim()));
  const nodeVersion = read('.node-version').trim();
  assert.match(nodeVersion, /^\d+\.\d+\.\d+$/u);
  assert.equal(process.version, `v${nodeVersion}`);
  assert.match(packageJson.packageManager, /^npm@\d+\.\d+\.\d+$/u);
  assert.deepEqual(packageJson.engines, { node: nodeVersion, npm: packageJson.packageManager.slice(4) });
  assert.equal(lock.lockfileVersion, 3);
  for (const group of ['dependencies', 'devDependencies']) {
    assert.deepEqual(lock.packages[''][group], packageJson[group]);
    for (const [name, version] of Object.entries(packageJson[group])) {
      assert.match(version, /^\d+\.\d+\.\d+$/u, name);
      assert.equal(lock.packages[`node_modules/${name}`].version, version, name);
    }
  }
  assert.deepEqual(read('.npmrc').trim().split(/\r?\n/u), ['engine-strict=true', 'save-exact=true']);
});

test('Vite and package scripts keep one offline production entry and native seal verification', () => {
  assert.equal(packageJson.private, true);
  assert.equal(packageJson.type, 'module');
  assert.deepEqual(packageJson.scripts, {
    build: 'powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_rhwp.ps1 && vite build && powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_web_artifact.ps1',
    test: 'node --test --test-concurrency=4 --test-reporter=tap "tests/js/*.test.js"',
    'verify:web': 'powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_web_artifact.ps1 -Verify',
  });
  assert.deepEqual({
    root: relative(config.root), base: config.base,
    build: {
      ...config.build, outDir: relative(config.build.outDir),
      sourcemap: config.build.sourcemap ?? false,
    },
  }, {
    root: 'frontend', base: './',
    build: {
      outDir: 'build/web', emptyOutDir: true, manifest: true, cssCodeSplit: false,
      assetsInlineLimit: 0, modulePreload: false, minify: false, sourcemap: false,
      rolldownOptions: { treeshake: false },
    },
  });
  assert.deepEqual(read('frontend/index.html').match(/<script\b[^>]*\bsrc="[^"]+"[^>]*><\/script>/gu),
    ['<script type="module" src="./src/main.js"></script>']);
  const build = read('build-web.ps1');
  assert.ok(build.indexOf('run build') < build.indexOf('run verify:web'));
  assert.ok(build.includes('run verify:web'));
});

test('TypeScript boundary is erasable, strict, and typechecks without emission', () => {
  const tsconfig = JSON.parse(read('tsconfig.json'));
  assert.deepEqual(tsconfig.include, ['frontend/src/**/*']);
  for (const option of ['strict', 'noEmit', 'erasableSyntaxOnly', 'verbatimModuleSyntax', 'allowImportingTsExtensions']) {
    assert.equal(tsconfig.compilerOptions[option], true, option);
  }
  assert.equal(tsconfig.compilerOptions.skipLibCheck, false);
  const result = spawnSync(process.execPath, ['node_modules/typescript/bin/tsc', '-p', 'tsconfig.json'],
    { cwd: root, encoding: 'utf8', timeout: 120_000 });
  assert.equal(result.status, 0, result.stdout + result.stderr + (result.error?.message ?? ''));
});

test('production imports form a closed acyclic graph with pinned bare dependencies', () => {
  const state = new Map();
  const visit = (module, trail) => {
    assert.notEqual(state.get(module), 1, `import cycle: ${[...trail, module].join(' -> ')}`);
    if (state.get(module) === 2) return;
    state.set(module, 1);
    const file = path.join(root, 'frontend', module);
    assert.ok(existsSync(file), `missing import: ${module}`);
    const source = readFileSync(file, 'utf8');
    const code = source.replace(/\/\*[\s\S]*?\*\//gu, '');
    assert.ok(!code.includes('import.meta.env') && !code.includes('process.env.NODE_ENV'), `build-time branch: ${module}`);
    const ast = parseAst(source, { lang: module.endsWith('.ts') ? 'ts' : 'js' });
    for (const node of ast.body) {
      if (!['ImportDeclaration', 'ExportNamedDeclaration', 'ExportAllDeclaration'].includes(node.type) || !node.source) continue;
      if (node.importKind === 'type' || node.exportKind === 'type') continue;
      const specifier = node.source.value;
      if (specifier.startsWith('.')) {
        const target = path.posix.normalize(path.posix.join(path.posix.dirname(module), specifier));
        assert.ok(!target.startsWith('../'), `import outside frontend: ${module} -> ${specifier}`);
        if (target.endsWith('.css')) assert.ok(existsSync(path.join(root, 'frontend', target)), `missing CSS: ${target}`);
        else visit(target, [...trail, module]);
      } else {
        const name = specifier.split('/').slice(0, specifier.startsWith('@') ? 2 : 1).join('/');
        assert.ok(!module.endsWith('.js') && Object.hasOwn(packageJson.dependencies, name), `unapproved bare import: ${module} -> ${specifier}`);
      }
    }
    state.set(module, 2);
  };
  visit('src/main.js', []);
});

test('frontend vendors remain inside their owned adapters and cannot enter product contracts', () => {
  const contract = readToml('tests/architecture_contract.toml');
  assert.deepEqual(Object.keys(contract).sort(), ['schema', 'vendor_integration']);
  const integrations = contract.vendor_integration;
  assert.deepEqual(Object.keys(integrations), Object.keys(integrations).sort());
  const approved = new Map();
  for (const [name, record] of Object.entries(integrations)) {
    assert.deepEqual(Object.keys(record).sort(),
      ['allowed_source_roots', 'dispose_owner', 'mount_owner', 'packages', 'update_owner'], name);
    for (const key of ['packages', 'allowed_source_roots']) {
      assert.deepEqual(record[key], [...new Set(record[key])].sort(), `${name}.${key}`);
      assert.ok(record[key].every(value => !/[*?[\]\\]|\.\./u.test(value)), `${name}.${key}: wildcard or unsafe path`);
    }
    for (const entry of record.allowed_source_roots) {
      assert.ok(entry.startsWith('frontend/src/') && existsSync(path.join(root, entry)), entry);
    }
    for (const key of ['mount_owner', 'update_owner', 'dispose_owner']) {
      const [file, symbol, extra] = record[key].split('|');
      assert.ok(!extra && file && symbol && inRoot(file, record.allowed_source_roots)
        && existsSync(path.join(root, file)) && declaredOwner(file, symbol), `${name}.${key}`);
    }
    for (const dependency of record.packages) {
      assert.ok(!approved.has(dependency), `duplicate vendor owner: ${dependency}`);
      approved.set(dependency, record.allowed_source_roots);
    }
  }
  assert.deepEqual([...approved.keys()].sort(), Object.keys(packageJson.dependencies).sort());

  const sources = new Map(globSync('frontend/{src,js}/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}', { cwd: root })
    .map(file => [file.replaceAll('\\', '/').replace(/^frontend\//u, ''), read(file)]));
  assert.ok(sources.has('js/bridge.js') && sources.has('src/main.js'), 'vendor scan covers frontend/src and frontend/js');
  assert.deepEqual(vendorScan(sources, approved), []);
  const bad = new Map([
    ['src/contract/reexport.ts', 'export { thing } from "../editorview/owned.ts";'],
    ['src/editorview/owned.ts', 'import { EditorView } from "@codemirror/view";'],
    ['src/screens/stray.ts', 'export { EditorView } from "@codemirror/view";'],
  ]);
  assert.deepEqual(vendorScan(bad, new Map([['@codemirror/view', ['frontend/src/editorview/owned.ts']]])),
    ['src/contract/reexport.ts -> vendor adapter', 'src/screens/stray.ts -> @codemirror/view']);
  // 우회 형태: 고전 스크립트·CommonJS·import-equals·triple-slash·module.require·절대 경로.
  const evasive = new Map([
    ['js/vendor_probe.js', 'import "react";'],
    ['src/screens/require_probe.cjs', 'require("react");'],
    ['src/screens/equals_probe.ts', 'import React = require("react");'],
    ['src/screens/reference_probe.d.ts', '/// <reference types="react" />\nexport {};'],
    ['src/screens/module_probe.mts', 'module.require("react-dom/client");'],
    ['src/contract/absolute.ts', 'export { x } from "/src/react/owned.ts";'],
    ['src/react/owned.ts', 'import "react";'],
  ]);
  assert.deepEqual(vendorScan(evasive, new Map([['react', ['frontend/src/react']], ['react-dom', ['frontend/src/react']]])), [
    'js/vendor_probe.js -> react',
    'src/contract/absolute.ts -> vendor adapter',
    'src/screens/equals_probe.ts -> react',
    'src/screens/module_probe.mts -> react-dom/client',
    'src/screens/reference_probe.d.ts -> react',
    'src/screens/require_probe.cjs -> react',
  ]);
  for (const source of ['require(name);', 'import(name);', 'module.require(name);']) {
    assert.throws(() => vendorScan(new Map([['src/screens/dynamic.js', source]]), new Map()), /string literal/u);
  }
});

test('production frontend does not import or recompute domain semantics', () => {
  const sources = new Map(globSync('frontend/src/**/*.{js,mjs,ts,tsx}', { cwd: root })
    .map(file => [file.replaceAll('\\', '/').replace(/^frontend\//u, ''), read(file)]));
  assert.deepEqual(semanticAuthorityViolations(sources), []);
  const probe = new Map([
    ['src/domain/canonical_execution_encoding.ts', 'crypto.subtle.digest("SHA-256", data);'],
    ['src/domain/slot_selection.ts', 'export const validateSelectionSet = () => true;'],
    ['src/domain/currentness.ts', 'import { x } from "./slot_selection.ts"; export const declaredSelectionDigest = crypto.subtle.digest("SHA-256", data);'],
    ['src/screens/static.ts', 'import { x } from "../domain/canonical_execution_encoding.ts";'],
    ['src/screens/dynamic.ts', 'await import("../domain/slot_selection.ts");'],
  ]);
  assert.deepEqual(semanticAuthorityViolations(probe), [
    'src/domain/currentness.ts -> crypto.subtle',
    'src/domain/currentness.ts -> declaredSelectionDigest',
    'src/domain/currentness.ts -> src/domain/slot_selection.ts',
    'src/screens/dynamic.ts -> src/domain/slot_selection.ts',
    'src/screens/static.ts -> src/domain/canonical_execution_encoding.ts',
  ]);
  assert.deepEqual(semanticAuthorityViolations(new Map([
    ['src/screens/harmless.ts', '// crypto.subtle\nconst message = "canonicalExecutionDigest";'],
  ])), []);
});
