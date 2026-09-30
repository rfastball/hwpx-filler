/* 저장한 필터 칩 줄 + 필터 빌더(`data_zone.ts`, 2026-09-30 재설계) — 판정은 하나도 여기 없다.
 *
 * 이 파일이 재는 것은 다섯이다: ①칩 줄이 세 칸 격자(머리표 | 칩 영역 | 「+ 필터」)이고 Python 이 준
 * 무리(`preset_groups`)를 그대로 그리는가 — 칩이 둘 이상이면 알약 무리 + 열 이름 표지, 하나면 맨 칩
 * ②▾ 메뉴 단추는 **켜진 칩에만** 서고, 메뉴(고치기·삭제)는 어느 칩이든 문맥 메뉴 키로도 열린다
 * ③머리 줄 — 「표시 N/M」·「모두 보기」(필터가 설 때만)·순서 스위치(지금 방향)·표 모서리 ⤢
 * ④빌더가 줄을 상태 모양으로만 옮기는가 — 줄 사이 「그리고」, 겹친 조건의 무손실 분할, 살아 있는 수의
 * 지연·순서, 「비우고 시작」 ⑤닫힘의 키·초점 규칙. */
import test from "node:test";
import assert from "node:assert/strict";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  FOLD_ROW,
  FilterBuilder,
  FilterChipRow,
  JobDataZone,
  PresetChip,
  RANGE_WORDS,
  SEARCH_ROW,
  blankRow,
  builderKeyAction,
  builderPlacement,
  createCountRequester,
  deletePreset,
  focusFinder,
  focusReturnTarget,
  formatAmount,
  isMenuKey,
  pickerKey,
  pickerOptions,
  rangeFromWords,
  rowsFromState,
  stateFromRows,
  wordsFromRange,
} from "../../frontend/src/screens/data_zone.ts";

const SMALL = { search: "", pruned: [], columns: { 추정가격: { text: "", values: null, range: {
  first: { op: "lt", operand: "100,000,000" }, second: null, joiner: "and" } } } };

const PRESET = (name, extra) => Object.assign({
  name, active: false, usable: true, reason: "", dimension: "추정가격", dimension_label: "추정가격",
  description: `추정가격 < '${name}'`, state: SMALL,
}, extra || {});

const FILTER = {
  active: true, chips: [{ column: "공고명", text: "공고명 포함 '전산'" }], branches: [],
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
      { name: "공고명", kind: "text", label: "텍스트", hidden: false, values: ["청사 청소", "전산 유지보수", ""], more: 0 },
      { name: "추정가격", kind: "amount", label: "금액", hidden: false, values: [], more: 0 },
      { name: "계약일자", kind: "date", label: "날짜", hidden: false, values: [], more: 0 },
    ],
  },
};

function controller(extra) {
  return Object.assign({
    doc: { defaultView: null },
    notify() {}, prompt: async () => null, confirm: async () => false,
    uiModel: { subscribe: () => () => {}, getSnapshot: () => ({}) },
    zone: async () => ({ ok: true }), call: async () => ({}),
    scheduleColumnText() {}, scheduleSearch() {}, openDataSheet: async () => {},
    closeDataSheet() {}, discardRange: async () => {}, applyRange: async () => {}, placePopover() {},
  }, extra || {});
}

const chipRow = (filter, extra) => renderToStaticMarkup(createElement(FilterChipRow, Object.assign({
  filter, hasData: true, hiddenColumns: [], controller: controller(), builder: null,
  onNew() {}, onEdit() {},
}, extra || {})));

const builderMarkup = (filter, spec) => renderToStaticMarkup(createElement(FilterBuilder, {
  controller: controller(), filter, spec, trigger: { current: null }, rootRef: { current: null },
  close() {},
}));

function Scroll(props) {
  return createElement("div", { className: "tbwrap jobtbwrap", id: "jobTableWrap", hidden: props.hidden }, props.children);
}

const zoneMarkup = (snapshot, ui) => renderToStaticMarkup(createElement(JobDataZone, {
  snapshot: Object.assign({
    has_data: true, record_count: 11, zone_selected_count: 3, view_order: "sourceDesc",
    filter: { active: false, search: "", columns: [], presets: [], preset_groups: [], builder: FILTER.builder },
    table: {
      columns: [{ name: "공고명", kind: "text", visible: true }, { name: "추정가격", kind: "amount", visible: true }],
      rows: [{ index: 0, cells: [[["청사 청소", false]], [["95,000,000", false]]] }],
      visible_count: 11, hidden_selected: [], hidden_columns: [],
    },
  }, snapshot || {}),
  controller: controller({ uiModel: { subscribe: () => () => {}, getSnapshot: () => ui || {} } }),
  scroll: Scroll,
}));

