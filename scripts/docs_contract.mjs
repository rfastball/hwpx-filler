#!/usr/bin/env node
// Route and verify documentation ownership, generated facts, links, and review drift.
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { acknowledgeReview, bodyDigest, CORE, INDEX, inventory, MANIFEST, route,
  safePath, sourceDigest, topicBodies, withoutFences } from './docs_contract_core.mjs';
import { generatedOutputs } from './docs_contract_render.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DOC_SUFFIXES = new Set(['.md', '.markdown', '.mdx', '.rst', '.html', '.htm']);
const read = (root, name) => readFileSync(safePath(root, name), 'utf8')
  .replace(/^\uFEFF/, '').replaceAll('\r\n', '\n');
const sha = text => createHash('sha256').update(text).digest('hex');
const lines = text => text.split('\n').length - (text.endsWith('\n') ? 1 : 0);
const sameSet = (left, right) => left.size === right.size && [...left].every(value => right.has(value));

function htmlUnescape(text) {
  return text.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (_, entity) => {
    const named = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: '\u00A0' };
    if (entity[0] !== '#') return named[entity.toLowerCase()] ?? `&${entity};`;
    const hex = entity[1].toLowerCase() === 'x';
    return String.fromCodePoint(Number.parseInt(entity.slice(hex ? 2 : 1), hex ? 16 : 10));
  });
}

function htmlTags(text) {
  const targets = [];
  const anchors = new Set();
  for (const tag of text.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)) {
    const found = htmlAttributes(tag[1], tag[2]);
    targets.push(...found.targets);
    for (const anchor of found.anchors) anchors.add(anchor);
  }
  return { targets, anchors };
}

