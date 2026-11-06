import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { CORE, INDEX, MANIFEST, SLOTS, acknowledgeReview, inventory, route, sourceDigest } from '../../scripts/docs_contract_core.mjs';
import { check, writeGenerated } from '../../scripts/docs_contract.mjs';

const put = (root, name, body) => {
  const target = path.join(root, name);
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, body, 'utf8');
};
const read = (root, name) => readFileSync(path.join(root, name), 'utf8');
const encodeRecord = record => Object.entries(record).map(([key, value]) =>
  `${key} = ${JSON.stringify(value)}`).join('\n');

function fixture() {
  const cache = path.join(process.cwd(), '.cache');
  mkdirSync(cache, { recursive: true });
  const root = mkdtempSync(path.join(cache, 'docs-native-'));
  const git = spawnSync('git', ['init', '-q', root], { encoding: 'utf8' });
  assert.equal(git.status, 0, git.stderr);
  put(root, '.node-version', '24.18.1\n');
  put(root, 'rust-toolchain.toml', '[toolchain]\nchannel="1.93.1"\ncomponents=["clippy", "rustfmt"]\n');
  put(root, 'Cargo.toml', '[workspace]\nmembers=["crates/hwpx-core", "crates/hwpx-filler"]\n');
  put(root, 'crates/hwpx-desktop/Cargo.toml', '[package]\nversion="1.0.0"\n[[bin]]\nname="hwpxfiller"\npath="src/bin/hwpxfiller.rs"\n[[bin]]\nname="documentnarmi"\npath="src/bin/documentnarmi.rs"\n');
  put(root, 'crates/hwpx-desktop/src/bin/hwpxfiller.rs', 'fn main() {}\n');
  put(root, 'crates/hwpx-desktop/src/bin/documentnarmi.rs', 'fn main() {}\n');
  put(root, 'crates/hwpx-desktop/src/tauri_host.rs', '// capability-gated native test channel\n');
  put(root, 'package.json', JSON.stringify({ engines: { node: '24.18.1', npm: '11.16.0' },
    packageManager: 'npm@11.16.0' }));
  put(root, '.github/workflows/quality.yml',
    'name: quality\njobs:\n  static:\n    steps: []\n  quality-gate:\n    needs:\n      - static\n    steps: []\n');
  put(root, 'crates/hwpx-desktop/src/host_contract.json', JSON.stringify({
    dispatch_rejection: { key: '__reject__', fields: ['name', 'message'] },
    host_methods: [{ name: 'initial', params: [{ name: 'screen', type: 'string' }] }],
  }));
  put(root, 'crates/hwpx-desktop/src/action_registry.json', JSON.stringify({
    job: { ping: { required: [], optional: ['epoch'] } },
  }));
  put(root, 'src/entry.rs', '// source\n');
  put(root, 'tests/evidence.test.js', 'export const test = true;\n');
  const data = { schema: 'docs-contract/v2', document: [], topic: [], support: [] };
  const hashes = { source_sha256: '0'.repeat(64), body_sha256: '0'.repeat(64) };
  for (const [role, [kind, name]] of Object.entries(SLOTS)) {
    const record = { path: name, kind, role, title: role, max_lines: 500 };
    let body = `# ${role}\n\n`;
    if (kind === 'canonical') {
      const id = `${role}-primary`;
      body += `<a id="${id}"></a>\n## Current\n\noriginal\n`;
      if (role === 'product') body += '\n### Platform\n\nweb\n';
      data.topic.push({ id, document: name, sources: ['src/entry.rs'],
        tests: ['tests/evidence.test.js'], ...hashes });
    } else if (kind === 'current') Object.assign(record, {
      sources: ['src/entry.rs'], tests: ['tests/evidence.test.js'], ...hashes,
    });
    if (kind === 'machine') body = '# Machine contract\n';
    put(root, name, body);
    data.document.push(record);
  }
  put(root, MANIFEST, [
    'schema = "docs-contract/v2"',
    'support = []',
    ...['document', 'topic'].flatMap(kind => data[kind].map(record =>
      `\n[[${kind}]]\n${encodeRecord(record)}`)),
  ].join('\n') + '\n');
  writeGenerated(root);
  for (const topic of data.topic) acknowledgeReview(root, `${topic.document}#${topic.id}`);
  for (const doc of data.document.filter(item => item.kind === 'current')) {
    acknowledgeReview(root, doc.path);
  }
  assert.deepEqual(check(root), []);
  return root;
}