test("칩 줄 = 세 칸 격자: 머리표 | 칩 영역 | 「+ 필터」 — 「+ 필터」는 칩 영역 밖 마지막 칸이다", () => {
  const html = chipRow(FILTER);
  assert.ok(html.startsWith('<div class="fchips" id="jobFilterChips">'), html.slice(0, 80));
  const cap = html.indexOf('<span class="fchips-cap">저장한 필터</span>');
  const area = html.indexOf('<div class="fchips-area">');
  const plus = html.indexOf('data-act="filter-new"');
  assert.ok(cap >= 0 && cap < area && area < plus, "머리표 → 칩 영역 → 「+ 필터」 순서");
  // 「+ 필터」는 칩 영역의 자식이 아니다(영역이 닫힌 뒤에 선다) — 칩이 늘어도 따라 흐르지 않는다.
  assert.ok(html.lastIndexOf("</div>", plus) > area, "칩 영역이 「+ 필터」 앞에서 닫힌다");
  assert.ok(html.endsWith("+ 필터</button></div>"));
  // 저장본이 없으면 머리표 칸이 빠진다(.nocap) — 「열 조건」 칩만 있어도 격자는 그대로다.
  const bare = chipRow(Object.assign({}, FILTER, { presets: [], preset_groups: [] }));
  assert.ok(bare.startsWith('<div class="fchips nocap"') && !bare.includes("fchips-cap"));
  assert.ok(!bare.includes("fchips-sep"), "저장본이 없으면 구분선도 없다");
});

test("같은 열의 칩 둘은 무리로, 홀로 선 칩은 맨 칩으로 선다 — 무리는 Python 이 정한 그대로", () => {
  const html = chipRow(FILTER);
  const clusters = html.match(/<span class="fcluster"[^>]*>/g) || [];
  assert.equal(clusters.length, 1, "무리는 칩이 둘 이상인 차원 하나뿐이어야 합니다");
  assert.ok(clusters[0].includes('data-dimension="추정가격"') && clusters[0].includes('role="group"'));
  assert.ok(html.includes('<span class="fcluster-label" aria-hidden="true">추정가격</span>'));
  const inside = html.slice(html.indexOf('class="fcluster"'), html.indexOf('data-preset-chip="상반기"'));
  assert.ok(inside.indexOf('data-preset="소기업"') < inside.indexOf('data-preset="중소기업"'));
  assert.equal((html.match(/fcluster-label/g) || []).length, 1, "홀로 선 칩에는 표지가 서지 않습니다");
});

test("칩 = 이름 하나를 든 눌림 단추, ▾ 메뉴 단추는 켜진 칩에만 선다(꺼진 칩은 빈자리 없음)", () => {
  const html = chipRow(FILTER);
  assert.ok(/data-preset="소기업"[^>]*aria-pressed="true"[^>]*title="소기업: 추정가격 &lt; &#x27;소기업&#x27;"/.test(html),
    "켜진 칩의 title 은 `이름: Python 조건 문안`");
  assert.ok(/data-preset="지역"[^>]*aria-disabled="true"[^>]*title="이 필터의 열이 지금 데이터에 없습니다: 지역"/.test(html));
  const menus = html.match(/<button class="preset-menu"[^>]*>/g) || [];
  assert.equal(menus.length, 1, "켜진 칩(소기업) 하나에만 ▾");
  assert.ok(menus[0].includes('data-preset-menu="소기업"') && menus[0].includes('aria-label="소기업 필터 메뉴"')
    && menus[0].includes('aria-haspopup="menu"') && menus[0].includes('aria-expanded="false"'));
  assert.ok(!html.includes("preset-edit") && !html.includes("필터 고치기"), "⋯ 고치기 단추는 없다");
  assert.ok(html.includes('<span class="preset-name">중소기업</span>'), "이름은 말줄임 칸에 든다");
});

