/* N-08 클러스터 D — 편집기·작업대·데이터 프로브. 네 레인 중 **가장 넓다**(상수 15·키 15).
 *
 * 기준 이식본은 형제 파일 `persistence_geometry.js`(클러스터 E) 다. 구조·이름꼴·주석 밀도·
 * 오류 처리를 그대로 따른다 — 레인마다 제 규약을 지으면 이식은 되돌릴 수 없이 갈라진다.
 *
 * 무엇을 옮겼나 — `src/hwpxfiller/webapp/app.py` 의 상수 15개와 그 호출 자리 22곳:
 *   ① `_VIEW_ORDER_PROBE_SETUP_JS`(2665)        → view_order            · 3754·3757·3762
 *   ② `_DATA_SHEET_PROBE_SETUP_JS`(2698)        → data_sheet            · 3764·3767·3772
 *   ③ `_RANGE_DRAFT_PROBE_SETUP_JS`(2799)       → range_draft           · 3774·3777·3782
 *   ④ `_PREVIEW_DRAWER_PROBE_SETUP_JS`(2825)    → preview_drawer        · 3786
 *   ⑤ `_EDITOR_GUARD_PROBE_SETUP_JS`(2032)      → editor_guard          · 3794
 *   ⑥ `_EDITOR_DISCARD_CANCEL_PROBE_JS`(2110)   → editor_discard_cancel · 3802
 *   ⑦ `_EDITOR_TXT_BAND_PROBE_SETUP_JS`(3311)   → editor_txt_band       · 3808
 *   ⑧ `_WORKBENCH_PROBE_SETUP_JS`(3371)         → workbench             · 3814
 *   ⑨ `_SHEET_PROBE_SETUP_JS`(797)              → sheet_gate            · 3863·3865
 *   ⑩ `_JOB_EDITMODE_PROBE_JS`(1950)            → job_editmode          · 3948
 *   ⑪ `_DATA_PICKER_PROBE_SETUP_JS`(2297)       → data_picker           · 3952
 *   ⑫ `_EDITOR_CHIP_PROBE_JS`(2221)             → editor_chip           · 3959
 *   ⑬ `_EDITOR_SAVE_GATE_PROBE_JS`(2389)        → editor_save_gate      · 3961
 *   ⑭ `_EDITOR_LIBRARY_MANAGE_PROBE_JS`(2506)   → editor_lib_manage     · 3966
 *   ⑮ `_EDITOR_LIB_PICKER_PROBE_JS`(2608)       → editor_lib            · 3985
 *
 * 호출 자리 22곳 중 **7곳은 후계자가 없다** — 사라진 게 아니라 러너가 삼킨 것이다:
 * 3757·3767·3777 은 창 객체 위의 스태시 이름을 문자열 보간으로 조회하는 폴링 줄이고,
 * 3762·3772·3782·3865 는 그 뒤의 회수 줄이다.
 * 폴링(시한)은 `deadlineMs` 가, 회수(값 인계)는 프로브의 **반환값**이 진다. 나머지 15곳이
 * 위 표의 1:1 대응이다.
 *
 * 무엇을 **안** 바꿨나: 프로브가 하는 일·순서·발신·재는 필드·타이밍 의도. 값 모양은 기준
 * 실행과 같다 — `tests/test_web_selftest_gate.py` 가 이 필드들을 이름으로 단언한다.
 *
 * 무엇을 바꿨나: **상태 인계 방식 하나뿐**. 창 객체 위의 `__<이름>` 스태시가 사라지고
 * 프로브가 결과를 반환한다. 실렌더를 모는 푸시 진입점도 전역 조회가 아니라 `ctx.push` 주입이고
 * `Nav`·`Bridge`·`Modal`·`SheetPicker`·`DataPicker`·`SurfaceSheet` 는 `ctx.services` 로 받는다.
 * 전역 쓰기 금지가 첫 이유고, 두 번째가 더 무겁다 — 번들러가 모듈 스코프 이름을 바꾸면 문자열
 * 보간으로 만든 전역 조회가 **조용히** 빗나간다(선언은 살고 결과는 죽는 결함류).
 *
 * 그리고 정리(teardown)의 소유가 바뀐다. 편집기·작업대 프로브는 셸을 덮는 화면을 열어 두고
 * 끝나면 **뒤따르는 프로브가 상단 탭을 「사라졌다」고 읽는다**. 레거시는 그 복귀를 측정 본문
 * 안에 섞어 두고 실패하면 `teardown_error` 필드에만 적었는데 그 필드를 읽는 테스트가 하나도
 * 없다 — 정리 실패가 **보이지 않는 채로** 다음 국면을 오염시킨다. 여기서는 복귀가 `teardown`
 * 훅이고, 실패는 러너 오류(`teardown_failed`)로 서서 뒤 프로브를 멈춘다. 필드 자체는
 * 배선 호환을 위해 그대로 남긴다(값 모양이 소비자 계약이다).
 *
 * 보존한 양성/음성 대조(하나도 잃지 않는다):
 *   · view_order            : `control_before`(양성대조 선행 — 없으면 무동작 프로브가 통과한다)
 *                             ↔ `after_roundtrip=='sourceAsc'` ↔ `restored=='sourceDesc'`.
 *   · data_sheet            : `moved`/`not_moved`/`restored` · `first_sticky` ·
 *                             `foot_shown_in_sheet` ↔ range_draft 의 `foot_hidden_in_screen`.
 *   · range_draft           : `opened_without_data === false`(거절) ↔ `present === true`.
 *   · preview_drawer        : 거절(`opened_without_data === false`) ↔ 성사(`opened === true`) ·
 *                             `prev_disabled=false`/`next_disabled=true` ·
 *                             `focus_on_body=false` + `focus_returned` · `pos_text=='2 / 2'` ·
 *                             `value_rows==2` · `closed_by_state`.
 *   · sheet_gate            : 확정(`picked=='확정됨:낙찰현황'`) ↔ 취소(`cancelled===null` +
 *                             `closed_after`). `status=='done'` 이 나머지를 유의미하게 만든다.
 *   · editor_guard          : `calls == [goto_section, save, goto_section:save]` — 마지막 하나가
 *                             저장→이어짐의 재발신이고, 그게 빠지면 처분이 절반만 일어난다.
 *   · editor_discard_cancel : `discarded === false`(취소 ≠ 버림) · `focus_fell_to_screen_root
 *                             === false` · `name_value_after_cancel=='공고서 수정'` ·
 *                             `flushed_before_open` · `trigger_connected_at_open`.
 *   · editor_save_gate      : 3단 `clean_disabled → typing_enabled → reverted_disabled` 와 그
 *                             행(row_*) 거울 · `gone_control_disables` · `row_value_survives_push`.
 *   · workbench             : `prev_disabled=false`/`next_disabled=true` ↔ 큐 퇴화
 *                             `degen_prev=='none'`/`degen_adv=='none'` · `card_fill`/`card_blank` ·
 *                             `leave_calls == [leave_guard, close]`.
 *   · data_picker           : `use_active_enabled` ↔ `use_archived_disabled` ·
 *                             `browse_pin_visible`(계산 스타일 + offsetParent 실가시성) ·
 *                             `register_gone` · `dupes_shown`.
 *   · editor_lib_manage /
 *     editor_lib            : 그룹 구획 ↔ 퇴화 평면(`flat_heads==0 && flat_rows==1`) ·
 *                             `move_hidden_before` ↔ `move_shown_after_chip`.
 *   · job_editmode          : `discard_disabled_clean`/`save_disabled_clean` ↔
 *                             `discard_enabled_dirty`/`save_enabled_dirty` ·
 *                             `ctx_hidden_when_voluntary` ↔ `ctx_shown`.
 *   · editor_chip           : `has_checkbox_staging === false`(소거의 음성 단언) ·
 *                             `src_cell_h_manual == src_cell_h_suggested`(실렌더 기하).
 *
 * **알면서 그대로 옮긴 취약점 둘**(가리지 않는다):
 *   ⓐ `editor_lib_manage` 의 클릭 5곳은 가시성 단언이 없다. 프로브 click 은 hidden 요소도
 *      통과하므로(F8 교훈) 「눈으로 본 것과 다른 결론」이 날 수 있는 자리다. 고치는 것은 이
 *      이식의 일이 아니다 — 실렌더 계약을 바꾸는 별건이고, 여기서 슬쩍 더하면 이식이
 *      「무엇을 바꿨나」의 한 줄을 잃는다. 아래 CLICK_SITES_WITHOUT_VISIBILITY 에 적어 둔다.
 *   ⓑ `editor_discard_cancel` 의 내부 폴링 상한(60 × 50ms + 300ms)은 레거시 회수 시한
 *      (`_probe_late` 2.5초)보다 **길다**. 레거시는 그래서 아직 pending 인 객체를 그대로
 *      실을 수 있었다(조용한 만료). 시한은 늘리지 않으므로 그 초과는 이제 시끄러운 실패다.
 *
 * 이 모듈은 **비활성(inert)** 이다. 제품 그래프가 import 하지 않고 전역을 쓰지 않으며,
 * import 만으로는 DOM 을 만지지도 리스너를 걸지도 않는다 — 전부 호출 시점에 일어난다.
 */

import { ERROR_CODES } from "../runner.js";

export const D_CLUSTER = "D";

/** 이 클러스터가 내는 키 전수. `schema.js` 의 `keysForCluster("D")` 와 **정확히** 같아야 하고,
 *  그 동일성은 테스트가 기계로 센다(여기서 schema 를 import 해 유도하면 그 대조가 사라진다 —
 *  둘 다 틀려도 같으면 초록인 자리가 된다). */
export const D_KEYS = Object.freeze([
  "data_picker", "data_sheet", "editor_chip", "editor_discard_cancel", "editor_guard",
  "editor_lib", "editor_lib_manage", "editor_save_gate", "editor_txt_band",
  "job_editmode", "preview_drawer", "range_draft", "sheet_gate", "view_order", "workbench",
]);

/** 가시성 단언 없이 `.click()` 하는 자리 전수 — **아는 채로** 옮긴 감도 공백이다.
 *  이식이 이 목록을 지어내지도, 조용히 메우지도 않는다(둘 다 이식을 흐린다). */
const CLICK_SITES_WITHOUT_VISIBILITY = Object.freeze([
  "editor_lib_manage: 흘리기용 body 클릭(Popover 바깥-닫기 잔재 청소)",
  "editor_lib_manage: 행 ⋮ (b.hwpx)",
  "editor_lib_manage: 행 ⋮ (메모.txt)",
  "editor_lib_manage: 그룹 헤더 ⋮",
  "editor_lib_manage: ＋그룹지정 칩",
  "editor_guard: 단계 탭(filename) · 3택 모달 주 행동",
  "editor_discard_cancel: 「변경 버리기」 · 확인 모달 취소",
  "data_picker: 「이 데이터 고정」 · 「찾아보기」(뒤이어 browse_pin_visible 이 가시성을 잰다)",
  "data_sheet: ⤢ 트리거 · 면 닫기",
  "preview_drawer: 미리보기 열기 트리거",
  "workbench: 결과 조각(data-token)",
]);

/* ────────────────────────── 공용 조각 ────────────────────────── */

/** 주입 서비스 회수 — 없으면 조용히 no-op 되지 않고 계약 위반으로 선다. */
function service(ctx, name) {
  const found = ctx.services ? ctx.services[name] : null;
  if (!found) ctx.fail(ERROR_CODES.CONTRACT, `${name} 이(가) 주입되지 않았습니다.`);
  return found;
}

/** React 제어 입력에 값을 넣는다 — `el.value = …` 는 React 의 값 추적기를 지나쳐
 *  `onChange` 가 안 뜬다(제어 컴포넌트는 자기가 쓴 값을 기억한다). 네이티브 setter 로
 *  써야 추적기가 「바뀌었다」를 보고, 그때서야 사용자 입력과 같은 경로가 된다.
 *  legacy 는 비제어 입력이라 대입 한 줄이면 됐다 — 그 차이가 이 헬퍼의 존재 이유다. */
function typeValue(ctx, element, value) {
  /* setter 는 **원소의 프로토타입 사슬**에서 찾는다 — 생성자 이름(`HTMLInputElement`)으로
     집으면 그 전역이 없는 대역에서 던지고, 그 던짐은 계약이 아니라 환경의 사실이다. */
  let setter = null;
  for (let proto = Object.getPrototypeOf(element); proto; proto = Object.getPrototypeOf(proto)) {
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && typeof descriptor.set === "function") {
      setter = descriptor.set;
      break;
    }
  }
  if (setter) setter.call(element, value);
  else element.value = value;          // 접근자가 없는 대역 — 대입이 곧 값이다
  fire(ctx, element, "input");
}

/** React 커밋 한 turn 양보 — R4 표면은 push·상태 변이를 **같은 호출 스택에서 받지만**
 *  concurrent root 의 DOM 커밋은 다음 turn 에 끝난다. 고정 지연이 아니라 0ms turn 하나다.
 *  legacy 렌더가 동기였던 자리마다 이 한 줄이 들어간다(`probes/job.js` 의 같은 관례). */
function settleRender(ctx) {
  return ctx.sleep(0);
}

/** 조건이 설 때까지 turn 을 양보한다 — 첫 portal 묶음이 나뉘어 커밋될 때의 방어선.
 *  조건 충족 즉시 끝나므로 고정 지연이 아니고, 안 서면 그대로 읽어 **빨강으로** 남는다. */
async function settleUntil(ctx, ready, turns = 12) {
  for (let turn = 0; turn < turns; turn += 1) {
    if (ready()) return true;
    await ctx.sleep(0);
  }
  return !!ready();
}

/** 모달 닫힘 전이(CSS opacity)를 정착시킨다. 카드가 없으면 이미 정착한 것으로 본다. */
function settleModal(ctx, id) {
  const card = ctx.doc.querySelector(`#${id} .modal-card`);
  if (!card) return false;
  const ev = new ctx.win.Event("transitionend", { bubbles: true });
  Object.defineProperty(ev, "propertyName", { value: "opacity" });
  card.dispatchEvent(ev);
  return true;
}

/** legacy `Bridge.call`과 R4 `Client.dispatch`를 **같은 수명**으로 가로챈다.
 *
 *  R4 React owner는 typed client를 부르고 #416 legacy remainder는 Bridge를 부른다. 합성
 *  snapshot 위에서 하나만 스텁하면 다른 하나가 실 백엔드로 새어 서로 다른 세계를 본다.
 *  typed 쪽 반환은 HostResult로 감싸되 스텁 본문은 기존 raw Bridge 계약을 그대로 쓴다.
 *  복원은 "내 스텁일 때만" — 앞 블록의 복원이 뒤 블록의 발신을 삼키는 표본이 이미 있다
 *  (프로브 교차 오염 금지, [[gate-env-gotchas]]). */
