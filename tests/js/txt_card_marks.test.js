import test from "node:test";
import assert from "node:assert/strict";
import { lintpadDecorations } from "../../frontend/src/editorview/txt_lintpad.ts";
import { cardMarks } from "../../frontend/src/screens/workbench.ts";

// #1148 PR B — 검토·복사 작업대 본문의 표식 층. 종류·자리·채움은 Python 이 낸다(`card.marks`,
// tests/test_txt_card_edit.py 가 그 판정을 잰다). 여기서는 받은 표식을 그리고, 편집 뒤에도 자리를 옮겨
// 들며, 빈 자리에 친 글자가 그 표식의 범위(값 칠)가 되는지만 잰다.

const DOC = "담당: \n비고: \n수신 회계과";
const MARKS = cardMarks([
  { kind: "blank", name: "담당", start: 4, end: 4 },
  { kind: "declared", name: "비고", start: 9, end: 9 },
  { kind: "fill", name: "수신", start: 13, end: 16 },
]);
const marksOf = (drawn) => drawn.filter((item) => item.layer === "mark");

test("표식 변환 — 빈 값·비워 둠은 표지 문구와 채움 칠을, 값은 칠만 진다", () => {
  assert.deepEqual(MARKS, [
    { start: 4, end: 4, className: "seg-blank", token: "담당", label: "〈빈 값〉", filledClassName: "seg-fill" },
    { start: 9, end: 9, className: "seg-declared", token: "비고", label: "〈비워 둠〉", filledClassName: "seg-fill" },
    { start: 13, end: 16, className: "seg-fill", token: "수신" },
  ]);
  assert.deepEqual(cardMarks(null), []);
});

test("표식 층 — 길이 0 은 그 자리의 표지, 범위는 글자 칠", () => {
  assert.deepEqual(marksOf(lintpadDecorations(DOC, { marks: MARKS })), [
    { layer: "mark", from: 4, to: 4, className: "seg-blank", label: "〈빈 값〉" },
    { layer: "mark", from: 9, to: 9, className: "seg-declared", label: "〈비워 둠〉" },
    { layer: "mark", from: 13, to: 16, className: "seg-fill" },
  ]);
});

test("빈 자리에 친 글자는 그 표식의 범위가 되고 값 칠로 바뀐다 — 뒤의 표식은 함께 밀린다", () => {
  const drawn = lintpadDecorations(DOC, { marks: MARKS, edits: [{ start: 4, end: 4, text: "홍길동" }] });
  assert.equal(drawn.doc, "담당: 홍길동\n비고: \n수신 회계과");
  assert.deepEqual(marksOf(drawn), [
    { layer: "mark", from: 4, to: 7, className: "seg-fill" },
    { layer: "mark", from: 12, to: 12, className: "seg-declared", label: "〈비워 둠〉" },
    { layer: "mark", from: 16, to: 19, className: "seg-fill" },
  ]);
});

test("Python 이 본 문서와 지금 문서가 다르면 받은 표식을 덮지 않는다(편집 왕복 사이)", () => {
  const drawn = lintpadDecorations(DOC, {
    marks: MARKS,
    edits: [{ start: 4, end: 4, text: "홍" }],
    updates: [{ sourceDoc: DOC, marks: [] }],
  });
  assert.equal(marksOf(drawn).length, 3, "옛 문서 기준 표식(빈 목록)이 지금 문서의 표식을 지우지 않는다");
});
