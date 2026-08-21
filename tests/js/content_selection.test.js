/* SX-02(#725) 「문서 만들기」 "포함할 내용" zone — 서비스·컨트롤러·컴포넌트 계약.
 *
 * 판정·token·projection 은 Python(#679·#678)이 소유한다. 여기가 잰다:
 *   A. 서비스 — local optimistic authority 0 · fresh view 통째 교체 · stale · loud error · token 미조작.
 *   B. 컨트롤러/컴포넌트 — 실 JobScreen 렌더, display_text 소비/내부 id 비노출, needs/selected/broken/
 *      detached, pending disabled, **render/mount 가 open/ensure command 를 발신하지 않음**(#744).
 *   C. architecture negative — Active Field 계산 0 · Template 재해석 0 · direct write 0 · 새 화면 0.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

import { createSlotConfigService } from "../../frontend/src/screens/job_slot_config.ts";
import {
  JobContentSelection,
  createJobContentSelectionController,
} from "../../frontend/src/screens/job_content_selection.ts";
import { PRODUCT_SCREEN_IDS } from "../../frontend/src/screens/product_screens.ts";

/* ── 대역 빌더 ─────────────────────────────────────────────────────────────────────────── */
function opt(id, text, effective = false) {
  return {
    option_id: id, display_text: text, selected: effective, effective,
    structurally_associated_field_ids: [],
  };
}
function slot(id, text, status, options, sharedFields = []) {
  return {
    slot_id: id, display_text: text, selection_policy: "EXACTLY_ONE", status,
    declared_option_ids: [], effective_option_ids: options.filter((o) => o.effective).map((o) => o.option_id),
    options, shared_field_ids: sharedFields,
  };
}
function view(status, slots, extra = {}) {
  const {
    token = "tok-1", detached = [], blocking = [], viewStatus = "CURRENT", contextError = null,
    contextErrorMessage = null,
  } = extra;
  return {
    view_status: viewStatus,
    configuration_status: status,
    context_error: contextError,
    context_error_message: contextErrorMessage,
    new_configuration_token: token,
    projection: viewStatus === "CONTEXT_ERROR" ? null : {
      view_status: viewStatus, configuration_status: status, configuration_present: true,
      slots, detached_selections: detached, blocking_items: blocking, informational_changes: [],
    },
  };
}
function response(v, extra = {}) {
  const { refresh = false, mutation = null } = extra;
  return { mutation_outcome: mutation, current_view: v, refresh_required: refresh };
}
function zone(v) {
  return {
    supported: true, initialized: true, mutation_outcome: null,
    current_view: v, refresh_required: false, error: null,
  };
}
function inactiveZone(error = null) {
  return {
    supported: true, initialized: false, mutation_outcome: null,
    current_view: null, refresh_required: false, error,
  };
}
function fakeClient(responder) {
  const calls = [];
  return {
    calls,
    dispatch(screen, action, payload) {
      calls.push({ screen, action, payload });
      return Promise.resolve(responder(action, payload));
    },
  };
}
function okv(value) {
  return { ok: true, value };
}
function fakeRuntime(fullSnapshot, { refreshError = null } = {}) {
  let snap = fullSnapshot;
  const subs = new Set();
  const refreshes = [];
  const model = {
    getSnapshot: () => ({ full: snap, progress: null }),
    subscribe(listener) {
      subs.add(listener);
      return () => subs.delete(listener);
    },
  };
  return {
    runtime: {
      model: () => model,
      async refresh(screen) {
        refreshes.push(screen);
        if (refreshError !== null) throw refreshError;
        for (const listener of [...subs]) listener();
        return snap;
      },
    },
    refreshes,
    push(next) {
      snap = next;
      for (const listener of [...subs]) listener();
    },
  };
}

const NEEDS = view("NEEDS_SELECTION",
  [slot("s1", "표지 유형", "MISSING_REQUIRED_SELECTION",
    [opt("o1", "기본 표지"), opt("o2", "간이 표지")])],
  { blocking: [{ slot_id: "s1", kind: "MISSING_REQUIRED_SELECTION", option_id: null }] });