test("칩 메뉴: 고치기·삭제 두 항목, 문맥 메뉴 키(Shift+F10·메뉴 키)가 같은 메뉴를 연다", () => {
  const trigger = { isConnected: true, focus() {} };
  const open = renderToStaticMarkup(createElement(PresetChip, {
    preset: PRESET("상반기"), controller: controller(), menu: { name: "상반기", trigger },
    openMenu() {}, closeMenu() {}, onEdit() {},
  }));
  assert.ok(/<div class="ctx-menu preset-pop" role="menu" aria-label="상반기 필터 메뉴"/.test(open),
    "꺼진 칩도 문맥 메뉴로 같은 메뉴가 선다");
  const items = open.match(/role="menuitem"[^>]*>[^<]*</g) || [];
  assert.deepEqual(items.map((item) => item.replace(/.*>/, "").replace("<", "")), ["고치기", "삭제"]);
  assert.ok(/class="danger"[^>]*data-preset-act="delete"/.test(open), "삭제는 위험 글자색");
  assert.equal(isMenuKey({ key: "F10", shiftKey: true }), true);
  assert.equal(isMenuKey({ key: "ContextMenu" }), true);
  assert.equal(isMenuKey({ key: "F10" }), false);
  assert.equal(isMenuKey({ key: "Enter" }), false);
  assert.equal(isMenuKey({ key: "ContextMenu", isComposing: true }), false);
});

test("칩 메뉴 「삭제」는 저장본 하나만 손실로 적는 확인 뒤에만 지운다", async () => {
  const calls = [];
  const ctrl = controller({
    confirm: async (spec) => { calls.push(["confirm", spec]); return calls.length > 1; },
    zone: async (action, payload) => { calls.push([action, payload]); return { ok: true }; },
  });
  assert.equal(await deletePreset(ctrl, "소기업", null), null, "취소면 지우지 않는다");
  assert.deepEqual(calls.map((c) => c[0]), ["confirm"]);
  assert.deepEqual(await deletePreset(ctrl, "소기업", null), { ok: true });
  const spec = calls[1][1];
  assert.equal(spec.title, "저장한 필터 삭제");
  assert.equal(spec.body, "사라지는 것: 저장한 필터 '소기업'");
  assert.equal(spec.confirmLabel, "삭제");
  assert.deepEqual(calls[2], ["delete_filter_preset", { name: "소기업" }]);
});

test("「+ 필터」는 데이터가 있으면 늘 서고, 열 머리 조건 칩은 「열 조건」 + × (검색 칩은 × 없음)", () => {
  const empty = chipRow({ active: false, presets: [], preset_groups: [], builder: FILTER.builder });
  assert.ok(!empty.includes(" hidden=\"\""), "필터가 없어도 칩 줄은 섭니다");
  assert.ok(empty.includes('data-act="filter-new"') && empty.includes("+ 필터"));
  assert.ok(!empty.includes("저장한 필터") && !empty.includes("fchips-sep"));
  const html = chipRow(Object.assign({}, FILTER, {
    chips: FILTER.chips.concat([{ column: "", text: "(공고명) 포함 '청'" }]),
  }));
  assert.ok(html.includes('<span class="chip-role">열 조건</span><span class="chip-text">공고명 포함 &#x27;전산&#x27;</span>'));
  assert.ok(/data-clear-col="공고명"[^>]*aria-label="공고명 열 조건 지우기"/.test(html));
  assert.equal((html.match(/data-clear-col=/g) || []).length, 1, "검색 칩에는 × 가 없다");
  assert.ok(html.indexOf("fchips-sep") < html.indexOf("chip-role"), "저장본 칩 뒤 구분선, 그 뒤 「열 조건」");
  assert.ok(!html.includes('data-act="filter-clear"') && !html.includes("필터 지우기"), "「필터 지우기」는 없다");
  const blocked = chipRow(Object.assign({}, FILTER, {
    builder: Object.assign({}, FILTER.builder, { can_create: false, reason: "필터는 등록 데이터에만 저장할 수 있습니다." }),
  }));
  assert.ok(/data-act="filter-new"[^>]*aria-disabled="true"[^>]*title="필터는 등록 데이터에만 저장할 수 있습니다."/.test(blocked));
  assert.ok(chipRow(FILTER, { hasData: false }).includes('hidden=""'));
});

