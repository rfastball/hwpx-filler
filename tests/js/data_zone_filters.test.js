/* 저장한 필터 칩 줄 + 필터 빌더(`data_zone.ts`, 2026-09-30 재설계) — 판정은 하나도 여기 없다.
 *
 * 이 파일이 재는 것은 넷이다: ①Python 이 준 무리(`preset_groups`)를 그대로 그리는가 — 칩이
 * 둘 이상이면 알약 무리 + 열 이름 표지, 하나면 맨 칩 ②⋯ 고치기가 **탭 순서에 늘 있는** 단추인가
 * (숨김은 CSS opacity 의 몫이라 마크업에는 늘 선다) ③빌더가 줄을 상태 모양으로만 옮기는가 —
 * 줄 사이 「그리고」, 겹친 조건의 무손실 분할, 살아 있는 수의 지연·순서 ④닫힘의 키·초점 규칙. */
import test from "node:test";
import assert from "node:assert/strict";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  FilterBuilder,
  FilterChipRow,
  RANGE_OPS,
  SEARCH_ROW,
  blankRow,
  builderKeyAction,
  createCountRequester,
  focusFinder,
  focusReturnTarget,
  freeColumn,
  rowsFromState,
  stateFromRows,
} from "../../frontend/src/screens/data_zone.ts";

const SMALL = { search: "", pruned: [], columns: { 추정가격: { text: "", values: null, range: {
  first: { op: "lt", operand: "100,000,000" }, second: null, joiner: "and" } } } };

const PRESET = (name, extra) => Object.assign({
  name, active: false, usable: true, reason: "", dimension: "추정가격", dimension_label: "추정가격",
  description: `추정가격 < '${name}'`, state: SMALL,
}, extra || {});

const FILTER = {
  active: true, chips: ["공고명 포함 '전산'"], branches: [],
  presets: [
    PRESET("소기업", { active: true }),
    PRESET("중소기업"),
    PRESET("상반기", { dimension: "계약일자", dimension_label: "계약일자" }),
    PRESET("지역", {
      usable: false, reason: "이 필터의 열이 지금 데이터에 없습니다: 지역",
      dimension: "지역", dimension_label: "지역", description: "",
    }),
  ],
  preset_groups: [
    { key: "추정가격", label: "추정가격", names: ["소기업", "중소기업"] },
    { key: "계약일자", label: "계약일자", names: ["상반기"] },
    { key: "지역", label: "지역", names: ["지역"] },
  ],
  builder: {
    total: 6, can_create: true, reason: "", adhoc: null,
    columns: [
      { name: "공고명", kind: "text", values: ["청사 청소", "전산 유지보수", ""] },
      { name: "추정가격", kind: "amount", values: [] },
      { name: "계약일자", kind: "date", values: [] },
    ],
  },
};

function controller() {
  return {
    doc: { defaultView: null },
    notify() {}, prompt: async () => null, confirm: async () => false,
    uiModel: { subscribe: () => () => {}, getSnapshot: () => ({}) },
    zone: async () => ({ ok: true }), call: async () => ({}),
    scheduleColumnText() {}, scheduleSearch() {}, openDataSheet: async () => {},
    closeDataSheet() {}, discardRange: async () => {}, applyRange: async () => {}, placePopover() {},
  };
}

const chipRow = (filter, extra) => renderToStaticMarkup(createElement(FilterChipRow, Object.assign({
  filter, hasData: true, hiddenColumns: [], controller: controller(), builder: null,
  onNew() {}, onEdit() {},
}, extra || {})));

const builderMarkup = (filter, spec) => renderToStaticMarkup(createElement(FilterBuilder, {
  controller: controller(), filter, spec, trigger: { current: null }, rootRef: { current: null },
  close() {},
}));

test("같은 열의 칩 둘은 무리로, 홀로 선 칩은 맨 칩으로 선다 — 무리는 Python 이 정한 그대로", () => {
  const html = chipRow(FILTER);
  const clusters = html.match(/<span class="fcluster"[^>]*>/g) || [];
  assert.equal(clusters.length, 1, "무리는 칩이 둘 이상인 차원 하나뿐이어야 합니다");
  assert.ok(clusters[0].includes('data-dimension="추정가격"') && clusters[0].includes('role="group"'));
  assert.ok(html.includes('<span class="fcluster-label" aria-hidden="true">추정가격</span>'));
  // 무리 안에 두 칩이 순서대로, 무리 밖에 홀로 선 칩이 있다.
  const inside = html.slice(html.indexOf('class="fcluster"'), html.indexOf('data-preset-chip="상반기"'));
  assert.ok(inside.indexOf('data-preset="소기업"') < inside.indexOf('data-preset="중소기업"'));
  assert.equal((html.match(/fcluster-label/g) || []).length, 1, "홀로 선 칩에는 표지가 서지 않습니다");
  assert.ok(html.indexOf("저장한 필터") < html.indexOf('class="fcluster"'), "캡션이 칩보다 앞섭니다");
});