const SELECTED = view("SLOT_SELECTIONS_COMPLETE",
  [slot("s1", "표지 유형", "RESOLVED", [opt("o1", "기본 표지", true), opt("o2", "간이 표지")])]);
const LATEST_B = { ...SELECTED, new_configuration_token: "tok-b" };
const LATEST_C = { ...NEEDS, new_configuration_token: "tok-c" };

/* ══ A. 서비스 계약 ═══════════════════════════════════════════════════════════════════════ */
test("selectOption: 응답 전엔 선택을 로컬로 켜지 않는다(local optimistic authority 0)", async () => {
  const client = fakeClient(() => okv(response(SELECTED)));
  const svc = createSlotConfigService({ client });
  svc.hydrate(NEEDS); // baseline: 미선택
  const before = svc.state().view;
  const p = svc.selectOption("s1", "o2");
  // 왕복 중에는 phase 만 pending — view(선택 상태)는 이전 그대로다.
  assert.equal(svc.state().phase, "pending");
  assert.equal(svc.state().view, before);
  await p;
});

test("응답 도착 → backend fresh view 로 통째 교체(재판정 0)", async () => {
  const client = fakeClient(() => okv(response(SELECTED)));
  const svc = createSlotConfigService({ client });
  svc.hydrate(NEEDS);
  const st = await svc.selectOption("s1", "o1");
  assert.equal(st.view, SELECTED); // 로컬 병합이 아니라 backend view 로 교체
  assert.equal(st.phase, "idle");
});

test("refresh_required → phase='stale' + fresh view 유지(옛 Application 유령 반영 0)", async () => {
  const client = fakeClient(() => okv(response(SELECTED, { refresh: true })));
  const svc = createSlotConfigService({ client });
  svc.hydrate(NEEDS);
  const st = await svc.selectOption("s1", "o1");
  assert.equal(st.phase, "stale");
  assert.equal(st.view, SELECTED);
});

test("command 실패는 시끄럽게 phase='error' + alarm(성공 UI 뒤에 숨기지 않음)", async () => {
  const alarms = [];
  const client = fakeClient(() => ({ ok: false, failure: { message: "거절" } }));
  const svc = createSlotConfigService({ client, alarm: (m) => alarms.push(m) });
  svc.hydrate(SELECTED);
  const st = await svc.selectOption("s1", "o2");
  assert.equal(st.phase, "error");
  assert.match(st.error, /거절/);
  assert.equal(alarms.length, 1);
});

test("token 은 backend 발급값만 쓴다(프런트가 짓지 않는다)", async () => {
  const client = fakeClient(() => okv(response(view("SLOT_SELECTIONS_COMPLETE",
    [slot("s1", "표지", "RESOLVED", [opt("o1", "기본", true)])], { token: "tok-server-2" }))));
  const svc = createSlotConfigService({ client });
  svc.hydrate(view("NEEDS_SELECTION",
    [slot("s1", "표지", "MISSING_REQUIRED_SELECTION", [opt("o1", "기본")])], { token: "tok-1" }));
  await svc.selectOption("s1", "o1");
  // 보낸 token 은 hydrate 가 실어준 backend token, 받은 token 은 응답의 새 backend token.
  assert.equal(client.calls[0].payload.configuration_token, "tok-1");
  assert.equal(svc.state().token, "tok-server-2");
});

test("token 없이 mutation 하면 조용히 무동작하지 않고 시끄럽게 던진다", async () => {
  const client = fakeClient(() => okv(response(SELECTED)));
  const svc = createSlotConfigService({ client });
  await assert.rejects(async () => svc.selectOption("s1", "o1"), /configuration_token 이 없습니다/);
  assert.equal(client.calls.length, 0);
});

