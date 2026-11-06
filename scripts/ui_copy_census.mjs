// Enforce one reviewed sentence multiset across the React frontend and Rust product.
import { existsSync, globSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readToml } from './read_toml.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const allowlistPath = 'tests/contracts/ui-copy-census.toml';
const jsGlobs = [
  'frontend/src/**/*.ts', 'frontend/src/**/*.tsx', 'frontend/src/**/*.js',
  'frontend/js/*.js',
];
const sentence = /(니다|세요|십시오|까요|네요|군요|(?:[아어여해워와봐줘돼게래]|예|에)요|죠)(?=[.!?…)\]'"」』]|\s|$)/u;
const normalize = value => value.replace(/\s+/gu, ' ').trim();
export const isSentence = text => sentence.test(text);

// docs/ui-style.md#ui-copy owns these narration classes and their legacy exception.
const narrationPatterns = [
  [1, /해야 .{0,20}할 수 있습니다/u, '전제 조건 낭독. 차단은 동작(비활성 + 사유)이 한다'],
  [2, /불러왔습니다|가져왔습니다|복원했습니다/u, '정상 경로 완료 낭독. 화면에 결과가 이미 보인다'],
  [3, /^.{0,40}(입니다|습니다)\s*·\s/u, '문장 뒤에 `·` 로 수치를 이어 붙인 혼합형. 수치만 남긴다'],
  [4, /실제 .{0,10}입니다/u, '시스템 원칙 낭독'],
  [5, /을\(를\) 편집합니다|을\(를\) 봅니다|화면입니다/u, '현재 모드 낭독. 제목이 이미 말한다'],
  [6, /손쉽게|간편하게|간단하게|편리하게|강력한|원활하게|최적화|스마트|직관적|완벽|효율적|매끄러|한눈에|지금 바로|걱정 없이|놀라운|혁신/u, '홍보 상투어. 기능은 동작과 결과가 말한다'],
  [7, /[아어여해워와] ?보세요/u, '권유형 광고 문체(~해 보세요). 명령형 `~하세요` 로 쓴다'],
  [8, /[!！]\s*$|[\u{1F300}-\u{1FAFF}\u2705\u274C\u2728]/u, '감탄·이모지. 문장은 마침표로 끝나고 상태는 표지·라벨이 말한다'],
  [9, /성공적으로|정상적으로/u, '완료 낭독. 정상 경로는 무음이다'],
  [10, /(?:(?:[아어여해워와봐줘돼게래]|예|에)요|죠)[.!?]?$/u, '해요체. 문체는 `~하세요` 명령형과 `~습니다` 서술형만 쓴다'],
];

export function narrationHits(text) {
  return narrationPatterns.filter(([, pattern]) => pattern.test(text)).map(([number, , reason]) => [number, reason]);
}

export function narrationReport(entries = readToml(allowlistPath).sentence) {
  const problems = [];
  for (const entry of entries) {
    const hits = narrationHits(entry.text);
    if (hits.length && !entry.legacy) problems.push(`${entry.file}: ${entry.text}: ${hits.map(([number]) => number).join(', ')}`);
    if (!hits.length && entry.legacy) problems.push(`${entry.file}: legacy flag without narration: ${entry.text}`);
  }
  return problems;
}

function files(globs) {
  return [...new Set(globs.flatMap(glob => globSync(glob, { cwd: root })
    .map(name => name.replaceAll('\\', '/'))))].sort();
}

function lineAt(source, offset) {
  let line = 1;
  for (let index = 0; index < offset; index++) if (source[index] === '\n') line++;
  return line;
}

function skipInterpolation(source, index, line) {
  let depth = 1;
  index += 2;
  while (index < source.length && depth) {
    if (source[index] === '\n') line++;
    else if (source[index] === '{') depth++;
    else if (source[index] === '}') depth--;
    index++;
  }
  return { index, line };
}

function readJsEscape(source, index, line) {
  const following = source[index + 1];
  const escapes = { n: '\n', r: '\r', t: '\t', 0: '\0' };
  if (following === '\n') line++;
  return { index: index + (following === undefined ? 1 : 2), line,
    value: escapes[following] ?? following ?? '' };
}

function readJsString(source, index, line) {
  const quote = source[index++];
  const template = quote === '`';
  let value = '';
  while (index < source.length) {
    const current = source[index];
    if (current === '\\') {
      const escape = readJsEscape(source, index, line);
      value += escape.value;
      ({ index, line } = escape);
    } else if (current === quote) {
      index++;
      break;
    } else if (template && source.startsWith('${', index)) {
      ({ index, line } = skipInterpolation(source, index, line));
      value += '{}';
    } else if (current === '\n' && !template) {
      line++;
      break;
    } else {
      if (current === '\n') line++;
      value += current;
      index++;
    }
  }
  return { index, line, value: normalize(value) };
}

function skipJsComment(source, index, line) {
  if (source.startsWith('//', index)) {
    const end = source.indexOf('\n', index);
    return { index: end < 0 ? source.length : end, line };
  }
  if (source.startsWith('/*', index)) {
    const end = source.indexOf('*/', index + 2);
    const stop = end < 0 ? source.length : end + 2;
    return { index: stop,
      line: line + (source.slice(index, stop).match(/\n/gu) ?? []).length };
  }
  return null;
}

export function scanJs(source) {
  const found = [];
  let index = 0;
  let line = 1;
  while (index < source.length) {
    const char = source[index];
    if (char === '\n') { line++; index++; continue; }
    const comment = skipJsComment(source, index, line);
    if (comment) { ({ index, line } = comment); continue; }
    if (char === "'" || char === '"' || char === '`') {
      const start = line;
      const result = readJsString(source, index, line);
      found.push([start, result.value]);
      ({ index, line } = result);
      continue;
    }
    index++;
  }
  return found;
}