test("머리 줄: 필터가 서면 「표시 N/M」 + 「모두 보기」, 순서 스위치는 지금 방향, ⤢ 는 표 모서리", () => {
  const plain = zoneMarkup();
  assert.ok(plain.includes('id="jobSelCount">선택 3/11</span>'), "필터가 없으면 표시 수·「모두 보기」 없음");
  assert.ok(!plain.includes("모두 보기"));
  assert.ok(/id="jobOrderToggle"[^>]*aria-pressed="false"[^>]*data-order-values="sourceDesc,sourceAsc"/.test(plain));
  assert.ok(/id="jobOrderToggle"[^>]*><svg class="icon"[^>]*>.*?<\/svg><span>아래 행부터<\/span><\/button>/.test(plain),
    "기본(sourceDesc) = ↓ 아래 행부터");
  assert.ok(!plain.includes("원본 역순") && !plain.includes("원본 순서") && !plain.includes("펼쳐서"));
  const asc = zoneMarkup({ view_order: "sourceAsc" });
  assert.ok(/id="jobOrderToggle"[^>]*aria-pressed="true"/.test(asc) && asc.includes("<span>위 행부터</span>"));
  // ⤢ 는 표 틀(.jobtb-host)의 자식이고 스크롤하는 표(#jobTableWrap) 밖이다.
  const host = plain.slice(plain.indexOf('id="jobTableHost"'));
  const wrapEnd = host.indexOf("</table></div>");
  const expand = host.indexOf('id="jobDataExpand"');
  assert.ok(expand > wrapEnd && wrapEnd > 0, "⤢ 는 스크롤 표 바깥, 표 틀 안");
  assert.ok(/class="jobtb-expand" id="jobDataExpand" type="button" aria-label="표 크게 열기" title="표 크게 열기"><svg/.test(plain));
  assert.ok(!zoneMarkup({}, { sheetOpen: true }).includes('id="jobDataExpand"'), "시트 안에서는 그리지 않는다");
  assert.ok(/id="jobDataExpand" type="button" hidden=""/.test(zoneMarkup({ has_data: false })),
    "데이터가 없으면 표처럼 숨는다(노드는 선다)");

  const filtered = zoneMarkup({
    filter: Object.assign({}, FILTER, {
      columns: [
        { name: "공고명", kind: "text", active: false, filtered: false, constraints: [] },
        { name: "추정가격", kind: "amount", active: false, filtered: true, constraints: ["필터 '소기업'"] },
      ],
    }),
    table: Object.assign({}, { columns: [{ name: "공고명", kind: "text" }, { name: "추정가격", kind: "amount" }],
      rows: [], visible_count: 7, hidden_selected: [], hidden_columns: [] }),
  });
  assert.ok(filtered.includes('id="jobSelCount">선택 3/11 · 표시 7/11</span><button class="btn showall" id="jobShowAll"'),
    "「모두 보기」는 표시 수 바로 뒤");
  assert.ok(filtered.includes(">모두 보기</button>"));
  // 저장한 필터가 조이는 열의 머리도 표지를 세우고 title 이 그 무리를 이름으로 말한다.
  assert.ok(/class="fico on" data-col="추정가격"[^>]*title="필터 &#x27;소기업&#x27;"/.test(filtered));
  assert.ok(/class="fico" data-col="공고명"/.test(filtered));
});

