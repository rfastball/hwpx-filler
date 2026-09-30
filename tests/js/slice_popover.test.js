/* 「가공」 칩·팝오버(`slice_popover.ts`) — 판정은 하나도 여기 없다.
 *
 * 입력은 Python 투영 그대로다(`fixtures/slice_popover.json` — `tests/test_slice_popover_fixture.py`
 * 가 `slice_assist` 로 다시 지어 대조한다). 이 파일이 재는 것은 넷이다: ①방식 문장 조각을 Python
 * 순서대로 그리는가(글자·입력 칸·몇째 선택, 접근 이름) ②입력 글자를 명세로 모으는 규약 — 불완전은
 * 보내지 않고, 새 명세는 Python 이 준 빠짐 처리 기본값(원본 그대로)을 싣고, 지금 명세를 고치면
 * 그 빠짐 처리를 잇는다 ③미리보기·후보 꼬리표·빈 값 표식·빠짐 처리 단추가 Python 값 그대로 서는가
 * ④칩의 잠김·문장·접근 이름. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  SliceCell,
  SlicePopoverView,
  composeSliceSpec,
  flatMethods,
  missPolicyFor,
  sameSpec,
  seedInputs,
  sliceKeyAction,
} from "../../frontend/src/screens/slice_popover.ts";

const FIXTURE = JSON.parse(readFileSync(new URL("./fixtures/slice_popover.json", import.meta.url), "utf8"));
const METHODS = flatMethods(FIXTURE.methods);
const method = (mode) => METHODS.find((item) => item.mode === mode);

function view(extra) {
  return renderToStaticMarkup(createElement(SlicePopoverView, Object.assign({
    field: "계약금액", column: "계약금액", spec: null, groups: FIXTURE.methods,
    preview: FIXTURE.preview_none, tags: {}, message: "", selected: null, inputs: {},
  }, extra || {})));
}

const PORT = {
  doc: null, open: false, toggle() {}, close() {},
  commit: async () => true, preview: async () => ({}), propose: async () => ({}),
};

/* ---- ① 방식 목록 ---- */

test("방식 목록 — 두 무리와 문장 조각을 Python 순서대로 그린다", () => {
  assert.deepEqual(FIXTURE.methods.map((group) => group.label), ["일부만 쓰기", "글자 고치기"]);
  assert.deepEqual(METHODS.map((item) => item.mode),
    ["before", "after", "between", "split", "head", "tail", "chars", "replace", "remove"]);
  const markup = view();
  assert.ok(markup.indexOf("일부만 쓰기") < markup.indexOf("글자 고치기"));
  for (const label of ["앞까지의 기준 글자", "뒤부터의 기준 글자", "나누는 글자", "몇째 조각",
    "앞에서 글자 수", "뒤에서 글자 수", "몇 번째 글자부터", "글자 수", "찾을 글자", "바꿀 글자", "지울 글자"]) {
    assert.ok(markup.includes(`aria-label="${label}"`), `접근 이름 ${label}`);
  }
  for (const word of ["앞까지", "뒤부터", "로 나눈 조각 중", "앞에서", "뒤에서", "번째 글자부터", "글자", "대신", "지우기"]) {
    assert.ok(markup.includes(`>${word}<`), `문장 조각 ${word}`);
  }
  assert.ok(!markup.includes("가공 없음"), "「가공 없음」 줄은 없다 — 해제는 바닥의 「가공 지우기」");
  const radios = markup.match(/type="radio"/g) || [];
  assert.equal(radios.length, 9);
});

test("몇째 선택지는 Python 이 낸다 — 저장된 흔치 않은 번째도 선다", () => {
  const plain = view();
  assert.ok(plain.includes(">첫째<") && plain.includes(">마지막<"));
  assert.ok(!plain.includes("다섯째"));
  const unusual = view({ groups: FIXTURE.methods_split5, spec: { mode: "split", delimiter: ",", index: 5 },
    selected: "split", inputs: seedInputs({ mode: "split", delimiter: ",", index: 5 }) });
  assert.ok(unusual.includes(">다섯째<"));
  assert.match(unusual, /<option value="5" selected="">다섯째<\/option>/);
});

/* ---- ② 명세 모으기 ---- */