test("hydrate 는 dispatch 없이 read-only view 를 seed 한다", () => {
  const client = fakeClient(() => okv(response(SELECTED)));
  const svc = createSlotConfigService({ client });
  const st = svc.hydrate(NEEDS);
  assert.equal(st.view, NEEDS);
  assert.equal(st.token, "tok-1");
  assert.equal(st.phase, "idle");
  assert.equal(client.calls.length, 0); // read-only — 왕복 0
});

/* ══ B. 컨트롤러 — render/mount 가 durable write 를 내지 않는다(#744) ═════════════════════════ */
test("컨트롤러 생성/hydrate 는 open/ensure command 를 발신하지 않는다", () => {
  const client = fakeClient(() => okv(response(SELECTED)));
  const svc = createSlotConfigService({ client });
  const { runtime } = fakeRuntime({ slot_configuration: zone(NEEDS) });
  const ctrl = createJobContentSelectionController({ runtime, service: svc });
  // model 스냅샷의 read-only view 로 passive hydrate — dispatch 0.
  assert.equal(client.calls.length, 0);
  assert.equal(ctrl.getSnapshot().view, NEEDS);
  assert.equal(ctrl.getSnapshot().token, "tok-1");
});

test("job 스냅샷 갱신(Template 변경 등)마다 read-only view 로 재hydrate — 여전히 dispatch 0", () => {
  const client = fakeClient(() => okv(response(SELECTED)));
  const svc = createSlotConfigService({ client });
  const rt = fakeRuntime({ slot_configuration: zone(NEEDS) });
  const ctrl = createJobContentSelectionController({ runtime: rt.runtime, service: svc });
  rt.push({ slot_configuration: zone(SELECTED) });
  assert.equal(ctrl.getSnapshot().view, SELECTED);
  assert.equal(client.calls.length, 0);
});

test("사용자 select 만 durable command — hydrate 된 backend token 을 되돌려준다", async () => {
  const client = fakeClient(() => okv(response(SELECTED)));
  const svc = createSlotConfigService({ client });
  const { runtime } = fakeRuntime({ slot_configuration: zone(NEEDS) });
  const ctrl = createJobContentSelectionController({ runtime, service: svc });
  await ctrl.selectOption("s1", "o1");
  assert.equal(client.calls.length, 1);
  assert.equal(client.calls[0].action, "select_slot_option");
  assert.equal(client.calls[0].payload.configuration_token, "tok-1");
  assert.equal(client.calls[0].payload.slot_id, "s1");
  assert.ok(client.calls[0].payload.request_id); // request_id 는 프런트 발급(재전송 단위) — token 아님
});

/* ══ B. 컴포넌트 렌더 ═════════════════════════════════════════════════════════════════════ */
function fakeController(state, handlers = {}) {
  return {
    subscribe: () => () => {},
    getSnapshot: () => state,
    selectOption: handlers.selectOption ?? (async () => state),
    clearSelection: handlers.clearSelection ?? (async () => state),
    refresh: handlers.refresh ?? (async () => state),
  };
}
function stateOf(v, phase = "idle", error = null, zoneError = null) {
  return { view: v, token: v?.new_configuration_token ?? null, phase, error, zoneError };
}
function render(state) {
  return renderToStaticMarkup(createElement(JobContentSelection, { controller: fakeController(state) }));
}

test("실 JobScreen 컴포넌트가 '포함할 내용'을 display_text 로 렌더(내부 id 비노출)", () => {
  const html = render(stateOf(NEEDS));
  assert.match(html, /포함할 내용/);
  assert.match(html, /표지 유형/); // slot display_text
  assert.match(html, /기본 표지/); // option display_text
  assert.match(html, /간이 표지/);
  // 내부 id 는 화면 텍스트로 새지 않는다(id/name 속성으로만 쓰이고 가시 텍스트 노드가 아니다).
  assert.ok(!html.includes(">s1<"));
  assert.ok(!html.includes(">o1<"));
  assert.ok(!html.includes(">o2<"));
});