test("빌더: 지금 조건 프리필은 열마다 카드, 카드 사이 「그리고」, 맨 아래 새 조건 콤보박스", () => {
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
  assert.ok(html.includes(">필터 만들기<") && html.includes("열 머리 조건에서 채움"));
  assert.ok(/class="btn sm quiet fb-reset"[^>]*data-act="fb-reset"[^>]*>비우고 시작</.test(html),
    "지금 조건으로 채운 초안은 「비우고 시작」으로 비운다");
  assert.equal((html.match(/class="fb-card" data-fb-row/g) || []).length, 3, "공고명·추정가격·전체 열 검색 세 카드");
  assert.equal((html.match(/class="fb-and"[^>]*>그리고</g) || []).length, 3, "카드 사이와 새 조건 앞마다 「그리고」");
  assert.ok(/<span class="fb-card-name" title="추정가격">추정가격<\/span><span class="fb-kind">금액<\/span>/.test(html),
    "카드 머리 = 열 이름 + 유형 표지(Python 표지 그대로)");
  assert.ok(html.includes('aria-label="추정가격 조건 지우기"'));
  // 텍스트 카드: 값 고르기 | 포함 글자 분절 단추, 값은 눌림 태그, (빈값)
  assert.ok(/data-fb-seg="values"[^>]*aria-pressed="true"[^>]*>값 고르기</.test(html));
  assert.ok(/data-fb-val="청사 청소"[^>]*aria-pressed="true"/.test(html));
  assert.ok(html.includes(">(빈값)<"));
  // 금액 카드: 한국어 비교 말 일곱 개, 숫자 칸은 오른쪽 정렬 클래스
  for (const [, label] of RANGE_WORDS) assert.ok(html.includes(`>${label.replace("<", "&lt;").replace(">", "&gt;")}<`), label);
  assert.ok(/class="field fb-operand num"[^>]*value="100,000,000"/.test(html));
  // 새 조건 콤보박스 — 늘 맨 아래, ARIA 콤보박스, 「+ 조건」 단추는 없다
  assert.ok(/id="jobFilterColumnPicker"[^>]*role="combobox"[^>]*aria-expanded="false"/.test(html));
  assert.ok(html.includes('placeholder="열 이름을 적어 고르세요"'));
  assert.ok(html.lastIndexOf("fb-new") > html.lastIndexOf("data-fb-row"), "새 조건 카드는 맨 아래");
  assert.ok(!html.includes("+ 조건"));
  // 이름은 아래(선택), footer 는 상태 + 취소·저장
  assert.ok(html.includes("(비우면 조건이 이름이 됩니다)"));
  assert.ok(html.indexOf("data-fb-name") > html.lastIndexOf("fb-new"), "이름 칸은 카드 목록 아래");
  assert.ok(html.includes(">저장<") && html.includes(">취소<") && !html.includes('data-act="fb-delete"'));
});

test("빌더: 빈 만들기는 새 조건 카드 하나, 고치기는 이름·「사이」·삭제를 채운다", () => {
  const blank = builderMarkup(FILTER, { mode: "create", name: "" });
  assert.equal((blank.match(/data-fb-row=/g) || []).length, 0);
  assert.ok(blank.includes("fb-new") && !blank.includes('class="fb-and"') && !blank.includes("열 머리 조건에서 채움"));
  assert.ok(!blank.includes("비우고 시작"), "비울 초안이 없으면 「비우고 시작」도 없다");
  const medium = { search: "", pruned: [], columns: { 추정가격: { text: "", values: null, range: {
    first: { op: "ge", operand: "100,000,000" }, second: { op: "lt", operand: "220,000,000" }, joiner: "and" } } } };
  const filter = Object.assign({}, FILTER, { presets: [PRESET("중소기업", { state: medium })] });
  const edit = builderMarkup(filter, { mode: "edit", name: "중소기업" });
  assert.ok(edit.includes(">필터 고치기<") && edit.includes('value="중소기업"'));
  assert.ok(/<option value="between" selected="">사이<\/option>/.test(edit), "≥ a 그리고 < b = 「사이」");
  assert.ok(edit.includes('value="220,000,000"') && edit.includes(">이상<") && edit.includes(">미만<"));
  assert.ok(edit.indexOf('data-act="fb-delete"') < edit.indexOf('data-fb-count'), "삭제는 footer 맨 왼쪽");
  assert.ok(!edit.includes("비우고 시작"), "고치기는 저장본으로 연다 — 비우기는 만들기의 몫");
});