export function scanHtml(source) {
  const blank = whole => '\n'.repeat((whole.match(/\n/gu) ?? []).length);
  const stripped = source.replace(/<!--.*?-->/gsu, blank)
    .replace(/<(script|style)\b[^>]*>.*?<\/\1\s*>/gisu, blank);
  const found = [];
  const tags = /<[^>]*>/gsu;
  let cursor = 0;
  for (const tag of stripped.matchAll(tags)) {
    if (tag.index > cursor) found.push([lineAt(stripped, cursor), normalize(stripped.slice(cursor, tag.index))]);
    for (const attr of tag[0].matchAll(/\b(title|placeholder|aria-label|alt)\s*=\s*(?:"([^"]*)"|'([^']*)')/giu)) {
      found.push([lineAt(stripped, tag.index), normalize(attr[2] ?? attr[3] ?? '')]);
    }
    cursor = tag.index + tag[0].length;
  }
  if (cursor < stripped.length) found.push([lineAt(stripped, cursor), normalize(stripped.slice(cursor))]);
  return found;
}

export function frontendCensus() {
  const rows = [];
  for (const name of files(jsGlobs)) {
    if (name.startsWith('frontend/src/selftest/')) continue;
    for (const [line, text] of scanJs(readFileSync(path.join(root, name), 'utf8')))
      if (sentence.test(text)) rows.push([name, line, text]);
  }
  for (const name of ['frontend/index.html']) {
    for (const [line, text] of scanHtml(readFileSync(path.join(root, name), 'utf8')))
      if (sentence.test(text)) rows.push([name, line, text]);
  }
  return rows;
}

function rustEnvironment() {
  const env = { ...process.env };
  const localCargo = path.join(root, '.cache/rhwp-cargo/bin/cargo.exe');
  if (!env.CARGO_HOME && existsSync(localCargo)) {
    env.CARGO_HOME = path.join(root, '.cache/rhwp-cargo');
    env.RUSTUP_HOME ??= path.join(root, '.cache/rhwp-rustup');
    env.PATH = `${path.dirname(localCargo)}${path.delimiter}${env.PATH ?? ''}`;
  }
  return env;
}

export function rustCensus() {
  const env = rustEnvironment();
  const build = spawnSync('cargo', ['build', '--quiet', '--offline', '--locked',
    '-p', 'hwpx-artifact', '--example', 'ui_copy_literals'],
  { cwd: root, env, encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
  if (build.error) throw build.error;
  if (build.status !== 0) throw new Error(`Rust literal scanner build failed:\n${build.stderr}`);
  const binary = path.resolve(root, env.CARGO_TARGET_DIR ?? 'target', 'debug', 'examples',
    `ui_copy_literals${process.platform === 'win32' ? '.exe' : ''}`);
  const sources = files([
    'crates/hwpx-core/src/**/*.rs', 'crates/hwpx-filler/src/**/*.rs',
    'crates/hwpx-desktop/src/**/*.rs',
  ]);
  const scan = spawnSync(binary, [], {
    cwd: root, env, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
    input: JSON.stringify({ root, files: sources }),
  });
  if (scan.error) throw scan.error;
  if (scan.status !== 0) throw new Error(`Rust literal scanner failed:\n${scan.stderr}`);
  return JSON.parse(scan.stdout).map(row => ({ ...row, text: normalize(row.text) }))
    .filter(row => sentence.test(row.text));
}

export function census() {
  return [...frontendCensus(), ...rustCensus().map(row => [row.file, 0, row.text])];
}

function counts(rows) {
  const result = new Map();
  for (const [file, , text] of rows) {
    const key = JSON.stringify([file, text]);
    result.set(key, (result.get(key) ?? 0) + 1);
  }
  return result;
}

export function diffReport(rows = census(), entries = readToml(allowlistPath).sentence) {
  const actual = counts(rows);
  const expected = counts(entries.map(entry => [entry.file, 0, entry.text]));
  const added = [];
  const removed = [];
  for (const [key, number] of actual) if (number > (expected.get(key) ?? 0)) added.push([JSON.parse(key), number - (expected.get(key) ?? 0)]);
  for (const [key, number] of expected) if (number > (actual.get(key) ?? 0)) removed.push([JSON.parse(key), number - (actual.get(key) ?? 0)]);
  return { added, removed };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 2 &&
      !(process.argv.length === 3 && process.argv[2] === '--check')) {
    process.stderr.write('usage: node scripts/ui_copy_census.mjs [--check]\n');
    process.exitCode = 2;
  } else {
    try {
      const rows = census();
      const { added, removed } = diffReport(rows);
      const narration = narrationReport();
      process.stdout.write(`문장 ${rows.length}건\n`);
      if (process.argv[2] === '--check' && (added.length || removed.length)) {
        process.stderr.write(`census 불일치: 추가 ${added.length}종, 사라짐 ${removed.length}종\n`);
        for (const [[file, text], number] of added) process.stderr.write(`+ ${number} ${file}: ${text}\n`);
        for (const [[file, text], number] of removed) process.stderr.write(`- ${number} ${file}: ${text}\n`);
        process.exitCode = 1;
      }
      if (process.argv[2] === '--check' && narration.length) {
        process.stderr.write(narration.join('\n') + '\n');
        process.exitCode = 1;
      }
    } catch (error) { process.stderr.write(`${error.stack ?? error}\n`); process.exitCode = 1; }
  }
}
