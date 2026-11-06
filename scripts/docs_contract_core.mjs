// Shared ownership, routing, and review-hash mechanics for the Python-free docs gate.
import { createHash } from 'node:crypto';
import { existsSync, globSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { readToml } from './read_toml.mjs';

export const MANIFEST = 'docs/manifest.toml';
export const INDEX = 'docs/README.md';
export const REFERENCE = 'docs/reference/runtime.md';
export const PRODUCT = 'PRODUCT.md';
export const CORE = Object.freeze({
  product: 'docs/product.md', architecture: 'docs/architecture.md',
  workflow: 'docs/workflow.md', 'ui-style': 'docs/ui-style.md', contributing: 'CONTRIBUTING.md',
});
export const SLOTS = Object.freeze({
  ...Object.fromEntries(Object.entries(CORE).map(([role, name]) => [role, ['canonical', name]])),
  navigation: ['generated', INDEX], 'runtime-reference': ['generated', REFERENCE],
  'product-adapter': ['generated', PRODUCT], 'user-entry': ['current', 'README.md'],
  'agents-entry': ['current', 'AGENTS.md'], 'ui-gallery': ['current', 'docs/reference/ui-gallery.html'],
  'coverage-floors': ['machine', 'tests/contracts/package-coverage-floors.toml'],
  'ui-copy-census': ['machine', 'tests/contracts/ui-copy-census.toml'],
  'architecture-contract': ['machine', 'tests/architecture_contract.toml'],
});
const DOCUMENT_FIELDS = new Set(['path', 'kind', 'role', 'title', 'max_lines', 'sources', 'tests',
  'source_sha256', 'body_sha256', 'why_separate']);
const TOPIC_FIELDS = new Set(['id', 'document', 'sources', 'tests', 'source_sha256', 'body_sha256']);
const DOC_SUFFIXES = new Set(['.md', '.markdown', '.mdx', '.rst', '.html', '.htm']);
const fail = message => { throw new Error(message); };
const sameSet = (a, b) => a.size === b.size && [...a].every(value => b.has(value));
const hasOnly = (value, allowed) => Object.keys(value).every(key => allowed.has(key));
const sorted = values => [...values].sort();
const textFile = (root, name) => readFileSync(safePath(root, name), 'utf8')
  .replace(/^\uFEFF/, '').replaceAll('\r\n', '\n');

export function safePath(root, name) {
  if (typeof name !== 'string' || !name || path.isAbsolute(name) || name.includes('\\') ||
      name.split('/').includes('..')) fail(`unsafe relative path: ${name}`);
  const target = path.resolve(root, name);
  const base = path.resolve(root);
  if (target !== base && !target.startsWith(`${base}${path.sep}`)) fail(`path leaves repository: ${name}`);
  assertRealPathInside(base, target, name);
  return target;
}

function assertRealPathInside(base, target, name) {
  const actualRoot = realpathSync(base);
  if (existsSync(target) && realpathSync(target) !== actualRoot &&
      !realpathSync(target).startsWith(`${actualRoot}${path.sep}`)) {
    fail(`path leaves repository: ${name}`);
  }
}

function strings(item, key) {
  const values = item[key] ?? [];
  if (!Array.isArray(values) || values.some(value => typeof value !== 'string' || !value) ||
      new Set(values).size !== values.length) fail(`invalid or duplicate ${key}`);
  return values;
}

function reviewFields(item) {
  if (!strings(item, 'sources').length || !strings(item, 'tests').length) {
    fail('review unit needs sources and tests');
  }
  for (const field of ['source_sha256', 'body_sha256']) {
    if (!/^[a-f0-9]{64}$/.test(item[field] ?? '')) fail(`invalid ${field}`);
  }
}

function normalName(name) {
  const stem = path.parse(name).name;
  return /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(stem) &&
    stem.split('-').every(part => !/^(?:[vsu]\d+|(?:19|20)\d{2,6}|final|new|completion|spike)$/.test(part));
}

function independentDocumentName(item) {
  const { path: name, kind, role } = item;
  return name.startsWith(`docs/${kind}/`) && name.split('/').length === 3 &&
    path.extname(name) === '.md' && normalName(name) &&
    role === `${kind}-${path.parse(name).name}` &&
    typeof item.why_separate === 'string' && !!item.why_separate.trim();
}

function documentRole(item) {
  const { path: name, kind, role } = item;
  if (role in SLOTS) {
    if (kind !== SLOTS[role][0] || name !== SLOTS[role][1]) fail(`role has a fixed kind/path: ${role}`);
    return;
  }
  if (kind !== 'evidence' && kind !== 'research') {
    fail(`unknown document role: ${role}; use --route before adding a file`);
  }
  if (!independentDocumentName(item)) fail(`invalid independent document name/path/reason: ${name}`);
}

function documentReviewFields(item) {
  const { kind } = item;
  strings(item, 'sources');
  strings(item, 'tests');
  if (kind === 'current') reviewFields(item);
  else if ('source_sha256' in item || 'body_sha256' in item) {
    fail('only current entry documents have file review hashes');
  }
  if (kind === 'canonical' && (item.sources?.length || item.tests?.length)) {
    fail('canonical review inputs belong to topics');
  }
}

function documentRequiredFields(item) {
  if (!item || typeof item !== 'object' || !hasOnly(item, DOCUMENT_FIELDS)) fail('unknown document fields');
  for (const key of ['path', 'kind', 'role', 'title']) {
    if (typeof item[key] !== 'string' || !item[key].trim()) fail(`missing/invalid document ${key}`);
  }
}

function registerDocument(root, item, paths, roles) {
  documentRequiredFields(item);
  const { path: name, role } = item;
  safePath(root, name);
  if (paths.has(name) || roles.has(role)) fail(`duplicate document path/role: ${name}`);
  paths.add(name);
  roles.add(role);
  documentRole(item);
  if (!Number.isInteger(item.max_lines) || item.max_lines <= 0) fail(`invalid line budget: ${name}`);
  documentReviewFields(item);
}

function registerTopic(item, seen, owned) {
  if (!item || !sameSet(new Set(Object.keys(item)), TOPIC_FIELDS) ||
      typeof item.id !== 'string' || !/^[a-z][a-z0-9-]*$/.test(item.id)) fail('invalid topic fields');
  if (seen.has(item.id)) fail(`duplicate topic owner: ${item.id}`);
  seen.add(item.id);
  if (!Object.values(CORE).includes(item.document)) fail(`topic must belong to a canonical document: ${item.id}`);
  owned.add(item.document);
  reviewFields(item);
}

const SUPPORT_PATHS = {
  example: name => name.startsWith('examples/') && path.extname(name) === '.md',
  corpus: name => name.startsWith('tests/corpus/') && path.basename(name) === 'README.md',
  fixture: name => name.startsWith('tests/js/fixtures/') && path.extname(name) === '.html',
  runtime: name => name === 'frontend/index.html',
  entry: name => name === 'packaging/README.md',
};
const allowedSupportPath = item => SUPPORT_PATHS[item.kind]?.(item.path) ?? false;

function registerSupport(root, item, paths) {
  if (!item || !sameSet(new Set(Object.keys(item)), new Set(['path', 'kind', 'reason']))) {
    fail('invalid support record');
  }
  const name = item.path;
  safePath(root, name);
  if (paths.has(name) || typeof item.reason !== 'string' || !item.reason.trim()) {
    fail(`duplicate/invalid support document: ${name}`);
  }
  paths.add(name);
  if (!allowedSupportPath(item)) fail(`support kind cannot shelter this path: ${name}`);
  if (path.extname(name) === '.md' && path.basename(name) !== 'README.md' && !normalName(name)) {
    fail(`invalid supporting document name: ${name}`);
  }
}

function assertInventoryShape(data) {
  if (!sameSet(new Set(Object.keys(data)), new Set(['schema', 'document', 'topic', 'support'])) ||
      data.schema !== 'docs-contract/v2') fail('invalid documentation manifest schema');
  if (![data.document, data.topic, data.support].every(Array.isArray)) {
    fail('document/topic/support must be arrays');
  }
}

function assertDocumentInventory(paths, roles) {
  for (const role of Object.keys(SLOTS)) if (!roles.has(role)) fail(`missing fixed document role: ${role}`);
  if ([...paths].filter(name => name.startsWith('docs/') && DOC_SUFFIXES.has(path.extname(name))).length > 10) {
    fail('documentation count budget exceeded');
  }
}

export function inventory(root) {
  const data = readToml(MANIFEST, { cwd: root });
  assertInventoryShape(data);
  const { document: documents, topic: topics, support } = data;
  const paths = new Set();
  const roles = new Set();
  for (const item of documents) registerDocument(root, item, paths, roles);
  assertDocumentInventory(paths, roles);
  const seen = new Set();
  const owned = new Set();
  for (const item of topics) registerTopic(item, seen, owned);
  if (!sameSet(owned, new Set(Object.values(CORE)))) fail('each canonical role needs an owned topic');
  if (support.length > 9) fail('support document count budget exceeded');
  for (const item of support) registerSupport(root, item, paths);
  return data;
}

export function sourcePaths(root, item) {
  const paths = new Set();
  for (const pattern of item.sources ?? []) {
    safePath(root, pattern);
    const hits = [...globSync(pattern, { cwd: root })].map(name => name.replaceAll('\\', '/'))
      .filter(name => statSync(safePath(root, name)).isFile());
    if (!hits.length) fail(`empty source glob: ${pattern}`);
    for (const name of hits) paths.add(name.replaceAll('\\', '/'));
  }
  return sorted(paths);
}

function pythonScope(item) {
  const str = JSON.stringify;
  const arr = values => `[${sorted(values).map(str).join(', ')}]`;
  return `{"owner": ${str(item.document ?? item.path ?? '')}, "sources": ${arr(item.sources ?? [])}, ` +
    `"tests": ${arr(item.tests ?? [])}, "topic": ${str(item.id ?? '')}}`;
}

function validEvidenceTest(root, name) {
  const file = safePath(root, name);
  if (!existsSync(file) || !statSync(file).isFile()) return false;
  if (name.startsWith('tests/') || /^crates\/[^/]+\/tests\/.+\.rs$/.test(name)) return true;
  if (!/^crates\/[^/]+\/(?:src|examples)\/.+\.rs$/.test(name)) return false;
  const source = textFile(root, name);
  return /^\s*#\[cfg\(test\)\]/m.test(source) &&
    /^\s*#\[(?:test|[^\]]+::test)\]/m.test(source);
}

export function sourceDigest(root, item) {
  const digest = createHash('sha256');
  digest.update(`${pythonScope(item)}\0`);
  const files = new Set(sourcePaths(root, item));
  for (const name of item.tests ?? []) {
    if (!validEvidenceTest(root, name)) fail(`missing/invalid evidence test: ${name}`);
    files.add(name);
  }
  for (const name of sorted(files)) digest.update(`${name}\0${textFile(root, name)}\0`);
  return digest.digest('hex');
}

export function bodyDigest(root, name) {
  return createHash('sha256').update(textFile(root, name)).digest('hex');
}

export function withoutFences(text) {
  let fence = '';
  const lines = [];
  for (const line of text.split('\n')) {
    const run = line.match(/^\s{0,3}(`{3,}|~{3,})/)?.[1];
    if (run) {
      if (!fence) fence = run;
      else if (run[0] === fence[0] && run.length >= fence.length) fence = '';
    } else if (!fence) lines.push(line);
  }
  return lines.join('\n');
}

export function topicBodies(root, item) {
  const text = textFile(root, item.path);
  const marker = /^<a id="([a-z][a-z0-9-]*)"><\/a>\s*$/gm;
  const visible = [...withoutFences(text).matchAll(marker)].map(match => match[1]);
  const matches = [...text.matchAll(marker)];
  if (matches.map(match => match[1]).join('\0') !== visible.join('\0')) {
    fail('topic marker examples must not use a literal standalone marker');
  }
  if (!matches.length || text.slice(0, matches[0].index) !== `# ${item.title}\n\n`) {
    fail(`unowned canonical preamble: ${item.path}`);
  }
  if (new Set(visible).size !== visible.length) fail(`duplicate topic marker: ${item.path}`);
  const bodies = {};
  for (let index = 0; index < matches.length; index++) {
    const body = text.slice(matches[index].index, matches[index + 1]?.index ?? text.length);
    if (!/^## .+/m.test(body)) fail(`topic requires a heading: ${matches[index][1]}`);
    bodies[matches[index][1]] = body;
  }
  return bodies;
}

export function route(root, selector = '') {
  const data = inventory(root);
  const selected = [];
  for (const topic of data.topic) {
    const owner = data.document.find(doc => doc.path === topic.document);
    const target = `${topic.document}#${topic.id}`;
    if (topicMatches(owner, topic, target, selector)) selected.push(target);
  }
  for (const doc of data.document) {
    if (documentMatches(doc, selector)) selected.push(doc.path);
  }
  if (!selected.length) fail(`no document owner: '${selector}'; classify the change before writing`);
  return selected;
}

function topicMatches(owner, topic, target, selector) {
  return !selector || [owner.role, topic.id, owner.path, target].includes(selector) ||
    [...topic.sources, ...topic.tests].some(pattern => path.matchesGlob(selector, pattern));
}

function documentMatches(doc, selector) {
  return doc.kind !== 'canonical' && selector && ([doc.role, doc.path].includes(selector) ||
    [...(doc.sources ?? []), ...(doc.tests ?? [])].some(pattern => path.matchesGlob(selector, pattern)));
}

function reviewedItem(root, data, target) {
  const [name, ident = ''] = target.split('#');
  const document = data.document.find(item => item.path === name);
  if (!document) fail(`unknown review destination: ${target}`);
  if (document.kind === 'canonical') {
    const item = data.topic.find(topic => topic.document === name && topic.id === ident);
    if (!item) fail('review must name one canonical topic: document#topic-id');
    return { item, kind: 'topic', field: 'id', value: ident,
      body: createHash('sha256').update(topicBodies(root, document)[ident]).digest('hex') };
  }
  if (document.kind === 'current' && !ident) {
    return { item: document, kind: 'document', field: 'path', value: name,
      body: bodyDigest(root, name) };
  }
  fail('review must name one current document or canonical topic');
}

function replaceReviewHashes(block, values, target) {
  let changed = block;
  for (const [key, hash] of Object.entries(values)) {
    const pattern = new RegExp(`^${key} = "[a-f0-9]{64}"$`, 'gm');
    if ([...changed.matchAll(pattern)].length !== 1) fail(`cannot record review: ${target}: ${key}`);
    changed = changed.replace(pattern, `${key} = "${hash}"`);
  }
  return changed;
}

export function acknowledgeReview(root, target) {
  const data = inventory(root);
  const { item, kind, field, value, body } = reviewedItem(root, data, target);
  const values = { source_sha256: sourceDigest(root, item), body_sha256: body };
  const manifest = textFile(root, MANIFEST);
  const starts = [...manifest.matchAll(/^\[\[(document|topic|support)\]\]$/gm)];
  const index = { document: 0, topic: 0, support: 0 };
  for (let at = 0; at < starts.length; at++) {
    const match = starts[at];
    const record = data[match[1]][index[match[1]]++];
    if (match[1] !== kind || record?.[field] !== value) continue;
    const end = starts[at + 1]?.index ?? manifest.length;
    const block = replaceReviewHashes(manifest.slice(match.index, end), values, target);
    writeFileSync(safePath(root, MANIFEST), manifest.slice(0, match.index) + block + manifest.slice(end), 'utf8');
    return;
  }
  fail(`missing review record: ${target}`);
}