function stubBridgeCall(ctx, make) {
  const Bridge = service(ctx, "Bridge");
  const real = Bridge.call;
  const mine = make(real);
  Bridge.call = mine;
  const Client = ctx.services && ctx.services.Client;
  const realDispatch = Client && Client.dispatch;
  const typedMine = typeof realDispatch === "function"
    ? async function (screen, action, payload) {
      return { ok: true, value: await mine(screen, action, payload) };
    }
    : null;
  if (typedMine) Client.dispatch = typedMine;
  return {
    real,
    restore() {
      if (Bridge.call === mine) Bridge.call = real;
      if (typedMine && Client.dispatch === typedMine) Client.dispatch = realDispatch;
    },
  };
}

/** 직접 bridge 메서드도 R4 `Client.invoke(snake_name, …)`와 한 수명으로 교체한다. */
function stubBridgeInvoke(ctx, bridgeName, contractName, make) {
  const Bridge = service(ctx, "Bridge");
  const real = Bridge[bridgeName];
  const mine = make(real);
  Bridge[bridgeName] = mine;
  const Client = ctx.services && ctx.services.Client;
  const realInvoke = Client && Client.invoke;
  const typedMine = typeof realInvoke === "function"
    ? async function (method, ...args) {
      if (method !== contractName) return realInvoke.call(Client, method, ...args);
      return { ok: true, value: await mine(...args) };
    }
    : null;
  if (typedMine) Client.invoke = typedMine;
  return {
    restore() {
      if (Bridge[bridgeName] === mine) Bridge[bridgeName] = real;
      if (typedMine && Client.invoke === typedMine) Client.invoke = realInvoke;
    },
  };
}

function styleOf(ctx, el) {
  return ctx.win.getComputedStyle(el);
}

function displayOf(ctx, el) {
  return styleOf(ctx, el).display;
}

function isHidden(ctx, el) {
  return displayOf(ctx, el) === "none";
}

function byId(ctx, id) {
  return ctx.doc.getElementById(id);
}

function textOf(el) {
  return el ? String(el.textContent) : "";
}

function fire(ctx, el, type) {
  el.dispatchEvent(new ctx.win.Event(type, { bubbles: true }));
}

/** **원소에서** 키를 올린다(문서 직접 발사가 아니다) — vendor 편집기가 그 키를 먹는지를
 *  재려면 사건이 그 편집기의 DOM 을 먼저 지나야 한다. 문서에 바로 쏘면 중간층을 건너뛰어
 *  「먹히지 않았다」가 언제나 참인 거짓 초록이 된다. */
function keydownOn(ctx, el, key) {
  el.dispatchEvent(new ctx.win.KeyboardEvent("keydown", { key, bubbles: true }));
}

/** contentEditable 표면에 **붙여넣기**로 본문을 넣는다.
 *
 *  `el.value = …`(React 제어 입력)도 `el.textContent = …`(DOM 되쓰기)도 여기서는 통하지
 *  않는다 — 앞은 그런 프로퍼티가 없고, 뒤는 편집기가 자기 상태로 DOM 을 되돌린다(실측:
 *  주입 뒤 문서가 그대로였다). 붙여넣기는 편집기가 **명시 처리기**로 받는 실제 사용자
 *  경로라, 그 경로로 넣어야 「사용자가 친 것과 같은 길」이라는 말이 참이 된다. */
function pasteInto(ctx, el, text) {
  const transfer = new ctx.win.DataTransfer();
  transfer.setData("text/plain", text);
  el.dispatchEvent(new ctx.win.ClipboardEvent("paste", {
    clipboardData: transfer, bubbles: true, cancelable: true,
  }));
}

/** 실시간(ms) 대기 — `settleUntil` 은 turn 양보라 **디바운스·브리지 왕복을 못 넘긴다**.
 *  조건이 서면 즉시 끝나므로 고정 지연이 아니고, 안 서면 그대로 읽어 빨강으로 남는다. */
async function waitFor(ctx, ready, tries = 30, ms = 40) {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (ready()) return true;
    await ctx.sleep(ms);
  }
  return !!ready();
}

/** TXT 저작 린트메모장 실물 확인(S10-05 #862 · #299 회수) — `editor_txt_band` 의 뒷단계.
 *
 *  정적 계약이 못 보는 넷을 실 WebView2 에서 센다:
 *
 *  ① CodeMirror 가 **정말 마운트되는가**(모듈은 있는데 붙지 않는 상태가 정적으로는 초록).
 *  ② 판정이 **왕복해 실물이 되는가** — 강조 두 종과 진단 줄이 Python 이 낸 좌표·문안에서
 *     온다. 프론트에 정규식이 없으므로 왕복이 죽으면 강조가 0 이 되어 바로 드러난다.
 *  ③ **Escape 를 vendor 가 먹지 않는가** — 키맵을 안 세운 것이 계약이고, 그 계약이 깨지면
 *     더럽혀진 창의 이탈 가드가 조용히 우회된다(저장 안 한 저작이 소리 없이 사라진다).
 *  ④ 창을 닫으면 **인스턴스가 걷히는가**(누수는 다음 열기에서 두 벌로 보인다).
 *
 *  본문 주입은 `contentDOM.textContent` 다 — CodeMirror 가 IME·붙여넣기로 DOM 이 바뀌었을 때
 *  쓰는 **되읽기** 경로와 같은 자리라, 값 대입으로 상태를 밀어 넣는 것보다 사용자 입력에
 *  가깝다. 새 창을 늘리지 않는다: 이 단계는 이미 서 있는 편집기 세션 위에 얹힌다. */
async function probeLintpad(ctx, out) {
  const doc = ctx.doc;
  const trigger = doc.querySelector('#editor-body [data-act="lib-new-txt"]');
  out.lintpad_trigger = !!trigger;
  if (!trigger) return;
  trigger.click();
  out.lintpad_mounted = await waitFor(ctx, () => !!doc.querySelector("#txtLintpad .cm-editor"));
  if (!out.lintpad_mounted) return;
  const content = doc.getElementById("txtEditContent");
  out.lintpad_content_editable = !!content && content.isContentEditable === true;
  /* 새 생성 창의 첫 초점은 **이름 칸**이다(메모장이 마운트에서 가로채면 여기가 갈린다).
     메모장 자신이 초점 대상이 되는지는 바로 아래에서 따로 잰다. */
  out.lintpad_focus = doc.activeElement ? doc.activeElement.id : "";
  content.focus();
  out.lintpad_focusable = doc.activeElement ? doc.activeElement.id : "";
  /* 양성 대조의 **선행 음성** — 주입 전에는 강조가 0 이어야 한다. 이게 없으면 늘 켜져 있는
     클래스도 초록을 훔친다. */
  out.lintpad_marks_before = doc.querySelectorAll("#txtLintpad .cm-txtField").length
    + doc.querySelectorAll("#txtLintpad .cm-txtMarker").length;
  pasteInto(ctx, content, "제목: {{공고명}}\n{{#항목 사유}}");
  out.lintpad_lint_arrived = await waitFor(
    ctx, () => doc.querySelectorAll("#txtLintDiag li").length > 0);
  out.lintpad_field_marks = doc.querySelectorAll("#txtLintpad .cm-txtField").length;
  out.lintpad_marker_marks = doc.querySelectorAll("#txtLintpad .cm-txtMarker").length;
  const diagnostics = doc.querySelectorAll("#txtLintDiag li");
  out.lintpad_diag_count = diagnostics.length;
  out.lintpad_diag_text = diagnostics.length ? diagnostics[0].textContent : "";
  /* ③ 편집기 안에서 올린 Escape 가 모달 이탈 가드까지 도달하는가. 창은 더럽혀졌으므로
     **확인 왕복**이 서야 한다 — 바로 닫히면 그것이 곧 가드 우회다. */
  keydownOn(ctx, content, "Escape");
  const confirmRoot = doc.getElementById("confirmModal");
  out.lintpad_escape_asks = await waitFor(
    ctx, () => !!confirmRoot && !confirmRoot.classList.contains("hidden"), 20);
  if (out.lintpad_escape_asks) {
    doc.getElementById("confirmModalOk").click();
    settleModal(ctx, "confirmModal");
  }
  settleModal(ctx, "txtEditModal");
  out.lintpad_disposed = await waitFor(ctx, () => doc.getElementById("txtLintpad") === null, 20);
}

/** 몰입 표면을 걷고 셸을 되돌린다 — app.py:2058-2065 · 2158-2162 · 3316-3322 의 `finish()` 앞머리.
 *
 *  레거시는 실패를 `out.teardown_error` 에만 적었고 **아무 테스트도 그 필드를 읽지 않는다**.
 *  그래서 정리가 실패해도 증거는 초록이고, 뒤따르는 프로브가 상단 탭을 「사라졌다」고 읽는
 *  오염만 남았다. 여기서는 필드를 배선 호환으로 그대로 채우고 **동시에 던진다** — 러너가
 *  `teardown_failed` 로 세우고 뒤 국면을 건너뛴다. */
function restoreShell(ctx, out) {
  try {
    const Nav = ctx.services ? ctx.services.Nav : null;
    if (!Nav || typeof Nav.go !== "function") throw new Error("Nav.go 가 주입되지 않았습니다.");
    Nav.go("job", { force: true });
    const home = ctx.doc.querySelector('.navbtn[data-scr="job"]');
    if (home) home.focus();
  } catch (thrown) {
    out.teardown_error = String((thrown && thrown.message) || thrown);
    throw new Error(`셸 복귀 실패: ${out.teardown_error}`);
  }
  const nav = ctx.doc.querySelector(".nav");
  if (!nav || isHidden(ctx, nav)) {
    out.teardown_error = "몰입 표면이 걷히지 않아 상단 2탭이 숨은 채입니다.";
    throw new Error(
      `${out.teardown_error} — 뒤따르는 프로브가 탭을 「사라졌다」고 읽습니다.`,
    );
  }
}

/** 편집기 스냅샷의 공통 뼈대. 레거시 상수마다 손으로 적혀 있던 필드를 한 자리에 모으되,
 *  **값은 그대로**다(각 프로브가 자기 상수의 값으로 덮어쓴다). */
function editorBase(overrides) {
  return Object.assign({
    section: "template", sections: ["template", "binding", "filename"],
    reachable: { template: false, binding: false, filename: false },
    dirty_sections: [], dirty: false, is_draft: true, changes: {}, revisions: {},
    context: { entry_reason: "voluntary", evidence: {}, return_context: {} },
    template_path: "", template_name: "",
    field_count: 0, fields: [], raw_block: "", gate_error: false, gate: null, notice: null,
    editing_origin: "",
  }, overrides || {});
}

/** 편집기가 통지하는 세 탭(#323) — 노드가 서야 하는 자리의 전수. */
const NOTICE_SECTIONS = Object.freeze(["template", "binding", "filename"]);

/** 인라인 알림 채널 측정(#323) — 노드 실재(세 탭) · 구조화 거절의 **가시** 인라인 · alert 0.
 *
 *  `save` 만 스텁해 「막힌 저장」을 실제로 태운다. 값을 직접 심지 않는 이유는 그러면
 *  이 프로브가 자기가 심은 값을 되읽는 무동작 측정이 되기 때문이다 — 클릭 → 판정 →
 *  patch → 커밋의 실 경로를 지나야 「어느 탭에서 어디로 가는가」가 관측된다. */
async function measureNoticeChannel(ctx, baseSnap, saveBtn) {
  const BLOCKED = "저장 게이트 대역: 인라인으로 서야 합니다.";
  const out = { present: {}, alerts: 0 };
  let alerts = 0;
  const realAlert = ctx.win.alert;
  ctx.win.alert = function () { alerts += 1; };
  const stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
    if (screen === "editor" && action === "save") {
      return Promise.resolve({ ok: false, block_reason: BLOCKED });
    }
    return real(screen, action, payload);
  });
  try {
    for (const section of NOTICE_SECTIONS) {
      ctx.push("editor", Object.assign({}, baseSnap, { section, dirty: true }));
      await settleRender(ctx);
      out.present[section] = !!byId(ctx, "save-msg");
    }
    const save = saveBtn();
    out.save_enabled = !!(save && !save.disabled);
    if (save) save.click();
    await ctx.sleep(80);                              // 저장 왕복 + patch 커밋
    await settleRender(ctx);
    const node = byId(ctx, "save-msg");
    out.text = textOf(node);
    out.matches_block_reason = out.text.indexOf(BLOCKED) >= 0;
    /* 존재와 가시는 다르다 — 노드가 셸에 있어도 본문 재렌더가 덮거나 display:none 이면
       사용자는 아무것도 못 읽는다(프로브 click 이 hidden 을 통과하는 것과 같은 함정). */
    out.visible = !!node && !isHidden(ctx, node) && !!node.offsetParent;
    /* 셸 자리 확인 — 본문(`#editor-body`) 안이면 탭 전환·재렌더에 다시 증발한다. */
    const body = byId(ctx, "editor-body");
    out.inside_body = !!(node && body && body.contains(node));
  } finally {
    stub.restore();
    ctx.win.alert = realAlert;
  }
  out.alerts = alerts;
  return out;
}

/* ────────────────────────── 프로브 정의 ────────────────────────── */

/** 클러스터 D 의 프로브 전수를 **정의 데이터**로 낸다. 부작용 없음 — 부르기 전엔 아무 일도
 *  일어나지 않고, 이 함수를 부르는 것만으로도 DOM 을 만지지 않는다. */