test("NEEDS_SELECTION → 선택 필요 상태를 그린다", () => {
  const html = render(stateOf(NEEDS));
  assert.match(html, /선택이 필요/);
});

test("selected/effective option 은 checked 로 그린다", () => {
  const html = render(stateOf(SELECTED));
  assert.match(html, /checked/); // effective 옵션이 radio checked
});

test("broken 선택은 '다시 선택' 행동 대상으로 그린다", () => {
  const broken = view("HAS_BROKEN_SELECTIONS",
    [slot("s1", "표지 유형", "SELECTED_OPTION_REMOVED", [opt("o2", "간이 표지")])],
    { blocking: [{ slot_id: "s1", kind: "SELECTED_OPTION_REMOVED", option_id: "gone" }] });
  const html = render(stateOf(broken));
  assert.match(html, /다시 선택/);
});

test("detached 는 현재 포함 내용과 분리된 informational 로만 그린다(내부 key 비노출)", () => {
  const withDetached = view("SLOT_SELECTIONS_COMPLETE",
    [slot("s1", "표지 유형", "RESOLVED", [opt("o1", "기본 표지", true)])],
    { detached: [{ slot_id: "removed-slot", selected_option_ids: ["ghost-opt"], clearable: true, status: "SLOT_REMOVED" }] });
  const html = render(stateOf(withDetached));
  assert.match(html, /현재 문서에는 적용되지 않습니다/); // 정직한 일반 문안
  assert.ok(!html.includes("removed-slot")); // raw slot_id 비노출
  assert.ok(!html.includes("ghost-opt")); // raw option_id 비노출
});

test("pending 동안 radio 를 disabled 로 그려 중복 mutation 을 막는다", () => {
  const html = render(stateOf(NEEDS, "pending"));
  assert.match(html, /disabled/);
  assert.match(html, /반영 중/);
});

test("context error 는 backend 사용자 문안만 service와 alert에 공유한다", async () => {
  const code = "TEMPLATE_INITIALIZATION_REQUIRED";
  const message = "템플릿 확인이 끝나지 않아 포함할 내용을 불러오지 못했습니다. 템플릿을 확인하세요.";
  const errView = view("CONTEXT_ERROR", [], {
    viewStatus: "CONTEXT_ERROR", contextError: code, contextErrorMessage: message, token: null,
  });
  const client = fakeClient(() => okv(response(errView, { refresh: true })));
  const svc = createSlotConfigService({ client });

  assert.equal(svc.hydrate(errView).error, message);
  const state = await svc.refresh();
  assert.equal(state.error, message);

  const html = render(state);
  assert.match(html, new RegExp(message));
  assert.match(html, /role="alert"/);
  assert.ok(!html.includes(code));
});

/* ══ 리뷰 회수 fixes(#725 Codex) ═════════════════════════════════════════════════════════ */
test("P2#6 collision-free radio id: slot_id 이어붙이기가 충돌해도 radio id 는 갈린다", () => {
  // ("a-b","c") 와 ("a","b-c") 는 slot_id+option_id 를 이어붙이면 같은 문자열이 된다.
  const collide = view("NEEDS_SELECTION",
    [slot("a-b", "표지", "MISSING_REQUIRED_SELECTION", [opt("c", "옵션C")]),
      slot("a", "부록", "MISSING_REQUIRED_SELECTION", [opt("b-c", "옵션BC")])],
    { blocking: [
      { slot_id: "a-b", kind: "MISSING_REQUIRED_SELECTION", option_id: null },
      { slot_id: "a", kind: "MISSING_REQUIRED_SELECTION", option_id: null }] });
  const html = render(stateOf(collide));
  const ids = [...html.matchAll(/id="(cs-opt-[^"]+)"/g)].map((m) => m[1]);
  assert.equal(ids.length, 2);
  assert.equal(new Set(ids).size, 2); // index 기반이라 전부 유일(충돌 0)
});