test("명세 모으기 — 불완전은 null, 글자 칸의 공백 한 칸은 값이다", () => {
  assert.equal(composeSliceSpec(method("before"), {}, null, null), null);
  assert.deepEqual(composeSliceSpec(method("split"), { delimiter: " " }, null, null),
    { mode: "split", delimiter: " ", index: 1, on_missing: "keep" }, "몇째는 보이는 첫 선택지");
  assert.equal(composeSliceSpec(method("head"), { count: "" }, null, null), null);
  assert.equal(composeSliceSpec(method("head"), { count: "3.5" }, null, null), null);
  assert.deepEqual(composeSliceSpec(method("head"), { count: " 11 " }, null, null),
    { mode: "head", count: 11 }, "앞에서 N글자는 빠짐이 없어 빠짐 처리를 싣지 않는다");
  assert.deepEqual(composeSliceSpec(method("chars"), { start: "3" }, null, null),
    { mode: "chars", start: 3, on_missing: "keep" }, "글자 수는 비우면 끝까지");
  assert.equal(composeSliceSpec(method("replace"), { find: "(주)", replace: "" }, null, null), null,
    "빈 「바꿀 글자」는 보내지 않는다(지우기가 따로 있다)");
  assert.deepEqual(composeSliceSpec(method("remove"), { find: "(VAT 포함)" }, null, null),
    { mode: "remove", find: "(VAT 포함)" });
});

test("빠짐 처리 — 새 명세는 Python 기본값(원본 그대로), 같은 방식을 고치면 지금 값을 잇는다", () => {
  const before = method("before");
  const after = method("after");
  assert.equal(before.on_missing, "keep");
  assert.equal(method("head").on_missing, null);
  assert.equal(missPolicyFor(before, null, null), "keep", "새 가공");
  // v0.10.0 이 저장한 명세(키 없음 = 빈 값)를 고칠 때는 그 뜻을 바꾸지 않는다.
  const legacy = { mode: "split", delimiter: "-", index: 1 };
  assert.equal(missPolicyFor(method("split"), legacy, method("split")), "empty");
  assert.deepEqual(composeSliceSpec(method("split"), { delimiter: "/", index: "1" }, legacy, method("split")),
    { mode: "split", delimiter: "/", index: 1 });
  // 사람이 빠짐 처리를 고르는 방식끼리 옮기면 고른 값을 잇는다.
  const chosen = { mode: "before", delimiter: "-", on_missing: "empty" };
  assert.equal(missPolicyFor(after, chosen, before), "empty");
  // 고르는 칸이 없던 방식에서 옮기면 새 명세다.
  assert.equal(missPolicyFor(after, legacy, method("split")), "keep");
});

test("같은 명세 판정 — 키 순서·빈 값의 두 철자를 접는다", () => {
  assert.ok(sameSpec({ mode: "split", delimiter: "-", index: 1 }, { index: 1, delimiter: "-", mode: "split" }));
  assert.ok(sameSpec({ mode: "before", delimiter: "-" }, { mode: "before", delimiter: "-", on_missing: "empty" }));
  assert.ok(!sameSpec({ mode: "before", delimiter: "-" }, { mode: "before", delimiter: "-", on_missing: "keep" }));
  assert.ok(sameSpec(null, null));
  assert.ok(!sameSpec(null, { mode: "head", count: 1 }));
});

test("입력 칸 씨앗 — 명세의 방식 칸만, 빠짐 처리는 칸이 아니다", () => {
  assert.deepEqual(seedInputs(null), {});
  assert.deepEqual(seedInputs({ mode: "between", open: "(", close: ")", on_missing: "keep" }),
    { between: { open: "(", close: ")" } });
});

test("키 — 한글 조합 중 Enter·Escape 는 뜻이 없다", () => {
  assert.equal(sliceKeyAction({ key: "Enter" }), "commit");
  assert.equal(sliceKeyAction({ key: "Escape" }), "close");
  assert.equal(sliceKeyAction({ key: "Enter", isComposing: true }), null);
  assert.equal(sliceKeyAction({ key: "Escape", keyCode: 229 }), null);
  assert.equal(sliceKeyAction({ key: "a" }), null);
});

/* ---- ③ 미리보기·후보 ---- */

test("가공 없음 — 안내 한 문장, 예시 값은 흐린 원본, 빈 행은 잠긴 칩", () => {
  const markup = view();
  assert.ok(markup.includes("쓸 부분을 끌어 고르거나 방식을 고르세요."));
  assert.ok(markup.includes('aria-label="예시 값"'));
  assert.ok(markup.includes('title="예시 값: 쓸 부분을 끌어 고르면 방식이 맞춰집니다"'));
  assert.ok(markup.includes('aria-label="5행, 빈 값"') && /aria-label="5행, 빈 값"[^>]*disabled=""/.test(markup));
  assert.ok(markup.includes("불러온 5행 미리보기"));
  assert.ok(markup.includes("빈 값 1행"));
  assert.ok(!markup.includes("맞음"), "가공이 없으면 맞음을 세지 않는다");
  assert.ok(markup.includes("〘미입력·계약금액〙"), "빈 칸의 결과는 생성이 넣는 표식 그대로");
  assert.match(markup, /data-act="slice-clear"[^>]*disabled=""/, "지울 가공이 없다");
});

