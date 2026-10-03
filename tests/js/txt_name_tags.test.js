import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { lintpadDecorations, lintpadPieces, snapOutOfTokens } from "../../frontend/src/editorview/txt_lintpad.ts";

// FB-03(#1079) — TXT 편집면은 표기 원문 대신 HWPX 편집면과 같은 이름표를 그린다. 이름·짝은 Python 이 준다
// (`analysis.spans[].label/region/role/paired`, tests/test_text_structure.py 가 그 판정을 잰다). 여기서는 받은 것을
// 가리고·그리고·원자 범위로 세우고·편집 뒤에도 원문 좌표를 지키는지만 잰다.

const DOC = "제목: {{공고명}}\n{{#항목 사유 변경 사유}}\n본문 {{담당}}\n{{/항목}}\n";
// 줄 머리: 0(제목) · 12(여는 표기, 줄바꿈 28) · 29(본문) · 38(닫는 표기, 줄바꿈 45) · 문서 길이 46
const at = (source) => DOC.indexOf(source);
const span = (kind, source, extra = {}) => ({ kind, start: at(source), end: at(source) + source.length, source, ...extra });
const SPANS = [
  span("field", "{{공고명}}", { label: "공고명" }),
  span("marker", "{{#항목 사유 변경 사유}}", { label: "변경 사유", region: "slot", role: "open", paired: true }),
  span("field", "{{담당}}", { label: "담당" }),
  span("marker", "{{/항목}}", { label: "변경 사유", region: "slot", role: "close", paired: true }),
];
const REGIONS = [{ kind: "slot", start: 12, end: 46 }];

test("FB-03: every named token is hidden behind its name tag, and the hidden ranges are exactly the atomic ranges", () => {
  const drawn = lintpadDecorations(DOC, { spans: SPANS });
  const tokens = drawn.filter((item) => item.layer === "token");
  assert.deepEqual(tokens.map(({ from, to, className, label, role }) => [DOC.slice(from, to), className, label, role]), [
    ["{{공고명}}", "cm-txtField", "공고명", undefined],
    ["{{#항목 사유 변경 사유}}", "cm-txtMarker", "변경 사유", "open"],
    ["{{담당}}", "cm-txtField", "담당", undefined],
    // 닫는 표기는 짝이 된 여는 표기의 이름을 보인다(Python 이 짝지은 이름).
    ["{{/항목}}", "cm-txtMarker", "변경 사유", "close"],
  ]);
  // 원문 위 강조(mark)는 하나도 남지 않는다 — 모든 표기가 이름표로 가려졌다.
  assert.equal(drawn.filter((item) => item.layer === "span").length, 0);
  // 원자 범위 facet 이 편집기에 내주는 범위 = 가린 토큰 — 캐럿·지우기가 그 안에 서지 않는다.
  assert.deepEqual(drawn.atoms, tokens.map(({ from, to }) => ({ from, to })));
  // 원문은 문서에 그대로다(가릴 뿐 바꾸지 않는다).
  assert.equal(drawn.doc, DOC);
});

test("FB-03: tokens Python could not name, clipped tokens and stale coordinates stay visible as source", () => {
  const pieces = lintpadPieces([
    { kind: "marker", start: 0, end: 9, source: "{{#그밖 x}}", label: "", region: "", role: "open" },    // 알 수 없는 키워드
    { kind: "field", start: 10, end: 17, source: "{{공고명}}", label: "공고명" },                         // 판정 뒤 문서가 바뀜
    { kind: "field", start: 18, end: 26, source: "{{긴 이름}}", label: "긴 이름" },                        // 문서 끝에서 잘림
    { kind: "marker", start: 0, end: 3, label: "x", region: "slot", role: "open" },                        // 앞 조각과 겹침
  ], "{{#그밖 x}}\n{{공고X}}\n{{긴");
  assert.deepEqual(pieces, [
    { from: 0, to: 9, className: "cm-txtMarker" },
    { from: 10, to: 17, className: "cm-txtField" },
    { from: 18, to: 21, className: "cm-txtField" },
  ]);
});