test("비교 말 ↔ 연산자: 여섯은 1:1, 「사이」는 ≥ a 그리고 < b, 옮길 수 없는 2절은 기호 그대로", () => {
  const pairs = { lt: "lt", le: "le", gt: "gt", ge: "ge", eq: "eq", ne: "ne" };
  for (const [word, op] of Object.entries(pairs)) {
    assert.deepEqual(rangeFromWords(word, "5", ""), { first: { op, operand: "5" }, second: null, joiner: "and" });
    assert.deepEqual(wordsFromRange(rangeFromWords(word, "5", "")), { op: word, a: "5", b: "" });
  }
  assert.deepEqual(rangeFromWords("between", "1", "9"), {
    first: { op: "ge", operand: "1" }, second: { op: "lt", operand: "9" }, joiner: "and",
  });
  assert.deepEqual(wordsFromRange(rangeFromWords("between", "1", "9")), { op: "between", a: "1", b: "9" });
  assert.equal(rangeFromWords("lt", "  ", ""), null, "빈 값은 조건이 아니다");
  assert.equal(wordsFromRange({ first: { op: "ge", operand: "1" }, second: { op: "le", operand: "9" }, joiner: "and" }), null);
  assert.equal(wordsFromRange({ first: { op: "ge", operand: "1" }, second: { op: "lt", operand: "9" }, joiner: "or" }), null);
  // 열 머리에서 건 2절(≥·≤)은 카드가 기호 2절로 그대로 들고 무손실로 돌려준다.
  const legacy = { columns: { 계약일자: { text: "", values: null, range: {
    first: { op: "ge", operand: "2026-01-01" }, second: { op: "le", operand: "2026-06-30" }, joiner: "and" } } },
  search: "", pruned: [] };
  const rows = rowsFromState(legacy, FILTER.builder.columns);
  assert.ok(rows[0].legacy, "7개 말로 옮길 수 없는 범위");
  assert.deepEqual(stateFromRows(rows), legacy);
  // 금액 칸의 천 단위 쉼표 — 숫자 모양만 다시 쓴다(「1억」은 그대로 두고 Python 이 거절).
  assert.equal(formatAmount("100000000"), "100,000,000");
  assert.equal(formatAmount(" 1,0000.5 "), "10,000.5");
  assert.equal(formatAmount("1억"), "1억");
  assert.equal(formatAmount("-2500"), "-2,500");
});

test("카드 ↔ 상태 옮김은 무손실이다 — 겹친 조건은 카드를 나누고, 빈 카드는 조건이 아니다", () => {
  const columns = FILTER.builder.columns;
  const state = {
    search: "전산", pruned: ["공고명"],
    columns: {
      공고명: { text: "청", values: ["청사 청소", ""], range: null },
      추정가격: { text: "", values: null, range: { first: { op: "ge", operand: "1" },
        second: { op: "lt", operand: "9" }, joiner: "and" } },
    },
  };
  const rows = rowsFromState(state, columns);
  assert.deepEqual(rows.map((row) => [row.column, row.mode]), [
    ["공고명", "values"], ["공고명", "text"], ["추정가격", "range"], [SEARCH_ROW, "search"],
  ]);
  assert.deepEqual(stateFromRows(rows, ["공고명"]), state);
  const blanks = [blankRow(1, "공고명", "text"), blankRow(2, "추정가격", "amount")];
  assert.deepEqual(stateFromRows(blanks), { columns: {}, search: "", pruned: [] });
});

test("콤보박스 목록: 쓴 열은 빠지고, 숨긴 열은 뒤로 접히며, 「전체 열 검색」이 마지막", () => {
  const matched = [
    { name: "공고명", label: "텍스트", hidden: false, segments: [["공고명", false]] },
    { name: "추정가격", label: "금액", hidden: false, segments: [["추정", false], ["가격", true]] },
    { name: "비고", label: "텍스트", hidden: true, segments: [["비고", false]] },
    { name: "메모", label: "텍스트", hidden: true, segments: [["메모", false]] },
  ];
  const rows = [blankRow(1, "공고명", "text")];
  const folded = pickerOptions(matched, rows, { query: "", expanded: false });
  assert.deepEqual(folded.map((o) => [o.name, o.label, o.muted, !!o.fold]), [
    ["추정가격", "금액", false, false], ["숨긴 열 2개", "", true, true], ["전체 열 검색", "모든 열", false, false],
  ]);
  const opened = pickerOptions(matched, rows, { query: "", expanded: true });
  assert.deepEqual(opened.map((o) => o.name), ["추정가격", "숨긴 열 2개", "비고", "메모", "전체 열 검색"]);
  assert.ok(opened[2].muted && opened[3].muted, "숨긴 열은 흐리게");
  // 질의가 있으면 접지 않고 결과에 섞인다(흐린 표지 유지).
  const searched = pickerOptions(matched, rows, { query: "비", expanded: false });
  assert.deepEqual(searched.map((o) => [o.name, o.muted]), [
    ["추정가격", false], ["비고", true], ["메모", true], ["전체 열 검색", false],
  ]);
  const withSearch = pickerOptions(matched, rows.concat([blankRow(2, SEARCH_ROW, "")]), { query: "", expanded: false });
  assert.ok(!withSearch.some((o) => o.value === SEARCH_ROW), "검색 카드가 있으면 그 줄은 빠진다");
  assert.equal(FOLD_ROW === SEARCH_ROW, false);
});