test("P2#2 NO_AVAILABLE_OPTIONS: '선택할 수 있는 항목이 없습니다'(다시 선택 오안내 금지)", () => {
  const noav = view("HAS_BROKEN_SELECTIONS",
    [slot("s1", "표지", "NO_AVAILABLE_OPTIONS", [])],
    { blocking: [{ slot_id: "s1", kind: "NO_AVAILABLE_OPTIONS", option_id: null }] });
  const html = render(stateOf(noav));
  assert.match(html, /선택할 수 있는 항목이 없습니다/);
  // per-slot note 가 "다시 선택해야 합니다"(재선택 오안내)가 아니다 — config 요약줄과는 다른 문자열.
  assert.ok(!html.includes("다시 선택해야 합니다"));
});

test("P2#2 UNSUPPORTED_SELECTION_POLICY: 현재 방식 선택 불가 + radio disabled(무동작 no-op 방지)", () => {
  const unsup = view("HAS_BROKEN_SELECTIONS",
    [slot("s1", "표지", "UNSUPPORTED_SELECTION_POLICY", [opt("o1", "기본")])],
    { blocking: [{ slot_id: "s1", kind: "UNSUPPORTED_SELECTION_POLICY", option_id: null }] });
  const html = render(stateOf(unsup));
  assert.match(html, /선택할 수 없습니다/);
  assert.match(html, /disabled/);
});

test("P2#3 clearable detached 는 단일 명시 제거 액션을 준다(내부 key 비노출)", () => {
  const withDetached = view("SLOT_SELECTIONS_COMPLETE",
    [slot("s1", "표지", "RESOLVED", [opt("o1", "기본", true)])],
    { detached: [{ slot_id: "gone-slot", selected_option_ids: ["gone-opt"], clearable: true, status: "SLOT_REMOVED" }] });
  const html = render(stateOf(withDetached));
  assert.match(html, /이전 선택 모두 제거/);
  assert.ok(!html.includes("gone-slot"));
  assert.ok(!html.includes("gone-opt"));
});

test("P2#3 detached 여러 개여도 모호한 항목별 버튼이 아니라 clear-all 하나만 그린다", () => {
  const withDetached = view("SLOT_SELECTIONS_COMPLETE",
    [slot("s1", "표지", "RESOLVED", [opt("o1", "기본", true)])],
    { detached: [
      { slot_id: "a", selected_option_ids: ["x"], clearable: true, status: "SLOT_REMOVED" },
      { slot_id: "b", selected_option_ids: ["y"], clearable: true, status: "SLOT_REMOVED" }] });
  const html = render(stateOf(withDetached));
  const buttons = (html.match(/cs-detached-clear/g) ?? []).length;
  assert.equal(buttons, 1); // 항목 수와 무관하게 명시 액션 하나
});

test("P2#3 clearable=false detached 는 제거 액션이 없다", () => {
  const withDetached = view("SLOT_SELECTIONS_COMPLETE",
    [slot("s1", "표지", "RESOLVED", [opt("o1", "기본", true)])],
    { detached: [{ slot_id: "gone", selected_option_ids: ["o"], clearable: false, status: "SLOT_REMOVED" }] });
  const html = render(stateOf(withDetached));
  assert.ok(!html.includes("이전 선택 모두 제거"));
});

test("P2#5 pending 중 도착한 스냅샷을 settle 뒤 최신 model 로 재hydrate", async () => {
  let resolveDispatch = null;
  const client = {
    calls: [],
    dispatch(screen, action, payload) {
      this.calls.push({ screen, action, payload });
      return new Promise((r) => { resolveDispatch = r; });
    },
  };
  const svc = createSlotConfigService({ client });
  const rt = fakeRuntime({ slot_configuration: zone(NEEDS) });
  const ctrl = createJobContentSelectionController({ runtime: rt.runtime, service: svc });
  const p = ctrl.selectOption("s1", "o1"); // 느린 command → pending 창
  assert.equal(svc.state().phase, "pending");
  rt.push({ slot_configuration: zone(LATEST_B) });
  rt.push({ slot_configuration: zone(LATEST_C) }); // 여러 delivery도 latest 하나로 합친다
  assert.notEqual(ctrl.getSnapshot().view, LATEST_C); // pending 소유 — 아직 반영 안 함
  resolveDispatch(okv(response(NEEDS))); // 옛 command 응답이 뒤늦게 settle
  await p;
  assert.equal(ctrl.getSnapshot().view, LATEST_C); // 건너뛴 latest C로 복구(유령 반영 0)
  assert.equal(ctrl.getSnapshot().token, "tok-c");
});