function htmlAttributes(tagName, source) {
  const targets = [];
  const anchors = [];
  for (const attr of source.matchAll(/([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/gi)) {
    const name = attr[1].toLowerCase();
    const value = attr[2] ?? attr[3];
    if (!value) continue;
    if (name === 'href' || name === 'src') targets.push(value);
    if (name === 'srcset') targets.push(...value.split(',').filter(Boolean).map(item => item.trim().split(/\s+/)[0]));
    if (name === 'id' || (tagName.toLowerCase() === 'a' && name === 'name')) anchors.push(value);
  }
  return { targets, anchors };
}

function anchors(text) {
  const visible = withoutFences(text);
  const found = htmlTags(visible).anchors;
  const seen = new Map();
  for (const match of visible.matchAll(/^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$/gm)) {
    const title = htmlUnescape(match[1].replace(/<[^>]+>/g, '')).toLowerCase();
    const slug = [...title].filter(char => /[ _\-\p{L}\p{N}\p{M}]/u.test(char)).join('')
      .replaceAll(' ', '-');
    const count = seen.get(slug) ?? 0;
    seen.set(slug, count + 1);
    found.add(`${slug}${count ? `-${count}` : ''}`);
  }
  return found;
}

function linkTargets(text) {
  const visible = withoutFences(text).replace(/`+[^`\n]*`+/g, '');
  const out = [...htmlTags(visible).targets];
  out.push(...inlineLinkTargets(visible));
  out.push(...referenceLinkTargets(visible));
  return out;
}

function inlineLinkTargets(visible) {
  const out = [];
  for (const match of visible.matchAll(/!?\[[^\n]*?\]\(/g)) {
    let depth = 1;
    let at = match.index + match[0].length;
    const start = at;
    while (at < visible.length && depth) {
      const char = visible[at];
      if (char === '\\') { at += 2; continue; }
      if (char === '(') depth++;
      else if (char === ')') depth--;
      at++;
    }
    if (depth) throw new Error('unterminated Markdown link');
    const target = visible.slice(start, at - 1).trim();
    if (target.startsWith('<')) out.push(target.slice(1, target.indexOf('>')));
    else if (target) out.push(target.split(/\s+/)[0]);
  }
  return out;
}

function referenceLinkTargets(visible) {
  const references = new Map([...visible.matchAll(/^ {0,3}\[([^\]]+)\]:\s*<?([^\s>]+)>?/gm)]
    .map(match => [match[1].toLowerCase(), match[2]]));
  for (const match of visible.matchAll(/\[([^\]\n]+)\]\[([^\]\n]*)\]/g)) {
    if (!references.has((match[2] || match[1]).toLowerCase())) {
      throw new Error(`undefined reference link: ${match[2] || match[1]}`);
    }
  }
  return [...references.values()];
}

export function linkProblems(root, name) {
  if (!new Set(['.md', '.html']).has(path.extname(name).toLowerCase())) return [];
  const problems = [];
  const source = safePath(root, name);
  const base = realpathSync(root);
  for (const raw of linkTargets(read(root, name))) {
    problems.push(...oneLinkProblems(root, name, source, base, raw));
  }
  return problems;
}

function oneLinkProblems(root, name, source, base, raw) {
  const targetText = htmlUnescape(raw);
  if (/^[a-z][\w+.-]*:/i.test(targetText) || targetText.startsWith('//')) return [];
  const [pathname, fragment = ''] = targetText.split('#');
  const decoded = decodeURIComponent(pathname);
  const target = decoded ? path.resolve(decoded.startsWith('/') ? root : path.dirname(source),
    decoded.replace(/^\//, '')) : source;
  if (!existsSync(target) || !insideRepository(target, base)) {
    return [`broken local link: ${name}: ${raw}`];
  }
  if (fragment && ['.md', '.html'].includes(path.extname(target).toLowerCase()) &&
      !anchors(readFileSync(target, 'utf8').replaceAll('\r\n', '\n')).has(decodeURIComponent(fragment))) {
    return [`broken anchor: ${name}: ${raw}`];
  }
  return [];
}

function insideRepository(target, base) {
  const actual = realpathSync(target);
  return actual === base || actual.startsWith(`${base}${path.sep}`);
}

function repositoryFiles(root) {
  const git = args => {
    const result = spawnSync('git', ['-C', root, ...args], { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
    if (result.error || result.status !== 0) throw new Error(`git inventory failed: ${result.stderr}`);
    return result.stdout;
  };
  if (realpathSync(git(['rev-parse', '--show-toplevel']).trim()) !== realpathSync(root)) {
    throw new Error('documentation inventory must run at the repository root');
  }
  return new Set(git(['ls-files', '--cached', '--others', '--exclude-standard', '-z'])
    .split('\0').filter(name => name && existsSync(path.join(root, name)) && statSync(path.join(root, name)).isFile()));
}

export function check(root = ROOT) {
  const problems = [];
  let context;
  try {
    const data = inventory(root);
    context = { data, generated: generatedOutputs(root, data), files: repositoryFiles(root) };
  } catch (error) { return [error.message]; }
  const { data, generated, files } = context;
  problems.push(...inventoryProblems(data, files));
  const coreTexts = [];
  for (const item of data.document) {
    const result = documentProblems(root, item, data, generated);
    problems.push(...result.problems);
    if (result.canonicalText) coreTexts.push(result.canonicalText);
  }
  if (coreTexts.reduce((n, text) => n + lines(text), 0) > 850 ||
      coreTexts.reduce((n, text) => n + Buffer.byteLength(text), 0) > 75_000) {
    problems.push('canonical total budget exceeded; remove duplication before splitting files');
  }
  for (const item of data.support) problems.push(...supportProblems(root, item));
  return problems;
}

function inventoryProblems(data, files) {
  const actual = new Set([...files].filter(name =>
    (DOC_SUFFIXES.has(path.extname(name).toLowerCase()) &&
      !['.claude/agents/*.md', '.claude/rules/*.md'].some(glob => path.matchesGlob(name, glob))) ||
    (name.startsWith('docs/') && path.extname(name) === '.toml')));
  const expected = new Set([
    ...data.document.filter(item => DOC_SUFFIXES.has(path.extname(item.path).toLowerCase())).map(item => item.path),
    ...data.support.map(item => item.path), MANIFEST,
  ]);
  const problems = [];
  if (!sameSet(actual, expected)) {
    problems.push(`inventory mismatch: unregistered=${JSON.stringify([...actual].filter(name => !expected.has(name)).sort())}, ` +
      `missing=${JSON.stringify([...expected].filter(name => !actual.has(name)).sort())}`);
  }
  return problems;
}

function canonicalProblems(root, item, data, bodies) {
  const name = item.path;
  const problems = [];
  const topics = data.topic.filter(topic => topic.document === name);
  if (!sameSet(new Set(Object.keys(bodies)), new Set(topics.map(topic => topic.id)))) {
    problems.push(`topic ownership mismatch: ${name}`);
  }
  for (const topic of topics) {
    if (bodies[topic.id] && (sourceDigest(root, topic) !== topic.source_sha256 ||
        sha(bodies[topic.id]) !== topic.body_sha256)) {
      problems.push(`review required: ${name}#${topic.id}`);
    }
  }
  return problems;
}