test("FB-03: the document view keeps the names but drops colour, marks and region bars (HWPX document view has no marks)", () => {
  const drawn = lintpadDecorations(DOC, { spans: [...SPANS, { kind: "field", start: 0, end: 3 }], labels: "none", regions: REGIONS });
  assert.deepEqual(drawn.filter((item) => item.layer === "token").map(({ className, label }) => [className, label]), [
    ["cm-txtToken", "공고명"], ["cm-txtToken cm-txtToken-marker", "변경 사유"], ["cm-txtToken", "담당"], ["cm-txtToken cm-txtToken-marker", "변경 사유"],
  ]);
  assert.equal(drawn.filter((item) => item.layer === "span" || item.layer === "region").length, 0);
  // 조용한 이름표도 원문을 가린다 — 원자 범위는 그대로다.
  assert.equal(drawn.atoms.length, 4);
});

test("FB-03: region bars follow the HWPX labels vocabulary — selected strengthens only the range under the caret, all strengthens every range", () => {
  const nested = "밖\n{{#항목 a}}\n{{#선택 가}}\n가\n{{/선택}}\n{{/항목}}\n";
  // 줄 머리: 0 · 2(항목) · 12(선택) · 22(가) · 24(닫는 선택) · 32(닫는 항목) · 길이 40
  const regions = [{ kind: "slot", start: 2, end: 40 }, { kind: "option", start: 12, end: 32 }];
  const lines = (spec) => lintpadDecorations(nested, { regions, ...spec }).filter((item) => item.layer === "region")
    .map(({ from, className }) => [from, className]);
  assert.deepEqual(lines({ labels: "selected", caret: 0 }), [
    [2, "cm-txtRegion-slot"], [12, "cm-txtRegion-option cm-txtRegion-slot"], [22, "cm-txtRegion-option cm-txtRegion-slot"],
    [24, "cm-txtRegion-option cm-txtRegion-slot"], [32, "cm-txtRegion-slot"],
  ]);
  // 캐럿이 선택 안(가 줄)이면 선택과 그 항목이 짙어진다.
  assert.deepEqual(lines({ labels: "selected", caret: 22 }).map(([from, className]) => [from, className.includes("-strong")]), [
    [2, true], [12, true], [22, true], [24, true], [32, true],
  ]);
  assert.match(lines({ labels: "selected", caret: 22 })[0][1], /^cm-txtRegion-slot cm-txtRegion-slot-strong$/);
  // 캐럿이 항목 안·선택 밖(닫는 항목 줄)이면 항목만 짙다.
  assert.deepEqual(lines({ labels: "selected", caret: 32 })[1], [12, "cm-txtRegion-option cm-txtRegion-slot cm-txtRegion-slot-strong"]);
  assert.ok(lines({ labels: "all", caret: 0 }).every(([, className]) => className.split(" ").filter((name) => name.endsWith("-strong")).length
    === className.split(" ").filter((name) => !name.endsWith("-strong")).length));
  assert.deepEqual(lines({ labels: "none", caret: 22 }), []);
});

test("FB-03: offsets stay source offsets — an edit before or after a name tag moves it with its token, atoms included", () => {
  const before = lintpadDecorations(DOC, { spans: SPANS, edits: [{ start: 0, end: 0, text: "[안내] " }] });
  const shift = "[안내] ".length;
  const tokens = before.filter((item) => item.layer === "token");
  assert.deepEqual(tokens.map(({ from, to }) => before.doc.slice(from, to)), ["{{공고명}}", "{{#항목 사유 변경 사유}}", "{{담당}}", "{{/항목}}"]);
  assert.deepEqual(tokens.map(({ from }) => from), SPANS.map((item) => item.start + shift));
  assert.deepEqual(before.atoms, tokens.map(({ from, to }) => ({ from, to })));
  // 필드 바로 뒤에 친 글자는 토큰 밖이다(원자 범위는 끝에 붙은 입력을 삼키지 않는다).
  const after = lintpadDecorations(DOC, { spans: SPANS, edits: [{ start: SPANS[0].end, end: SPANS[0].end, text: " 건" }] });
  const field = after.filter((item) => item.layer === "token")[0];
  assert.equal(after.doc.slice(field.from, field.to), "{{공고명}}");
  assert.equal(after.doc.slice(field.to, field.to + 2), " 건");
  // 토큰 바로 앞에 친 글자도 토큰 밖이다.
  const front = lintpadDecorations(DOC, { spans: SPANS, edits: [{ start: SPANS[2].start, end: SPANS[2].start, text: "새" }] });
  const moved = front.filter((item) => item.layer === "token")[2];
  assert.equal(front.doc.slice(moved.from - 1, moved.to), "새{{담당}}");
});

