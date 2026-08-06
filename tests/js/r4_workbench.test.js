/* R4-02 — React 작업대 controller 의 행동 계약.
 *
 * `n06_workbench.test.js` 가 화면의 **경계**(표면·멱등·이탈 관문·음성 구조)를 재고, 이
 * 파일은 그 안에서 일어나는 일을 잰다: 한 체인 직렬화, 복사 사전확인, 결속 확인 왕복,
 * blur 커밋, 기본 규칙 저장의 확인 재질의.
 *
 * 이 화면의 핵심은 **복사되는 것 = 눈에 보이는 것**이다. legacy 가 그것을 세 규율로 세웠고
 * 후계도 같다: ①상태 변이는 한 줄에 선다 ②커밋은 그 줄을 먼저 정산한다 ③복사는 사전확인이
 * 본 **그 카드**의 토큰을 실어 보낸다. 셋 중 하나가 빠지면 화면엔 방금 친 값이 보이는데
 * 클립보드엔 이전 값이 나간다 — 조용히, 그리고 법적 효력이 있는 문서에.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createWorkbenchController } from "../../frontend/src/screens/workbench.ts";
import { Intent } from "../../frontend/js/intent.js";
import { mapField, TARGET_FONT_FIELD } from "../../frontend/src/screens/workbench_state.ts";
import { valueOf } from "../../frontend/src/screens/editor_state.ts";

const tick = () => new Promise((resolve) => setImmediate(resolve));

const OPEN = {
  open: true, job_name: "작업A", mode_label: "TXT", revision: { binding: 1, template: 1 },
  dirty: { count: 0 }, target_font: "gulimche", can_save: true, save_block: "",
  view: "filled", notice: null, source_fields: ["성명", "기한"], type_options: [], fmt_options: {},
  total: 3, copied_count: 0,
  rows: [
    { name: "납품기한", own: "auto", source: "기한", fmt_kind: "date", fmt_code: "ymd", value: "", confirmed: false },
    { name: "비고", own: "man", source: "", fmt_kind: "", fmt_code: "", value: "손으로", confirmed: false },
  ],
  card: {
    segments: [], review_state: "todo", lint: {}, position: 0, index_map: [],
    queue_degenerate: false, can_prev: false, can_next: true, advance_after: false,
    has_current: true, copy_block: "", last_copy: null, source_row: 1,
  },
};

function build(options = {}) {
  const trace = [];
  const notices = [];
  const listeners = new Set();
  let snapshot = options.snapshot ?? OPEN;
  const model = {
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  };
  const client = {
    async dispatch(screen, action, payload) {
      trace.push(["dispatch", screen, action, payload]);
      if (options.dispatchFails?.(screen, action)) throw new Error("백엔드 거절");
      if (options.dispatch) return { ok: true, value: await options.dispatch(screen, action, payload) };
      return { ok: true, value: {} };
    },
    async invoke(method, ...args) {
      trace.push(["invoke", method, ...args]);
      if (options.invoke) return { ok: true, value: await options.invoke(method, ...args) };
      return { ok: true, value: {} };
    },
  };
  const controller = createWorkbenchController({
    doc: { getElementById: () => null },
    runtime: { model: () => model, loadInitial: async () => snapshot, refresh: async () => snapshot },
    client,
    modal: {
      confirm: async (spec) => { trace.push(["modal.confirm", spec]); return options.confirm ?? false; },
      choose: async () => null,
    },
    chain: Intent,
    navigation: { go() {} },
    notify: (message) => notices.push(String(message)),
  });
  return {
    controller, trace, notices,
    actions: () => trace.filter((row) => row[0] === "dispatch").map((row) => [row[2], row[3]]),
    push(next) { snapshot = next; for (const listener of [...listeners]) listener(); },
  };
}

/* ================= 한 체인 직렬화 ================= */

test("상태 변이는 한 줄에 선다 — 동시 발신이 서로를 추월하지 않는다", async () => {
  let active = 0;
  let peak = 0;
  const h = build({
    dispatch: async () => { active += 1; peak = Math.max(peak, active); await tick(); active -= 1; return {}; },
  });
  await Promise.all([
    h.controller.setView("raw"),
    h.controller.step(1),
    h.controller.setCurrent(2),
  ]);
  assert.equal(peak, 1, "축별로 가르면 「값을 고치고 곧바로 유형을 고쳤다」가 뒤집힌다");
  assert.deepEqual(h.actions().map((row) => row[0]), ["set_view", "step", "set_current"]);
});

/* ================= draft 소유 ================= */

test("push 는 타이핑 중인 값 칸을 덮지 않고 이웃 행만 갱신한다", () => {
  const h = build();
  const field = mapField("비고", "value");
  h.controller.type(field, "치는 중");
  h.push({
    ...OPEN,
    revision: { binding: 2, template: 1 },
    rows: [
      { ...OPEN.rows[0], source: "성명" },
      { ...OPEN.rows[1], value: "서버가 민 값" },
    ],
  });
  const draft = h.controller.draftModel.getSnapshot();
  assert.equal(valueOf(draft, field), "치는 중");
  assert.equal(valueOf(draft, mapField("납품기한", "source")), "성명");
});