test("콤보박스 키: ↑↓ 는 돌고, Enter 는 고르고, Escape 는 목록만 닫고, 조합 중에는 무시", () => {
  const closed = { open: false, active: -1, count: 3 };
  assert.deepEqual(pickerKey({ key: "ArrowDown" }, closed), { active: 0, open: true, choose: null, handled: true });
  assert.deepEqual(pickerKey({ key: "ArrowUp" }, closed), { active: 2, open: true, choose: null, handled: true });
  const open = { open: true, active: 2, count: 3 };
  assert.equal(pickerKey({ key: "ArrowDown" }, open).active, 0, "끝에서 처음으로 돈다");
  assert.equal(pickerKey({ key: "ArrowUp" }, { open: true, active: 0, count: 3 }).active, 2);
  assert.deepEqual(pickerKey({ key: "Enter" }, open), { active: 2, open: false, choose: 2, handled: true });
  assert.equal(pickerKey({ key: "Enter" }, { open: true, active: -1, count: 3 }).choose, 0, "고른 줄이 없으면 첫 줄");
  assert.equal(pickerKey({ key: "Enter" }, closed).handled, false, "닫힌 목록의 Enter 는 넘긴다");
  assert.deepEqual(pickerKey({ key: "Escape" }, open), { active: -1, open: false, choose: null, handled: true });
  assert.equal(pickerKey({ key: "Escape" }, closed).handled, false, "닫힌 목록의 Escape 는 빌더를 닫는다");
  assert.equal(pickerKey({ key: "Enter", isComposing: true }, open).handled, false);
  assert.equal(pickerKey({ key: "ArrowDown", keyCode: 229 }, open).handled, false);
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

test("저장·삭제 뒤 초점: 고친 칩은 새 이름의 칩, 지운 칩은 「+ 필터」, 바깥 누름은 그대로", () => {
  const plus = { id: "plus" };
  const edits = [
    { getAttribute: () => "소기업" },
    { getAttribute: () => "중소 \"기업\"" },
  ];
  const doc = {
    querySelector: (selector) => (selector === '[data-act="filter-new"]' ? plus : null),
    querySelectorAll: (selector) => (selector === "[data-preset]" ? edits : []),
  };
  assert.equal(focusFinder("none", null, doc), null);
  assert.equal(focusFinder("new", null, doc)(), plus);
  assert.equal(focusFinder({ edit: "중소 \"기업\"" }, null, doc)(), edits[1], "따옴표 든 이름도 찾는다");
  assert.equal(focusFinder({ edit: "없음" }, null, doc)(), null, "아직 다시 그려지지 않았으면 기다린다");
  const trigger = { isConnected: true };
  assert.equal(focusFinder("trigger", trigger, doc)(), trigger);
});

test("빌더 배치: 트리거에 붙은 채 높이를 자른다 — 아래가 320px 이상이면 아래, 아니면 넓은 쪽으로", () => {
  const trigger = { top: 500, bottom: 530, left: 860 };
  // 큰 화면(1440×900): 아래 공간 900−530−16−4 = 350 ≥ 320 → 아래, 최대 높이 350.
  assert.deepEqual(builderPlacement(trigger, { width: 1440, height: 900 }, 460),
    { placement: "below", maxHeight: 350, left: 860 });
  // CI 처럼 낮은 화면(1024×768): 아래 218 < 320, 위 480 > 218 → 위로 뒤집고 위 공간이 최대 높이.
  assert.deepEqual(builderPlacement(trigger, { width: 1024, height: 768 }, 460),
    { placement: "above", maxHeight: 480, left: 560 });
  // 아래가 모자라도 위보다 넓으면 아래에 남는다(트리거 위로 끌어올리지 않는다).
  assert.deepEqual(builderPlacement({ top: 200, bottom: 230, left: 0 }, { width: 800, height: 520 }, 460),
    { placement: "below", maxHeight: 270, left: 4 });
  // 공간이 음수가 되면 0(가로는 화면 안으로 민다).
  assert.equal(builderPlacement({ top: 10, bottom: 40, left: 900 }, { width: 900, height: 50 }, 460).maxHeight, 0);
});
