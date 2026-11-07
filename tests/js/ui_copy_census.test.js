import assert from 'node:assert/strict';
import { test } from 'node:test';

import { frontendCensus, diffReport, isSentence, narrationHits, narrationReport, scanHtml, scanJs } from '../../scripts/ui_copy_census.mjs';
import { readToml } from '../../scripts/read_toml.mjs';

test('frontend copy scanner preserves the existing sentence multiset', () => {
  assert.deepEqual(scanJs('// "주석입니다."\nconst copy = `본문 ${name}입니다.`;'), [
    [2, '본문 {}입니다.'],
  ]);
  assert.deepEqual(scanHtml('<span title="제목입니다.">본문입니다.</span><script>"숨깁니다."</script>'), [
    [1, '제목입니다.'], [1, '본문입니다.'],
  ]);

  const rows = frontendCensus();
  const entries = readToml('tests/contracts/ui-copy-census.toml').sentence
    .filter(entry => entry.file.startsWith('frontend/'));
  assert.deepEqual(diffReport(rows, entries), { added: [], removed: [] });
  const missing = diffReport(rows.slice(1), entries);
  assert.ok(missing.removed.length > 0);
  const extra = diffReport([...rows, ['frontend/index.html', 1, '새 문장입니다.']], entries);
  assert.deepEqual(extra.added, [[["frontend/index.html", '새 문장입니다.'], 1]]);
  const rust = ['crates/hwpx-desktop/src/job_controller.rs', 0, '데이터를 선택하세요.'];
  const expected = [...entries, { file: rust[0], text: rust[2] }];
  assert.deepEqual(diffReport([...rows, rust], expected), { added: [], removed: [] });
  assert.deepEqual(diffReport([...rows, rust, rust], expected).added, [[[rust[0], rust[2]], 1]]);
  assert.deepEqual(diffReport(rows, expected).removed, [[[rust[0], rust[2]], 1]]);
  assert.deepEqual(diffReport([...rows, ['crates/hwpx-filler/src/job.rs', 0, rust[2]]], expected), {
    added: [[['crates/hwpx-filler/src/job.rs', rust[2]], 1]], removed: [[[rust[0], rust[2]], 1]],
  });
});

test('copy style rejects narration and restricts legacy flags to existing narration', () => {
  assert.deepEqual(narrationReport(), []);
  const normal = { file: 'copy.rs', text: '필터를 저장했습니다.' };
  const narration = { file: 'copy.rs', text: '성공적으로 저장했습니다.' };
  assert.equal(narrationReport([normal, { ...narration, legacy: true }]).length, 0);
  assert.equal(narrationReport([narration]).length, 1);
  assert.match(narrationReport([{ ...normal, legacy: true }])[0], /legacy flag/u);
  for (const [number, hit, miss] of [
    [6, '손쉽게 필터를 저장합니다.', '필터를 저장했습니다.'],
    [7, '필터를 만들어 보세요.', '필터를 만드세요.'],
    [8, '필터를 저장했습니다!', '⚠ 파일을 읽을 수 없습니다. 다시 선택하세요.'],
    [9, '성공적으로 저장했습니다.', '저장할 조건이 없습니다.'],
    [10, '필터를 저장했어요.', '확인 필요'],
  ]) {
    assert.ok(narrationHits(hit).some(([found]) => found === number), hit);
    assert.ok(!narrationHits(miss).some(([found]) => found === number), miss);
  }
  for (const text of ['필터를 저장했어요.', '열 이름이에요', '다시 선택하세요.']) assert.ok(isSentence(text), text);
  assert.ok(!isSentence('확인 필요'));
  assert.ok(!narrationHits('다시 선택하세요.').some(([number]) => number === 10));
});