test("값 커밋은 blur 에서만, 그것도 dirty 일 때만 나간다", async () => {
  const h = build();
  h.controller.commitValue("비고");
  await tick();
  assert.deepEqual(h.actions(), [], "안 고쳤으면 떠나도 발신 0");

  h.controller.type(mapField("비고", "value"), "고친 값");
  h.controller.commitValue("비고");
  await tick();
  assert.deepEqual(h.actions(), [["set_map_value", { name: "비고", text: "고친 값" }]]);
});

test("체크·유형·표시형은 낙관 표시와 발신을 함께 낸다", async () => {
  const h = build();
  h.controller.setConfirmed("납품기한", true);
  h.controller.setMapType("납품기한", "amount");
  h.controller.setMapFmt("납품기한", "won");
  await tick();
  assert.deepEqual(h.actions(), [
    ["set_confirmed", { name: "납품기한", value: true }],
    ["set_map_type", { name: "납품기한", type: "amount" }],
    ["set_map_fmt", { name: "납품기한", code: "won" }],
  ]);
  assert.equal(valueOf(h.controller.draftModel.getSnapshot(), mapField("납품기한", "type")), "amount");
});

test("대상 글꼴은 전역 설정이라 같은 체인으로 나간다", async () => {
  const h = build();
  h.controller.setTargetFont("malgun");
  await tick();
  assert.deepEqual(h.actions(), [["set_target_font", { font: "malgun" }]]);
  assert.equal(valueOf(h.controller.draftModel.getSnapshot(), TARGET_FONT_FIELD), "malgun");
});

/* ================= 결속 확인 왕복 ================= */

test("음성 — 직접 입력 값을 덮는 결속은 확인을 거절하면 드롭다운을 되돌린다", async () => {
  const h = build({
    confirm: false,
    dispatch: (_s, action) => (action === "set_source"
      ? { confirm: "'비고' 에 직접 입력한 값이 있습니다." } : {}),
  });
  await h.controller.bindColumn("비고", "성명");
  assert.deepEqual(h.actions().map((row) => row[0]), ["set_source"],
    "거절 뒤 확정 발신 0 — 확인을 거절하면 아무 일도 없었던 것과 같다");
  assert.equal(valueOf(h.controller.draftModel.getSnapshot(), mapField("비고", "source")), "",
    "표시도 스냅샷 상태로 되돌아간다");
});

test("양성 — 확인을 승인하면 confirm 을 실어 다시 보낸다", async () => {
  const h = build({
    confirm: true,
    dispatch: (_s, action) => (action === "set_source"
      ? { confirm: "'비고' 에 직접 입력한 값이 있습니다." } : {}),
  });
  await h.controller.bindColumn("비고", "성명");
  assert.deepEqual(h.actions(), [
    ["set_source", { name: "비고", col: "성명" }],
    ["set_source", { name: "비고", col: "성명", confirm: true }],
  ]);
});

test("확인이 필요 없으면 왕복 한 번으로 끝난다(무의미한 확인 금지)", async () => {
  const h = build();
  await h.controller.bindColumn("납품기한", "기한");
  assert.deepEqual(h.actions(), [["set_source", { name: "납품기한", col: "기한" }]]);
  assert.equal(h.trace.some((row) => row[0] === "modal.confirm"), false);
});

/* ================= 복사 — 사전확인이 본 그 카드 ================= */

test("복사는 정산 → 사전확인 → 그 토큰으로 나간다", async () => {
  const h = build({
    dispatch: (_s, action) => (action === "copy_precheck" ? { token: "tok-7" } : {}),
  });
  let release;
  Intent.chained("workbench:session", () => new Promise((resolve) => { release = resolve; }));
  const copying = h.controller.copyCard();
  await tick();
  assert.deepEqual(h.actions(), [], "정산 전에는 사전확인도 안 나간다");
  release();
  await copying;
  assert.deepEqual(h.trace.filter((row) => row[0] === "invoke"),
    [["invoke", "copy_clipboard", "workbench", "tok-7"]],
    "사전확인이 본 그 카드의 토큰을 실어 보낸다");
});

test("음성 — 빈 항목이 있으면 확인을 거치고, 거절하면 복사가 안 나간다", async () => {
  const h = build({
    confirm: false,
    dispatch: (_s, action) => (action === "copy_precheck"
      ? { token: "t", missing_fields: ["납품기한"], empty_fields: ["비고"] } : {}),
  });
  await h.controller.copyCard();
  const spec = h.trace.find((row) => row[0] === "modal.confirm")[1];
  assert.match(spec.body, /채우지 못한 항목: 납품기한/);
  assert.match(spec.body, /값이 빈 항목: 비고/);
  assert.match(spec.body, /확정-비움으로 선언한 항목은 여기 세지 않습니다/);
  assert.equal(h.trace.some((row) => row[0] === "invoke"), false, "거절 뒤 클립보드 발신 0");
});