test("칩 = 이름 하나를 든 눌림 단추 + 탭 순서에 늘 있는 ⋯ 고치기", () => {
  const html = chipRow(FILTER);
  assert.ok(/data-preset="소기업"[^>]*aria-pressed="true"[^>]*title="추정가격 &lt; &#x27;소기업&#x27;"/.test(html),
    "켜진 칩의 title 은 Python 조건 문안이어야 합니다");
  assert.ok(/data-preset="지역"[^>]*aria-disabled="true"[^>]*title="이 필터의 열이 지금 데이터에 없습니다: 지역"/.test(html));
  const edits = html.match(/<button class="preset-edit"[^>]*>/g) || [];
  assert.equal(edits.length, 4, "칩마다 ⋯ 고치기가 섭니다");
  for (const edit of edits) {
    assert.ok(!/hidden|display:none|tabindex="-1"/.test(edit), `⋯ 은 탭 순서에서 빠지면 안 됩니다: ${edit}`);
  }
  assert.ok(html.includes('aria-label="소기업 필터 고치기"'));
  assert.ok(html.includes('<svg class="icon"'), "⋯ 은 글자가 아니라 그린 아이콘입니다");
});

test("「+ 필터」는 데이터가 있으면 늘 서고, 지금 조건 칩은 「열 조건」으로 불린다", () => {
  const empty = chipRow({ active: false, presets: [], preset_groups: [], builder: FILTER.builder });
  assert.ok(!empty.includes(" hidden=\"\""), "필터가 없어도 칩 줄은 섭니다");
  assert.ok(empty.includes('data-act="filter-new"') && empty.includes("+ 필터"));
  assert.ok(!empty.includes("저장한 필터") && !empty.includes("fchips-sep"),
    "저장본이 없으면 캡션이, 뒤따르는 칩이 없으면 구분선이 서지 않습니다");
  const html = chipRow(FILTER);
  assert.ok(html.includes('<span class="chip-role">열 조건</span>공고명 포함 &#x27;전산&#x27;'));
  assert.ok(html.indexOf('data-act="filter-new"') < html.indexOf("fchips-sep"));
  const blocked = chipRow(Object.assign({}, FILTER, {
    builder: Object.assign({}, FILTER.builder, { can_create: false, reason: "필터는 등록 데이터에만 저장할 수 있습니다." }),
  }));
  assert.ok(/data-act="filter-new"[^>]*aria-disabled="true"[^>]*title="필터는 등록 데이터에만 저장할 수 있습니다."/.test(blocked));
  assert.ok(chipRow(FILTER, { hasData: false }).includes('hidden=""'));
});

test("빌더: 지금 조건 프리필은 열마다 한 줄, 줄 사이 「그리고」, 만들기 제목", () => {
  const filter = Object.assign({}, FILTER, {
    builder: Object.assign({}, FILTER.builder, { adhoc: {
      search: "청", pruned: [],
      columns: {
        공고명: { text: "", values: ["청사 청소"], range: null },
        추정가격: SMALL.columns.추정가격,
      },
    } }),
  });
  const html = builderMarkup(filter, { mode: "create", name: "" });
  assert.ok(html.includes('id="jobFilterBuilder"') && html.includes('role="dialog"'));
  assert.ok(html.includes(">필터 만들기<"));
  assert.equal((html.match(/class="fb-row"/g) || []).length, 3, "공고명·추정가격·전체 열 검색 세 줄");
  assert.equal((html.match(/class="fb-and"[^>]*>그리고</g) || []).length, 2, "줄 사이마다 「그리고」");
  assert.ok(/data-fb-mode="values"/.test(html) && /data-fb-mode="range"/.test(html) && /data-fb-mode="search"/.test(html));
  assert.ok(html.includes(">값 고르기<") && html.includes(">포함 글자<"), "텍스트 열은 방식을 고른다");
  assert.ok(html.includes("(빈값)"), "빈 문자열은 (빈값)으로 선다");
  assert.ok(html.includes(">+ 조건<") && html.includes(">저장<") && html.includes(">취소<"));
  assert.ok(!html.includes('data-act="fb-delete"'), "만들기에는 삭제가 없다");
  for (const [op] of RANGE_OPS) assert.ok(html.includes(`value="${op}"`));
});

test("빌더: 빈 만들기는 첫 열 한 줄, 고치기는 이름·조건을 채우고 삭제를 든다", () => {
  const blank = builderMarkup(FILTER, { mode: "create", name: "" });
  assert.equal((blank.match(/class="fb-row"/g) || []).length, 1);
  assert.ok(!blank.includes('class="fb-and"'));
  const edit = builderMarkup(FILTER, { mode: "edit", name: "소기업" });
  assert.ok(edit.includes(">필터 고치기<") && edit.includes('value="소기업"'));
  assert.ok(edit.includes('value="100,000,000"'), "저장본의 피연산자가 채워진다");
  assert.ok(edit.includes('data-act="fb-delete"'));
});

