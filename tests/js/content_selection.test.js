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
  } = extra;
  return {
    view_status: viewStatus,
    configuration_status: status,
    context_error: contextError,
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
  return { supported: true, initialized: true, mutation_outcome: null, current_view: v, refresh_required: false };
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
function fakeRuntime(fullSnapshot) {
  let snap = fullSnapshot;
  const subs = new Set();
  const model = {
    getSnapshot: () => ({ full: snap, progress: null }),
    subscribe(listener) {
      subs.add(listener);
      return () => subs.delete(listener);
    },
  };
  return {
    runtime: { model: () => model },
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
function stateOf(v, phase = "idle", error = null) {
  return { view: v, token: v?.new_configuration_token ?? null, phase, error };
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

test("context error 는 숨기지 않고 alert 로 그린다", () => {
  const errView = view("CONTEXT_ERROR", [], { viewStatus: "CONTEXT_ERROR", contextError: "복원 불가" });
  const html = render(stateOf(errView, "error", "복원 불가"));
  assert.match(html, /복원 불가/);
  assert.match(html, /role="alert"/);
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

test("view 부재(미지원 zone) → 빈칸을 새지 않고 조용히 비운다", () => {
  const html = render(stateOf(null));
  assert.equal(html, "");
});

test("새 제품 화면 id/root/lifecycle 을 만들지 않는다(기존 4화면 그대로)", () => {
  assert.deepEqual([...PRODUCT_SCREEN_IDS], ["library", "job", "editor", "workbench"]);
});
