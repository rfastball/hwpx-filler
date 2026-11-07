import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { buildManifest, main, run } from '../../scripts/gen_studio_runtime_manifest.mjs';

test('Studio manifest compares parsed content and writes one LF trailer', () => {
  const root = mkdtempSync(join(tmpdir(), 'studio-manifest-'));
  try {
    const sourceDir = join(root, 'vendor', 'rhwp');
    const outputDir = join(root, 'build', 'rhwp', 'studio');
    mkdirSync(sourceDir, { recursive: true });
    mkdirSync(outputDir, { recursive: true });
    writeFileSync(join(sourceDir, 'source.json'), JSON.stringify({ commit: 'a'.repeat(40) }));
    const html = Buffer.from('<html></html>\n');
    writeFileSync(join(outputDir, 'index.html'), html);
    writeFileSync(join(outputDir, 'app.js'), "window.boot = () => 'ready';\n");
    const expected = buildManifest(outputDir, 'a'.repeat(40));
    assert.deepEqual(expected.files.map(item => item.path), ['studio/app.js', 'studio/index.html']);
    assert.equal(expected.files[1].sha256, createHash('sha256').update(html).digest('hex'));
    const target = join(sourceDir, 'studio-runtime.json');
    const quiet = { root, log: () => {}, error: () => {} };
    const lf = `${JSON.stringify(expected, null, 2)}\n`;
    writeFileSync(target, lf);
    assert.equal(run({ ...quiet, check: true }), 0);
    writeFileSync(target, lf.replaceAll('\n', '\r\n'));
    assert.equal(run({ ...quiet, check: true }), 0);
    writeFileSync(target, JSON.stringify({ files: expected.files, source_commit: expected.source_commit, schema: 1 }));
    assert.equal(run({ ...quiet, check: true }), 0);
    writeFileSync(target, `${JSON.stringify({ ...expected, source_commit: 'b'.repeat(40) }, null, 2)}\n`);
    assert.equal(run({ ...quiet, check: true }), 1);
    assert.equal(run(quiet), 0);
    const written = readFileSync(target, 'utf8');
    assert.ok(!written.includes('\r\n'));
    assert.ok(written.endsWith('\n') && !written.endsWith('\n\n'));
    assert.deepEqual(JSON.parse(written), expected);
    assert.equal(main(['--bogus'], quiet), 1);
    assert.equal(readFileSync(target, 'utf8'), written);
    writeFileSync(join(sourceDir, 'source.json'), '{}');
    assert.equal(main([], quiet), 1);
    assert.equal(readFileSync(target, 'utf8'), written);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