test('docs contract detects source, prose, inventory, link, and review drift without Python', () => {
  const root = fixture();
  try {
    assert.deepEqual(route(root, 'src/entry.rs'), dataOwnerNames(root));
    put(root, 'crates/hwpx-desktop/tests/tutorial_walk.rs', '// native integration evidence\n');
    const nativeEvidence = { document: 'docs/product.md', id: 'product-primary',
      sources: ['src/entry.rs'], tests: ['crates/hwpx-desktop/tests/tutorial_walk.rs'] };
    const nativeDigest = sourceDigest(root, nativeEvidence);
    put(root, 'crates/hwpx-desktop/tests/tutorial_walk.rs', '// changed evidence\n');
    assert.notEqual(sourceDigest(root, nativeEvidence), nativeDigest);
    assert.throws(() => sourceDigest(root, { ...nativeEvidence, tests: ['crates/hwpx-desktop/tests/missing.rs'] }),
      /missing\/invalid evidence test/);
    for (const name of ['crates/hwpx-filler/src/format_engine.rs',
      'crates/hwpx-desktop/src/bin/hwpxfiller.rs', 'crates/hwpx-desktop/src/editor/save.rs',
      'crates/hwpx-desktop/examples/check_rust_coverage.rs']) {
      put(root, name,
        'pub fn render() {}\n#[cfg(test)]\nmod tests {\n  #[test]\n  fn render_round_trip() {}\n}\n');
      const inlineEvidence = { ...nativeEvidence, tests: [name] };
      assert.match(sourceDigest(root, inlineEvidence), /^[a-f0-9]{64}$/);
      put(root, name, 'pub fn render() {}\n');
      assert.throws(() => sourceDigest(root, inlineEvidence), /missing\/invalid evidence test/);
    }
    put(root, 'src/entry.rs', '// changed source\n');
    assert.ok(check(root).some(problem => problem.includes('review required: docs/product.md#product-primary')));
    put(root, 'docs/new.md', '# unregistered\n');
    assert.ok(check(root).some(problem => problem.includes('unregistered=') && problem.includes('docs/new.md')));
    rmSync(path.join(root, 'docs/new.md'));
    put(root, 'src/entry.rs', '// source\n');
    assert.deepEqual(check(root), []);
    writeFileSync(path.join(root, 'src/entry.rs'), Buffer.from('// source\r\n'));
    assert.deepEqual(check(root), []);
    put(root, 'src/entry.rs', '// source\n');
    put(root, 'crates/hwpx-desktop/Cargo.toml', read(root, 'crates/hwpx-desktop/Cargo.toml').replace('1.0.0', '1.1.0'));
    assert.ok(check(root).includes('generated drift: docs/reference/runtime.md'));
    put(root, 'crates/hwpx-desktop/Cargo.toml', read(root, 'crates/hwpx-desktop/Cargo.toml').replace('1.1.0', '1.0.0'));
    put(root, CORE.workflow, read(root, CORE.workflow).replace('original', '[missing](gone.md)'));
    assert.ok(check(root).some(problem => problem.includes('broken local link: docs/workflow.md')));
    assert.throws(() => acknowledgeReview(root, 'docs/workflow.md'));
    put(root, CORE.workflow, read(root, CORE.workflow).replace('[missing](gone.md)', '<IMG SRC="gone.png">'));
    assert.ok(check(root).some(problem => problem.includes('broken local link: docs/workflow.md: gone.png')));
    put(root, CORE.workflow, read(root, CORE.workflow).replace('<IMG SRC="gone.png">', 'original'));
    put(root, MANIFEST, read(root, MANIFEST).replace('sources = ["src/entry.rs"]',
      'sources = ["src/missing/*.rs"]'));
    assert.ok(check(root).some(problem => problem.includes('empty source glob')));
    put(root, MANIFEST, read(root, MANIFEST).replace('sources = ["src/missing/*.rs"]',
      'sources = ["src/entry.rs"]'));
    put(root, CORE.workflow, read(root, CORE.workflow).replace('# workflow\n\n',
      '# workflow\n\nunowned prose\n\n'));
    assert.ok(check(root).some(problem => problem.includes('unowned canonical preamble')));
    put(root, CORE.workflow, read(root, CORE.workflow).replace('unowned prose\n\n', ''));
    rmSync(path.join(root, 'AGENTS.md'));
    assert.ok(check(root).some(problem => problem.includes('missing=') && problem.includes('AGENTS.md')));
    assert.throws(() => route(root, 'unowned-file.rs'), /no document owner/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

const dataOwnerNames = root => {
  const data = inventory(root);
  return [
    ...data.topic.map(item => `${item.document}#${item.id}`),
    ...data.document.filter(item => item.kind === 'current').map(item => item.path),
  ];
};

test('generated docs are written separately from semantic review acknowledgements', () => {
  const root = fixture();
  try {
    const runtime = read(root, 'docs/reference/runtime.md');
    for (const name of ['hwpxfiller', 'documentnarmi']) {
      assert.ok(runtime.includes(`| Cargo binary | \`${name}\` |`));
    }
    assert.ok(runtime.includes('.\\run-filler.ps1 -Cli --template T.hwpx --data data.csv --out out --ledger'));
    const before = read(root, MANIFEST);
    put(root, INDEX, `${read(root, INDEX)}\nmanual drift`);
    assert.ok(check(root).includes(`generated drift: ${INDEX}`));
    writeGenerated(root);
    assert.equal(read(root, MANIFEST), before);
    assert.deepEqual(check(root), []);
    put(root, CORE.workflow, read(root, CORE.workflow).replace('original', 'revised'));
    const target = 'docs/workflow.md#workflow-primary';
    assert.ok(check(root).includes(`review required: ${target}`));
    acknowledgeReview(root, target);
    assert.deepEqual(check(root), []);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