test("가공 있음 — 남긴 자리·결과·요약·빠짐 처리 단추가 Python 값 그대로 선다", () => {
  const spec = FIXTURE.preview_before.slice;
  assert.deepEqual(spec, { mode: "before", delimiter: "원", on_missing: "keep" });
  const markup = view({ spec, preview: FIXTURE.preview_before, selected: "before", inputs: seedInputs(spec) });
  assert.ok(markup.includes('<span class="slicepop-keep">170,309,180</span>원 (VAT 포함)'));
  assert.ok(markup.includes("맞음 4행 · 빈 값 1행"));
  assert.ok(markup.includes("‘원’ 없는 행"));
  assert.match(markup, /aria-pressed="true" data-slice-miss="keep">원본 그대로</);
  assert.match(markup, /aria-pressed="false" data-slice-miss="empty">빈 값</);
  assert.match(markup, /<label class="slice-method on" data-slice-method="before">/);
  assert.match(markup, /<input type="radio" name="slice-method" checked="" value="before"\/>/);
});

test("사이 — 빠진 행은 「확인 필요」로 세고 꼬리표를 단다", () => {
  const spec = FIXTURE.preview_between.slice;
  const markup = view({ spec, preview: FIXTURE.preview_between, selected: "between", inputs: seedInputs(spec) });
  assert.ok(markup.includes("‘(’ 또는 ‘)’ 없음"));
  assert.ok(markup.includes("‘(’ 또는 ‘)’ 없는 행"));
  assert.match(markup, /확인 필요 1행/);
  assert.match(markup, /aria-pressed="true" data-slice-miss="empty">빈 값</, "키 없는 명세는 빈 값");
});

test("후보 꼬리표 — 맞는 방식 줄에 N/M행 맞음과 툴팁", () => {
  const candidates = FIXTURE.propose_amount.candidates;
  assert.equal(candidates[0].label, "‘원’ 앞까지");
  assert.deepEqual(candidates[0].slice, { mode: "before", delimiter: "원", on_missing: "keep" });
  const tags = Object.fromEntries(candidates.map((item) => [item.mode, item]));
  const markup = view({ tags });
  assert.match(markup, /<span class="slice-tag good" title="맞는 행: 값 있는 4행 중 4행">4\/4행 맞음<\/span>/);
  assert.match(markup, /<span class="slice-tag bad" title="맞는 행: 값 있는 4행 중 1행">1\/4행 맞음<\/span>/);
});

test("후보 없음 — Python 문장이 안내 자리를 대신한다", () => {
  assert.deepEqual(FIXTURE.propose_none.candidates, []);
  const markup = view({ message: FIXTURE.propose_none.message });
  assert.ok(markup.includes("고른 부분에 맞는 방식이 없습니다. 방식을 직접 고르세요."));
  assert.ok(!markup.includes("쓸 부분을 끌어 고르거나"));
});

test("머리·바닥 — 필드 이름·데이터 열, 닫기·가공 지우기·완료", () => {
  const markup = view({ spec: { mode: "head", count: 3 } });
  assert.ok(markup.includes(">계약금액 가공<") && markup.includes(">데이터 열 계약금액<"));
  assert.ok(markup.includes('role="dialog"') && markup.includes('aria-modal="false"'));
  assert.ok(markup.includes('aria-label="닫기"'));
  assert.ok(markup.includes(">가공 지우기<") && markup.includes(">완료<"));
});

/* ---- ④ 칩 ---- */

test("칩 — 문장은 Python 값, 없으면 점선 칩, 잠긴 행은 disabled(웹 재판정 0)", () => {
  const chip = (row) => renderToStaticMarkup(createElement(SliceCell, {
    row, field: "공고번호", port: PORT, chipProps: { "data-act": "row-slice", "data-index": 0 },
  }));
  const set = chip({ slice: { mode: "before", delimiter: "-" }, slice_label: "‘-’ 앞까지", slice_enabled: true });
  assert.match(set, /class="slicechip set"/);
  assert.ok(set.includes('aria-label="공고번호 가공"') && set.includes('aria-haspopup="dialog"'));
  assert.ok(set.includes(">‘-’ 앞까지<") && set.includes('title="‘-’ 앞까지"'));
  const add = chip({ slice: null, slice_label: "+ 가공", slice_enabled: true });
  assert.match(add, /class="slicechip add"/);
  assert.ok(!add.includes("disabled"));
  const locked = chip({ slice: null, slice_label: "+ 가공", slice_enabled: false });
  assert.ok(locked.includes('disabled=""'));
  // 열림 표지가 서도 잠긴 행에는 팝오버가 서지 않는다.
  const openLocked = renderToStaticMarkup(createElement(SliceCell, {
    row: { slice: null, slice_label: "+ 가공", slice_enabled: false }, field: "f",
    port: { ...PORT, open: true },
  }));
  assert.ok(!openLocked.includes("slicepop"));
});
