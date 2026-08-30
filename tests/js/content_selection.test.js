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
/** `settled`(끝난 슬롯 = 기본 접힘)는 **backend 가 낸 값**이다(U4 14~17) — 대역은 그것을
 *  흉내내되(RESOLVED ∧ 실효 선택 있음) 호출자가 명시로 뒤집을 수 있다. */
function slot(id, text, status, options, sharedFields = [], settled = undefined) {
  const effective = options.filter((o) => o.effective).map((o) => o.option_id);
  return {
    slot_id: id, display_text: text, selection_policy: "EXACTLY_ONE", status,
    declared_option_ids: [], effective_option_ids: effective,
    options, shared_field_ids: sharedFields,
    settled: settled ?? (status === "RESOLVED" && effective.length > 0),
  };
}
/** `zone_actionable`·`savable_selection` 은 **backend 가 낸 값**이다(U4 13번) — 대역은 그것을
 *  흉내내되(항목 ≥1 · 선언 선택 ≥1) 호출자가 명시로 뒤집을 수 있다. 술어를 여기서 재구현하는
 *  것이 아니라 「Python 이 이 값을 실어 보냈다」를 세우는 자리다. */
function view(status, slots, extra = {}) {
  const {
    token = "tok-1", blocking = [], viewStatus = "CURRENT", contextError = null,
    contextErrorMessage = null, retained = [],
    zoneActionable = slots.length > 0,
    savableSelection = slots.some((s) => s.options.some((o) => o.selected)),
  } = extra;
  return {
    view_status: viewStatus,
    configuration_status: status,
    context_error: contextError,
    context_error_message: contextErrorMessage,
    new_configuration_token: token,
    projection: viewStatus === "CONTEXT_ERROR" ? null : {
      view_status: viewStatus, configuration_status: status, configuration_present: true,
      zone_actionable: zoneActionable, savable_selection: savableSelection,
      slots, blocking_items: blocking, informational_changes: [],
      retained_selections: retained,
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
    refresh: handlers.refresh ?? (async () => state),
  };
}
function stateOf(v, phase = "idle", error = null, zoneError = null, extra = {}) {
  return {
    view: v, token: v?.new_configuration_token ?? null, phase, error, zoneError,
    // S9-03(#829) — 보관된 선택 축은 서비스가 항상 세운다(미지원이 기본값).
    presets: extra.presets ?? { supported: false, items: [], corrupt: [] },
    presetNotice: extra.presetNotice ?? null,
  };
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

test("사라진 이전 선택은 현재 포함 내용과 분리된 informational 로만 그린다(내부 key 비노출)", () => {
  const withGone = view("SLOT_SELECTIONS_COMPLETE",
    [slot("s1", "표지 유형", "RESOLVED", [opt("o1", "기본 표지", true)])],
    { retained: [{ slot_id: "removed-slot", slot_display_text: null, option_ids: ["ghost-opt"], fate: "SLOT_REMOVED" }] });
  const html = render(stateOf(withGone));
  assert.match(html, /현재 문서에는 반영되지 않습니다/); // 정직한 일반 문안
  assert.ok(!html.includes("removed-slot")); // raw slot_id 비노출
  assert.ok(!html.includes("ghost-opt")); // raw option_id 비노출
});

test("pending 동안 radio 를 disabled 로 그려 중복 mutation 을 막는다", () => {
  const html = render(stateOf(NEEDS, "pending"));
  assert.match(html, /disabled/);
  assert.match(html, /aria-busy="true"/);
});

test("pending 은 **줄을 세우지 않는다** — 왕복 하나에 높이가 두 번 튀지 않게", () => {
  // U4 계열1-26: 임시 줄이 섰다 사라지면 구획이 「접혔다 깜빡인다」로 보이는데 그 사이
  // 실제로 바뀐 것은 없다. 왕복 사실은 레이아웃을 안 건드리는 aria-busy·disabled 가 진다.
  const idle = render(stateOf(NEEDS, "idle"));
  const pending = render(stateOf(NEEDS, "pending"));
  const statusLines = (html) => (html.match(/class="cs-status/g) || []).length;

  assert.equal(statusLines(pending), statusLines(idle));
  assert.ok(!pending.includes("cs-status-pending"));
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

test("#903 detached 정리 표면은 없다 — 사라진 이전 선택은 정보로만 선다", () => {
  // detached 는 SG-01(#733) 이후 제품 경로에서 만들어지지 않는다(승계는 AUTO_KEEP 만 싣고,
  // AUTO_KEEP 은 그 Option 이 target 에 있어야 성립한다). 렌더될 수 없던 정리 버튼은 #903 에서
  // 걷혔고, 사라진 항목의 사연은 #777 의 `retained_selections` 가 정보로 재진술한다.
  const successor = view("NEEDS_SELECTION",
    [slot("s1", "표지", "MISSING_REQUIRED_SELECTION", [opt("o1", "기본")])],
    { retained: [
      { slot_id: "gone-slot", slot_display_text: null, option_ids: ["gone-opt"], fate: "SLOT_REMOVED" }] });
  const html = render(stateOf(successor));
  assert.ok(!html.includes("cs-detached"));
  assert.ok(!html.includes("이전 선택 모두 제거"));
  assert.match(html, /cs-retained-gone/); // 정보는 남는다(숨기지 않는다)
  assert.ok(!html.includes("gone-slot")); // 내부 key 비노출은 그대로
});

test("#777 이전 선택의 운명 셋을 서로 다르게 그린다(재판정 0·내부 key 비노출)", () => {
  // Template 이 바뀌면 이전 선택은 자동 승계되지 않는다(SG-01 fail-closed). 그렇다고 셋이
  // 똑같이 사라지면 사용자는 무엇을 잃었는지 묻지도 못한다 — 그래서 셋은 서로 다른 것으로
  // 그려진다. 판정(fate)은 backend 가 이미 했고 여기서 재판정하지 않는다.
  const successor = view(
    "NEEDS_SELECTION",
    [
      slot("s-keep", "공고 상세", "MISSING_REQUIRED_SELECTION", [opt("o-keep", "추정가격 표시")]),
      slot("s-other", "표지", "MISSING_REQUIRED_SELECTION", [opt("o-x", "기본")]),
    ],
    {
      blocking: [{ slot_id: "s-keep", kind: "MISSING_REQUIRED_SELECTION", option_id: null }],
      retained: [
        {
          slot_id: "s-keep", slot_display_text: "공고 상세",
          option_ids: ["o-keep"], fate: "RESOLVED",
        },
        {
          slot_id: "s-other", slot_display_text: "표지",
          option_ids: ["o-vanished"], fate: "SELECTED_OPTION_REMOVED",
        },
        {
          slot_id: "s-gone", slot_display_text: null,
          option_ids: ["o-gone"], fate: "SLOT_REMOVED",
        },
      ],
    },
  );
  const html = render(stateOf(successor));

  // 셋이 서로 다른 것으로 나온다 — 남은 둘은 그 Slot 자리에, 사라진 항목은 정보 블록으로.
  assert.match(html, /data-fate="RESOLVED"/);
  assert.match(html, /data-fate="SELECTED_OPTION_REMOVED"/);
  assert.match(html, /cs-retained-gone/);
  assert.ok(!html.includes('data-fate="SLOT_REMOVED"'));

  // 남은 것은 다시 확인하라 하고, 사라진 것은 다른 것을 고르라고 말한다.
  assert.match(html, /이전에 이 항목에서 1개를 고르셨습니다/);
  assert.match(html, /다른 것을 골라 주세요/);
  assert.match(html, /항목 1개가 이 템플릿에는 없습니다/);

  // 「유지됩니다」라고 말하지 않는다 — 자동 승계가 아니다(그렇게 쓰면 새 거짓말이다).
  assert.ok(!html.includes("유지됩니다"));
  // 이전에 고른 Option 의 **이름**도 대지 않는다. 같은 ID 의 현재 라벨은 이전 라벨이 아니라서,
  // successor 가 그 ID 를 다른 뜻으로 다시 쓰면 없는 역사를 지어내게 된다. (라벨 자체는 지금
  // 고를 수 있는 항목으로서 화면에 있다 — 문제는 그것을 「이전에 고르신 것」이라 부르는 것이다.)
  const notes = [...html.matchAll(/class="cs-retained-note"[^>]*>([^<]*)</g)].map((m) => m[1]);
  assert.equal(notes.length, 2);
  assert.ok(notes.every((text) => !text.includes("추정가격 표시")), notes.join(" | "));
  // 내부 key 는 화면에 없다.
  for (const key of ["o-vanished", "s-gone", "o-gone"]) {
    assert.ok(!html.includes(key), key);
  }
});

test("#777 고를 수 있는 것이 없으면 「다른 것을 고르세요」라고 하지 않는다", () => {
  // Slot 은 남았는데 Option 이 전부 사라진 successor. 현재 blocker 는 NO_AVAILABLE_OPTIONS 라
  // 입력이 전부 비활성인데, 이전 선택 문안이 재선택을 시키면 할 수 없는 일을 시키는 것이다.
  const stuck = view(
    "HAS_BROKEN_SELECTIONS",
    [slot("s1", "공고 상세", "NO_AVAILABLE_OPTIONS", [])],
    {
      blocking: [{ slot_id: "s1", kind: "NO_AVAILABLE_OPTIONS", option_id: null }],
      retained: [
        {
          slot_id: "s1", slot_display_text: "공고 상세",
          option_ids: ["o-old"], fate: "NO_AVAILABLE_OPTIONS",
        },
      ],
    },
  );
  const html = render(stateOf(stuck));
  assert.match(html, /선택할 수 있는 항목이 없습니다/); // 현재 상태
  assert.match(html, /이 템플릿에서는 선택할 수 없습니다/); // 이전 선택의 운명
  assert.ok(!html.includes("다른 것을 골라 주세요"));
  assert.ok(!html.includes("다시 확인이 필요합니다"));
});

test("#777 이전 선택 이야기가 없으면 아무것도 그리지 않는다", () => {
  // 필드 부재(옛 backend)와 빈 목록 둘 다 조용히 통과해야 한다 — null 가드 결함이 초록으로
  // 지나가지 않게 두 경로를 다 센다.
  const plain = view("NEEDS_SELECTION", [
    slot("s1", "표지", "MISSING_REQUIRED_SELECTION", [opt("o1", "기본")]),
  ]);
  assert.ok(!render(stateOf(plain)).includes("cs-retained"));

  delete plain.projection.retained_selections;
  assert.ok(!render(stateOf(plain)).includes("cs-retained"));
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
  // U4 14~17 로 슬롯 상자가 `<details>` 가 됐다(접힘은 네이티브 위젯이 진다) — 세는 대상만
  // 바뀌고 재는 사실은 그대로다: **backend 가 준 slot 수 그대로**, 더하거나 빼지 않는다.
  const boxes = (html.match(/<details/g) ?? []).length;
  assert.equal(boxes, 2);
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

/* ══ S9-03(#829) 보관된 선택(Preset) — 저장·적용 두 동사 ═══════════════════════════════════ */
/** `actionable` 은 Python `preset_zone_actionable` 이 낸 값이다(U4 13번) — 대역은 그 셋 중
 *  둘(보관·손상)을 흉내내고, 「지금 저장할 선택」 갈래는 호출자가 명시로 세운다. */
/** 두 구획의 술어는 Python 이 낸다(U4 14~17): 목록은 `preset_list_actionable`, 저장은 저장
 *  게이트 그 자체다. 대역은 목록 축만 흉내내고 저장 축은 호출자가 세운다. */
function presetZone(items = [], corrupt = [], { listActionable, saveActionable } = {}) {
  return {
    supported: true,
    listActionable: listActionable ?? (items.length > 0 || corrupt.length > 0),
    saveActionable: saveActionable ?? false,
    items,
    corrupt,
  };
}
function presetItem(key, name, createdAt = "2026-08-24T09:00:00") {
  return { key, name, created_at: createdAt };
}
function saveResult(status, extra = {}) {
  return {
    status,
    code: extra.code ?? null,
    saved_key: extra.savedKey ?? null,
    existing_key: extra.existingKey ?? null,
    existing_created_at: extra.existingCreatedAt ?? null,
    detail: extra.detail ?? null,
  };
}
function applyResult(v, extra = {}) {
  const {
    applied = [], broken = [], refresh = false, rejection = null, detail = null,
    mutation = {
      outcome_code: "CHANGED", changed: true, outcome_replayed: false, request_relation: "CURRENT",
    },
  } = extra;
  return {
    mutation_outcome: rejection === null ? mutation : null,
    current_view: rejection === null ? v : null,
    refresh_required: refresh,
    applied_slot_ids: applied,
    broken,
    applied_count: applied.length,
    broken_count: broken.length,
    rejection_code: rejection,
    rejection_detail: detail,
  };
}
function fakeModal(answers = {}) {
  const calls = [];
  return {
    calls,
    prompt(spec) {
      calls.push({ kind: "prompt", spec });
      return Promise.resolve(answers.prompt ?? null);
    },
    confirm(spec) {
      calls.push({ kind: "confirm", spec });
      return Promise.resolve(answers.confirm ?? false);
    },
  };
}

test("savePreset: dispatch 왕복 뒤 결과를 상태로 싣는다(Configuration 은 건드리지 않는다)", async () => {
  const client = fakeClient(() => okv(saveResult("SAVED", { savedKey: "k1" })));
  const svc = createSlotConfigService({ client });
  svc.hydrate(SELECTED);
  const st = await svc.savePreset("표준 구성");
  assert.equal(client.calls[0].action, "save_selection_preset");
  assert.deepEqual(client.calls[0].payload, { configuration_token: "tok-1", name: "표준 구성" });
  assert.deepEqual(st.presetNotice, { kind: "saved", name: "표준 구성" });
  assert.equal(st.view, SELECTED); // 저장은 view 를 바꾸지 않는다
  assert.equal(st.token, "tok-1"); // 새 token 이 없으므로 쓰던 것을 그대로 든다
  assert.equal(st.phase, "idle");
});

test("savePreset: 이름 충돌은 확정 근거(key)와 함께 상태로 돌아온다(모달은 렌더 층 소관)", async () => {
  const client = fakeClient(() => okv(saveResult("NEEDS_CONFIRM", {
    code: "PRESET_NAME_CONFLICT", existingKey: "k-old", existingCreatedAt: "2026-08-01",
  })));
  const svc = createSlotConfigService({ client });
  svc.hydrate(SELECTED);
  const st = await svc.savePreset("표준 구성");
  assert.deepEqual(st.presetNotice, {
    kind: "save_conflict", name: "표준 구성", existingKey: "k-old", existingCreatedAt: "2026-08-01",
  });
  assert.equal(client.calls.length, 1); // 확정 없이 두 번째 저장을 스스로 보내지 않는다
});

test("savePreset(확정): 사용자가 본 그 항목의 key 를 되돌려 보낸다", async () => {
  const client = fakeClient(() => okv(saveResult("SAVED", { savedKey: "k-old" })));
  const svc = createSlotConfigService({ client });
  svc.hydrate(SELECTED);
  await svc.savePreset("표준 구성", "k-old");
  assert.equal(client.calls[0].payload.confirmed_overwrite_key, "k-old");
});

test("savePreset 거절은 코드로 상태에 남는다(조용한 성공 0)", async () => {
  const client = fakeClient(() => okv(saveResult("REJECTED", {
    code: "PRESET_EMPTY_SELECTION", detail: "저장할 선택이 없습니다(선택 0건).",
  })));
  const svc = createSlotConfigService({ client });
  svc.hydrate(NEEDS);
  const st = await svc.savePreset("빈 구성");
  assert.equal(st.presetNotice.kind, "save_rejected");
  assert.equal(st.presetNotice.code, "PRESET_EMPTY_SELECTION");
});

test("applyPreset: fresh view 통째 교체 + 새 token + 수치는 응답 값 그대로(재계산 0)", async () => {
  const applied = { ...SELECTED, new_configuration_token: "tok-after" };
  const broken = [{
    slot_id: "s-gone", selected_option_ids: ["o-gone"], clearable: false, status: "SLOT_REMOVED",
  }];
  const client = fakeClient(() => okv(applyResult(applied, { applied: ["s1"], broken })));
  const svc = createSlotConfigService({ client });
  svc.hydrate(NEEDS);
  const st = await svc.applyPreset("k1");
  assert.deepEqual(client.calls[0].payload, { configuration_token: "tok-1", preset_key: "k1" });
  assert.equal(st.view, applied);
  assert.equal(st.token, "tok-after");
  assert.equal(st.phase, "idle");
  // 수치는 목록 길이를 다시 센 값이 아니라 backend 가 낸 applied_count/broken_count 다.
  assert.equal(st.presetNotice.kind, "applied");
  assert.equal(st.presetNotice.applied, 1);
  assert.equal(st.presetNotice.broken, 1);
  assert.equal(st.presetNotice.brokenItems, broken);
});

test("applyPreset 거절: 새 view 가 없으므로 옛 상태를 두고 사유만 싣는다", async () => {
  const client = fakeClient(() => okv(applyResult(null, {
    rejection: "PRESET_NOT_FOUND", detail: "없는 파일",
  })));
  const svc = createSlotConfigService({ client });
  svc.hydrate(SELECTED);
  const st = await svc.applyPreset("gone");
  assert.equal(st.view, SELECTED); // 유령 교체 0
  assert.equal(st.token, "tok-1");
  assert.equal(st.presetNotice.kind, "apply_rejected");
  assert.equal(st.presetNotice.code, "PRESET_NOT_FOUND");
});

test("applyPreset: refresh_required 는 select 와 같은 stale 규율", async () => {
  const client = fakeClient(() => okv(applyResult(SELECTED, { applied: ["s1"], refresh: true })));
  const svc = createSlotConfigService({ client });
  svc.hydrate(NEEDS);
  const st = await svc.applyPreset("k1");
  assert.equal(st.phase, "stale");
  assert.equal(st.view, SELECTED);
});

test("token 없이 preset 왕복은 조용히 무동작하지 않고 시끄럽게 던진다", async () => {
  const client = fakeClient(() => okv(saveResult("SAVED", { savedKey: "k" })));
  const svc = createSlotConfigService({ client });
  await assert.rejects(async () => svc.savePreset("이름"), /configuration_token 이 없습니다/);
  await assert.rejects(async () => svc.applyPreset("k"), /configuration_token 이 없습니다/);
  assert.equal(client.calls.length, 0);
});

test("다른 command 가 끼면 직전 preset 결과 재진술은 지워진다(남의 왕복 결과 금지)", async () => {
  const client = fakeClient((action) => okv(
    action === "save_selection_preset" ? saveResult("SAVED", { savedKey: "k" }) : response(SELECTED),
  ));
  const svc = createSlotConfigService({ client });
  svc.hydrate(NEEDS);
  await svc.savePreset("표준 구성");
  assert.ok(svc.state().presetNotice !== null);
  await svc.selectOption("s1", "o1");
  assert.equal(svc.state().presetNotice, null);
});

test("컨트롤러: snapshot content_presets 존을 dispatch 없이 hydrate 한다", () => {
  const client = fakeClient(() => okv(response(SELECTED)));
  const svc = createSlotConfigService({ client });
  const { runtime } = fakeRuntime({
    slot_configuration: zone(NEEDS),
    content_presets: presetZone([presetItem("k1", "표준 구성")]),
  });
  const ctrl = createJobContentSelectionController({ runtime, service: svc });
  assert.deepEqual(ctrl.getSnapshot().presets.items, [presetItem("k1", "표준 구성")]);
  assert.equal(client.calls.length, 0);
});

test("컨트롤러 savePreset: 이름 입력 취소는 dispatch 0(빈 이름 보관 0)", async () => {
  const client = fakeClient(() => okv(saveResult("SAVED", { savedKey: "k" })));
  const svc = createSlotConfigService({ client });
  const { runtime } = fakeRuntime({
    slot_configuration: zone(SELECTED), content_presets: presetZone(),
  });
  const modal = fakeModal({ prompt: null });
  const ctrl = createJobContentSelectionController({ runtime, service: svc, modal });
  await ctrl.savePreset();
  assert.equal(modal.calls.length, 1);
  assert.equal(client.calls.length, 0);
});

test("컨트롤러 savePreset: 충돌 → danger 확인 → 그 항목 key 로 확정(조용한 덮기 0)", async () => {
  let round = 0;
  const client = fakeClient(() => okv(round++ === 0
    ? saveResult("NEEDS_CONFIRM", { code: "PRESET_NAME_CONFLICT", existingKey: "k-old" })
    : saveResult("SAVED", { savedKey: "k-old" })));
  const svc = createSlotConfigService({ client });
  const { runtime } = fakeRuntime({
    slot_configuration: zone(SELECTED), content_presets: presetZone(),
  });
  const modal = fakeModal({ prompt: "표준 구성", confirm: true });
  const ctrl = createJobContentSelectionController({ runtime, service: svc, modal });
  const st = await ctrl.savePreset();
  assert.equal(client.calls.length, 2);
  assert.equal(client.calls[0].payload.confirmed_overwrite_key, undefined);
  assert.equal(client.calls[1].payload.confirmed_overwrite_key, "k-old");
  assert.equal(st.presetNotice.kind, "saved");
  const confirmCall = modal.calls.find((c) => c.kind === "confirm");
  assert.equal(confirmCall.spec.danger, true); // 되돌릴 수 없는 덮어쓰기
  assert.match(String(confirmCall.spec.body), /되돌릴 수 없습니다/);
});

test("컨트롤러 savePreset: 확인 거절이면 두 번째 저장을 보내지 않는다", async () => {
  const client = fakeClient(() => okv(saveResult("NEEDS_CONFIRM", {
    code: "PRESET_NAME_CONFLICT", existingKey: "k-old",
  })));
  const svc = createSlotConfigService({ client });
  const { runtime } = fakeRuntime({
    slot_configuration: zone(SELECTED), content_presets: presetZone(),
  });
  const modal = fakeModal({ prompt: "표준 구성", confirm: false });
  const ctrl = createJobContentSelectionController({ runtime, service: svc, modal });
  await ctrl.savePreset();
  assert.equal(client.calls.length, 1);
});

test("존 렌더: 목록·적용 버튼과 정직한 빈 상태", () => {
  // U4 14~17: 두 구획이 갈렸다. 보관 0건 ∧ 저장할 선택 있음이면 **저장 구획만** 선다 —
  // 목록이 없으므로 「아직 없습니다」를 말할 목록 자체가 서지 않는다.
  const empty = render(stateOf(SELECTED, "idle", null, null, {
    presets: presetZone([], [], { saveActionable: true }),
  }));
  assert.ok(!empty.includes("보관된 선택이 아직 없습니다"));
  assert.match(empty, /현재 선택을 프리셋으로 저장/);

  const listed = render(stateOf(SELECTED, "idle", null, null, {
    presets: presetZone([presetItem("k1", "표준 구성")]),
  }));
  assert.match(listed, /표준 구성/);
  assert.match(listed, /적용/);
  assert.ok(!listed.includes(">k1<")); // 슬롯 키는 내부 식별자다
});

/* ══ U4 13번 — 확인할 것이 없으면 구획이 서지 않는다(#932 · U3 §3 적용 확장) ═══════════ */

test("13번: 고를 항목이 없으면 「포함할 내용」 구획이 통째로 서지 않는다", () => {
  const none = view("SLOT_SELECTIONS_COMPLETE", []);
  assert.equal(render(stateOf(none)), "");
});

test("13번: 술어는 Python 값이다 — 웹이 slots 길이로 다시 판정하지 않는다", () => {
  // 항목은 있는데 backend 가 「세우지 않는다」고 실으면 그 말을 따른다. 링2 가 `slots.length`
  // 로 재조립하면 이 단언이 빨강이 되고, 그것이 곧 같은 상태의 두 판정이다.
  const said = view("SLOT_SELECTIONS_COMPLETE",
    [slot("s1", "표지 유형", "RESOLVED", [opt("o1", "기본 표지", true)])],
    { zoneActionable: false });
  assert.equal(render(stateOf(said)), "");
});

test("13번: 항목 0건이어도 실패·거절 재진술은 숨기지 않는다", () => {
  const none = view("SLOT_SELECTIONS_COMPLETE", []);
  const failed = render(stateOf(none, "error", "옵션을 바꾸지 못했습니다"));
  assert.match(failed, /옵션을 바꾸지 못했습니다/);
  assert.match(failed, /role="alert"/);

  const noticed = render(stateOf(none, "idle", null, null, {
    presets: presetZone(),
    presetNotice: { kind: "saved", name: "표준 구성" },
  }));
  assert.match(noticed, /표준 구성.{0,12} 이름으로 보관했습니다/); // 따옴표는 HTML escape 된다
});

test("13번: 보관 0건 ∧ 저장할 선택 0건이면 「보관된 선택」 구획이 서지 않는다", () => {
  const html = render(stateOf(NEEDS, "idle", null, null, { presets: presetZone() }));
  assert.ok(!html.includes("cs-presets"));
  assert.ok(!html.includes("현재 선택을 프리셋으로 저장"));
  assert.match(html, /표지 유형/); // 구획 자체는 항목이 있어 그대로 선다
});

/* ══ U4 14~17 — 프리셋을 위로 · 끝난 슬롯은 접기 (#932) ═══════════════════════════════ */

test("14~17: 보관된 선택 목록이 첫 슬롯보다 **앞에** 그려진다", () => {
  const html = render(stateOf(SELECTED, "idle", null, null, {
    presets: presetZone([presetItem("k1", "표준 구성")]),
  }));
  // 한 번에 끝내는 길을 먼저 보여 준다 — 자리가 곧 순서의 뜻이다.
  assert.ok(html.indexOf("cs-presets") < html.indexOf("cs-slot"), html);
});

test("14~17: 저장 동사는 슬롯 **아래**에 남는다(고르고 나서 보관한다)", () => {
  const html = render(stateOf(SELECTED, "idle", null, null, {
    presets: presetZone([presetItem("k1", "표준 구성")], [], { saveActionable: true }),
  }));
  assert.ok(html.indexOf("cs-slot") < html.indexOf("cs-preset-save"), html);
});

test("14~17: 끝난 슬롯은 접힌 채 서고 고른 값을 그 줄이 말한다", () => {
  const html = render(stateOf(SELECTED));
  assert.match(html, /<details/);
  // `open` 은 class 뒤에 붙으므로 속성 순서에 기대지 않는다 — `/<details open/` 는 언제나
  // 거짓이라 이 단언이 vacuous 하게 통과했다(음성 단언이 아무것도 안 재던 자리).
  assert.ok(!/<details[^>]*\sopen=/.test(html), "끝난 슬롯이 펼쳐진 채 섰습니다");
  assert.match(html, /cs-slot-chosen/);
  assert.match(html, /기본 표지/); // 접힌 줄이 고른 값을 대신 말한다
});

test("14~17: 고를 것이 남은 슬롯은 펼쳐진 채 선다", () => {
  const html = render(stateOf(NEEDS));
  assert.match(html, /<details[^>]*\sopen=/);
});

test("14~17: 술어는 Python 값이다 — 웹이 status 로 다시 판정하지 않는다", () => {
  // RESOLVED 인데 backend 가 「접지 말라」고 실으면 그 말을 따른다. 웹이 재판정하면 빨강.
  const held = view("SLOT_SELECTIONS_COMPLETE",
    [slot("s1", "표지 유형", "RESOLVED", [opt("o1", "기본 표지", true)], [], false)]);
  assert.match(render(stateOf(held)), /<details[^>]*\sopen=/);
});

test("14~17: 접힌 슬롯도 DOM 에 남는다 — `cs-opt-N-M` 인덱스가 밀리지 않는다", () => {
  // 걸러내면 뒤 슬롯의 index 가 전부 밀려 실주행 대본이 **다른 슬롯을 누르고도 초록**이 된다.
  const mixed = view("NEEDS_SELECTION",
    [slot("s1", "표지 유형", "RESOLVED", [opt("o1", "기본", true), opt("o2", "간이")]),
      slot("s2", "부록 유형", "MISSING_REQUIRED_SELECTION", [opt("o3", "없음")])],
    { blocking: [{ slot_id: "s2", kind: "MISSING_REQUIRED_SELECTION", option_id: null }] });
  const html = render(stateOf(mixed));
  for (const id of ["cs-opt-0-0", "cs-opt-0-1", "cs-opt-1-0"]) {
    assert.ok(html.includes(`id="${id}"`), `${id} 가 사라졌습니다`);
  }
});

test("13번: 손상 항목만 있어도 「보관된 선택」 구획은 선다(비활성 + 사유 병기)", () => {
  const html = render(stateOf(NEEDS, "idle", null, null, {
    presets: presetZone([], [{ file_name: "bad.preset.json", error: "digest 불일치" }]),
  }));
  assert.match(html, /cs-preset-corrupt/);
  assert.match(html, /파일이 손상돼 적용할 수 없습니다/);
});

test("존 렌더: 손상 항목은 숨기지 않고 비활성 + 사유 병기", () => {
  const html = render(stateOf(SELECTED, "idle", null, null, {
    presets: presetZone(
      [presetItem("k1", "표준 구성")],
      [{ file_name: "bad.preset.json", error: "digest 불일치" }],
    ),
  }));
  assert.match(html, /표준 구성/); // 정상 항목은 그대로
  assert.match(html, /cs-preset-corrupt/);
  assert.match(html, /파일이 손상돼 적용할 수 없습니다/);
  assert.match(html, /disabled/);
  assert.ok(!html.includes("digest 불일치")); // 내부 진단 원문은 화면 문안이 아니다
});

test("존 렌더: 적용 결과를 「적용 n · 깨짐 m」으로 재진술하고 m>0 을 숨기지 않는다", () => {
  const clean = render(stateOf(SELECTED, "idle", null, null, {
    presets: presetZone([presetItem("k1", "표준 구성")]),
    presetNotice: { kind: "applied", applied: 2, broken: 0, brokenItems: [] },
  }));
  assert.match(clean, /2개를 적용했습니다/);
  assert.match(clean, /aria-live="polite"/);

  const partial = render(stateOf(SELECTED, "idle", null, null, {
    presets: presetZone([presetItem("k1", "표준 구성")]),
    presetNotice: {
      kind: "applied", applied: 1, broken: 2,
      brokenItems: [{
        slot_id: "s-gone", selected_option_ids: ["o"], clearable: false, status: "SLOT_REMOVED",
      }],
    },
  }));
  assert.match(partial, /1개를 적용했고 2개는 현재 문서에 적용되지 않습니다/);
  assert.ok(!partial.includes("s-gone")); // 내부 key 비노출
});

test("존 렌더: 거절은 alert 로 서고 내부 진단 원문을 그리지 않는다", () => {
  const html = render(stateOf(SELECTED, "idle", null, null, {
    presets: presetZone(),
    presetNotice: { kind: "apply_rejected", code: "PRESET_ENTRY_CORRUPT", detail: "선언 digest 불일치" },
  }));
  assert.match(html, /읽을 수 없어 적용하지 않았습니다/);
  assert.match(html, /role="alert"/);
  assert.ok(!html.includes("선언 digest 불일치"));
});

test("존 렌더: pending 중에는 저장·적용 버튼이 비활성이다", () => {
  const html = render(stateOf(SELECTED, "pending", null, null, {
    presets: presetZone([presetItem("k1", "표준 구성")]),
  }));
  const disabled = (html.match(/disabled=""/g) ?? []).length;
  assert.ok(disabled >= 2, html); // 저장 + 적용
});

test("존 렌더: 미지원(비-hwpx·미선택)이면 프리셋 구획 자체가 서지 않는다", () => {
  const html = render(stateOf(SELECTED));
  assert.ok(!html.includes("cs-presets"));
});