test("stale settle은 notice와 latest view/null/error를 함께 보존한다", async () => {
  const loadError = {
    code: "INVALID_CONFIGURATION_TOKEN",
    message: "포함할 내용을 불러오지 못했습니다. 다시 불러오세요.",
    action: { key: "refresh", label: "다시 불러오기" },
  };
  const cases = [
    { latest: zone(LATEST_B), view: LATEST_B, token: "tok-b", message: null },
    { latest: inactiveZone(), view: null, token: null, message: null },
    { latest: inactiveZone(loadError), view: null, token: null, message: loadError.message },
  ];
  for (const item of cases) {
    let resolveDispatch = null;
    const client = {
      calls: [],
      dispatch(screen, action, payload) {
        this.calls.push({ screen, action, payload });
        return new Promise((r) => { resolveDispatch = r; });
      },
    };
    const svc = createSlotConfigService({ client });
    const rt = fakeRuntime({ slot_configuration: zone(NEEDS) });
    const ctrl = createJobContentSelectionController({ runtime: rt.runtime, service: svc });
    const p = ctrl.selectOption("s1", "o1");
    rt.push({ slot_configuration: item.latest });
    resolveDispatch(okv(response(SELECTED, { refresh: true })));
    await p;

    const state = ctrl.getSnapshot();
    assert.equal(state.phase, "stale");
    assert.equal(state.view, item.view);
    assert.equal(state.token, item.token);
    const html = render(state);
    assert.match(html, /설정이 갱신되어 최신 내용을 다시 불러왔습니다/);
    if (item.message !== null) {
      assert.match(html, new RegExp(item.message));
      assert.match(html, /다시 불러오기/);
      assert.ok(!html.includes(loadError.code));
    }
  }
});

test("error settle도 command 사유와 latest backend view/token을 함께 보존한다", async () => {
  let resolveDispatch = null;
  const client = {
    calls: [],
    dispatch(screen, action, payload) {
      this.calls.push({ screen, action, payload });
      return new Promise((r) => { resolveDispatch = r; });
    },
  };
  const svc = createSlotConfigService({ client });
  const rt = fakeRuntime({ slot_configuration: zone(NEEDS) });
  const ctrl = createJobContentSelectionController({ runtime: rt.runtime, service: svc });
  const p = ctrl.selectOption("s1", "o1");
  rt.push({ slot_configuration: zone(LATEST_B) });
  resolveDispatch({ ok: false, failure: { message: "거절" } });

  const state = await p;
  assert.equal(state.phase, "error");
  assert.match(state.error, /거절/);
  assert.equal(state.view, LATEST_B);
  assert.equal(state.token, "tok-b");
});

test("P2#4 display_text==id 인 production 형상에서도 지정 표시 필드를 소비한다(라벨 소스=backend, 후속 분리)", () => {
  // v1 backend 는 canonical label 이 없어 display_text=slot_id/option_id 다(Slot/Option 저작=비소유).
  // 프런트는 id 를 직접 조립하지 않고 지정 필드(display_text)를 그린다 — 라벨 개선은 backend projection 몫.
  const prod = view("NEEDS_SELECTION",
    [{
      slot_id: "표지유형", display_text: "표지유형", selection_policy: "EXACTLY_ONE",
      status: "MISSING_REQUIRED_SELECTION", declared_option_ids: [], effective_option_ids: [],
      options: [{ option_id: "기본", display_text: "기본", selected: false, effective: false, structurally_associated_field_ids: [] }],
      shared_field_ids: [],
    }],
    { blocking: [{ slot_id: "표지유형", kind: "MISSING_REQUIRED_SELECTION", option_id: null }] });
  const html = render(stateOf(prod));
  assert.match(html, /표지유형/); // display_text 필드를 그대로 소비(현재는 id 와 동일값)
});