test("late TXT analysis preserves mapped name tags and atomic ranges until its source matches", () => {
  const text = "가나 " + DOC;
  const shifted = (by) => SPANS.map((span) => ({ ...span, start: span.start + by, end: span.end + by }));
  for (const labels of ["selected", "all", "none"]) {
    for (const stale of [
      { sourceDoc: "가 " + DOC, spans: shifted(2) },
      { sourceDoc: text.replace("제목", "문서"), spans: [] },
    ]) {
      const spec = { spans: SPANS, edits: [{ start: 0, end: 0, text: "가나 " }], updates: [{ ...stale, labels }] };
      const drawn = lintpadDecorations(DOC, spec);
      const tokens = drawn.filter((item) => item.layer === "token");
      assert.equal(tokens.length, SPANS.length, "늦은 분석이 이름표를 지우면 원문이 노출된다");
      assert.deepEqual(tokens.map(({ from, to }) => [from, to, drawn.doc.slice(from, to)]),
        shifted(3).map(({ start, end, source }) => [start, end, source]));
      assert.deepEqual(drawn.atoms, tokens.map(({ from, to }) => ({ from, to })));
      assert.equal(tokens[0].className, labels === "none" ? "cm-txtToken" : "cm-txtField");
      assert.equal(drawn.doc, text, "장식 갱신은 입력한 본문을 바꾸지 않는다");
      const current = lintpadDecorations(DOC, { ...spec, updates: [...spec.updates, { sourceDoc: text, spans: [] }] });
      assert.equal(current.filter((item) => item.layer === "token").length, 0, "현재 분석의 토큰 해제는 적용한다");
      assert.deepEqual(current.atoms, []);
    }
  }
});

test("FB-03: coordinates from outside (problems, search, outline) never leave the caret inside a hidden token", () => {
  const atoms = [{ from: 4, to: 11 }, { from: 20, to: 30 }];
  assert.deepEqual(snapOutOfTokens(atoms, 6, 6), [4, 4], "가까운 앞 경계");
  assert.deepEqual(snapOutOfTokens(atoms, 9, 9), [11, 11], "가까운 뒤 경계");
  assert.deepEqual(snapOutOfTokens(atoms, 4, 11), [4, 11], "토큰 전체는 그대로");
  assert.deepEqual(snapOutOfTokens(atoms, 6, 25), [4, 30], "걸친 토큰을 통째로 담는다");
  assert.deepEqual(snapOutOfTokens(atoms, 25, 6), [30, 4], "뒤로 고른 방향은 지킨다");
  assert.deepEqual(snapOutOfTokens(atoms, 12, 15), [12, 15], "토큰 밖은 그대로");
});

test("FB-03: problem underlines stay their own layer over a name tag (IDE-05 layering)", () => {
  const drawn = lintpadDecorations(DOC, { spans: SPANS, problems: [{ severity: "error", start: 12, end: 29, message: "닫는 표지가 없습니다." }] });
  assert.deepEqual(drawn.filter((item) => item.layer === "problem").map(({ from, to, className }) => [from, to, className]),
    [[12, 28, "cm-authoring-problem-error"]]);
  assert.equal(drawn.filter((item) => item.layer === "token").length, 4);
});

test("FB-03: TXT name tags speak the HWPX editor's colours — semantic tokens equal the rhwp overlay palette", () => {
  const tokens = JSON.parse(readFileSync(new URL("../../src/hwpxfiller/viewmodel/design_tokens.json", import.meta.url), "utf8"));
  const patch = readFileSync(new URL("../../vendor/rhwp/patches/authoring.patch", import.meta.url), "utf8");
  for (const kind of ["field", "slot", "option"]) {
    const rhwp = patch.match(new RegExp(`--rhwp-semantic-${kind}: (#[0-9a-f]{6});`, "i"));
    assert.ok(rhwp, `rhwp ${kind} 색이 없습니다`);
    assert.equal(tokens.semantic[kind].toLowerCase(), rhwp[1].toLowerCase(), `${kind} 색이 HWPX 편집면과 갈렸습니다`);
  }
  // 편집면 CSS 는 그 토큰만 쓴다(색 리터럴 없음).
  const editor = readFileSync(new URL("../../frontend/css/editor.css", import.meta.url), "utf8");
  for (const kind of ["field", "slot", "option"]) assert.match(editor, new RegExp(`var\\(--a-sem-${kind}\\)`));
});