test("줄 ↔ 상태 옮김은 무손실이다 — 겹친 조건은 줄을 나누고, 빈 줄은 조건이 아니다", () => {
  const columns = FILTER.builder.columns;
  const state = {
    search: "전산", pruned: ["공고명"],
    columns: {
      공고명: { text: "청", values: ["청사 청소", ""], range: null },
      추정가격: { text: "", values: null, range: { first: { op: "ge", operand: "1" },
        second: { op: "lt", operand: "9" }, joiner: "or" } },
    },
  };
  const rows = rowsFromState(state, columns);
  assert.deepEqual(rows.map((row) => [row.column, row.mode]), [
    ["공고명", "values"], ["공고명", "text"], ["추정가격", "range"], [SEARCH_ROW, "search"],
  ]);
  assert.deepEqual(stateFromRows(rows, ["공고명"]), state);
  // 빈 줄(피연산자 없음·고른 값 없음·빈 글자)은 조건이 아니다 — 저장 거절은 Python 이 말한다.
  const blanks = [blankRow(1, "공고명", "text"), blankRow(2, "추정가격", "amount")];
  assert.deepEqual(stateFromRows(blanks), { columns: {}, search: "", pruned: [] });
  // 새 줄은 아직 줄이 없는 첫 열 → 다 쓰였으면 「전체 열 검색」 → 그것도 있으면 없음.
  assert.equal(freeColumn(columns, []), "공고명");
  assert.equal(freeColumn(columns, rows.slice(0, 3).concat([blankRow(9, "계약일자", "date")])), SEARCH_ROW);
  assert.equal(freeColumn(columns, rows.concat([blankRow(9, "계약일자", "date")])), "");
});

test("살아 있는 수: 마지막 입력 뒤 한 번만 묻고, 늦게 온 옛 응답은 버린다", async () => {
  const timers = [];
  const sent = [];
  const applied = [];
  const resolvers = [];
  const requester = createCountRequester({
    setTimer: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length - 1; },
    clearTimer: (handle) => { timers[handle].live = false; },
    send: (state) => { sent.push(state); return new Promise((resolve) => resolvers.push(resolve)); },
    apply: (result) => applied.push(result),
  });
  const fire = (index) => { timers[index].live = false; timers[index].fn(); };
  requester.request({ n: 1 });
  requester.request({ n: 2 });
  assert.deepEqual(timers.map((t) => [t.ms, t.live]), [[150, false], [150, true]]);
  fire(1);
  assert.deepEqual(sent, [{ n: 2 }], "지연 안의 입력은 마지막 한 번만 보낸다");
  requester.request({ n: 3 });
  fire(2);
  resolvers[1]({ ok: true, count: 3, total: 6 });
  resolvers[0]({ ok: true, count: 9, total: 6 });  // 옛 요청의 늦은 응답
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(applied, [{ ok: true, count: 3, total: 6 }]);
  requester.request({ n: 4 });
  requester.cancel();  // 닫힌 빌더는 예약된 질의를 보내지 않는다
  assert.equal(timers.filter((t) => t.live).length, 0);
});

test("닫힘 규칙: Escape 닫기·이름칸 Enter 저장, 한글 조합 중에는 아무 뜻도 없다", () => {
  assert.equal(builderKeyAction({ key: "Escape" }, false), "close");
  assert.equal(builderKeyAction({ key: "Enter" }, true), "submit");
  assert.equal(builderKeyAction({ key: "Enter" }, false), null);
  assert.equal(builderKeyAction({ key: "Enter", isComposing: true }, true), null);
  assert.equal(builderKeyAction({ key: "Escape", keyCode: 229 }, false), null);
  const plus = { id: "plus" };
  const doc = { querySelector: (selector) => (selector === '[data-act="filter-new"]' ? plus : null) };
  const trigger = { isConnected: true };
  assert.equal(focusReturnTarget(trigger, doc), trigger, "연 단추로 돌아간다");
  assert.equal(focusReturnTarget({ isConnected: false }, doc), plus, "연 단추가 사라졌으면 「+ 필터」로");
  assert.equal(focusReturnTarget(null, doc), plus);
});

test("저장·삭제 뒤 초점: 고친 칩은 새 이름의 ⋯, 지운 칩은 「+ 필터」, 바깥 누름은 그대로", () => {
  const plus = { id: "plus" };
  const edits = [
    { getAttribute: () => "소기업" },
    { getAttribute: () => "중소 \"기업\"" },
  ];
  const doc = {
    querySelector: (selector) => (selector === '[data-act="filter-new"]' ? plus : null),
    querySelectorAll: (selector) => (selector === "[data-preset-edit]" ? edits : []),
  };
  assert.equal(focusFinder("none", null, doc), null);
  assert.equal(focusFinder("new", null, doc)(), plus);
  assert.equal(focusFinder({ edit: "중소 \"기업\"" }, null, doc)(), edits[1], "따옴표 든 이름도 찾는다");
  assert.equal(focusFinder({ edit: "없음" }, null, doc)(), null, "아직 다시 그려지지 않았으면 기다린다");
  const trigger = { isConnected: true };
  assert.equal(focusFinder("trigger", trigger, doc)(), trigger);
});