export function createEditorWorkbenchDataProbes() {
  return [
    /* ── view_order (app.py:2665 상수 · 3754·3757·3762 호출) ─────────────────
       표시순서 축의 **실 왕복**. 결함류는 "왕복 뒤 옛 값으로 되돌아간다"라 실행으로만 잡힌다. */
    {
      name: "view_order",
      keys: ["view_order"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3754,
      deadlineMs: 6000,
      completionField: "pending",
      note:
        "양성대조 선행(measurement-litmus): `control_before` 가 없으면 값이 안 바뀌는"
        + " 무동작 프로브도 통과한다. 부팅 직후 값이 스냅샷과 같음을 먼저 증명하고 그 다음"
        + " 바뀌는지 본다 — 둘 중 하나는 반드시 깨진다.",
      async run(ctx) {
        const Bridge = service(ctx, "Bridge");
        const out = { pending: true };
        const sel = byId(ctx, "jobOrderSel");
        out.present = !!sel;
        if (!sel) { out.pending = false; return { view_order: out }; }
        out.options = Array.prototype.map.call(sel.options, (o) => o.value);
        try {
          const snap = await Bridge.initial("job");
          out.control_before = sel.value === snap.view_order && sel.value === "sourceDesc";
          out.note_before = String(textOf(byId(ctx, "jobOrderNote")) || "");
          sel.value = "sourceAsc";
          sel.dispatchEvent(new ctx.win.Event("change"));
          await ctx.sleep(400);                       // 왕복 + push 재렌더 여유(app.py:2685)
          out.after_roundtrip = sel.value;            // 되돌아왔으면 'sourceDesc'
          await Bridge.call("job", "set_view_order", { value: "sourceDesc" });
          await ctx.sleep(200);
          out.restored = sel.value;
        } catch (thrown) {
          /* 레거시는 `out.error` 를 담은 정상 모양 값을 그대로 내보냈다. 러너 계약은
             "프로브가 실패한 것"과 "프로브가 false 를 잰 것"을 가른다. */
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        }
        out.pending = false;
        return { view_order: out };
      },
    },

    /* ── data_sheet (app.py:2698 상수 · 3764·3767·3772 호출) ──────────────────
       ⤢ 데이터 펼침 면의 React 재마운트·복귀와 범위 편집기 footer 의 자리(F3).
       R4 전에는 SurfaceSheet 가 같은 노드를 옮겼지만, 이제 inline/sheet portal 중 한쪽만
       렌더한다. 그러므로 캡처한 노드의 identity 가 아니라 안정 ID의 현재 소유 위치를 잰다. */
    {
      name: "data_sheet",
      keys: ["data_sheet"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3764,
      deadlineMs: 6000,
      completionField: "pending",
      after: ["view_order"],
      afterReason:
        "레거시 드라이버 순서 그대로(3754 → 3764). 앞 프로브의 늦은 push 를 흘려보낸 뒤에"
        + " 자기 판을 세워야 남의 스냅샷이 내 면을 닫지 않는다.",
      settleBeforeMs: 300,
      settleReason:
        "app.py:2732 의 0.3초 quiesce — 실 세션은 작업 미선택이라 앞 프로브의 `!has_job`"
        + " 스냅샷이 늦게 도착하면 `syncModeDisplay` 가 펼침 면을 **정당하게** 닫는다."
        + " 내 면이 남의 push 에 닫히면 「이동 안 됨」으로 오독된다(관측자 오염의 반대 방향).",
      note:
        "`Nav.go('job')` 를 부르지 않는다 — 화면 전환은 REFRESH_ON_NAV 로 실 refresh 를 쏘고"
        + " 그 응답(작업 미선택 스냅샷)이 내가 연 면을 닫는다. 부팅 기본 화면이 이미 job 이다.",
      async run(ctx) {
        const ids = ["jobRecsHead", "jobOrderBar", "jobFilterChips", "jobTableHost",
          "jobSelStrip", "jobRangeFoot"];
        const out = { pending: true };
        const liveNodes = () => ids.map((id) => byId(ctx, id));
        const inside = (host, node) => !!host && !!node
          && (host.contains(node) || node.parentNode === host);
        out.present = liveNodes().every(Boolean);
        if (!out.present) { out.pending = false; return { data_sheet: out }; }

        const inlineHost = byId(ctx, "scr-job");
        const slot = byId(ctx, "dataSheetSlot");
        const trigger = byId(ctx, "jobDataExpand");
        ctx.state.ids = ids;
        ctx.state.inlineHost = inlineHost;
        ctx.state.slot = slot;

        /* 이 프로브가 합성한 초안의 생성·폐기만 스텁한다. R4 close guard는 폐기 성공 **뒤**에
           면을 닫으므로 open만 가로채면 cancel이 초안 없는 실 backend로 새고 복귀가 막힌다.
           다음 range_draft 프로브의 실 open은 복원 뒤라 양성 대조를 그대로 유지한다. */
        const stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
          if (screen === "job"
            && (action === "range_draft_open" || action === "range_draft_cancel")) {
            return Promise.resolve({ ok: true });
          }
          return real(screen, action, payload);
        });
        ctx.state.stub = stub;

        /* 아래 두 경로 리터럴의 역슬래시는 레거시 원문 그대로다(app.py:2737·2739): JS 는
           `\R` 을 항등 이스케이프로, `\t` 를 탭으로 읽는다. 값을 읽는 단언이 없어 무해하고,
           고치면 이식이 "무엇을 바꿨나" 한 줄을 잃는다 — 그대로 옮기고 여기 적어 둔다. */
        ctx.push("job", {                             // ② 자기 판(app.py:2736-2758)
          job_name: "공고서", has_job: true, out_dir: "C:\Results",
          data_label: "d.csv", data_source_label: "d.csv (파일)", data_notice: null,
          template_name: "t.hwpx", template_path: "C:\t.hwpx", template_missing: false,
          filename_pattern: "doc-{{seq}}", has_data: true, record_count: 2, selected_count: 2,
          view_order: "sourceDesc", order_note: "보이는 순서대로 생성됩니다.",
          range_draft: {
            open: true, dirty: false, sel_count: 2, selected_only: false,
            view_order: "sourceDesc",
          },
          records: [{ index: 1, selected: true, name: "doc-001.hwpx", summary: "사무비품" },
            { index: 0, selected: true, name: "doc-002.hwpx", summary: "전산장비" }],
          filter: {
            active: false, reapply_available: false, reapply_hint: "", search: "",
            chips: [], definition: "", branches: [],
            columns: [{ name: "공고명", kind: "text" }],
          },
          table: {
            columns: [{ name: "공고명", kind: "text" }],
            rows: [{
              index: 1, selected: true, name: "doc-001.hwpx", summary: "사무비품",
              cells: [[["사무비품", false]]],
            }, {
              index: 0, selected: true, name: "doc-002.hwpx", summary: "전산장비",
              cells: [[["전산장비", false]]],
            }],
            visible_count: 2, hidden_selected: [],
          },
          restate: { origin: "manual", filter_active: false, in_def: 0, extra: 0, sample: [1, 0] },
          preflight: { level: "ok", text: "ok" }, blank_fields: [], drift: [], name_tokens: [],
          gate: { enabled: true, level: "", text: "생성 준비" },
        });
        await settleRender(ctx);
        trigger.focus();
        trigger.click();
        await ctx.sleep(0);

        try {
          const sheetNodes = liveNodes();
          out.moved = sheetNodes.every((el) => inside(slot, el));
          out.not_moved = ids.filter((_id, i) => !inside(slot, sheetNodes[i]));
          out.first_sticky = styleOf(
            ctx, ctx.doc.querySelector("#jobTableHead th:first-child"),
          ).position === "sticky";
          /* footer 는 면 안에서만 선다 — 화면 안에서 숨긴 것과 같은 CSS 규칙의 반대 분기. */
          out.foot_shown_in_sheet = !isHidden(ctx, byId(ctx, "jobRangeFoot"));
          /* 닫기는 **비동기**다(리뷰 1R: 초안 폐기 성사 뒤에 닫는다) — 클릭 직후를 재면 아직
             안 끝난 복귀를 실패로 읽는다. 퇴장 전이를 정착시키며 복귀를 폴링한다. */
          byId(ctx, "dataSheetClose").click();
          let tries = 0;
          for (;;) {
            await ctx.sleep(50);
            settleModal(ctx, "dataSheet");
            const done = liveNodes().every((el) => inside(inlineHost, el));
            if (done || tries++ > 40) {
              out.restored = done && ctx.doc.activeElement === trigger;
              break;
            }
          }
        } catch (thrown) {
          out.error = `throw:${thrown && thrown.message}`;
          ctx.fail(ERROR_CODES.PROBE_THREW, out.error);
        }
        out.pending = false;
        return { data_sheet: out };
      },
      /* 실패해도 면은 **반드시** 닫는다: 열린 채 남기면 뒤 프로브의 포커스·모달 스택이
         통째로 오염돼 남의 계약이 대신 깨진다(app.py:2788-2791 의 의도 그대로). 레거시는 이
         구제를 조용히 했지만 여기서는 구제가 필요했다는 사실 자체를 시끄럽게 남긴다. */
      teardown(ctx) {
        if (ctx.state.stub) ctx.state.stub.restore();
        const ids = ctx.state.ids;
        const inlineHost = ctx.state.inlineHost;
        if (!ids || !inlineHost) return;
        const restored = () => ids.every((id) => {
          const node = byId(ctx, id);
          return !!node && (inlineHost.contains(node) || node.parentNode === inlineHost);
        });
        if (restored()) return;
        try {
          const SurfaceSheet = ctx.services ? ctx.services.SurfaceSheet : null;
          if (SurfaceSheet) SurfaceSheet.closeAndRestore("dataSheet");
          settleModal(ctx, "dataSheet");
        } catch (_) { /* 구제 실패도 아래에서 한 번에 시끄럽다 */ }
        if (restored()) return;
        throw new Error(
          "⤢ 펼침 면이 열린 채 남았습니다 — 뒤 프로브의 포커스·모달 스택을 오염시킵니다.",
        );
      },
    },

    /* ── range_draft (app.py:2799 상수 · 3774·3777·3782 호출) ─────────────────
       면과 초안이 같이 서고 같이 죽는가. 데이터 없으면 초안 생성이 **거절**되는 것이 계약이다. */
    {
      name: "range_draft",
      keys: ["range_draft"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3774,
      deadlineMs: 6000,
      completionField: "pending",
      after: ["data_sheet"],
      afterReason:
        "data_sheet 가 `range_draft_open` 을 스텁했다가 되돌린다 — 그 복원 **뒤**에 실 액션을"
        + " 불러야 거절 경로가 산다(스텁이 새면 `opened_without_data` 가 참이 되어 양성대조가"
        + " 뒤집힌다). `foot_hidden_in_screen` 은 data_sheet 의 `foot_shown_in_sheet` 와"
        + " 짝인 음성 극이라 같은 부팅에서 이 순서로 재야 대조가 성립한다.",
      note:
        "양성대조: 거절 경로와 성사 경로가 다른 값을 내야 프로브가 실물을 잰 것이다.",
      async run(ctx) {
        const Bridge = service(ctx, "Bridge");
        const out = { pending: true };
        const expand = byId(ctx, "jobDataExpand");
        const foot = byId(ctx, "jobRangeFoot");
        out.present = !!(expand && foot);
        if (!out.present) { out.pending = false; return { range_draft: out }; }
        out.foot_hidden_in_screen = isHidden(ctx, foot);
        try {
          await Bridge.call("job", "range_draft_open", {}).then(
            () => { out.opened_without_data = true; },
            () => { out.opened_without_data = false; },   // 데이터 없음 = 거절이 계약
          );
          const snap = await Bridge.initial("job");
          out.draft_state = snap.range_draft;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        }
        out.pending = false;
        return { range_draft: out };
      },
    },

    /* ── preview_drawer (app.py:2825 상수 · 3786 호출) ────────────────────────
       드로어가 실제로 값·이름·증거를 그리고, 상태가 면을 여닫는가. */
    {
      name: "preview_drawer",
      keys: ["preview_drawer"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3786,
      deadlineMs: 2500,
      deadlineRationale:
        "레거시 회수는 공용 `_probe_late`(app.py:3494-3506) 의 50 × 50ms = 2.5초 예산을 쓴다."
        + " 그 예산이 이 프로브의 전부이므로 그대로 두고, 초과는 조용한 통과가 아니라 실패다.",
      completionField: "pending",
      after: ["range_draft"],
      afterReason:
        "레거시 드라이버 순서 그대로(3774 → 3786). 양성대조인 **거절**을 스텁 걸기 전에"
        + " 실 액션으로 받아야 해서, 앞 프로브의 스텁 복원이 끝난 뒤여야 한다.",
      note:
        "양성대조 선행: 데이터 없이 열면 거절이다(§18.11-6). 거절과 성사가 다른 값을 내야"
        + " 이 프로브가 실물을 잰 것이다 — 둘 다 통과하면 아무것도 안 재고 있다는 뜻이다.",
      async run(ctx) {
        const Bridge = service(ctx, "Bridge");
        const out = { pending: true };
        const btn = byId(ctx, "jobPreviewOpen");
        const modal = byId(ctx, "previewSheet");
        out.present = !!(btn && modal);
        if (!out.present) { out.pending = false; return { preview_drawer: out }; }
        out.hidden_before = modal.classList.contains("hidden");

        /* 양성대조: 스텁을 걸기 **전에** 실 액션으로 거절을 받는다(데이터·작업 없음). */
        await Bridge.call("job", "preview_open", {}).then(
          () => { out.opened_without_data = true; },
          () => { out.opened_without_data = false; },
        );
        await ctx.sleep(60);                          // 앞 프로브의 늦은 push 를 흘려보낸다

        const stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
          if (screen === "job" && action === "preview_open") return Promise.resolve({ ok: true });
          if (screen === "job" && action === "preview_close") return Promise.resolve(null);
          return real(screen, action, payload);
        });
        ctx.state.stub = stub;

        ctx.push("job", {
          job_name: "공고서", has_job: true, out_dir: "C:\Results",
          data_label: "d.csv", data_source_label: "d.csv (파일)", data_notice: null,
          template_name: "t.hwpx", template_path: "C:\t.hwpx", template_missing: false,
          filename_pattern: "doc-{{seq}}", has_data: true, record_count: 2, selected_count: 2,
          view_order: "sourceDesc", order_note: "보이는 순서대로 생성됩니다.",
          range_draft: {
            open: false, dirty: false, sel_count: 0, selected_only: false,
            view_order: "sourceDesc",
          },
          records: [],
          filter: {
            active: false, reapply_available: false, reapply_hint: "",
            search: "", chips: [], definition: "", branches: [], columns: [],
          },
          table: { columns: [], rows: [], visible_count: 0, hidden_selected: [] },
          restate: { origin: null, filter_active: false, in_def: 0, extra: 0, sample: [] },
          preflight: { level: "ok", text: "ok" }, blank_fields: [], drift: [], name_tokens: [],
          gate: { enabled: false, level: "warn", text: "나갈 이름과 값을 승인해야 생성할 수 있습니다." },
          review: {
            required: true, approved: false, risk: "presentation",
            targets: ["금액(표시형)"], first_run: false, unknown_baseline: false,
            structure_changed: false,
          },
          preview: {
            open: true, can_open: true, pos: 1, total: 2, filename: "doc-002.hwpx",
            blank_only: false, blank_count: 1, can_prev: true, can_next: false,
            rows: [{ name: "공고명", value: "전산장비" }, { name: "금액", value: "" }],
            evidence: {
              policy: "formatted_value",
              rows: [{ name: "금액", value: "1,000", note: "표시형이 적용된 값입니다." }],
              note: "",
            },
            can_approve: true, empty_note: "",
          },
        });
        await settleRender(ctx);
        btn.focus();
        btn.click();
        await ctx.sleep(60);

        try {
          out.flag_shown = !isHidden(ctx, byId(ctx, "jobReviewFlag"));
          out.opened = !modal.classList.contains("hidden");
          out.pos_text = textOf(byId(ctx, "previewPos"));
          out.prev_disabled = byId(ctx, "previewPrev").disabled;
          out.next_disabled = byId(ctx, "previewNext").disabled;
          out.value_rows = ctx.doc.querySelectorAll("#previewRows .mir-row").length;
          out.evidence_rows = ctx.doc.querySelectorAll("#previewEvidenceRows .mir-row").length;
          out.filename = textOf(byId(ctx, "previewFilename"));
          /* 「빈 값 있는 건만 보기」(U2 §2.13) — 상태 되읽기(스냅샷이 정본, 낙관 토글 없음)와
             가용성(blank_count>0 이면 활성), 이름 계획 한 줄의 실렌더. */
          out.blank_toggle_pressed = byId(ctx, "previewBlankOnly").getAttribute("aria-pressed");
          out.blank_toggle_disabled = byId(ctx, "previewBlankOnly").disabled;
          out.name_plan = textOf(byId(ctx, "previewNamePlan"));
          /* 「적용 범위」 축 부재 되읽기(U2 §2.3) — 정적 계약은 id 부재를 보지만, JS 가 그
             자리를 다시 만들지 않는지는 실렌더에서만 확인된다. */
          out.scope_axis = !!byId(ctx, "previewScope");
          out.approve_shown = !isHidden(ctx, byId(ctx, "previewApprove"));
          /* 원격 닫힘: Python 이 닫았다고 말하면 DOM 도 닫힌다(상태의 진실은 스냅샷이다).
             세션은 살려 둔다 — 트리거가 살아 있어야 "초점이 트리거로 돌아온다"를 잴 수 있다
             (세션째 죽이면 트리거가 비활성이 되고, 그건 초점 **대안 착지**라는 다른 계약이다). */
          ctx.push("job", {
            job_name: "공고서", has_job: true, has_data: true,
            preview: {
              open: false, pos: 0, total: 2, can_open: true,
              blank_only: false, blank_count: 0, can_prev: false, can_next: false,
            },
            review: {
              required: false, approved: false, risk: "", targets: [],
              first_run: false, unknown_baseline: false, structure_changed: false,
            },
            records: [], blank_fields: [], drift: [], name_tokens: [],
            gate: { enabled: false, level: "warn", text: "" },
          });
          await ctx.sleep(40);
          const card = modal.querySelector(".modal-card");
          const ev = new ctx.win.Event("transitionend", { bubbles: true });
          Object.defineProperty(ev, "propertyName", { value: "opacity" });
          card.dispatchEvent(ev);                     // 비동기 닫힘을 정착시킨다
          out.closed_by_state = modal.classList.contains("hidden");
          out.focus_returned = ctx.doc.activeElement === btn;
          /* 초점이 문서 맨 앞으로 떨어지지 않았다는 사실도 따로 센다 — `focus()` 가 조용한
             no-op 이 되는 경로(비활성 트리거)의 증상이 정확히 이것이다. */
          out.focus_on_body = ctx.doc.activeElement === ctx.doc.body;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        }
        out.pending = false;
        return { preview_drawer: out };
      },
      teardown(ctx) {
        if (ctx.state.stub) ctx.state.stub.restore();
      },
    },

    /* ── editor_guard (app.py:2032 상수 · 3794 호출) ──────────────────────────
       탭 처분 3택의 **이어짐**(F7 1R P1) — 「저장하고 이동」이 저장까지만 하고 이동을 안 하면
       사용자가 고른 처분이 절반만 일어난다. 배선·문안·판정이 다 제자리이고 **성사 뒤 이어짐**만
       끊기므로 실 클릭 → 실 모달 → 실 재발신 순서를 그대로 밟고 발신 기록을 되읽는다. */
    {
      name: "editor_guard",
      keys: ["editor_guard"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3794,
      deadlineMs: 2500,
      deadlineRationale: "공용 `_probe_late` 예산 2.5초(app.py:3494-3506) 그대로.",
      completionField: "pending",
      after: ["preview_drawer"],
      afterReason:
        "레거시 드라이버 순서 그대로(3786 → 3794). 편집기는 셸을 덮는 화면이라 앞 프로브가"
        + " 「작업」 화면에서 재는 일을 끝낸 뒤에 열어야 한다.",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = { pending: true, calls: [] };
        ctx.state.out = out;

        const stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
          if (screen !== "editor") return real(screen, action, payload);
          out.calls.push(action + (payload && payload.disposition ? `:${payload.disposition}` : ""));
          if (action === "goto_section" && !(payload && payload.disposition)) {
            return Promise.resolve({
              ok: false, needs_section_guard: true, section: "binding",
              section_label: "필드 연결·표시", target: payload.section,
            });
          }
          if (action === "save") return Promise.resolve({ ok: true, saved_name: "공고서" });
          return Promise.resolve({});
        });
        ctx.state.stub = stub;

        try {
          Nav.go("editor", { force: true });
          ctx.push("editor", editorBase({
            section: "binding",
            reachable: { template: true, binding: true, filename: true },
            dirty_sections: ["binding"], dirty: true, is_draft: false,
            revisions: { template: 1, binding: 2 }, template_path: "C:/t/공고서.hwpx",
            template_name: "공고서.hwpx", editing_origin: "공고서",
            name: "공고서", pattern: "x", rows: [], source_fields: [],
            active_source_fields: [], ignored_source_fields: [], sample_rows: [],
            type_options: [], fmt_options: {}, provenance: null,
          }));
          await settleRender(ctx);
          const tab = ctx.doc.querySelector('#editor-steps button[data-section="filename"]');
          if (!tab) { out.why = "탭 버튼 없음"; out.pending = false; return { editor_guard: out }; }
          tab.click();

          let ticks = 0;
          for (;;) {
            await ctx.sleep(50);
            ticks += 1;
            /* R3-01(#410): chooseModal 골격은 React host 커밋 산물이라 이 프로브(실행 순서상
               첫 골격 소비자, 3794)가 닿는 시점의 부재를 관용한다 — 같은 폴링이 마운트 대기를
               겸하고, 끝내 안 뜨면 `why: "모달 미개방"` 이 게이트(`why == "완료"` 단언)에서 붉는다. */
            const ok = byId(ctx, "chooseModalOk");
            const chooseRoot = byId(ctx, "chooseModal");
            const open = chooseRoot !== null && !chooseRoot.classList.contains("hidden");
            if (open && ok) {
              out.modal_label = textOf(ok);
              ok.click();                             // 「저장하고 이동」
              await ctx.sleep(400);                   // 모달 정착(160ms) + 재발신 왕복
              out.why = "완료";
              break;
            }
            if (ticks > 40) { out.why = "모달 미개방"; break; }
          }
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, `throw:${thrown && thrown.message}`);
        } finally {
          stub.restore();
        }
        out.pending = false;
        return { editor_guard: out };
      },
      teardown(ctx) {
        if (ctx.state.stub) ctx.state.stub.restore();
        restoreShell(ctx, ctx.state.out || {});
      },
    },

    /* ── editor_discard_cancel (app.py:2110 상수 · 3802 호출) ─────────────────
       「변경 버리기」의 **취소 뒤 정합**(U2 §2.17 2R P2). 정산 없이 열면 blur 가 큐에 넣은
       `set_name` 이 모달이 떠 있는 사이 도착해 `#editor-foot` 을 갈아 끼우고, 저장해 둔
       트리거가 분리돼 취소가 화면 루트로 떨어진다. **비동기 도착 순서**만 어긋나는 결함이다. */
    {
      name: "editor_discard_cancel",
      keys: ["editor_discard_cancel"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3802,
      deadlineMs: 2500,
      deadlineRationale:
        "공용 `_probe_late` 예산 2.5초 그대로. 프로브 **안**의 폴링 상한(60 × 50ms + 300ms)이"
        + " 이 예산보다 길다는 것은 레거시의 결함이다 — 지나면 아직 pending 인 객체가 그대로"
        + " 실렸다. 시한을 늘려 그 결함을 덮지 않는다: 초과는 이제 시끄러운 실패다.",
      completionField: "pending",
      after: ["editor_guard"],
      afterReason: "레거시 드라이버 순서 그대로(3794 → 3802) — 같은 편집기 표면을 잇달아 쓴다.",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = { pending: true, calls: [] };
        ctx.state.out = out;

        const clean = editorBase({
          section: "filename",
          reachable: { template: true, binding: true, filename: true },
          dirty_sections: [], dirty: false, is_draft: false,
          revisions: { template: 1, binding: 2 }, template_path: "C:/t/공고서.hwpx",
          template_name: "공고서.hwpx", editing_origin: "공고서",
          name: "공고서", pattern: "공고서-{{ID}}", pattern_preview: "공고서-1.hwpx",
          rows: [], source_fields: [], active_source_fields: [], ignored_source_fields: [],
          sample_rows: [], type_options: [], fmt_options: {}, provenance: null,
          default_dataset: null, has_unsaved_work: false, dataset_name: "", schema_only: true,
          counts: { filled: 0, empty: 0, unmapped: 0 }, preview_empties: [],
          preview_index: 0, preview_count: 0, is_complete: true,
        });
        const dirty = Object.assign({}, clean, {
          dirty: true, dirty_sections: ["template"], has_unsaved_work: true, name: "공고서 수정",
        });
        const discardOf = () => ctx.doc.querySelector('#editor-foot [data-act="discard-patch"]');

        const stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
          if (screen !== "editor") return real(screen, action, payload);
          out.calls.push(action);
          if (action === "set_name") {
            /* 큐에 든 blur 발신이 **늦게** 도착하는 실제 조건을 그대로 만든다: 응답 전 지연 +
               도착 시 dirty 스냅샷 push(= `#editor-foot` 재구성 → 옛 트리거 분리). */
            return ctx.sleep(120).then(() => { ctx.push("editor", dirty); return {}; });
          }
          return Promise.resolve({});
        });
        ctx.state.stub = stub;

        try {
          Nav.go("editor", { force: true });
          ctx.push("editor", clean);
          await settleRender(ctx);
          const nameEl = byId(ctx, "editorName");
          if (!nameEl || !discardOf()) {
            out.why = "편집 표면 미구성";
            out.pending = false;
            return { editor_discard_cancel: out };
          }
          // ① 클린 세션에 타이핑 — 대기 편집이 서고 버리기가 열린다(1R 계약).
          nameEl.focus();
          typeValue(ctx, nameEl, "공고서 수정");
          out.discard_enabled_on_typing = !discardOf().disabled;
          out.name_node_stable = nameEl === byId(ctx, "editorName");
          out.name_node_connected = nameEl.isConnected;
          out.name_focus_stable = ctx.doc.activeElement === nameEl;
          // ② 곧바로 버리기 클릭. 실제 순서 그대로 blur→change(=큐 적재) 뒤 click 이 온다.
          fire(ctx, nameEl, "change");
          nameEl.blur();
          discardOf().click();

          let ticks = 0;
          for (;;) {
            await ctx.sleep(50);
            ticks += 1;
            const cancel = byId(ctx, "confirmModalCancel");
            const open = !byId(ctx, "confirmModal").classList.contains("hidden");
            if (open && cancel) {
              /* 확인이 열린 시점 = 정산이 끝난 뒤여야 한다: 큐의 set_name 이 이미 도착했으므로
                 그 push 의 재구성도 끝났고, 모달이 든 트리거는 **지금 살아 있는** 버튼이다. */
              out.flushed_before_open = out.calls.indexOf("set_name") === 0;
              out.trigger_connected_at_open = !!(discardOf() && discardOf().isConnected);
              cancel.click();                                   // ③ 취소
              await ctx.sleep(300);
              /* ④ 취소 뒤 정합: 초점이 화면 루트가 아니라 버리기 버튼으로 돌아오고, 친 값과
                    dirty 술어(두 버튼 활성)가 그대로다. 취소는 아무것도 버리지 않는다. */
              const active = ctx.doc.activeElement;
              out.focus_back_on_discard = !!(active && active.dataset
                && active.dataset.act === "discard-patch");
              out.focus_fell_to_screen_root = !!(active && active.id === "scr-editor");
              const nm = byId(ctx, "editorName");
              out.name_value_after_cancel = nm ? nm.value : null;
              const save = ctx.doc.querySelector('#editor-foot [data-act="save"]');
              out.discard_enabled_after_cancel = !!(discardOf() && !discardOf().disabled);
              out.save_enabled_after_cancel = !!(save && !save.disabled);
              out.discarded = out.calls.indexOf("discard_patch") !== -1;
              out.why = "완료";
              break;
            }
            if (ticks > 60) { out.why = "모달 미개방"; break; }
          }
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, `throw:${thrown && thrown.message}`);
        } finally {
          stub.restore();
        }
        out.pending = false;
        return { editor_discard_cancel: out };
      },
      teardown(ctx) {
        if (ctx.state.stub) ctx.state.stub.restore();
        restoreShell(ctx, ctx.state.out || {});
      },
    },

    /* ── editor_txt_band (app.py:3311 상수 · 3808 호출) ───────────────────────
       편집기 「템플릿」 탭 매체 2밴드(F6 PR-B). 겨누는 것 둘: ①TXT 밴드(선택 버튼 포함)가 실
       DOM 에 서는가 ②TXT 세션의 탭이 Python 이 파생한 2개(파일 이름 탭 부재, §3.2)인가. */
    {
      name: "editor_txt_band",
      keys: ["editor_txt_band"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3808,
      deadlineMs: 6000,
      deadlineRationale:
        "공용 `_probe_late` 예산 2.5초에 **린트메모장 단계**가 얹혔다(S10-05 #862): 창 열기 +"
        + " 디바운스 180ms + `tpl/txt_lint` 실왕복 + 이탈 확인 왕복이 한 프로브 안에서 돈다."
        + " 늘린 것은 매달림을 유한 시간에 빨강으로 만드는 상한이지 통과 조건이 아니다 —"
        + " 실측 여유(내부 대기 상한 2×1.2초)를 담되 무한정은 아니게 잡는다.",
      completionField: "pending",
      after: ["editor_discard_cancel"],
      afterReason: "레거시 드라이버 순서 그대로(3802 → 3808).",
      note:
        "레거시의 `teardown_error` 필드가 태어난 자리(app.py:3322). 그 필드를 읽는 테스트가"
        + " **하나도 없어** 정리 실패가 보이지 않았다 — 필드는 배선 호환으로 남기고, 실패는"
        + " 러너의 teardown 계약으로 시끄럽게 세운다."
        + " 같은 프로브가 TXT **저작** 표면까지 진다(S10-05 #862): 새 창을 늘리지 않고"
        + " 이미 선 세션에 단계를 얹는 것이 실창 게이트 규율이다.",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = { pending: true };
        ctx.state.out = out;
        try {
          Nav.go("editor", { force: true });
          const base = editorBase({
            context: {}, template_media: "",
            name: "", pattern: "", rows: [],
            source_fields: [], active_source_fields: [], ignored_source_fields: [],
            sample_rows: [], type_options: [], fmt_options: {}, provenance: null,
            library: {
              hwpx: { sections: [], flat: true },
              txt: {
                sections: [{
                  group: "", count: 1, collapsed: false,
                  items: [{
                    key: "기안.txt", name: "기안", path: "C:/t/기안.txt",
                    field_count: 3, error: "", current: false,
                  }],
                }],
                flat: true,
              },
            },
          });
          ctx.push("editor", base);
          await settleRender(ctx);
          const caps = Array.prototype.map.call(
            ctx.doc.querySelectorAll("#editor-body .grp .cap"), (el) => el.textContent);
          out.bands = caps.filter((t) => t === "HWPX 서식" || t === "TXT 기안");
          out.txt_pick = !!ctx.doc.querySelector(
            '#editor-body [data-act="use-library"][data-path="C:/t/기안.txt"]');
          await probeLintpad(ctx, out);
          ctx.push("editor", Object.assign({}, base, {
            sections: ["template", "binding"], template_path: "C:/t/기안.txt",
            template_name: "기안.txt", template_media: "txt",
          }));
          await settleRender(ctx);
          out.txt_tabs = ctx.doc.querySelectorAll("#editor-steps .wstep-tab").length;
          out.why = "완료";
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String(thrown && thrown.message));
        }
        out.pending = false;
        return { editor_txt_band: out };
      },
      teardown(ctx) {
        restoreShell(ctx, ctx.state.out || {});
      },
    },

    /* ── workbench (app.py:3371 상수 · 3814 호출) ─────────────────────────────
       TXT 검토·복사 작업대(재작성 F6 PR-A). 정적 계약이 못 보는 셋: ①몰입 셸(상단 2탭 은닉)이
       실제로 걸리는가 ②큐 퇴화가 큐 장치 3종을 실제로 감추는가 ③이탈이 **가드를 지나** 화면을
       바꾸는가(발신 순서까지). */
    {
      name: "workbench",
      keys: ["workbench"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3814,
      deadlineMs: 2500,
      deadlineRationale:
        "공용 `_probe_late` 예산 2.5초 그대로(내부 대기 160+120+260ms 가 그 안에 든다).",
      completionField: "pending",
      after: ["editor_txt_band"],
      afterReason: "레거시 드라이버 순서 그대로(3808 → 3814).",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = { pending: true };
        ctx.state.out = out;
        const seg = (t, kind, name) => ({ text: t, kind: kind || "literal", name: name || "" });
        const snap = {
          open: true, job_name: "발주요청_기안", mode_label: "온나라 기안 검토·복사",
          view: "filled", target_font: "malgun", fullwidth: false,
          notice: { text: "", level: "muted" },
          total: 3, copied_count: 1, is_complete: false,
          revision: { template: 1, binding: 4 },
          source_fields: ["부서", "사업명"],
          fmt_options: { text: [{ code: "plain", label: "그대로" }] },
          type_options: [{ code: "text", label: "텍스트" }],
          rows: [
            {
              name: "수신", state: "fill", source: "부서", own: "auto", manual: false,
              value: "회계과", fmt_kind: "text", fmt_code: "plain", suggest: "",
              can_revert: false, confirmed: true, blank_declared: false,
            },
            {
              name: "비고", state: "blank", source: "", own: "", manual: false, value: "",
              fmt_kind: "text", fmt_code: "plain", suggest: "", can_revert: false,
              confirmed: true, blank_declared: true,
            },
          ],
          dirty: { count: 1, fields: [{ name: "수신" }], pending: false },
          can_save: true, save_block: "",
          guard: { armed: true, lines: ["복사 진행 1/3건 — 나가면 이 진행은 사라집니다."] },
          card: {
            index: 0, has_current: true, queue_degenerate: false, position: 0, source_row: 7,
            /* 경계는 Python 이 낸다(2R P1) — 표시 자리는 머리(0)인데 순회상으로는 **후미**인
               상태를 합성한다(복사 직후의 실물). 표면이 서수로 계산하면 여기서 갈린다. */
            can_prev: true, can_next: false,
            /* 큐 색인(4R P2) — 순차 이동만으로는 아는 행에 못 간다. 자리 라벨은 원본 행 번호다. */
            index_map: [{ index: 0, row: 7, state: "current", recheck: true },
              { index: 1, row: 4, state: "uncopied", recheck: false }],
            review_state: "recheck", uncopied_count: 2, advance_after: false,
            segments: [seg("수신: "), seg("회계과", "fill", "수신"), seg("", "blank", "비고")],
            missing_fields: [], empty_fields: [],
            lint: { proportional: true, space_run: true, applied: false, active: true },
            last_copy: null, copied_total: 1,
          },
        };
        Nav.go("workbench");
        ctx.push("workbench", snap);
        await ctx.sleep(160);

        try {
          out.screen_on = !!ctx.doc.querySelector("#scr-workbench.on");
          out.nav_hidden = isHidden(ctx, ctx.doc.querySelector(".nav"));
          out.title = textOf(byId(ctx, "wbTitle"));
          out.position = textOf(byId(ctx, "wbPosition"));
          out.copied = textOf(byId(ctx, "wbCopied"));
          out.revision = textOf(byId(ctx, "wbRevision"));
          out.dirty_note = textOf(byId(ctx, "wbDirtyNote"));
          out.review = textOf(byId(ctx, "wbReview"));
          out.map_rows = ctx.doc.querySelectorAll("#wbMapPanel tbody tr").length;
          out.declared = ctx.doc.querySelectorAll("#wbMapPanel .mapval-declared").length;
          out.card_fill = ctx.doc.querySelectorAll("#wbCard .seg-fill").length;
          out.card_blank = ctx.doc.querySelectorAll("#wbCard .seg-blank").length;
          out.lint_shown = byId(ctx, "wbLint").style.display !== "none";
          /* 린트는 표지 + **행동**이 한 벌이다(2R P2) — 경고만 두면 손잡이 없는 통보가 된다. */
          out.lint_action = (function () {
            const b = ctx.doc.querySelector("#wbLint [data-fullwidth]");
            return b ? `${b.getAttribute("data-fullwidth")}:${b.textContent}` : "";
          })();
          out.dots = Array.prototype.map.call(
            ctx.doc.querySelectorAll("#wbDots .wc-dot"), (d) => d.getAttribute("title"));
          out.font_value = byId(ctx, "wbTargetFont").value;
          out.prev_disabled = byId(ctx, "wbPrev").disabled;
          out.next_disabled = byId(ctx, "wbNext").disabled;
          out.save_enabled = !byId(ctx, "wbSaveRules").disabled;
          /* 결과 → 규칙(계약 §11) — 조각이 토큰 신원을 지고 나가고, 누르면 소유 행이 선다.
             정적으로는 조각도 표도 다 있어 통과한다: 둘을 잇는 길만 없는 상태가 여기서만 잡힌다. */
          out.card_tokens = ctx.doc.querySelectorAll("#wbCard [data-token]").length;
          (function () {
            const s = ctx.doc.querySelector('#wbCard [data-token="수신"]');
            if (s) s.click();
          })();
          out.aim_row = (function () {
            const a = ctx.doc.activeElement;
            return a && a.tagName === "TR" ? (a.getAttribute("data-name") || "") : "";
          })();
          /* 강조는 CSS 파생이라 **실 스타일 계산**까지 봐야 참이다 — 표 클래스가 스타일시트와
             어긋나 있으면(구 `maptable`) 배선은 멀쩡한데 선 행이 아무 표지도 못 받는다. */
          out.aim_marked = (function () {
            const a = ctx.doc.activeElement;
            if (!a || a.tagName !== "TR" || !a.cells.length) return "";
            return styleOf(ctx, a.cells[0]).boxShadow;
          })();
          /* 큐 퇴화 — 1건이면 순회 장치가 숨는다(정보가 없어서지 장식이라서가 아니다). */
          ctx.push("workbench", Object.assign({}, snap, {
            total: 1, copied_count: 0,
            card: Object.assign({}, snap.card, { queue_degenerate: true, position: 0 }),
          }));
          await ctx.sleep(120);
          out.degen_prev = displayOf(ctx, byId(ctx, "wbPrev"));
          out.degen_adv = displayOf(ctx, ctx.doc.querySelector(".wb-adv"));
          /* 이탈이 가드를 지나는가 — Nav.go 가 위임하고, 위임이 발신 순서를 지키는지. */
          const calls = [];
          const stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
            if (screen === "workbench") {
              calls.push(action);
              if (action === "leave_guard") return Promise.resolve({ armed: false, lines: [] });
              return Promise.resolve({ ok: true });
            }
            return real(screen, action, payload);
          });
          ctx.state.stub = stub;
          Nav.go("job");
          await ctx.sleep(260);
          stub.restore();
          out.leave_calls = calls;
          out.landed = !!ctx.doc.querySelector("#scr-job.on");
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String(thrown));
        }
        out.pending = false;
        return { workbench: out };
      },
      /* 이탈은 이 프로브의 **측정 대상**이라 본문에 남는다. 정리는 그 이탈이 실제로 셸을
         되돌렸는지 확인하는 자리다 — 안 돌아왔으면 뒤 프로브가 상단 탭을 「사라졌다」고 읽는다. */
      teardown(ctx) {
        if (ctx.state.stub) ctx.state.stub.restore();
        restoreShell(ctx, ctx.state.out || {});
      },
    },

    /* ── sheet_gate (app.py:797 상수 · 3863·3865 호출) ────────────────────────
       다중 시트 확정 게이트(#33). 조용한 첫 시트 로드 금지의 핵심 보장을 실 DOM 에서 되읽는다:
       (1) 확정(시트 클릭)하면 그 시트로 로드돼 파일명이 해소되고, (2) 취소(Escape)하면 로드가
       일어나지 않고 null 로 해소(중단)된다. 모달 a11y 가 아니라 **데이터 적재 게이트**다. */
    {
      name: "sheet_gate",
      keys: ["sheet_gate"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3863,
      deadlineMs: 800,
      deadlineRationale:
        "app.py:3864 의 0.8초 고정 대기가 이 프로브의 **전 예산**이다(폴링이 아니라 sleep)."
        + " 지나면 레거시는 `status:'running'` 을 그대로 실어 게이트가 붉어졌다 — 같은 시한을"
        + " 그대로 쓰되 초과를 러너가 세운다.",
      after: ["workbench"],
      afterReason:
        "레거시 드라이버 순서 그대로(3814 → 3863). 앞의 몰입 프로브들이 셸을 되돌린 뒤여야"
        + " 모달 초기 포커스(`focus_first`)가 남의 잔재를 재지 않는다.",
      note:
        "`Bridge.loadDataSheet` 는 창을 실제로 열지 않도록 스텁(확정 시 파일명 반환)하고"
        + " 저장·복원한다. 확정/취소 두 회차가 서로 다른 값을 내야 게이트가 실물을 잰 것이다.",
      async run(ctx) {
        service(ctx, "Bridge");
        const SheetPicker = service(ctx, "SheetPicker");
        const out = { status: "running" };
        const loadStub = stubBridgeInvoke(
          ctx, "loadDataSheet", "load_data_sheet", () => function (screen, path, sheet) {
          return Promise.resolve(`확정됨:${sheet}`);   // 실 다이얼로그 대신 확정 시트명을 되쏨
          },
        );
        ctx.state.restoreLoad = () => { loadStub.restore(); };
        const payload = {
          needs_sheet: true, path: "C:/x/multi.xlsx", name: "multi.xlsx",
          sheets: [{ name: "공고목록", rows: 3, cols: 2 }, { name: "낙찰현황", rows: 4, cols: 3 }],
        };
        try {
          // (1) 확정 경로 — 열림·버튼수·초기포커스 되읽고 둘째 시트를 클릭해 해소.
          const p1 = SheetPicker.choose("job", payload);
          await settleUntil(ctx, () => ctx.doc.querySelectorAll("#sheetList .sheet-opt").length > 0);
          const opened = !byId(ctx, "sheetModal").classList.contains("hidden");
          const btns = ctx.doc.querySelectorAll("#sheetList .sheet-opt");
          const focusFirst = ctx.doc.activeElement === btns[0];
          btns[1].dispatchEvent(new ctx.win.MouseEvent("click", { bubbles: true }));
          /* onPick 은 Bridge.loadDataSheet(Promise)를 await 한 뒤 close 하므로 마이크로태스크를
             먼저 흘려 실제 is-closing 진입을 만든 다음 transitionend 를 완료시킨다. */
          await Promise.resolve();
          settleModal(ctx, "sheetModal");
          const picked = await p1;
          // (2) 취소 경로 — 다시 열고 Escape → null 로 해소(로드 없음).
          const p2 = SheetPicker.choose("job", payload);
          await settleRender(ctx);
          ctx.doc.dispatchEvent(
            new ctx.win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
          settleModal(ctx, "sheetModal");
          const cancelled = await p2;
          out.status = "done";
          out.opened = opened;                        // choose 가 모달을 열었는가
          out.btn_count = btns.length;                // 시트 수만큼 옵션 버튼
          out.focus_first = focusFirst;               // 초기 포커스가 첫 옵션에
          out.picked = picked;                        // 확정 시 확정 시트로 로드된 결과
          out.cancelled = cancelled;                  // 취소 시 null(중단 — 첫 시트 강등 없음)
          out.closed_after = byId(ctx, "sheetModal").classList.contains("hidden");
        } catch (thrown) {
          /* 레거시는 `{status:'throw', message}` 를 그대로 실었고 게이트가 `status=='done'`
             에서 붉어졌다. 러너 계약에서는 실패한 프로브의 키가 결과에 실리지 않는다. */
          ctx.fail(ERROR_CODES.PROBE_THREW, String(thrown && thrown.message));
        } finally {
          loadStub.restore();
        }
        return { sheet_gate: out };
      },
      teardown(ctx) {
        if (ctx.state.restoreLoad) ctx.state.restoreLoad();
      },
    },

    /* ── job_editmode (app.py:1950 상수 · 3948 호출) ──────────────────────────
       이름은 `JOB_` 이지만 재는 것은 **몰입 편집기 셸**이다(주제로 갈라 이 클러스터가 진다).
       정적 계약(클래스 존재)만 보면 「배선했지만 여전히 나갈 구멍이 있는」 상태를 통과시킨다. */
    {
      name: "job_editmode",
      keys: ["job_editmode"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3948,
      deadlineMs: 0,
      deadlineRationale:
        "동기 evaluate_js 한 번(app.py:3948) — 레거시에도 폴링도 대기도 없다.",
      after: ["sheet_gate"],
      afterReason:
        "레거시 드라이버 순서 그대로(3863 → 3948). 이 프로브가 마지막에 `Nav.go('job')` 로"
        + " 셸을 되돌리는 것이 뒤따르는 data_picker 의 전제(작업 화면 활성)를 만든다.",
      note:
        "마지막 `nav_back_after_leave` 는 **측정**이지 정리가 아니다 — 몰입이 영구 은닉이"
        + " 되는 회귀를 이 한 줄이 잡는다. 그래서 teardown 으로 옮기지 않았다.",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = {};
        try {
          Nav.go("editor", { force: true });
          out.editor_screen_on = byId(ctx, "scr-editor").classList.contains("on");
          out.job_screen_off = !byId(ctx, "scr-job").classList.contains("on");
          out.nav_hidden = isHidden(ctx, ctx.doc.querySelector(".nav"));
          out.back_shown = !isHidden(ctx, byId(ctx, "editorBack"));
          /* section 어휘(F7 판정 B) — 탭 집합은 Python 이 매체에서 파생해 내려준다. */
          const draft = editorBase({
            reachable: { template: false, binding: false, filename: false },
            is_draft: true, dirty: false, changes: {},
            context: { entry_reason: "voluntary", evidence: {}, return_context: {} },
            field_count: 0, fields: [], raw_block: "", editing_origin: "",
          });
          ctx.push("editor", draft);
          await settleRender(ctx);
          out.wizard_steps = ctx.doc.querySelectorAll("#editor-steps .wstep-tab .k").length;
          out.foot_shown_new = !isHidden(ctx, byId(ctx, "editor-foot"));
          draft.editing_origin = "공고서";
          draft.is_draft = false;
          ctx.push("editor", draft);
          await settleRender(ctx);
          out.edit_tabs = ctx.doc.querySelectorAll("#editor-steps button.wstep-tab.as-tab").length;
          /* 편집의 주 행동(「변경 저장」)은 어느 탭에서도 상시 있다(§10.13 판정 E). */
          out.foot_shown_edit = !isHidden(ctx, byId(ctx, "editor-foot"));
          /* 「변경 버리기」는 상시 표시 + 상태 비활성(U2 §2.17) — 존재 단언은 상시 표시가 되는
             순간 무엇을 밀어 넣어도 참이라 조용히 죽는다. 비활성 판정으로 승격해 clean/dirty
             **두 값**을 각각 재고, 저장이 같은 술어를 쓰는지도 함께 본다(음성·양성 대조). */
          const discardOf = () => ctx.doc.querySelector('#editor-foot [data-act="discard-patch"]');
          const saveOf = () => ctx.doc.querySelector('#editor-foot [data-act="save"]');
          out.discard_shown_clean = !!discardOf();
          out.discard_disabled_clean = !!(discardOf() && discardOf().disabled);
          out.save_disabled_clean = !!(saveOf() && saveOf().disabled);
          out.edit_dirty_tab_marked = await (async function () {
            draft.dirty_sections = ["binding"];
            draft.dirty = true;                 // 세션 수준 판정은 Python 이 낸 값 하나(3R)
            ctx.push("editor", draft);
            await settleRender(ctx);
            /* 손댄 상태에서는 머리가 「저장하지 않은 변경」을 말하고 제자리 되돌리기가 활성이다 —
               「저장됨」이라 말하면서 버릴 길도 없던 자리(3R P2). */
            out.dirty_head = textOf(byId(ctx, "editorSaveState"));
            out.discard_shown_dirty = !!discardOf();
            out.discard_enabled_dirty = !!(discardOf() && !discardOf().disabled);
            out.save_enabled_dirty = !!(saveOf() && !saveOf().disabled);
            return ctx.doc.querySelectorAll("#editor-steps button.wstep-tab.dirty").length;
          })();
          /* 머리 — 이름(안정 입력)·저장 상태·판본(§10.13 판정 O 표시 자리 ①). */
          draft.name = "공고서";
          draft.revisions = { template: 2, binding: 5 };
          draft.dirty_sections = [];
          draft.dirty = false;
          ctx.push("editor", draft);
          await settleRender(ctx);
          out.name_input_value = byId(ctx, "editorName").value;
          out.save_state = textOf(byId(ctx, "editorSaveState"));
          /* 진입 문맥 배너 — 사유가 있으면 서고 자발적 진입이면 침묵한다. */
          out.ctx_hidden_when_voluntary = isHidden(ctx, byId(ctx, "editorContext"));
          draft.context = {
            entry_reason: "preview_result", evidence: { "보고 있던 행": "4 / 12" },
            return_context: { surface: "preview" },
          };
          ctx.push("editor", draft);
          await settleRender(ctx);
          out.ctx_shown = !isHidden(ctx, byId(ctx, "editorContext"));
          out.ctx_text = textOf(byId(ctx, "editorContext"));
          out.ctx_return_btn = !!ctx.doc.querySelector('#editorContext [data-act="context-return"]');
          /* 나간 뒤엔 셸이 돌아온다 — 몰입이 영구 은닉이 되면 다른 화면으로 갈 길이 사라진다. */
          Nav.go("job", { force: true });
          out.nav_back_after_leave = !isHidden(ctx, ctx.doc.querySelector(".nav"));
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, `throw:${thrown && thrown.message}`);
        }
        return { job_editmode: out };
      },
    },

    /* ── data_picker (app.py:2297 상수 · 3952 호출) ───────────────────────────
       데이터 선택 다이얼로그 — `pool` 화면 사망의 승계처가 **실제로 서는지**(F1 · U2 §2.7). */
    {
      name: "data_picker",
      keys: ["data_picker"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3952,
      deadlineMs: 2500,
      deadlineRationale: "공용 `_probe_late` 예산 2.5초(app.py:3953-3956) 그대로.",
      completionField: "pending",
      after: ["job_editmode"],
      afterReason:
        "app.py:3949-3951 의 주석이 이 자리를 못 박는다 — 「작업」이 **활성인 지점**에 두고,"
        + " 다이얼로그가 Nav 를 옮기므로 **화면 폭 측정 프로브 앞**이어야 한다. 앞의"
        + " job_editmode 가 셸을 job 으로 되돌리는 것이 그 전제를 만든다. 폭 측정 프로브들은"
        + " 다른 클러스터에 살아 `after` 로 가리킬 수 없고, 그 순서는 legacySite 3952 <"
        + " 3969(milestone_h_wave1) < 3974(overlay resize) 가 잇는다.",
      cooldownAfterMs: 400,
      cooldownReason:
        "app.py:3957 의 0.4초 — 모달 닫힘 전이(CSS 160ms)를 정산해 **다음 프로브의 클릭이"
        + " 백드롭에 막히지 않게** 한다. 이 대기는 이 프로브가 아니라 뒤 프로브를 위한 것이라,"
        + " 이유를 안 적으면 다음 이식에서 조용히 사라진다(그리고 그때 깨지는 것은 남의 계약이다).",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        service(ctx, "Bridge");
        const DataPicker = service(ctx, "DataPicker");
        const Modal = service(ctx, "Modal");
        const out = { pending: true };
        try {
          Nav.go("job");
          /* open()은 pool/refresh를 fire-and-forget으로 쏜다. 이 프로브는 바로 아래의 합성 pool
             snapshot이 정본이므로, 늦은 실 refresh가 React 목록을 0행으로 되돌리지 못하게
             그 한 발신만 같은 Bridge/typed 수명에서 흡수한다. */
          const refreshStub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
            if (screen === "pool" && action === "refresh") return Promise.resolve({});
            if (typeof real === "function") return real(screen, action, payload);
            return Promise.resolve({});
          });
          try {
            DataPicker.open({
              screen: "job",
              current: {
                label: "파일: 대장.xlsx", detail: "3건", path: "C:/d/대장.xlsx",
                sheet: "물품", origin: "file",
              },
            });
          } finally {
            refreshStub.restore();
          }
          /* controller 외부 스토어는 같은 호출 스택에서 갱신되지만 concurrent React root의
             portal DOM 커밋은 다음 turn일 수 있다. 현재 데이터 카드·고정 버튼을 읽기 전에
             고정 지연 없이 한 turn만 넘긴다. */
          await ctx.sleep(0);
          out.opened = !byId(ctx, "dataPickerModal").classList.contains("hidden");
          out.pin_offered = !!byId(ctx, "dataPickerPin");
          // 「＋ 직접 등록…」 사망(U2 §2.7 4행) — DOM 자체가 없어야 한다.
          out.register_gone = !byId(ctx, "dataPickerRegister");
          const row = (key, name, status, badge, level, actions) => ({
            key, name, kind: "excel", kind_label: "엑셀/CSV", status,
            badge_label: badge, badge_level: level, reference: `C:/d/${name}.xlsx (물품)`,
            locate_path: `C:/d/${name}.xlsx`, sheet: "물품", missing: false, note: "",
            actions,
          });
          ctx.push("pool", {
            rows: [
              row("k1", "7월 공고목록", "active", "활성", "ok",
                [{ key: "archive", label: "보관" }, { key: "delete", label: "삭제" }]),
              row("k2", "6월 보관분", "archived", "보관", "muted",
                [{ key: "activate", label: "활성화" }, { key: "delete", label: "삭제" }]),
            ],
            /* 키를 따옴표로 싼다 — 값이 아니라 **표기**의 문제다. 봉인의 금지 패턴
               `\bfile:` 은 평범한 객체 키 `file:` 도 `file:` URL 로 읽어 산출물을 거절한다.
               따옴표를 두면 텍스트에 `file:` 이 연속하지 않아 오탐이 사라지고, 스냅샷
               모양(실 백엔드가 내는 `corrupted[].file`)은 한 글자도 바뀌지 않는다.
               N-08 까지는 이 모듈이 번들에 실리지 않아 드러나지 않았다. */
            corrupted: [{ "file": "broken.dataset.json", error: "JSON 을 읽을 수 없습니다" }],
            /* 같은 데이터 등록 2건(§5.3 구판 병합 대상) — loud 재진술 카드가 서는지 되읽는다. */
            duplicates: [{
              reference: "파일: 대장.xlsx · 시트 물품",
              entries: [{ key: "k1", name: "7월 공고목록" }, { key: "k2", name: "6월 보관분" }],
            }],
            count: "2건", empty: false, result: { text: "", level: "muted" },
          });
          await ctx.sleep(0);                      // pool external-store → portal DOM 커밋
          const host = byId(ctx, "dataPickerPinned");
          out.rows = host.querySelectorAll(".tplcard").length;
          const uses = host.querySelectorAll('[data-act="use"]');
          out.use_active_enabled = uses.length > 0 && !uses[0].disabled;
          out.use_archived_disabled = uses.length > 1 && !!uses[1].disabled;
          out.activate_reachable = !!host.querySelector('[data-act="activate"]');
          out.relink_reachable = !!host.querySelector('[data-act="relink"]');
          /* 행동 버튼이 슬롯 키를 겨눈다(§5.3 — 이름은 라벨). 키 없는 버튼은 남의 항목을 겨눈다. */
          out.use_targets_key = uses.length > 0 && uses[0].dataset.key === "k1";
          out.corrupt_shown = textOf(byId(ctx, "dataPickerCorrupt")).indexOf("손상") >= 0;
          /* 병합 대상(같은 데이터 등록 2건) — 숨김·자동 정리 금지: 카드와 확정 버튼이 선다. */
          const dupes = byId(ctx, "dataPickerDupes");
          out.dupes_shown = textOf(dupes).indexOf("같은 데이터") >= 0
            && dupes.querySelectorAll("[data-dup-keep]").length === 2;
          /* 「이 데이터 고정」 = 등록 모달 재사용(현재 대상 프리필) — 제목·프리필까지 되읽는다. */
          byId(ctx, "dataPickerPin").click();
          await ctx.sleep(0);                      // regModel → 등록 portal DOM 커밋
          out.pin_title = textOf(byId(ctx, "poolRegTitle"));
          out.pin_ok = textOf(byId(ctx, "poolRegOk"));
          out.pin_path = byId(ctx, "poolRegPath").value;
          out.pin_sheet = byId(ctx, "poolRegSheet").value;
          /* pin 모드 참조 잠금(U2 §2.7 5행) — path·sheet 읽기전용 + 폼 안 찾아보기 감춤. */
          out.pin_path_readonly = byId(ctx, "poolRegPath").readOnly;
          out.pin_sheet_readonly = byId(ctx, "poolRegSheet").readOnly;
          out.pin_browse_hidden = isHidden(ctx, byId(ctx, "poolRegBrowse"));
          Modal.close("poolRegModal");
          /* 찾아보기 성사 = 면 유지(U2 §2.7 1행) — 브리지를 descriptor 스텁으로 갈아 실클릭한다. */
          const pickStub = stubBridgeInvoke(
            ctx, "pickDataFile", "pick_data_file", () => function () {
            return Promise.resolve({
              label: "파일: 새목록.xlsx", path: "C:/d/새목록.xlsx", sheet: "", rows: 5,
            });
            },
          );
          ctx.state.restorePick = () => { pickStub.restore(); };
          try {
            byId(ctx, "dataPickerBrowse").click();
            /* browseFile 은 async — 상태줄 재진술이 설 때까지 짧게 폴링(마이크로태스크 흘리기). */
            for (let i = 0; i < 50; i += 1) {
              await ctx.sleep(10);
              const note = textOf(byId(ctx, "dataPickerNote"));
              if (note.indexOf("새목록.xlsx") >= 0) break;
            }
          } finally {
            pickStub.restore();
          }
          out.browse_kept_open = !byId(ctx, "dataPickerModal").classList.contains("hidden");
          out.browse_restated = textOf(byId(ctx, "dataPickerCurrent")).indexOf("새목록.xlsx") >= 0;
          const pin2 = byId(ctx, "dataPickerPin");
          /* 가시성까지 단언한다 — click 은 hidden 을 통과하므로 존재만으론 눈과 다른 결론이 난다. */
          out.browse_pin_visible = !!pin2 && !isHidden(ctx, pin2) && pin2.offsetParent !== null;
          Modal.close("dataPickerModal");
          out.error = null;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        }
        out.pending = false;
        return { data_picker: out };
      },
      teardown(ctx) {
        if (ctx.state.restorePick) ctx.state.restorePick();
      },
    },

    /* ── editor_chip (app.py:2221 상수 · 3959 호출) ───────────────────────────
       매핑 분류 칩-라이브(블록 2 결정 12·13). 합성 매핑 스냅샷을 실 render() 에 흘려 (a) 사용할
       헤더가 **즉시 토글 칩**(체크박스 스테이징 소거)으로, (b) 미사용 구역이 펼쳐지고,
       (c) 소유권 태그 4종이, (d) touched 행에 되돌리기가 그려지는지 되읽는다. */
    {
      name: "editor_chip",
      keys: ["editor_chip"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3959,
      deadlineMs: 0,
      deadlineRationale: "동기 evaluate_js 한 번(app.py:3959) — 레거시에도 폴링이 없다.",
      after: ["data_picker"],
      afterReason:
        "app.py:3957 의 0.4초 정산이 이 둘 **사이**에 있다 — data_picker 가 닫은 모달의"
        + " 백드롭이 아직 살아 있으면 이 프로브의 첫 클릭이 삼켜진다. 순서를 잃으면 그 대기가"
        + " 아무 데도 걸리지 않는 시간이 된다(cooldownAfterMs 는 data_picker 가 진다).",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = {};
        try {
          const row = (i, f, src, conf, touch, hascontent) => ({
            index: i, template_field: f, inferred_type: "text", context: "", source: src,
            type: "text", const: "", fmt: "", confirmed: conf, touched: touch,
            has_content: hascontent, suggestion_score: src ? 1 : 0,
            preview: src ? "값" : "", preview_empty: false, preview_error: false,
            row_state: conf ? "confirmed" : (hascontent ? "unconfirmed" : "unmatched"),
          });
          const snap = editorBase({
            section: "binding", notice: null,
            reachable: { template: true, binding: false, filename: false },
            is_draft: false, dirty: false, changes: {}, revisions: {},
            template_path: "C:/t/공고서.hwpx", template_name: "공고서.hwpx", field_count: 4,
            schema_summary: "", fields: [], raw_block: "", gate: null, gate_error: false,
            data_path: "C:/d/대장.xlsx", data_name: "대장.xlsx", data_sheet: "물품",
            record_count: 3,
            source_fields: ["품명", "세부품명", "수량", "비고"],
            active_source_fields: ["품명", "수량", "비고"], ignored_source_fields: ["세부품명"],
            active_count: 3, ignored_count: 1, ignored_expanded: true,
            sample_rows: [["A", "a", "3", "-"], ["B", "b", "6", "x"], ["C", "c", "1", "-"]],
            type_options: ["text", "date", "amount", "const"],
            fmt_options: { text: [], date: [], amount: [], const: [] },
            name: "", pattern: "x", has_unsaved_work: true, editing_origin: "",
            provenance: null,
            rows: [row(0, "품명", "품명", true, true, true),      // 확정
              row(1, "수량", "수량", false, true, true),          // 수동(touched 미확정)
              row(2, "규격", "비고", false, false, true),         // 제안(시스템 소유)
              row(3, "담당자", "", false, false, false)],         // 후보 없음
            counts: { filled: 3, empty: 0, unmapped: 1 }, preview_empties: [],
            preview_index: 1, preview_count: 3,
            is_complete: false, schema_only: false,
          });
          Nav.go("editor", { force: true });
          ctx.push("editor", snap);
          await settleRender(ctx);
          const root = byId(ctx, "scr-editor");
          out.active_chips = root.querySelectorAll('.hchip.on[data-act="toggle-header"]').length;
          out.has_checkbox_staging = !!root.querySelector(".hbx");  // 스테이징 소거 → false 여야
          out.ignored_chip = !!root.querySelector('.hchip.ign[data-act="toggle-header"]');
          out.ignored_fold_open = !!root.querySelector("details.hidden-hdrs[open]");
          out.use_none_btn = !!root.querySelector('[data-act="use-none"]');
          out.tags = Array.prototype.map.call(
            root.querySelectorAll("table.map .tag"), (t) => t.textContent.trim());
          out.auto_revert_option = !!root.querySelector('table.map [data-act="revert-source"]');
          /* 재제안 버튼이 **select 와 같은 줄에** 서는가(U2 §2.6). 종전엔 select 가 width:100%
             로 열폭을 다 먹고 버튼이 뒤에 인라인으로 붙어 둘째 줄로 밀렸다 — 정적 CSS 검사로는
             못 보고 실렌더 높이로만 드러나는 결함이라, 수동 행(버튼 有)과 제안 행(버튼 無)의
             「데이터 열」 칸 높이를 재서 비교한다. 같으면 안 밀린 것이다. */
          const cells = root.querySelectorAll("table.map tbody tr td:nth-child(3)");
          const manual = cells[1];
          const suggested = cells[2];
          out.src_cell_h_manual = manual
            ? Math.round(manual.getBoundingClientRect().height) : -1;
          out.src_cell_h_suggested = suggested
            ? Math.round(suggested.getBoundingClientRect().height) : -1;
          /* 버튼과 select 의 세로 중심이 같은가 — 줄이 갈리면 중심이 한 줄 높이만큼 벌어진다. */
          const wrap = manual && manual.querySelector(".srcwrap");
          const sel = wrap && wrap.querySelector(".sel");
          const btn = wrap && wrap.querySelector('[data-act="revert-source"]');
          if (sel && btn) {
            const a = sel.getBoundingClientRect();
            const b = btn.getBoundingClientRect();
            out.revert_same_line = Math.abs((a.top + a.height / 2) - (b.top + b.height / 2)) < 4;
          } else { out.revert_same_line = null; }
          out.error = null;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        }
        return { editor_chip: out };
      },
    },

    /* ── editor_save_gate (app.py:2389 상수 · 3961 호출) ──────────────────────
       편집(탭) 저장 게이트의 **입력 지연**(리뷰 R2) — `s.dirty` 는 `change`(=blur)에서만
       갱신되는데 「변경 저장」이 그때까지 disabled 면 방금 고친 사람의 첫 클릭이 삼켜진다
       (비활성 버튼은 click 을 내지 않는다). 정적 검사로는 못 본다. */
    {
      name: "editor_save_gate",
      keys: ["editor_save_gate"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3961,
      deadlineMs: 0,
      deadlineRationale: "동기 evaluate_js 한 번(app.py:3961-3963) — 레거시에도 폴링이 없다.",
      after: ["editor_chip"],
      afterReason: "레거시 드라이버 순서 그대로(3959 → 3961) — 같은 편집기 표면을 잇달아 쓴다.",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = {};
        try {
          const snap = editorBase({
            section: "filename", notice: null,
            reachable: { template: true, binding: true, filename: true },
            is_draft: false, dirty: false, changes: {}, revisions: { template: 1, binding: 1 },
            template_path: "C:/t/공고서.hwpx", template_name: "공고서.hwpx", field_count: 1,
            schema_summary: "", fields: [], raw_block: "", gate: null, gate_error: false,
            data_path: "", data_name: "", data_sheet: "", record_count: 0,
            source_fields: [], active_source_fields: [], ignored_source_fields: [],
            active_count: 0, ignored_count: 0, ignored_expanded: false, sample_rows: [],
            type_options: ["text"], fmt_options: { text: [] },
            name: "공고서", pattern: "공고서-{{공고번호}}", pattern_preview: "공고서-1.hwpx",
            has_unsaved_work: false, editing_origin: "공고서",
            provenance: null, rows: [],
            counts: { filled: 0, empty: 0, unmapped: 0 }, preview_empties: [],
            preview_index: 0, preview_count: 0,
            is_complete: true, schema_only: true,
          });
          Nav.go("editor", { force: true });
          ctx.push("editor", snap);
          await settleRender(ctx);
          const saveBtn = () => ctx.doc.querySelector('#editor-foot [data-act="save"]');
          out.save_present = !!saveBtn();
          // ① 깨끗한 저장본 — 바꾼 것이 없으니 잠겨 있다(U2 §2.4 게이트 자체).
          out.clean_disabled = !!(saveBtn() && saveBtn().disabled);
          // ② 이름을 고친다. 발신은 change(=blur) 뿐이지만 **버튼은 지금 열려야** 첫 클릭이 산다.
          const nameEl = byId(ctx, "editorName");
          nameEl.focus();
          typeValue(ctx, nameEl, "공고서 수정");
          out.typing_enabled = !!(saveBtn() && !saveBtn().disabled);
          /* 「변경 버리기」도 **같은 술어로 지금** 열려야 한다(§2.17 · PR #354 리뷰) — 저장만
             열면 clean 세션 타이핑 직후 버리기의 첫 클릭이 삼켜진다(같은 결함류의 다른 버튼). */
          const discardBtn = () => ctx.doc.querySelector('#editor-foot [data-act="discard-patch"]');
          out.typing_discard_enabled = !!(discardBtn() && !discardBtn().disabled);
          /* ②-b 그 사이 push 가 와 footer 가 다시 그려져도 열린 채여야 한다 — 직접 켠 버튼만
             으로는 재렌더 한 번에 도로 잠기고, 그 push 는 사용자가 만지지 않은 이유로도 온다. */
          ctx.push("editor", snap);
          await settleRender(ctx);
          out.rerender_keeps_enabled = !!(saveBtn() && !saveBtn().disabled);
          // ③ 되돌려 치면 편집이 없던 것과 같다 — 열어 둔 채로 두지 않는다.
          typeValue(ctx, nameEl, "공고서");
          out.reverted_disabled = !!(saveBtn() && saveBtn().disabled);
          out.reverted_discard_disabled = !!(discardBtn() && discardBtn().disabled);
          // ④ 파일명 패턴도 같은 자격(재구성되는 입력이라 위임으로 받는다).
          const patEl = ctx.doc.querySelector('#editor-body input[data-act="pattern"]');
          out.pattern_present = !!patEl;
          if (patEl) {
            patEl.focus();
            typeValue(ctx, patEl, "공고서-{{공고번호}}-2");
            out.pattern_typing_enabled = !!(saveBtn() && !saveBtn().disabled);
            /* 다음 단계로 넘어가기 전에 이 편집을 되돌린다 — 안 그러면 대기 상태가 그대로
               이어져 다음 단계의 「깨끗한 상태」 측정이 거짓 양성이 된다(자기 잔재를 재는 꼴). */
            typeValue(ctx, patEl, snap.pattern);
            patEl.blur();
          }
          nameEl.blur();
          /* ⑤ 매핑 행의 상수 입력도 **같은 자격**이다(리뷰 R3) — 머리·꼬리 입력만 세면 이
             자리에서만 첫 클릭이 삼켜진다. 행이 있는 단계로 갈아 끼우고 같은 것을 잰다. */
          const rowSnap = Object.assign({}, snap, {
            section: "binding", schema_only: false, field_count: 1,
            source_fields: ["품명"], active_source_fields: ["품명"], active_count: 1,
            sample_rows: [["A"]], type_options: ["text", "const"],
            fmt_options: { text: [], const: [] },
            rows: [{
              index: 0, template_field: "품명", inferred_type: "text", context: "", source: "",
              type: "const", const: "고정값", fmt: "", confirmed: false, touched: true,
              has_content: true, suggestion_score: 0, preview: "고정값", preview_empty: false,
              preview_error: false, row_state: "unconfirmed",
            }],
          });
          ctx.push("editor", rowSnap);
          await settleRender(ctx);
          out.row_clean_disabled = !!(saveBtn() && saveBtn().disabled);
          let constEl = ctx.doc.querySelector('#editor-body [data-act="row-const"]');
          out.row_const_present = !!constEl;
          if (constEl) {
            constEl.focus();
            typeValue(ctx, constEl, "고정값 수정");
            out.row_typing_enabled = !!(saveBtn() && !saveBtn().disabled);
            typeValue(ctx, constEl, "고정값");
            out.row_reverted_disabled = !!(saveBtn() && saveBtn().disabled);
            /* ⑥ **타이핑 도중 푸시**(리뷰 R4 P1) — `#editor-body` 가 옛 스냅샷으로 다시
               그려져도 친 값이 살아 있어야 한다. 값이 사라졌는데 버튼만 열려 있으면 사용자는
               사라진 값을 저장했다고 믿는다(조용한 소실 + 그것을 가리는 표지). */
            typeValue(ctx, constEl, "푸시 중 입력");
            ctx.push("editor", rowSnap);
            await settleRender(ctx);
            const after = ctx.doc.querySelector('#editor-body [data-act="row-const"]');
            out.row_value_survives_push = !!after && after.value === "푸시 중 입력";
            out.row_enabled_after_push = !!(saveBtn() && !saveBtn().disabled);
            /* ⑦ 되돌릴 자리가 사라지면(단계 이동) 대기도 버려야 한다 — 남은 편집이 없는데
               열린 버튼은 거짓말이다. */
            ctx.push("editor", snap);
            await settleRender(ctx);
            out.gone_control_disables = !!(saveBtn() && saveBtn().disabled);
            ctx.push("editor", rowSnap);
            await settleRender(ctx);
            constEl = ctx.doc.querySelector('#editor-body [data-act="row-const"]');
            if (constEl) constEl.blur();
          }
          /* ⑧ 인라인 알림 채널(#323) — 통지가 갈 자리(`#save-msg`)가 **세 탭 모두**에 서고,
             구조화 거절이 거기 **보이게** 실리며, `window.alert` 는 한 번도 안 뜬다.
             종전에는 파일 이름 탭 본문에만 노드가 있어 나머지 두 탭의 통지가 모달 경보로
             샜다 — 정적 계약은 노드의 존재만 보고 **어느 탭에서** 서는지는 못 본다.
             `click` 은 hidden 도 통과하므로 가시성을 계산 스타일 + offsetParent 로 명시한다. */
          out.notice_channel = await measureNoticeChannel(ctx, rowSnap, saveBtn);
          out.error = null;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        }
        return { editor_save_gate: out };
      },
    },

    /* ── editor_lib_manage (app.py:2506 상수 · 3966 호출) ─────────────────────
       편집기 「템플릿」 탭 관리 표면(F8, §10.17.2 판정 D). 구 `_TPL_LIST_GROUP_PROBE_JS` 의
       재작성 — 그룹 헤더·접힘 뷰 제외·⋮ 구성·＋그룹지정 칩·이동 다이얼로그 개폐·퇴화 평면. */
    {
      name: "editor_lib_manage",
      keys: ["editor_lib_manage"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3966,
      deadlineMs: 0,
      deadlineRationale: "동기 evaluate_js 한 번(app.py:3966) — 레거시에도 폴링이 없다.",
      after: ["editor_save_gate"],
      afterReason: "레거시 드라이버 순서 그대로(3961 → 3966).",
      note:
        "**아는 취약점**: 이 프로브의 클릭 5곳에 가시성 단언이 없다(흘리기 body 클릭·행 ⋮ 2회·"
        + "그룹 ⋮·＋그룹지정 칩). 프로브 click 은 hidden 을 통과하므로 눈으로 본 것과 다른"
        + " 결론이 날 수 있다 — 이식에서 고치지 않고 그대로 옮긴다(계약을 바꾸는 별건)."
        + ` 클러스터 전체의 같은 자리는 ${CLICK_SITES_WITHOUT_VISIBILITY.length} 군이다.`,
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const Modal = service(ctx, "Modal");
        const out = {};
        try {
          Nav.go("editor", { force: true });
          const acts = [{ key: "compile", label: "누름틀 변환" }, { key: "review", label: "검토" }];
          const H = (name, group, cur, warns) => ({
            key: name, group, name, path: `C:/lib/${name}`,
            badge_label: "누름틀", badge_level: "ok", is_error: false, detail: "필드 3개",
            fill_warns: warns || [], actions: acts, current: !!cur,
          });
          const draft = editorBase({
            library: {
              hwpx: {
                flat: false, count: 4, group_names: ["계약", "입찰"], dir: "C:/lib",
                sections: [
                  {
                    group: "입찰", collapsed: false, count: 2,
                    items: [H("a.hwpx", "입찰", true), H("b.hwpx", "입찰", false)],
                  },
                  { group: "계약", collapsed: true, count: 1, items: [H("c.hwpx", "계약", false)] },
                  {
                    group: "", collapsed: false, count: 1,
                    items: [H("d.hwpx", "", false, ["빈 값 2건은 공란으로 채워집니다"])],
                  },
                ],
              },
              txt: {
                flat: true, count: 1, group_names: [], dir: "C:/txt",
                sections: [{
                  group: "", collapsed: false, count: 1,
                  items: [{
                    key: "메모.txt", group: "", name: "메모", path: "C:/txt/메모.txt",
                    field_count: 2, error: "", current: false,
                  }],
                }],
              },
              result: { text: "검토: 문제 없음", level: "ok" },
              /* 검토가 낸 구간 항목 목록(S8-03 #834) — 같은 창에 얹는 단계다(새 부팅 0). */
              slots: {
                path: "C:/lib/구간.hwpx", name: "구간.hwpx", summary: "항목 1개 · 선택 1개",
                rows: [{
                  id: "특약", label: "특약 사항", option_count: 1, options: ["지체상금 조항"],
                }],
                diagnostics: [],
              },
            },
          });
          ctx.push("editor", draft);
          await settleRender(ctx);
          const host = byId(ctx, "scr-editor");
          await settleUntil(ctx, () => host.querySelectorAll(".libselrow").length > 0);
          /* 상단 행동 줄(죽은 .tpl-libbar 승계) — 가져오기·폴더 일괄(#339)·새 TXT·새로고침. */
          out.toolbar = ["import-template", "import-folder", "lib-new-txt", "lib-refresh"]
            .map((a) => !!host.querySelector(`button[data-act="${a}"]`));
          out.grp_heads = host.querySelectorAll(".job-grp-head").length;      // 입찰·계약·그룹없음
          out.rows_visible = host.querySelectorAll(".libselrow").length;      // 계약 접힘 제외 → 3+1
          out.row_more = host.querySelectorAll('[data-act="lib-more"]').length;  // 모든 가시 행
          out.grp_more = host.querySelectorAll(".grp-more").length;           // 명명 그룹만
          out.assign_chips = host.querySelectorAll('[data-act="lib-assign"]').length; // 무그룹 행만
          out.fill_warn = /빈 값 2건/.test(host.textContent);                 // #154 사전 고지 승계
          const res = host.querySelector(".run-result");
          out.result_line = !!res && /검토: 문제 없음/.test(res.textContent)
            && res.className.indexOf("ok") !== -1;                            // #tplResult 승계
          out.band_caption = /4개/.test(host.textContent) && /C:\/lib/.test(host.textContent);
          /* 앞선 프로브가 Popover 바깥-닫기 pointerdown 을 남기면 "다음 click 1회 소비"
             플래그가 상주해 우리 첫 click 을 먹는다(교차 프로브 오염) — 던짐 click 으로 청소. */
          const flush = () => { ctx.doc.body.click(); };
          const menuActions = () => {
            const menu = byId(ctx, "tplRowMenu");
            if (!menu) return [];
            return Array.prototype.map.call(
              menu.querySelectorAll("button[data-context-menu-action]"),
              (button) => button.dataset.contextMenuAction,
            );
          };
          /* 그룹 있는 HWPX 행 ⋮ = [링1 상태 동사(변환·검토), 이동, 삭제] — 소비 동사 없음. */
          flush();
          host.querySelector('[data-act="lib-more"][data-key="b.hwpx"]').click();
          await settleRender(ctx);
          const firstMenu = byId(ctx, "tplRowMenu");
          out.menu_shown = !!firstMenu && !isHidden(ctx, firstMenu);
          out.hwpx_menu_items = menuActions();
          ctx.doc.body.dispatchEvent(new ctx.win.MouseEvent("pointerdown", { bubbles: true }));
          await settleRender(ctx);
          const closedMenu = byId(ctx, "tplRowMenu");
          out.menu_closed = !closedMenu || isHidden(ctx, closedMenu);
          /* 무그룹 TXT 행 ⋮ = [내용 편집, 삭제](이동은 칩 소관). */
          flush();
          host.querySelector('[data-act="lib-more"][data-key="메모.txt"]').click();
          await settleRender(ctx);
          out.txt_menu_items = menuActions();
          ctx.doc.body.dispatchEvent(new ctx.win.MouseEvent("pointerdown", { bubbles: true }));
          await settleRender(ctx);
          /* 그룹 헤더 ⋮ = [개명, 해산]. */
          flush();
          host.querySelector(".grp-more").click();
          await settleRender(ctx);
          out.group_menu_items = menuActions();
          ctx.doc.body.dispatchEvent(new ctx.win.MouseEvent("pointerdown", { bubbles: true }));
          await settleRender(ctx);
          /* ＋그룹지정 칩 → 이동 다이얼로그(기존 #tplMoveModal DOM 재사용). */
          out.move_hidden_before = byId(ctx, "tplMoveModal").classList.contains("hidden");
          flush();
          host.querySelector('[data-act="lib-assign"]').click();
          out.move_shown_after_chip = !byId(ctx, "tplMoveModal").classList.contains("hidden");
          Modal.close("tplMoveModal");
          if (!settleModal(ctx, "tplMoveModal")) {
            ctx.fail(ERROR_CODES.CONTRACT, "#tplMoveModal .modal-card 가 없습니다 — 닫힘 전이를 정착시킬 수 없습니다.");
          }
          /* 구간 항목 목록 + 동사 1건 왕복(S8-03). 개명이 가장 싸다: 프롬프트 하나로
             끝나고 확인 왕복이 없다. 발신은 이 클러스터의 관례대로 가로챈다 — 목록 자체가
             **합성 스냅샷**이라 그 경로를 실 백엔드에 보내면 남의 라이브러리를 겨눈다.
             여기서 재는 것은 「트리거 → 프롬프트 → 등록된 액션·payload 발신 → 실패의
             인라인 착지」이고, 컨트롤러 쪽 판정은 헤드리스 계약(test_webapp_template)이 진다. */
          out.slot_rows = host.querySelectorAll("#tplSlots .slotrow").length;
          out.slot_verbs = ["slot-rename", "slot-decompile", "slot-remove"]
            .map((a) => !!host.querySelector(`[data-act="${a}"][data-slot="특약"]`));
          const renameBtn = host.querySelector('[data-act="slot-rename"][data-slot="특약"]');
          out.slot_rename_visible = !!renameBtn && !isHidden(ctx, renameBtn);
          const slotSent = [];
          const slotStub = stubBridgeCall(ctx, () => async (screen, action, payload) => {
            slotSent.push([screen, action, payload]);
            throw new Error("SLOT_PROBE_REFUSAL");   // 성공 경로의 재당김이 합성 draft 를 걷지 않게
          });
          try {
            flush();
            renameBtn.click();
            await settleRender(ctx);
            const promptModal = byId(ctx, "promptModal");
            out.slot_prompt_shown = !!promptModal && !isHidden(ctx, promptModal);
            out.slot_prompt_value = byId(ctx, "promptModalInput").value;
            byId(ctx, "promptModalOk").click();
            /* 확인은 **닫힘 전이가 끝난 뒤** 값을 낸다(runDialog 의 requestClose) —
               전이를 정착시키지 않으면 발신이 영영 안 서고 프로브가 조용히 0 을 읽는다. */
            if (!settleModal(ctx, "promptModal")) {
              ctx.fail(ERROR_CODES.CONTRACT, "#promptModal .modal-card 가 없습니다 — 닫힘 전이를 정착시킬 수 없습니다.");
            }
            await settleUntil(ctx, () => slotSent.length > 0);
            out.slot_dispatch = slotSent.map(([screen, action, payload]) => [
              screen, action, payload.path, payload.slot_id, payload.label,
            ]);
            /* 실패는 인라인 채널로 간다(#323) — 앞선 프로브가 남긴 문안과 섞이지 않게
               우리 사유가 실렸는지로 본다. */
            await settleUntil(ctx, () => {
              const node = byId(ctx, "save-msg");
              return !!node && node.textContent.indexOf("SLOT_PROBE_REFUSAL") !== -1;
            });
            const notice = byId(ctx, "save-msg");
            out.slot_notice_inline = !!notice
              && notice.textContent.indexOf("SLOT_PROBE_REFUSAL") !== -1
              && !isHidden(ctx, notice);
          } finally {
            slotStub.restore();
          }
          /* 퇴화 평면(그룹 0개) — 헤더 없는 행 나열. */
          draft.library.slots = null;
          draft.library.hwpx = {
            flat: true, count: 1, group_names: [], dir: "C:/lib",
            sections: [{ group: "", collapsed: false, count: 1, items: [H("d.hwpx", "", false)] }],
          };
          draft.library.txt = { flat: true, count: 0, group_names: [], dir: "C:/txt", sections: [] };
          ctx.push("editor", draft);
          await settleUntil(ctx, () => host.querySelectorAll(".job-grp-head").length === 0);
          out.flat_heads = host.querySelectorAll(".job-grp-head").length;
          out.flat_rows = host.querySelectorAll(".libselrow").length;
          out.error = null;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        }
        return { editor_lib_manage: out };
      },
    },

    /* ── editor_lib (app.py:2608 상수 · 3985 호출) ────────────────────────────
       에디터 1단계 피커(#108 슬라이스 3) — 라이브러리를 관리 표면과 **같은 그룹 구획**(선택
       전용)으로 그리는가. 두 표면이 한 조직을 보인다는 실증(editor_lib_manage 와 대칭). */
    {
      name: "editor_lib",
      keys: ["editor_lib"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3985,
      deadlineMs: 0,
      deadlineRationale: "동기 evaluate_js 한 번(app.py:3985) — 레거시에도 폴링이 없다.",
      after: ["editor_lib_manage"],
      afterReason:
        "레거시 드라이버 순서 그대로(3966 → 3985). 사이의 3969~3983 은 다른 클러스터(B)의"
        + " 폭 측정·overlay 프로브라 `after` 로 가리키지 않는다 — legacySite 가 그 순서를 잇는다.",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = {};
        try {
          Nav.go("editor", { force: true });
          const it = (name, badge, level, cur) => ({
            key: name, name, path: `C:/lib/${name}`, badge_label: badge, badge_level: level,
            is_error: false, detail: "필드 3개", current: !!cur,
          });
          const draft = editorBase({
            library: {
              hwpx: {
                flat: false,
                sections: [
                  {
                    group: "입찰", collapsed: false, count: 2,
                    items: [it("a.hwpx", "준비됨", "ok", true), it("b.hwpx", "변환 필요", "warn", false)],
                  },
                  {
                    group: "계약", collapsed: true, count: 1,
                    items: [it("c.hwpx", "준비됨", "ok", false)],
                  },
                  {
                    group: "", collapsed: false, count: 1,
                    items: [it("d.hwpx", "준비됨", "ok", false)],
                  },
                ],
              },
              txt: { flat: true, sections: [] },
            },
          });
          ctx.push("editor", draft);
          await settleRender(ctx);
          const host = byId(ctx, "scr-editor");
          out.grp_heads = host.querySelectorAll(".job-grp-head").length;   // 입찰·계약·그룹없음
          out.rows_visible = host.querySelectorAll(".libselrow").length;   // 계약 접힘 → 2+1
          out.pick_btns = host.querySelectorAll('.libselrow button[data-act="use-library"]').length;
          out.current_marked = host.querySelectorAll(".libselrow.cur").length;  // 현 선택(a) 1
          out.import_btn = !!host.querySelector('button[data-act="import-template"]');
          /* F6 PR-B — 「HWPX 서식만」 단일 매체 고지는 2밴드 구조로 대체됐다: 각 밴드가 자기
             산출물(파일 생성/복사)을 말한다. 두 고지의 실재를 되읽는다. */
          out.filter_notice = /\.hwpx 문서 파일을 만드는/.test(host.textContent)
            && /복사해 쓰는 작업/.test(host.textContent);
          const caret = host.querySelector('.job-grp-head[aria-expanded="false"] .grp-caret');
          out.caret_collapsed = caret ? styleOf(ctx, caret).visibility : "missing";
          /* F13 — 그룹 헤더에 안정 id(재렌더 뒤 포커스 복원 근거). F14 — 파일명 칸 말줄임/축소. */
          const head0 = host.querySelector(".job-grp-head");
          out.grp_head_has_id = !!(head0 && head0.id);
          const fn = host.querySelector(".libselrow .fname");
          out.fname_ellipsis = fn ? styleOf(ctx, fn).textOverflow : "missing";
          out.fname_minwidth = fn ? styleOf(ctx, fn).minWidth : "missing";
          /* 퇴화 평면(그룹 0개) — 헤더 없는 선택 행 나열. */
          draft.library = {
            hwpx: {
              flat: true,
              sections: [{
                group: "", collapsed: false, count: 1,
                items: [it("d.hwpx", "준비됨", "ok", false)],
              }],
            },
            txt: { flat: true, sections: [] },
          };
          ctx.push("editor", draft);
          await settleRender(ctx);
          out.flat_heads = host.querySelectorAll(".job-grp-head").length;
          out.flat_rows = host.querySelectorAll(".libselrow").length;
          out.error = null;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, `throw:${thrown && thrown.message}`);
        }
        return { editor_lib: out };
      },
    },
  ];
}

/** 러너에 이 클러스터를 통째로 등록한다. 레인 B·C·E 도 같은 이름꼴을 쓴다. */
export function registerEditorWorkbenchDataProbes(runner) {
  return runner.registerAll(createEditorWorkbenchDataProbes());
}