/* ══ C. architecture negative ═════════════════════════════════════════════════════════════ */
test("Active Field 를 계산·표시하지 않는다(structurally_associated_field_ids 미노출 — SX-03 소유)", () => {
  const withFields = view("NEEDS_SELECTION",
    [slot("s1", "표지 유형", "MISSING_REQUIRED_SELECTION",
      [{ option_id: "o1", display_text: "기본 표지", selected: false, effective: false,
        structurally_associated_field_ids: ["성과급금액", "지급일"] }],
      ["성과급금액"])],
    { blocking: [{ slot_id: "s1", kind: "MISSING_REQUIRED_SELECTION", option_id: null }] });
  const html = render(stateOf(withFields));
  // Active Field 인과("이 선택 때문에 …이 필요합니다")를 만들지 않는다 — field id 를 새지 않는다.
  assert.ok(!html.includes("성과급금액"));
  assert.ok(!html.includes("지급일"));
});

test("projection.slots 를 그대로 그린다(Template 구조 재해석/조립 0)", () => {
  const two = view("NEEDS_SELECTION",
    [slot("s1", "표지 유형", "MISSING_REQUIRED_SELECTION", [opt("o1", "기본")]),
      slot("s2", "부록 유형", "RESOLVED", [opt("o3", "없음", true)])],
    { blocking: [{ slot_id: "s1", kind: "MISSING_REQUIRED_SELECTION", option_id: null }] });
  const html = render(stateOf(two));
  const fieldsets = (html.match(/<fieldset/g) ?? []).length;
  assert.equal(fieldsets, 2); // backend 가 준 slot 수 그대로 — 더하거나 빼지 않는다
  assert.match(html, /표지 유형/);
  assert.match(html, /부록 유형/);
});

test("정상 view 부재는 비우고 init 실패는 backend 문안/action으로 복구한다", async () => {
  assert.equal(render(stateOf(null)), "");

  const loadError = {
    code: "INVALID_CONFIGURATION_TOKEN",
    message: "포함할 내용을 불러오지 못했습니다. 다시 불러오세요.",
    action: { key: "refresh", label: "다시 불러오기" },
  };
  const client = fakeClient(() => okv(response(SELECTED)));
  const alarms = [];
  const svc = createSlotConfigService({ client, alarm: (message) => alarms.push(message) });
  const rt = fakeRuntime(
    { slot_configuration: inactiveZone(loadError) },
    { refreshError: new Error("재당김 실패") },
  );
  const ctrl = createJobContentSelectionController({ runtime: rt.runtime, service: svc });

  const html = render(ctrl.getSnapshot());
  assert.match(html, new RegExp(loadError.message));
  assert.match(html, /다시 불러오기/);
  assert.match(html, /role="alert"/);
  assert.ok(!html.includes(loadError.code));
  assert.equal(client.calls.length, 0); // 표시만으로 durable slot command 0

  const failed = await ctrl.refresh();
  assert.deepEqual(rt.refreshes, ["job"]);
  assert.deepEqual(alarms, ["재당김 실패"]);
  assert.equal(failed.zoneError, loadError); // transport 실패가 backend 원인을 지우지 않음
  assert.equal(failed.error, "재당김 실패");
  assert.equal(client.calls.length, 0);
});

test("새 제품 화면 id/root/lifecycle 을 만들지 않는다(기존 4화면 그대로)", () => {
  assert.deepEqual([...PRODUCT_SCREEN_IDS], ["library", "job", "editor", "workbench"]);
});