function reviewProblems(root, item, data) {
  if (item.kind === 'canonical') return canonicalProblems(root, item, data, topicBodies(root, item));
  const observed = sourceDigest(root, item);
  if (item.kind === 'current' && (observed !== item.source_sha256 ||
      bodyDigest(root, item.path) !== item.body_sha256)) return [`review required: ${item.path}`];
  return [];
}

function documentProblems(root, item, data, generated) {
  const { path: name } = item;
  const problems = [];
  let text = '';
  try {
    text = read(root, name);
    if (lines(text) > item.max_lines) problems.push(`line budget exceeded: ${name}`);
    problems.push(...linkProblems(root, name));
    problems.push(...reviewProblems(root, item, data));
    if (name in generated && text !== generated[name]) problems.push(`generated drift: ${name}`);
    return { problems, canonicalText: item.kind === 'canonical' ? text : '' };
  } catch (error) {
    return { problems: [...problems, `${name}: ${error.message}`],
      canonicalText: item.kind === 'canonical' ? text : '' };
  }
}

function supportProblems(root, item) {
  try {
    const problems = ['runtime', 'fixture'].includes(item.kind) ? [] : linkProblems(root, item.path);
    if (item.kind === 'entry' && lines(read(root, item.path)) > 20) {
      problems.push(`support entry must remain a pointer: ${item.path}`);
    }
    return problems;
  } catch (error) { return [`${item.path}: ${error.message}`]; }
}

export function writeGenerated(root = ROOT) {
  for (const [name, text] of Object.entries(generatedOutputs(root, inventory(root)))) {
    const target = safePath(root, name);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, text, 'utf8');
  }
}

export function main(args = process.argv.slice(2), root = ROOT) {
  validateCommand(args);
  if (args[0] === '--route' && args.length <= 2) {
    process.stdout.write(`${route(root, args[1] ?? '').join('\n')}\n`);
  } else if (args[0] === '--write' && args.length === 1) {
    writeGenerated(root);
    process.stdout.write('Generated documents updated; review fingerprints unchanged.\n');
  } else if (args[0] === '--review' && args.length === 2) {
    acknowledgeReview(root, args[1]);
    process.stdout.write(`Review recorded: ${args[1]}; semantic accuracy remains reviewer-owned.\n`);
  } else return checkCommand(args, root);
  return 0;
}

function validateCommand(args) {
  const modes = new Set(['--check', '--write', '--route', '--review']);
  if (args.some((arg, at) => arg.startsWith('--') && !modes.has(arg) &&
      !(at > 0 && ['--route', '--review'].includes(args[at - 1])))) {
    throw new Error('usage: docs_contract.mjs [--check|--write|--route [SOURCE]|--review DOCUMENT#TOPIC]');
  }
}

function checkCommand(args, root) {
  if (args.length && (args[0] !== '--check' || args.length !== 1)) {
    throw new Error('usage: docs_contract.mjs [--check|--write|--route [SOURCE]|--review DOCUMENT#TOPIC]');
  }
  const problems = check(root);
  if (!problems.length) return 0;
  process.stderr.write(`${problems.join('\n')}\n`);
  return 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = main(); }
  catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