test("음성 — 작업점이 그사이 바뀌면(stale) 조용히 넘기지 않고 말한다", async () => {
  const h = build({
    dispatch: (_s, action) => (action === "copy_precheck" ? { token: "t" } : {}),
    invoke: () => ({ stale: true }),
  });
  await h.controller.copyCard();
  assert.equal(h.notices.length, 1);
  assert.match(h.notices[0], /작업점이 그사이 바뀌어 복사하지 않았습니다/);
});

test("음성 — 복사 차단 사유는 무동작이 아니라 재진술이다", async () => {
  const h = build({
    dispatch: (_s, action) => (action === "copy_precheck" ? { token: "t" } : {}),
    invoke: () => ({ error: "클립보드를 열지 못했습니다" }),
  });
  await h.controller.copyCard();
  assert.deepEqual(h.notices, ["클립보드를 열지 못했습니다"]);
});

/* ================= 기본 규칙 저장 ================= */

test("저장은 정산 뒤 나가고 확인 문안을 그대로 되돌려 보낸다", async () => {
  let asked = 0;
  const h = build({
    confirm: true,
    dispatch: (_s, action) => {
      if (action !== "save_rules") return {};
      asked += 1;
      return asked === 1 ? { needs_confirm: true, confirm_text: "기본 규칙 3개를 덮어씁니다" } : {};
    },
  });
  await h.controller.saveRules();
  assert.deepEqual(h.actions(), [
    ["save_rules", {}],
    ["save_rules", { confirm: true, confirmed_text: "기본 규칙 3개를 덮어씁니다" }],
  ], "본 문안을 실어 보낸다 — 열린 사이 대상이 바뀌었으면 Python 이 새 문안으로 다시 묻는다");
});

test("음성 — 저장 확인을 취소하면 둘째 발신이 없다", async () => {
  const h = build({
    confirm: false,
    dispatch: (_s, action) => (action === "save_rules"
      ? { needs_confirm: true, confirm_text: "덮어씁니다" } : {}),
  });
  await h.controller.saveRules();
  assert.deepEqual(h.actions().map((row) => row[0]), ["save_rules"]);
});

test("음성 — 저장 실패 사유는 조용히 접히지 않는다", async () => {
  const h = build({
    dispatch: (_s, action) => (action === "save_rules"
      ? { ok: false, error: "규칙 파일을 쓰지 못했습니다" } : {}),
  });
  await h.controller.saveRules();
  assert.deepEqual(h.notices, ["규칙 파일을 쓰지 못했습니다"]);
});

/* ================= 구독 수명 ================= */

test("음성 — 구독 해제 뒤 도착한 push 는 옛 구독자에게 알리지 않는다(unmount 뒤 late push)", () => {
  const h = build();
  let count = 0;
  const release = h.controller.draftModel.subscribe(() => { count += 1; });
  h.controller.type(mapField("비고", "value"), "1");
  assert.equal(count, 1);
  release();
  h.push({ ...OPEN, copied_count: 2 });
  h.controller.type(mapField("비고", "value"), "2");
  assert.equal(count, 1);
});

test("작업대가 닫히면 draft 세션이 비고 다음 진입이 새로 세운다", () => {
  const h = build();
  h.controller.type(mapField("비고", "value"), "이전 세션 값");
  h.push({ ...OPEN, open: false });
  assert.equal(h.controller.draftModel.getSnapshot().session, "");
  h.push(OPEN);
  assert.equal(h.controller.draftModel.getSnapshot().session, "wb:작업A");
  assert.equal(valueOf(h.controller.draftModel.getSnapshot(), mapField("비고", "value")), "손으로",
    "닫힌 작업대의 draft 를 들고 오지 않는다");
});

/* ================= 조준 ================= */

test("aimAt — 소유 행이 없는 토큰은 가짜 초점을 세우지 않는다", () => {
  const h = build();
  assert.doesNotThrow(() => h.controller.aimAt("없는토큰"));
});

test("aimAt — 소유 행이 있으면 그 행을 겨눈다", () => {
  const focused = [];
  const row = {
    focus: (options) => focused.push(["focus", options]),
    scrollIntoView: (options) => focused.push(["scroll", options]),
  };
  const trace = [];
  const model = { getSnapshot: () => OPEN, subscribe: () => () => {} };
  const controller = createWorkbenchController({
    doc: {
      getElementById: (id) => (id === `wbMap-row-${encodeURIComponent("납품기한")}` ? row : null),
    },
    runtime: { model: () => model, loadInitial: async () => OPEN, refresh: async () => OPEN },
    client: { async dispatch() { trace.push("dispatch"); return { ok: true, value: {} }; }, async invoke() { return { ok: true, value: {} }; } },
    modal: { confirm: async () => false, choose: async () => null },
    chain: Intent,
    navigation: { go() {} },
    notify: assert.fail,
  });
  controller.aimAt("납품기한");
  assert.deepEqual(focused, [["focus", { preventScroll: true }], ["scroll", { block: "nearest" }]]);
  assert.deepEqual(trace, [], "겨눔은 발신이 아니다 — 포커스 그 자체다");
});
