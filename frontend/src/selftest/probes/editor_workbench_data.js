/* N-08 클러스터 D — 편집기·작업대·데이터 프로브. 네 레인 중 **가장 넓다**(상수 15·키 15).
 *
 * 기준 이식본은 형제 파일 `persistence_geometry.js`(클러스터 E) 다. 구조·이름꼴·주석 밀도·
 * 오류 처리를 그대로 따른다 — 레인마다 제 규약을 지으면 이식은 되돌릴 수 없이 갈라진다.
 *
 * 무엇을 옮겼나 — `src/hwpxfiller/webapp/app.py` 의 상수 15개와 그 호출 자리 22곳:
 *   ① `_VIEW_ORDER_PROBE_SETUP_JS`(2665)        → view_order            · 3754·3757·3762
 *   ② `_DATA_SHEET_PROBE_SETUP_JS`(2698)        → data_sheet            · 3764·3767·3772
 *   ③ `_RANGE_DRAFT_PROBE_SETUP_JS`(2799)       → range_draft           · 3774·3777·3782
 *   ⑤ `_EDITOR_GUARD_PROBE_SETUP_JS`(2032)      → editor_tab_autodiscard   · 3794
 *   ⑥ `_EDITOR_DISCARD_CANCEL_PROBE_JS`(2110)   → editor_discard_immediate · 3802
 *   ⑦ `_EDITOR_TXT_BAND_PROBE_SETUP_JS`(3311)   → editor_txt_band       · 3808
 *   ⑧ `_WORKBENCH_PROBE_SETUP_JS`(3371)         → workbench             · 3814
 *   ⑨ `_SHEET_PROBE_SETUP_JS`(797)              → sheet_gate            · 3863·3865
 *   ⑩ `_JOB_EDITMODE_PROBE_JS`(1950)            → job_editmode          · 3948
 *   ⑪ `_DATA_PICKER_PROBE_SETUP_JS`(2297)       → data_picker           · 3952
 *   ⑫ `_EDITOR_CHIP_PROBE_JS`(2221)             → editor_binding        · 3959
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
 *   · sheet_gate            : 확정(`picked=='확정됨:낙찰현황'`) ↔ 취소(`cancelled===null` +
 *                             `closed_after`). `status=='done'` 이 나머지를 유의미하게 만든다.
 *   · editor_tab_autodiscard: `calls == [goto_section]`(양성 — 한 발) ↔ `choose_modal_open ===
 *                             false` · `payload_keys == [section]`(처분 표지 부재).
 *   · editor_discard_immediate : `call_order == 'set_name,discard_patch'`(정산 선행) ↔
 *                             `confirm_modal_open === false` · `name_value_after_discard=='공고서'`
 *                             · `discard_disabled_after` + `save_disabled_after`.
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
 *   · editor_binding        : 일괄 승격의 양성(`badges_after` 제안 2행이 「확인」) ↔ 음성
 *                             (확인 필요 2행 불변) · `sentinel_in_set_source === false` ·
 *                             퇴역 좌표 3종의 음성 단언 ·
 *                             `src_cell_h_manual == src_cell_h_suggested`(실렌더 기하).
 *
 * **알면서 그대로 옮긴 취약점 둘**(가리지 않는다):
 *   ⓐ `editor_lib_manage` 의 클릭 5곳은 가시성 단언이 없다. 프로브 click 은 hidden 요소도
 *      통과하므로(F8 교훈) 「눈으로 본 것과 다른 결론」이 날 수 있는 자리다. 고치는 것은 이
 *      이식의 일이 아니다 — 실렌더 계약을 바꾸는 별건이고, 여기서 슬쩍 더하면 이식이
 *      「무엇을 바꿨나」의 한 줄을 잃는다. 아래 CLICK_SITES_WITHOUT_VISIBILITY 에 적어 둔다.
 *   ⓑ `editor_discard_immediate` 의 내부 폴링 상한(60 × 50ms + 300ms)은 레거시 회수 시한
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
  "data_picker", "data_sheet", "editor_binding", "editor_discard_immediate",
  "editor_lib", "editor_lib_manage", "editor_save_gate", "editor_tab_autodiscard",
  "editor_txt_band",
  "job_editmode", "range_draft", "sheet_gate", "view_order", "workbench",
]);

/** 가시성 단언 없이 `.click()` 하는 자리 전수 — **아는 채로** 옮긴 감도 공백이다.
 *  이식이 이 목록을 지어내지도, 조용히 메우지도 않는다(둘 다 이식을 흐린다). */
const CLICK_SITES_WITHOUT_VISIBILITY = Object.freeze([
  "editor_lib_manage: 흘리기용 body 클릭(Popover 바깥-닫기 잔재 청소)",
  "editor_lib_manage: 행 ⋮ (b.hwpx·c.hwpx·메모.txt·깨진.txt·구간.hwpx)",
  "editor_lib_manage: 「자세히…」 메뉴 항목(열림 뒤 가시성은 detail_item_visible 이 잰다)",
  "editor_tab_autodiscard: 단계 탭(filename)",
  "editor_discard_immediate: 「변경 버리기」",
  "data_picker: 「이 데이터 고정」 · 「찾아보기」(뒤이어 browse_pin_visible 이 가시성을 잰다)",
  "data_sheet: ⤢ 트리거 · 면 닫기",
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

/** 저작 머리 띠의 「파일」 메뉴를 사용자 경로(단추 누름)로 열고 이름이 `label` 인 메뉴 항목을 돌려준다.
 *  파일 동사(문서 열기·새 TXT·저장·다른 이름으로 저장)는 머리 띠 단추가 아니라 이 메뉴 안에 선다.
 *  단추나 메뉴가 서지 않으면 null — 호출자가 그 사실을 빨강으로 남긴다. */
async function authoringFileItem(ctx, label) {
  const doc = ctx.doc;
  const opener = Array.prototype.find.call(doc.querySelectorAll("#scr-authoring .authoring-head button"), (el) => textOf(el).trim() === "파일");
  if (!opener) return null;
  opener.click();
  const menu = () => doc.querySelector('#scr-authoring [role="menu"][aria-label="파일"]');
  if (!await waitFor(ctx, () => !!menu(), 20, 50)) return null;
  return Array.prototype.find.call(menu().querySelectorAll('[role="menuitem"]'), (el) => textOf(el).trim() === label) || null;
}

/* ── §10 키보드·IME 실창 밴드의 공용 조각 ─────────────────────────────────────
 *
 *  **합성 키의 한계(중요)**: 스크립트가 쏜 KeyboardEvent 는 신뢰되지 않은 사건이라 브라우저의
 *  기본 동작(Tab 의 초점 이동 · 버튼 위 Enter 의 활성화 · 입력칸 Enter 의 암묵 제출)이 따르지
 *  않는다. 그래서 키는 **초점을 가진 원소에서** 쏘아 제품의 처리기(F6·F2·Escape·폼 onKeyDown)를
 *  실물로 지나게 하고, 처리기가 막지 않은(`defaultPrevented` 아님) 경우에만 그 기본 동작을 표준
 *  규칙대로 흉내 낸다: Tab = 문서 순서의 다음 탭 가능 원소, Enter = 버튼이면 click(), 폼
 *  입력칸이면 requestSubmit(). 좌표 클릭은 쓰지 않는다. OS 수준 키 주입(SendInput)은 사용자
 *  데스크톱을 건드리므로 쓰지 않는다 — 실 IME 조합도 같은 이유로 자동화하지 않는다. */
const TABBABLE = 'button:not([disabled]),input:not([disabled]):not([type="hidden"]),'
  + 'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"]),'
  + '[contenteditable="true"],iframe,details>summary';

/** 접힌 details 의 본문(요약 줄 밖)에 있는가 — Chromium 은 그 자리를 그리지 않고 초점도 주지 않는다. */
function insideClosedDetails(el) {
  for (let node = el.parentElement; node; node = node.parentElement) {
    if (node.tagName === "DETAILS" && !node.open) {
      const summary = node.querySelector(":scope > summary");
      if (!summary || !summary.contains(el)) return true;
    }
  }
  return false;
}

/** 저작 화면 안의 탭 가능 원소 — 숨김·inert·접힌 details 본문은 빠진다(브라우저 순서 규칙). */
function tabbables(ctx) {
  return Array.prototype.filter.call(
    ctx.doc.querySelectorAll(`#scr-authoring ${TABBABLE}`),
    (el) => !el.closest("[inert],[hidden]") && !insideClosedDetails(el) && el.getClientRects().length > 0
      && ctx.win.getComputedStyle(el).visibility !== "hidden",
  );
}

/** 초점 원소에서 키 하나 — 막히지 않았으면 기본 동작만 흉내 낸다(조합 중이면 흉내도 없다). */
function pressKey(ctx, key, init) {
  const opts = init || {};
  const target = ctx.doc.activeElement || ctx.doc.body;
  const event = new ctx.win.KeyboardEvent("keydown", Object.assign(
    { key, bubbles: true, cancelable: true }, opts));
  const proceed = target.dispatchEvent(event);
  if (!proceed || opts.isComposing) return { target, prevented: !proceed };
  if (key === "Tab") {
    const order = tabbables(ctx);
    const at = order.indexOf(target);
    const step = opts.shiftKey ? order.length - 1 : 1;
    /* 초점을 받지 못하는 후보(브라우저가 거절)는 건너뛴다 — 실제 Tab 도 그 자리에 서지 않는다. */
    let index = at < 0 ? (opts.shiftKey ? order.length - 1 : 0) : (at + step) % order.length;
    for (let tries = 0; tries < order.length; tries += 1) {
      order[index].focus();
      if (ctx.doc.activeElement === order[index]) break;
      index = (index + step) % order.length;
    }
  } else if (key === "Enter") {
    if (target.tagName === "BUTTON") target.click();
    else if (target.tagName === "INPUT" && target.form) target.form.requestSubmit();
  }
  return { target, prevented: false };
}

/** 키보드 이동 도구 — F6 으로 패널을 돌고 Tab 으로 대상 원소까지 간다. */
function keyboardNav(ctx) {
  const doc = ctx.doc;
  const active = () => doc.activeElement;
  const within = (selector) => !!(active() && active().closest && active().closest(selector));
  const nameOf = (el) => (el && (el.getAttribute("aria-label") || textOf(el).trim())) || "";
  return {
    active, within, nameOf,
    async cycleTo(selector) {
      // 초점이 화면 밖(body)이면 사건이 셸을 지나지 않는다 — 사용자처럼 Tab 으로 먼저 들어온다.
      if (!within("#scr-authoring")) pressKey(ctx, "Tab");
      for (let i = 0; i < 6 && !within(selector); i += 1) {
        pressKey(ctx, "F6");
        await settleRender(ctx);
      }
      return within(selector);
    },
    tabTo(match, limit, backwards) {
      for (let i = 0; i < (limit || 40) && !match(active()); i += 1) pressKey(ctx, "Tab", backwards ? { shiftKey: true } : undefined);
      return !!match(active());
    },
    /** roving 묶음(APG tabs·toolbar·menu) 안에서 방향키로 대상까지 — Tab 은 묶음을 떠난다. */
    arrowTo(match, key, limit) {
      for (let i = 0; i < (limit || 20) && !match(active()); i += 1) pressKey(ctx, key);
      return !!match(active());
    },
    /** 구조 목록(APG tree)에서 대상 줄까지: 그 tree 의 처음(Home)부터 ↓ 로 내려가고, 끝이면 Tab 으로 다음 tree 에 들어간다. */
    async treeTo(match, limit) {
      const top = async () => {
        if (!active() || active().getAttribute("role") !== "treeitem") return;
        pressKey(ctx, "Home");
        await settleRender(ctx);
      };
      await top();
      for (let i = 0; i < (limit || 60) && !match(active()); i += 1) {
        const before = active();
        pressKey(ctx, "ArrowDown");
        await settleRender(ctx);
        if (active() === before) { pressKey(ctx, "Tab"); await settleRender(ctx); await top(); }
      }
      return !!match(active());
    },
  };
}

/** 지금 초점 원소의 역할·이름 — 단계표(UX-04 키보드 증거)의 한 칸. */
function focusStep(ctx, key, outcome) {
  const el = ctx.doc.activeElement;
  const role = el ? (el.getAttribute("role") || el.tagName.toLowerCase()) : "";
  const name = el ? (el.getAttribute("aria-label") || textOf(el).trim()).slice(0, 60) : "";
  return { key, role, name, outcome };
}

/** §10·§6.2 IME — 이름 입력 중 합성 조합 사건을 쏘고 명령 미실행·커서 유지·입력 미절단을 되읽는다.
 *  조합 중 Enter 에 브라우저는 암묵 제출을 하지 않는다 — 여기서는 **최악**을 흉내 내 제출을 직접
 *  청해 제품의 방어선(조합 중 제출 무시)을 잰다. */
async function probeAuthoringIme(ctx, out, input) {
  const doc = ctx.doc;
  const compose = (type, data) => input.dispatchEvent(
    new ctx.win.CompositionEvent(type, { bubbles: true, cancelable: true, data }));
  const errorBand = () => textOf(doc.querySelector("#scr-authoring .authoring-shell > div.authoring-error")).trim();
  compose("compositionstart", "");
  typeValue(ctx, input, "공고명수");                       // 조합 중인 음절까지 든 값
  compose("compositionupdate", "수");
  await settleRender(ctx);
  input.setSelectionRange(4, 4);
  const caret = [input.selectionStart, input.selectionEnd];
  pressKey(ctx, "Enter", { isComposing: true, keyCode: 229 });
  if (input.form) input.form.requestSubmit();
  pressKey(ctx, "Escape", { isComposing: true, keyCode: 229 });
  pressKey(ctx, "F2", { isComposing: true, keyCode: 229 });
  await ctx.sleep(300);                                   // 늦게 오는 미리보기·거절까지 기다린다
  out.ime_no_preview = !doc.querySelector(".authoring-properties section.authoring-preview");
  out.ime_value_kept = input.isConnected && input.value === "공고명수";
  out.ime_focus_kept = doc.activeElement === input;
  out.ime_caret_kept = input.selectionStart === caret[0] && input.selectionEnd === caret[1];
  out.ime_panel_kept = !!doc.querySelector(".authoring-properties");
  out.ime_error_band = errorBand();
  compose("compositionend", "수");
  await settleRender(ctx);
  out.ime_value_after_end = input.value;
}

/** §10 키보드만으로: 구조 목록 → 필드 선택 → 속성(이름 변경 미리보기) → Escape 두 단계 → F2 →
 *  문제 위치 이동 → 원위치 복귀(TXT). 줄 번호는 Python 스냅샷에서 읽고, 화면의 위치 표기와 맞춘다. */
async function probeAuthoringKeyboard(ctx, out) {
  const doc = ctx.doc;
  const started = Date.now();
  const nav = keyboardNav(ctx);
  const nameInput = () => doc.querySelector(".authoring-properties input");
  const preview = () => doc.querySelector(
    ".authoring-properties section.authoring-preview:not(.authoring-refusal)");
  const contextText = () => textOf(doc.querySelector(".authoring-properties .authoring-context")).trim();
  const panelGone = () => !doc.querySelector(".authoring-properties");
  /* 편집면 캐럿이 선 줄(0부터) — CodeMirror 는 초점을 쥔 동안 제 선택을 DOM 선택으로 쓴다(activeElement 가 편집면이면
     창 초점과 무관하다). 속성 패널을 열지 않는 선택(NG-06 keepDock)의 이동은 이 줄로 잰다. */
  const caretLine = () => {
    const content = doc.querySelector(".authoring-document:not([hidden]) .cm-content");
    const picked = doc.getSelection ? doc.getSelection() : null;
    if (!content || !picked || !picked.anchorNode || !content.contains(picked.anchorNode)) return -1;
    let node = picked.anchorNode;
    if (node === content) node = content.childNodes[Math.min(picked.anchorOffset, content.childNodes.length - 1)];
    const el = node && (node.nodeType === 3 ? node.parentElement : node);
    const line = el && el.closest ? el.closest(".cm-line") : null;
    return line ? Array.prototype.indexOf.call(content.querySelectorAll(".cm-line"), line) : -1;
  };
  const snap = await service(ctx, "Bridge").initial("authoring");
  const tab = (((snap || {}).tabs) || []).find((item) => item.id === (snap || {}).active_id) || {};
  const field = ((((tab.analysis || {}).fields) || [])[0] || {});
  const occurrence = (field.occurrences || [])[0] || {};
  const problem = (tab.problems || []).find((item) => item.location) || {};
  const dockTab = (el) => !!el && !!el.closest(".authoring-dock") && el.getAttribute("role") === "tab";
  // 문맥 줄은 Python 의 사람이 읽는 위치(UX-10 R2: 「N행」)다 — 스냅샷의 줄 번호(0부터)로 기대값을 세운다.
  const range = (place) => `${Number((place || {}).line) + 1}행`;
  try {
    out.kbd_outline_reached = await nav.cycleTo(".authoring-outline");
    if (!out.kbd_outline_reached) return;
    /* 필드 목록은 구조 패널의 두 번째 보기다(UX-09): F6 은 보이는 보기(구조)의 tree 로 들어오므로, 보기 탭 줄로
       올라가(Shift+Tab) → 로 「필드」 보기를 연다(자동 활성화). 이어서 Tab 이 필터를 지나 그 보기의 tree 로 간다. */
    const outlineTab = (el) => !!el && el.getAttribute("role") === "tab" && !!el.closest(".authoring-outline");
    out.kbd_fields_view = nav.tabTo(outlineTab, 6, true)
      && nav.arrowTo((el) => outlineTab(el) && textOf(el).trim().indexOf("필드") === 0, "ArrowRight", 2);
    await settleRender(ctx);
    if (!out.kbd_fields_view) return;
    // 구조 목록은 APG tree 다(UX-04): 한 번의 Tab 으로 들어오고 ↓ 로 줄을 옮긴다.
    out.kbd_field_focused = await nav.treeTo((el) => nav.nameOf(el).indexOf(`필드 · ${field.name} · `) === 0, 16);
    out.kbd_field_label = nav.nameOf(nav.active());
    if (!out.kbd_field_focused) return;
    pressKey(ctx, "Enter");
    out.kbd_properties_focus = await waitFor(ctx, () => !!nameInput() && nav.active() === nameInput()
      && nameInput().value === field.name, 40, 50);
    out.kbd_properties_command = (doc.querySelector(".authoring-properties select") || {}).value || "";
    out.kbd_name_described_by = nameInput() ? String(nameInput().getAttribute("aria-describedby") || "") : "";
    out.kbd_properties_target = textOf(doc.getElementById("authoring-properties-target")).trim();
    out.kbd_properties_context = textOf(doc.getElementById("authoring-properties-context")).trim();
    if (!out.kbd_properties_focus) return;

    await probeAuthoringIme(ctx, out, nameInput());

    typeValue(ctx, nameInput(), "공고제목");
    pressKey(ctx, "Enter");
    out.kbd_rename_preview = await waitFor(
      ctx, () => textOf(preview()).indexOf("‘공고제목’으로 변경됩니다") >= 0, 40, 50);
    out.kbd_rename_preview_text = textOf(preview()).trim().slice(0, 120);
    pressKey(ctx, "Escape");                               // 1단계: 작성 중인 값만 되돌린다
    await settleUntil(ctx, () => !!nameInput() && nameInput().value === field.name);
    out.kbd_escape_reverts = !!nameInput() && nameInput().value === field.name;
    out.kbd_escape_keeps_panel = !panelGone();
    pressKey(ctx, "Escape");                               // 2단계: 패널을 닫고 선택으로 돌아간다
    out.kbd_escape_closes = await waitFor(ctx, panelGone, 20, 50);
    out.kbd_escape_focus_editor = await waitFor(ctx, () => nav.within(".cm-editor"), 20, 50);
    pressKey(ctx, "F2");                                   // 선택한 의미 요소의 이름 작업
    out.kbd_f2_focus = await waitFor(ctx, () => !!nameInput() && nav.active() === nameInput(), 20, 50);
    out.kbd_f2_command = (doc.querySelector(".authoring-properties select") || {}).value || "";
    pressKey(ctx, "Escape");
    await waitFor(ctx, panelGone, 20, 50);

    /* 문제는 하단 독(보조 패널)의 탭이다(§3.1): F6 으로 독에 들어가 「문제 N」 탭을 Enter 로 펼친다.
       탭 이름의 수는 Python 스냅샷의 problems 수와 같아야 하고, 펼친 뒤 독에는 탭 패널이 하나만 선다. */
    out.kbd_dock_reached = await nav.cycleTo(".authoring-dock");
    // 독 탭 줄은 APG tabs 다: 들어온 탭에서 Home 으로 첫 탭(문제)까지 간다.
    out.kbd_problems_tab = nav.arrowTo((el) => dockTab(el) && textOf(el).trim().indexOf("문제") === 0, "Home", 2);
    out.kbd_problems_tab_label = out.kbd_problems_tab ? textOf(nav.active()).trim() : "";
    out.kbd_problems_expected = (tab.problems || []).length;
    if (!out.kbd_problems_tab) return;
    const problemsTab = nav.active();
    pressKey(ctx, "Enter");
    const action = () => doc.querySelector(
      '.authoring-dock [role="tabpanel"] .authoring-bottom[aria-label="문제"] .authoring-problem button');
    out.kbd_problem_focus = await waitFor(ctx, () => !!action() && nav.active() === action(), 20, 50);
    out.kbd_problems_selected = problemsTab.getAttribute("aria-selected") === "true";
    out.kbd_dock_panels = doc.querySelectorAll('.authoring-dock [role="tabpanel"]').length;
    out.kbd_problem_action = nav.nameOf(nav.active());
    const problemRow = doc.querySelector('.authoring-bottom[aria-label="문제"] .authoring-problem');
    out.kbd_problem_text = textOf(problemRow).trim().slice(0, 120);
    // 문제 한 건은 행이다(UX-09) — 심각도는 글자 칩, 종류는 흐린 글로 선다(색이 아니라 글).
    out.kbd_problem_severity = textOf(problemRow && problemRow.querySelector(".authoring-badge")).trim();
    out.kbd_problem_category = textOf(problemRow && problemRow.querySelector(".authoring-problem-category")).trim();
    if (!out.kbd_problem_focus) return;
    /* 문제 행의 Enter 는 독에서 시작한 선택이다(NG-06 keepDock): 편집면 선택이 문제 위치로 옮겨 가고, 독의 활성 탭은
       「문제」 그대로이며 속성 패널은 열리지 않는다. 이동은 편집면 캐럿이 선 줄로 잰다(문제 위치는 Python 스냅샷의 줄). */
    pressKey(ctx, "Enter");
    out.kbd_problem_expected_line = Number((problem.location || {}).line);
    out.kbd_problem_moved = await waitFor(
      ctx, () => caretLine() === out.kbd_problem_expected_line, 40, 50);
    out.kbd_problem_caret_line = caretLine();
    await settleRender(ctx);
    out.kbd_problem_dock_kept = problemsTab.getAttribute("aria-selected") === "true"
      && !!doc.querySelector('.authoring-dock [role="tabpanel"] .authoring-bottom[aria-label="문제"]');
    out.kbd_problem_no_properties = panelGone();

    /* 「이전 위치로」는 도구 막대 「더보기」 메뉴 안에 있다: 더보기 → Enter → 메뉴 첫 항목에 초점 →
       ↓ 로 「이전 위치로」 → Enter. 도구 막대와 메뉴는 APG toolbar·menu 라 Tab 이 아니라 방향키로 옮긴다. */
    out.kbd_toolbar_again = await nav.cycleTo(".authoring-toolbar");
    /* 흐린 만들기 단추(NG-11): 도구 막대 roving 이 aria-disabled 단추에도 선다. Enter(누름)는 명령을 실행하지 않고
       위치 줄 메모에 그 판정의 Python 사유를 세운다 — hover 사유(title)와 같은 문장이다. 이 문서는 닫히지 않은
       항목(구조 오류)이 있어 「항목으로 만들기」가 어느 자리에서나 불가다. 펼친 독 탭(문제)과 초점은 그대로다. */
    const dimmedSlot = (el) => !!el && !!el.closest(".authoring-toolbar") && textOf(el).trim() === "항목으로 만들기";
    out.kbd_dimmed_reached = nav.arrowTo(dimmedSlot, "ArrowRight", 20);
    if (!out.kbd_dimmed_reached) return;
    const dimmed = nav.active();
    out.kbd_dimmed_aria = dimmed.getAttribute("aria-disabled") === "true" && !dimmed.disabled;
    out.kbd_dimmed_title = String(dimmed.getAttribute("title") || "");
    const noteText = () => textOf(doc.querySelector("#scr-authoring .authoring-selection-note")).trim();
    pressKey(ctx, "Enter");
    out.kbd_dimmed_note = await waitFor(ctx, () => !!noteText() && noteText() === out.kbd_dimmed_title, 20, 50);
    out.kbd_dimmed_note_text = noteText();
    out.kbd_dimmed_no_panel = panelGone() && problemsTab.getAttribute("aria-selected") === "true";
    out.kbd_dimmed_focus_kept = nav.active() === dimmed;
    out.kbd_more_button = nav.arrowTo(
      (el) => !!el && !!el.closest(".authoring-toolbar") && nav.nameOf(el) === "더보기", "ArrowRight", 20);
    if (!out.kbd_more_button) return;
    pressKey(ctx, "Enter");
    const moreMenu = () => doc.querySelector('#scr-authoring [role="menu"][aria-label="더보기"]');
    out.kbd_more_menu = await waitFor(ctx, () => !!moreMenu() && !!nav.active()
      && nav.active().getAttribute("role") === "menuitem" && moreMenu().contains(nav.active()), 20, 50);
    if (!out.kbd_more_menu) return;
    out.kbd_back_button = nav.arrowTo((el) => !!el && el.getAttribute("role") === "menuitem"
      && !!moreMenu() && moreMenu().contains(el) && textOf(el).trim() === "이전 위치로", "ArrowDown", 8);
    if (!out.kbd_back_button) return;
    pressKey(ctx, "Enter");
    out.kbd_more_menu_closed = await waitFor(ctx, () => !moreMenu(), 20, 50);
    /* 복귀는 편집면 캐럿이 원래 줄(필드 사용 위치)로 돌아온 것으로 잰다. 이어서 F2 로 속성 패널을 열어 그 자리의
       문맥 줄이 원시 offset 이 아니라 사람이 읽는 줄 번호(「N행」)임을 되읽는다(UX-10 R2). */
    out.kbd_back_expected_line = Number(occurrence.line);
    out.kbd_back_restored = await waitFor(ctx, () => caretLine() === out.kbd_back_expected_line, 40, 50);
    out.kbd_back_focus_editor = await waitFor(ctx, () => nav.within(".cm-editor"), 20, 50);
    out.kbd_back_expected = range(occurrence);
    pressKey(ctx, "F2");
    out.kbd_back_properties = await waitFor(ctx, () => !!nameInput() && contextText().indexOf(range(occurrence)) >= 0, 40, 50);
    out.kbd_back_context = contextText();
    pressKey(ctx, "Escape");
    await waitFor(ctx, panelGone, 20, 50);
    out.kbd_error_band = textOf(doc.querySelector("#scr-authoring .authoring-shell > div.authoring-error")).trim();
  } finally {
    out.kbd_ms = Date.now() - started;
  }
}

/** UX-04 §10 키보드 모델 밴드 — 실제 창에서 APG tabs·toolbar·tree·menu 와 초점 복귀를 단계마다 잰다.
 *  각 단계는 누른 키 → 초점 원소(역할·이름) → 보이는 결과를 `a11y_steps` 에 싣고, 단언 키는 `a11y_*` 이다.
 *  두 번째 문서(새 TXT)를 열어 탭 사이를 옮기고, 끝에 Delete 로 닫아 이웃 탭 초점을 잰다. */
async function probeAuthoringA11y(ctx, out) {
  const doc = ctx.doc;
  const nav = keyboardNav(ctx);
  const steps = [];
  out.a11y_steps = steps;
  const step = (key, outcome) => steps.push(focusStep(ctx, key, outcome));
  const press = async (key, init) => { pressKey(ctx, key, init); await settleRender(ctx); };
  const role = (name) => !!nav.active() && nav.active().getAttribute("role") === name;
  const docTabs = () => Array.prototype.slice.call(doc.querySelectorAll('#scr-authoring .authoring-tabs [role="tab"]'));
  const newTxt = await authoringFileItem(ctx, "새 TXT");
  if (!newTxt) { out.a11y_new_tab = false; return; }
  newTxt.click();
  out.a11y_new_tab = await waitFor(ctx, () => docTabs().length === 2 && docTabs()[1].getAttribute("aria-selected") === "true", 40, 50);
  if (!out.a11y_new_tab) return;
  const [firstTab, secondTab] = docTabs();

  // ① 문서 탭(APG tabs, 수동 활성화)
  out.a11y_tabs_reached = await nav.cycleTo(".authoring-tabs");
  out.a11y_tabs_entry = nav.active() === secondTab;
  step("F6", "문서 탭 줄 — 선택된 탭으로 들어온다");
  await press("ArrowLeft");
  out.a11y_tabs_left = nav.active() === firstTab && firstTab.getAttribute("aria-selected") === "false";
  step("ArrowLeft", "앞 탭으로 초점만 옮긴다(선택은 그대로)");
  await press("ArrowRight");
  out.a11y_tabs_right = nav.active() === secondTab;
  step("ArrowRight", "다음 탭으로");
  await press("Home");
  out.a11y_tabs_home = nav.active() === firstTab;
  await press("Enter");
  out.a11y_tabs_enter = await waitFor(ctx, () => firstTab.getAttribute("aria-selected") === "true", 40, 50);
  step("Home, Enter", "첫 탭을 연다(aria-selected)");
  await press("End");
  const closing = nav.active();
  out.a11y_tabs_end = closing === secondTab;
  await press("Delete");
  const asking = () => !byId(ctx, "chooseModal").classList.contains("hidden");
  if (await waitFor(ctx, asking, 10, 50)) { byId(ctx, "chooseModalAlt").click(); settleModal(ctx, "chooseModal"); }
  out.a11y_tabs_delete_closed = await waitFor(ctx, () => docTabs().length === 1, 40, 50);
  out.a11y_tabs_delete_focus = await waitFor(ctx, () => nav.active() === docTabs()[0], 20, 50);
  step("End, Delete", "새 문서 탭을 닫고 이웃 탭에 초점");

  // ② 도구 막대(APG toolbar)
  out.a11y_toolbar_reached = await nav.cycleTo(".authoring-toolbar");
  const entry = nav.active();
  out.a11y_toolbar_single_stop = doc.querySelectorAll('#scr-authoring .authoring-toolbar [tabindex="0"]').length === 1;
  step("F6", "도구 막대 — 입구 제어 하나");
  await press("ArrowRight");
  out.a11y_toolbar_right = nav.active() !== entry && !!nav.within(".authoring-toolbar");
  step("ArrowRight", "다음 제어");
  await press("End");
  // 막대의 마지막 제어는 실행 단추 「결과 시험」이다(확대는 상태 막대로 옮겼다).
  out.a11y_toolbar_end = nav.active().getAttribute("data-rove") === "trial" && textOf(nav.active()).trim() === "결과 시험";
  step("End", "마지막 제어(결과 시험)");
  const pressed = nav.active().getAttribute("aria-pressed");
  await press("ArrowRight");
  // End 뒤의 → 는 첫 **활성** 제어로 감싸 돈다(입구는 마지막 초점 자리라 첫 제어와 다를 수 있다). 옮기기만 하고 누르지 않는다.
  out.a11y_toolbar_wrap = nav.active() === doc.querySelector('#scr-authoring .authoring-toolbar [data-rove]:not([disabled])')
    && doc.querySelector('#scr-authoring .authoring-toolbar [data-rove="trial"]').getAttribute("aria-pressed") === pressed;
  step("ArrowRight", "처음으로 감싸 돈다 — 결과 시험은 눌리지 않는다");
  /* 흐린 만들기 단추(NG-11)는 roving 에 든다: 처음부터 → 로 끝(결과 시험)까지 걸으면 aria-disabled 만들기 단추를 모두
     지나고, disabled 제어(판정 전·실행 취소 불가)는 하나도 지나지 않는다. 걷기는 옮기기만 하고 누르지 않는다. */
  const visited = [];
  for (let i = 0; i < 20; i += 1) {
    const key = nav.active() && nav.active().getAttribute("data-rove");
    if (!key || visited.indexOf(key) >= 0) break;
    visited.push(key);
    if (key === "trial") break;
    await press("ArrowRight");
  }
  out.a11y_toolbar_visits = visited;
  const roveKeys = (selector) => Array.prototype.map.call(
    doc.querySelectorAll(`#scr-authoring .authoring-toolbar ${selector}`), (el) => el.getAttribute("data-rove"));
  out.a11y_toolbar_dimmed = roveKeys('[data-rove][aria-disabled="true"]:not([disabled])');
  out.a11y_toolbar_disabled = roveKeys("[data-rove][disabled]");
  out.a11y_toolbar_dimmed_in_order = out.a11y_toolbar_dimmed.length > 0
    && out.a11y_toolbar_dimmed.every((key) => visited.indexOf(key) >= 0)
    && out.a11y_toolbar_disabled.every((key) => visited.indexOf(key) < 0)
    && visited[visited.length - 1] === "trial";
  step("ArrowRight…", "흐린 만들기 단추도 차례에 든다 — disabled 제어는 건너뛴다");

  // ③ 하단 독 탭(APG tabs) — Enter 로 펼치면 패널 첫 제어로, Escape 는 그 탭으로 돌아온다
  out.a11y_dock_reached = await nav.cycleTo(".authoring-dock");
  out.a11y_dock_entry = role("tab");
  step("F6", "독 탭 줄");
  out.a11y_dock_search = nav.arrowTo((el) => !!el && el.getAttribute("role") === "tab" && textOf(el).trim() === "검색", "ArrowRight", 8);
  const searchTab = nav.active();
  step("ArrowRight", "검색 탭");
  await press("Enter");
  out.a11y_dock_enter_focus = await waitFor(ctx, () => !!nav.active() && nav.active().getAttribute("name") === "query", 20, 50);
  step("Enter", "검색 패널을 펼치고 검색어 칸으로");
  await press("Escape");
  out.a11y_dock_escape_closed = await waitFor(ctx, () => !doc.querySelector('#scr-authoring [role="tabpanel"] input[name="query"]'), 20, 50);
  out.a11y_dock_escape_return = await waitFor(ctx, () => nav.active() === searchTab, 20, 50);
  step("Escape", "패널을 닫고 연 탭으로 돌아온다");

  // ④ 구조 목록(APG tree)과 문맥 메뉴(APG menu) — Shift+F10 은 그 줄을 고른 뒤 그 아래에 메뉴를 연다
  out.a11y_tree_reached = await nav.cycleTo(".authoring-outline");
  out.a11y_tree_entry = role("treeitem");
  step("F6", "구조 목록 — 입구 줄");
  out.a11y_tree_field = await nav.treeTo((el) => nav.nameOf(el).indexOf("필드 · ") === 0, 16);
  const item = nav.active();
  step("ArrowDown", "필드 줄");
  const menu = () => doc.querySelector('#scr-authoring [role="menu"][aria-label="문맥 명령"]');
  pressKey(ctx, "F10", { shiftKey: true });
  out.a11y_menu_open = await waitFor(ctx, () => !!menu() && role("menuitem") && menu().contains(nav.active()), 40, 50);
  out.a11y_tree_current = item.getAttribute("aria-current") === "true";
  step("Shift+F10", "그 줄을 고르고(aria-current) 문맥 메뉴의 첫 사용 가능 항목에 초점");
  if (out.a11y_menu_open) {
    const items = () => Array.prototype.slice.call(menu().querySelectorAll('[role="menuitem"]'));
    // 판정이 선 뒤의 문맥 메뉴에는 불가 항목이 없다(판정 대기 중에만 사유 없는 흐린 항목이 선다).
    out.a11y_menu_no_disabled = await waitFor(ctx, () => items().length > 0 && items().every((el) => el.getAttribute("aria-disabled") !== "true"), 20, 50);
    const first = nav.active();
    await press("ArrowDown");
    out.a11y_menu_down = nav.active() === items()[(items().indexOf(first) + 1) % items().length];
    step("ArrowDown", "다음 항목(판정이 선 문맥 메뉴는 되는 명령과 대안만 싣는다 — IDE-02)");
    await press("End");
    out.a11y_menu_end = nav.active() === items()[items().length - 1];
    await press("Home");
    out.a11y_menu_home = nav.active() === items()[0];
    step("End, Home", "끝·처음 항목");
    const rect = menu().parentElement.getBoundingClientRect();
    out.a11y_menu_in_window = rect.top >= 0 && rect.left >= 0 && rect.bottom <= ctx.win.innerHeight && rect.right <= ctx.win.innerWidth;
    await press("Escape");
    out.a11y_menu_escape_closed = await waitFor(ctx, () => !menu(), 20, 50);
    out.a11y_menu_escape_return = await waitFor(ctx, () => nav.active() === item, 20, 50);
    step("Escape", "메뉴를 닫고 그 줄로 돌아온다");
  }
  // 명령 팔레트(IDE-02 · APG combobox + listbox): 그 줄에서 Ctrl+Shift+P → 머리 띠 아래 비모달 오버레이의 입력칸에 초점.
  // 독의 열린 탭은 그대로이고 독에 「명령」 탭이 서지 않는다. ↓ 는 활성 항목(aria-activedescendant)을 옮기고,
  // Escape 는 팔레트 안에서 멈춰(속성 패널을 닫지 않는다) 연 줄로 초점을 돌린다.
  const palette = () => doc.querySelector('#scr-authoring .authoring-command-palette[role="dialog"]');
  const combo = () => palette() && palette().querySelector('input[role="combobox"]');
  const dockSelected = () => { const tab = doc.querySelector('#scr-authoring .authoring-dock-tab[aria-selected="true"]'); return tab ? tab.id : ""; };
  const dockBefore = dockSelected();
  pressKey(ctx, "P", { ctrlKey: true, shiftKey: true });
  out.a11y_palette_open = await waitFor(ctx, () => !!combo() && nav.active() === combo(), 40, 50);
  step("Ctrl+Shift+P", "명령 팔레트 — 입력칸(combobox)에 초점");
  if (out.a11y_palette_open) {
    out.a11y_palette_dock_kept = dockSelected() === dockBefore
      && !Array.prototype.some.call(doc.querySelectorAll("#scr-authoring .authoring-dock-tab"), (tab) => textOf(tab).trim() === "명령");
    const first = combo().getAttribute("aria-activedescendant");
    await press("ArrowDown");
    out.a11y_palette_arrow = !!first && !!combo().getAttribute("aria-activedescendant") && combo().getAttribute("aria-activedescendant") !== first && nav.active() === combo();
    step("ArrowDown", "활성 항목이 옮겨 간다(초점은 입력칸에 남는다)");
    const properties = !!doc.querySelector("#scr-authoring .authoring-properties");
    await press("Escape");
    out.a11y_palette_escape_closed = await waitFor(ctx, () => !palette(), 20, 50);
    out.a11y_palette_escape_return = await waitFor(ctx, () => nav.active() === item, 20, 50)
      && !!doc.querySelector("#scr-authoring .authoring-properties") === properties;
    step("Escape", "팔레트만 닫고 연 줄로 돌아온다");
  }
  // ⑤ 창 아래 끝에서 연 메뉴도 창 안에 든다(위로 뒤집힘) — 편집면 오른쪽 클릭 사건을 창 아래 끝 좌표로 쏜다.
  const canvas = doc.querySelector("#scr-authoring .authoring-canvas");
  canvas.dispatchEvent(new ctx.win.MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 40, clientY: ctx.win.innerHeight - 4 }));
  out.a11y_bottom_menu_open = await waitFor(ctx, () => !!menu(), 20, 50);
  if (out.a11y_bottom_menu_open) {
    await settleRender(ctx);
    const rect = menu().parentElement.getBoundingClientRect();
    out.a11y_bottom_menu_rect = { top: Math.round(rect.top), bottom: Math.round(rect.bottom), height: Math.round(ctx.win.innerHeight) };
    out.a11y_bottom_menu_in_window = rect.top >= 0 && rect.bottom <= ctx.win.innerHeight;
    await press("Escape");
    await waitFor(ctx, () => !menu(), 20, 50);
  }
  // 속성 패널(Shift+F10 의 선택이 열었다)을 닫아 뒤 단언이 깨끗한 셸에서 돈다.
  if (doc.querySelector("#scr-authoring .authoring-properties")) {
    const input = doc.querySelector("#scr-authoring .authoring-properties input");
    if (input) { input.focus(); await press("Escape"); }
    await waitFor(ctx, () => !doc.querySelector("#scr-authoring .authoring-properties"), 20, 50);
  }
  out.a11y_error_band = textOf(doc.querySelector("#scr-authoring .authoring-shell > div.authoring-error")).trim();
}

/** 기존 editor_txt_band 부팅에서 실제 CM·Python 분석·미저장 보호를 검증한다. */
async function probeLintpad(ctx, out) {
  const doc = ctx.doc;
  const rowMenu = doc.querySelector('#editorTplList [data-act="lib-more"][data-key="기안.txt"]');
  if (!rowMenu) { out.lintpad_trigger = false; return; }
  doc.body.click(); rowMenu.click();
  const editSelector = '#tplRowMenu [data-context-menu-action="edit"]';
  out.lintpad_trigger = await waitFor(ctx, () => !!doc.querySelector(editSelector));
  if (!out.lintpad_trigger) return;
  // 합성 행의 파일 선택만 대체한다. 세션과 분석은 실제 backend 왕복이다.
  const stub = stubBridgeInvoke(ctx, "openAuthoringDocument", "open_authoring_document",
    () => async () => service(ctx, "Bridge").call("authoring", "new", { media: "txt" }));
  const canvas = ".authoring-document:not([hidden])";
  try {
    doc.querySelector(editSelector).click();
    out.lintpad_mounted = await waitFor(ctx, () => !!doc.querySelector(`${canvas} .cm-editor`));
  } finally { stub.restore(); }
  if (!out.lintpad_mounted) return;
  /* 편집면은 화면 전환보다 **먼저** 선다: controller.open 은 세션을 활성화(→ 탭·CodeMirror
     렌더)한 **뒤에** 저작 화면으로 간다. 마운트 순간에 한 번 읽으면 그 사이를 재서, 화면이
     아직 숨어 있어 포커스도 받지 못한 채로 두 키가 함께 거짓이 된다(전체 게이트 파일 실행에서
     실제로 났다). 전환을 기다린 뒤 잰다 — 전환이 끝내 오지 않으면 여전히 거짓이다. */
  out.authoring_screen_on = await waitFor(
    ctx, () => doc.getElementById("scr-authoring").classList.contains("on"));
  const content = doc.querySelector(`${canvas} .cm-content`);
  out.lintpad_content_editable = content.isContentEditable;
  content.focus(); out.lintpad_focusable = doc.activeElement === content;
  const marks = () => doc.querySelectorAll(`${canvas} .cm-txtField, ${canvas} .cm-txtMarker`).length;
  out.lintpad_marks_before = marks();
  pasteInto(ctx, content, "제목: {{공고명}}\n{{#항목 사유}}");
  out.lintpad_lint_arrived = await waitFor(ctx, () => marks() === 2);
  out.lintpad_field_marks = doc.querySelectorAll(`${canvas} .cm-txtField`).length;
  out.lintpad_marker_marks = doc.querySelectorAll(`${canvas} .cm-txtMarker`).length;
  // 문제는 하단 독의 탭이다(§3.1) — 탭 이름이 「문제」로 시작한다(수 배지가 뒤따른다).
  [...doc.querySelectorAll('.authoring-dock [role="tab"]')].find((el) => el.textContent.indexOf("문제") === 0).click();
  const problemsPanel = '.authoring-dock [role="tabpanel"] .authoring-bottom[aria-label="문제"]';
  await waitFor(ctx, () => !!doc.querySelector(`${problemsPanel} button`));
  out.lintpad_diag_text = doc.querySelector(problemsPanel)?.textContent || "";
  keydownOn(ctx, content, "Escape");
  out.authoring_escape_retains = await waitFor(ctx, () => !doc.querySelector('.authoring-dock [role="tabpanel"]')) && content.isConnected;
  // 표시 방식은 도구 막대의 세 갈래 버튼(aria-pressed)이다.
  const mode = (value) => doc.querySelector(`.authoring-toolbar .authoring-mode button[value="${value}"]`);
  mode("document").click();
  out.authoring_document_mode = await waitFor(ctx, () => marks() === 0)
    && mode("document").getAttribute("aria-pressed") === "true";
  mode("template").click();
  out.authoring_template_mode = await waitFor(ctx, () => marks() === 2)
    && mode("template").getAttribute("aria-pressed") === "true";
  /* FB-03(#1079): 편집면은 표기 원문 대신 이름표를 그린다 — 템플릿 표시의 편집면 글자에 표기 문법(`{{`)이 없고 이름은
     보인다. 이름표를 누르면 캐럿은 토큰 앞뒤에 선다(원자 범위): 편집면이 쓴 DOM 선택이 이름표 안에 들지 않는다. */
  out.lintpad_source_hidden = !content.textContent.includes("{{") && content.textContent.includes("공고명")
    && content.textContent.includes("사유");
  const tag = doc.querySelector(`${canvas} .cm-txtField`);
  if (tag) {
    /* 합성 mousedown 에는 기본 동작(초점 이동)이 없다 — 편집면이 초점을 쥐어야 CodeMirror 가 제 선택을 DOM 선택으로 쓴다.
       캐럿은 문서 끝(닫히지 않은 항목 줄)에서 출발하므로, 누른 뒤 이름표의 줄에 섰다면 누름이 캐럿을 옮긴 것이다. */
    content.focus();
    await settleRender(ctx);
    const box = tag.getBoundingClientRect();
    const point = { bubbles: true, cancelable: true, button: 0, detail: 1, clientX: box.left + box.width / 2, clientY: box.top + box.height / 2 };
    tag.dispatchEvent(new ctx.win.MouseEvent("mousedown", point));
    tag.dispatchEvent(new ctx.win.MouseEvent("mouseup", point));
    await settleRender(ctx);
    const picked = doc.getSelection();
    const shown = doc.querySelector(`${canvas} .cm-txtField`);
    const anchor = picked && picked.anchorNode;
    const anchorEl = anchor && (anchor.nodeType === 3 ? anchor.parentElement : anchor);
    const anchorLine = anchorEl && anchorEl.closest ? (anchorEl.classList && anchorEl.classList.contains("cm-content")
      ? anchorEl.childNodes[Math.min(picked.anchorOffset, anchorEl.childNodes.length - 1)] : anchorEl.closest(".cm-line")) : null;
    // 원자 범위: 선택의 두 끝이 모두 이름표 밖이고, 비어 있거나 이름표 하나를 통째로 담는다(토큰 일부만 고르지 않는다).
    const focusNode = picked && picked.focusNode;
    const whole = !!picked && !!shown && !picked.isCollapsed && picked.containsNode(shown, false)
      && picked.toString() === shown.textContent;
    out.lintpad_tag_caret_outside = !!anchor && !!focusNode && content.contains(anchor) && !!shown
      && !shown.contains(anchor) && !shown.contains(focusNode) && !!anchorLine && anchorLine === shown.closest(".cm-line")
      && (picked.isCollapsed || whole);
    out.lintpad_tag_caret_detail = { collapsed: !!picked && picked.isCollapsed, whole, text: picked ? picked.toString() : "",
      inContent: !!anchor && content.contains(anchor), inTag: !!shown && ((!!anchor && shown.contains(anchor)) || (!!focusNode && shown.contains(focusNode))),
      sameLine: !!anchorLine && !!shown && anchorLine === shown.closest(".cm-line"), focused: doc.activeElement === content };
  }
  /* §10 키보드·IME 밴드 — 같은 세션(필드 1 · 닫히지 않은 항목 1 = 문제 1) 위에서 돈다. 예외는
     `kbd_error` 에만 실어 뒤따르는 닫기 보호 단언을 끌고 죽지 않는다. */
  try {
    await probeAuthoringKeyboard(ctx, out);
  } catch (thrown) {
    out.kbd_error = String((thrown && thrown.message) || thrown);
  }
  try {
    await probeAuthoringA11y(ctx, out);
  } catch (thrown) {
    out.a11y_error = String((thrown && thrown.message) || thrown);
  }
  const close = () => doc.querySelector(".authoring-tab button[aria-label]").click();
  const asking = () => !doc.getElementById("chooseModal").classList.contains("hidden");
  close(); out.authoring_close_asks = await waitFor(ctx, asking);
  if (out.authoring_close_asks) {
    doc.getElementById("chooseModalCancel").click();
    await waitFor(ctx, () => !asking());
    out.authoring_cancel_retains = content.isConnected && content.textContent.includes("공고명");
    close(); await waitFor(ctx, asking);
    doc.getElementById("chooseModalAlt").click(); settleModal(ctx, "chooseModal");
  }
  out.lintpad_disposed = await waitFor(ctx, () => !doc.querySelector(`${canvas} .cm-editor`));
  service(ctx, "Nav").go("editor", { force: true }); await settleRender(ctx);
}

/** HWPX 저작 밴드가 열 후보 문서 — **게이트가 실 서식 폴더(테스트 홈)에 심어 둔 파일**이다.
 *
 *  경로를 여기 적을 수 없다: 홈이 부팅마다 tmp 라 절대 경로를 아는 것은 파이썬 쪽뿐이고,
 *  프로브가 아는 것은 **파일 이름**이다. 그래서 실 `tpl` 스냅샷(서식 폴더의 정본 목록)에서
 *  같은 이름의 행을 찾아 그 `path` 로 연다 — 합성 스냅샷을 밀지 않으므로 「목록에 있는
 *  경로만 연다」는 백엔드 관문(`screen_template.is_live_path`)도 실물로 지난다.
 *
 *  좌표는 `tests/corpus/real` 의 그 파일에서 왔고 헤드리스 왕복으로 확인했다:
 *   · `query` 는 본문 검색 적중이 **한 곳**인 문구이고, 그 문단의 run 이 굵게(charPr 28)라
 *     AC02 의 「서식 있는 문구」가 성립한다(`formatted`).
 *   · `field` 는 사용 위치가 정확히 `occurrences` 곳인 필드다 — AC07 이 세는 그 수다.
 *   · `newField`·`renamed` 는 문서에 없는 이름이다(이름 충돌 거절을 타지 않는다).
 *
 *  **순서대로 시도한다.** rhwp 왕복 보존 검사(`rhwp_roundtrip_preflight`)를 어느 문서가
 *  통과하는지는 vendor 편집기의 실측 사실이라 정적으로 알 수 없고, 통과하지 못한 문서는
 *  HWPX 수정 자체가 백엔드에서 차단된다(screen_authoring:517·548). 그래서 통과한 첫 문서로
 *  밴드를 돌고, 하나도 통과하지 못하면 후보별 진단을 그대로 싣는다 — 조용히 초록이 되면
 *  「편집이 아예 불가능했다」가 증거에서 사라진다. */
const HWPX_AUTHORING_CANDIDATES = Object.freeze([
  Object.freeze({
    key: "bid_notice_limited_under100m.hwpx",
    query: "입찰개요", context: "1. 입찰개요", formatted: true,
    newField: "개요구간", field: "수요기관", occurrences: 2, renamed: "수요기관확인",
  }),
  Object.freeze({
    key: "filled_notice_marine.hwpx",
    query: "입찰개요", context: "1. 입찰개요", formatted: true,
    newField: "개요구간", field: "수요기관", occurrences: 2, renamed: "수요기관확인",
  }),
]);

/** 비동기 술어 폴링 — `waitFor` 는 **동기** 술어라 백엔드 왕복을 기다릴 수 없다. */
async function pollFor(ctx, ready, tries, ms) {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (await ready()) return true;
    await ctx.sleep(ms);
  }
  return !!(await ready());
}

/** HWPX 저작 밴드 — 실 rhwp iframe 위에서 AC01·AC02·AC07·AC23 의 거동을 되읽는다.
 *
 *  **편집기는 스텁하지 않는다.** 대체하는 것은 네이티브 대화상자 둘뿐이다(TXT 밴드와 같은
 *  규율): 「문서 열기」의 파일 선택과 「저장」의 저장 위치 선택. 그 둘은 OS 창이라 게이트가
 *  누를 수 없고, 그대로 두면 프로브가 대화상자 앞에서 매달린다. 세션·분석·미리보기·적용·
 *  실행 취소·저장 판정은 전부 실제 왕복이다.
 *
 *  읽기는 **실 백엔드 스냅샷**(`Bridge.initial("authoring")`)으로 한다 — 컨트롤러 객체는
 *  services 자루에 없고(포트로만 결속된다), 화면이 그리는 텍스트를 되파싱하면 재는 것이
 *  제품의 상태가 아니라 표면의 문장이 된다. 쓰기는 반대로 전부 **실 DOM 클릭**이다.
 *
 *  바이트 비교의 기준선이 둘인 이유(중요): 마운트 시점의 세션 내용은 **디스크의 바이트**이고,
 *  편집기가 한 번이라도 발신하면 세션 내용은 **rhwp 의 내보낸 바이트**가 된다. 보존 검사가
 *  통과했다는 것은 그 둘이 c14n 동형이라는 뜻이지 바이트 동일이라는 뜻이 아니다. 그래서
 *  「되돌리면 원본과 같다」의 확정은 제품의 비교기(`rhwp_roundtrip_preflight`)로 하고,
 *  바이트 동일은 편집기 발신끼리(다시 실행 ↔ 적용, 두 번째 되돌리기 ↔ 첫 되돌리기)만 센다. */
async function probeHwpxAuthoring(ctx, out) {
  const doc = ctx.doc;
  const Bridge = service(ctx, "Bridge");
  const Nav = service(ctx, "Nav");
  const Personalization = service(ctx, "Personalization");
  const canvas = ".authoring-document:not([hidden])";
  const all = (selector) => Array.prototype.slice.call(doc.querySelectorAll(selector));
  const exact = (selector, label) => all(selector).find((el) => textOf(el).trim() === label) || null;
  const snapshot = () => Bridge.initial("authoring");
  const activeTab = (snap) => (((snap || {}).tabs) || []).find(
    (tab) => tab.id === (snap || {}).active_id) || {};
  const fieldsOf = (tab) => (((tab.analysis) || {}).fields) || [];
  const countOf = (tab, name) => {
    const found = fieldsOf(tab).find((field) => field.name === name);
    return found ? found.count : 0;
  };
  /* 예산 파수꾼 — 남은 시한이 다음 국면을 감당하지 못하면 **이유를 적고** 멈춘다.
     시한에 물려 죽으면 어디까지 갔는지가 증거에서 사라진다. */
  const afford = (ms) => ctx.remainingMs() > ms;
  const noAlert = () => {
    const real = ctx.win.alert;
    ctx.win.alert = function () { out.hwpx_authoring_alerts = (out.hwpx_authoring_alerts || 0) + 1; };
    return { restore() { if (ctx.win.alert !== real) ctx.win.alert = real; } };
  };

  out.hwpx_authoring_error = null;
  out.hwpx_authoring_alerts = 0;
  out.hwpx_authoring_candidate = "";
  out.hwpx_authoring_preflight = [];
  let openStub = null;
  let alerts = null;
  let sid = "";
  /* 되돌릴 배율은 **밴드 진입 시점**에 잡는다. 본 밴드가 배율 국면까지 가야 채워지는
     `hwpx_authoring_font_scale_before` 에 기대면, 그 앞에서 멈춘(중단·후보 없음·진입 실패)
     모든 경로에서 복원 목표가 「normal」로 떨어져 **이 부팅이 들고 있던 배율을 지운다** —
     배율 영속 검사의 되읽기 콜드부트(large/larger)가 이 밴드 뒤의 `personalization_persist`
     에서 normal 을 읽은 게이트 4차 실패가 그것이다. */
  const scaleAtEntry = doc.documentElement.getAttribute("data-font-scale") || "normal";
  try {
    const tpl = await Bridge.initial("tpl");
    const rows = (((tpl || {}).column) || {}).rows || [];
    out.hwpx_authoring_library_rows = rows.length;
    /* 저작 화면 진입은 편집기 머리의 「템플릿 만들기」다(editor.ts:103 → 포트 → open()).
       Nav 로 직접 가면 화면은 서지만 그 배선이 살아 있는지는 재지 못한다. */
    const entry = exact("#scr-editor button", "템플릿 만들기");
    out.hwpx_authoring_entry_affordance = !!entry;
    if (!entry) return;
    entry.click();
    out.hwpx_authoring_screen_on = await waitFor(
      ctx, () => byId(ctx, "scr-authoring").classList.contains("on"));
    if (!out.hwpx_authoring_screen_on) return;

    for (const candidate of HWPX_AUTHORING_CANDIDATES) {
      const row = rows.find((item) => item && item.key === candidate.key);
      const path = row ? String(row.path || "") : "";
      if (!path) {
        out.hwpx_authoring_preflight.push({ key: candidate.key, editable: null, reason: "목록에 없음" });
        continue;
      }
      /* 후보 하나의 최악 몫(마운트 6초 + 보존 검사 6초)과 본 밴드의 몫을 합친 문턱이다.
         남지 않았는데 들어가면 감시견이 프로브째 죽여 **TXT 단언 열둘까지** 증거를 잃는다. */
      if (!afford(14000)) {
        out.hwpx_authoring_preflight.push({ key: candidate.key, editable: null, reason: "예산 부족" });
        break;
      }
      /* 네이티브 파일 선택만 대체한다 — 「문서 열기」는 as_template=false 로 열어
         **저장 위치 미확정** 상태를 만든다(AC01 이 겨누는 그 상태다). */
      openStub = stubBridgeInvoke(ctx, "openAuthoringDocument", "open_authoring_document",
        (real) => (requested, asTemplate) => real(requested || path, asTemplate === true));
      const open = await authoringFileItem(ctx, "문서 열기");
      out.hwpx_authoring_open_affordance = !!open;
      try {
        if (!open) return;
        open.click();
        const started = await pollFor(ctx, async () => !!activeTab(await snapshot()).id, 20, 100);
        if (!started) {
          out.hwpx_authoring_preflight.push({ key: candidate.key, editable: null, reason: "세션 미생성" });
          continue;
        }
      } finally { openStub.restore(); openStub = null; }
      sid = String(activeTab(await snapshot()).id);
      /* 보존 판정 칩(U01·§7.1)은 Python 투영에서 선다 — 마운트 **도중**에 「보존 확인 중」이
         보이고, 판정이 서면 편집기 마운트와 무관하게 그 판정으로 바뀌어야 한다. 마운트를
         기다리는 동안 칩을 표본으로 읽는다. */
      const chip = () => textOf(doc.querySelector(".authoring-status [data-compat]")).trim();
      let chipFirst = "";
      let sawChecking = false;
      const sample = () => {
        const now = chip();
        if (!chipFirst && now) chipFirst = now;
        if (now === "보존 확인 중") sawChecking = true;
      };
      out.hwpx_authoring_mounted = await waitFor(
        ctx, () => { sample(); return !!doc.querySelector(`${canvas} .authoring-editor-host iframe`); }, 30, 200);
      /* 보존 검사 결과는 `rhwp_editable` 이 null 을 벗는 순간이다 — 마운트가 내보낸
         바이트로 파이썬이 판정한다. */
      await pollFor(ctx, async () => { sample(); return activeTab(await snapshot()).rhwp_editable !== null; }, 24, 250);
      const tab = activeTab(await snapshot());
      const limitedChip = "읽기 전용 · 보존 확인 필요";
      await waitFor(ctx, () => chip() === (tab.rhwp_editable === false ? limitedChip : ""), 20, 50);
      out.hwpx_authoring_preflight.push({
        key: candidate.key,
        editable: tab.rhwp_editable,
        diagnostics: (tab.rhwp_diagnostics || []).slice(0, 6),
        compat_state: String(((tab.compatibility) || {}).state || ""),
        chip_first: chipFirst,
        saw_checking: sawChecking,
        chip_after: chip(),
        banner: !!doc.querySelector("#scr-authoring section.authoring-compat"),
      });
      if (tab.rhwp_editable === true) {
        out.hwpx_authoring_candidate = candidate.key;
        out.hwpx_authoring_save_as_required = tab.save_as_required;
        out.hwpx_authoring_rhwp_editable = tab.rhwp_editable;
        out.hwpx_authoring_readiness = String(((tab.readiness) || {}).state || "");
        out.hwpx_authoring_field_count = fieldsOf(tab).length;
        out.hwpx_authoring_target_field_count = countOf(tab, candidate.field);
        out.hwpx_authoring_target_formatted = candidate.formatted === true;
        /* 필드 목록은 **셈과 함께** 싣는다 — 실패했을 때 「어느 필드가 몇 곳인가」를 증거에서
           바로 읽을 수 있어야 사후에 문서를 다시 열어 보지 않는다. */
        out.hwpx_authoring_fields = fieldsOf(tab)
          .slice(0, 12).map((field) => `${field.name}:${field.count}`);
        await runHwpxAuthoringBand(ctx, out, candidate, sid);
        break;
      }
      /* 통과하지 못한 문서는 수정이 차단된다 — 탭을 닫고 다음 후보로 간다(읽기 전용
         문서를 든 채로 다음 문서를 열면 어느 탭을 재는지가 흐려진다). */
      await closeHwpxAuthoringTab(ctx, out);
      sid = "";
    }
  } catch (thrown) {
    /* 밴드의 예외는 **이 키에만** 싣는다 — `ctx.fail` 로 올리면 같은 프로브가 지는 TXT
       단언 열둘이 함께 죽어 원인이 흐려진다. */
    out.hwpx_authoring_error = String((thrown && thrown.message) || thrown);
  } finally {
    if (openStub) openStub.restore();
    /* 복원은 **셋 다** 돈다(앞의 실패가 뒤의 복원을 삼키지 않는다): 배율 → 창 크기 →
       탭·화면. 배율과 창은 뒤따르는 클러스터 E 프로브가 그 값을 재므로 남기면 그쪽 실패로
       나타나 귀인이 갈린다(shell_settings 가 테마를 되돌리는 것과 같은 규율). */
    try {
      alerts = noAlert();
      /* 올렸던 배율만 되돌린다 — 속성이 아예 없는 대역에서 부르면 개인화 동사가 폭까지
         새로 심어(하한 180px) 뒤따르는 프로브의 값을 바꾼다. */
      const scale = doc.documentElement.getAttribute("data-font-scale");
      if (scale !== null && scale !== scaleAtEntry) Personalization.setFontScale(scaleAtEntry);
    } catch (thrown) {
      out.hwpx_authoring_restore_error = String((thrown && thrown.message) || thrown);
    } finally { if (alerts) { alerts.restore(); alerts = null; } }
    if (ctx.state.hwpxWindowResized === true) {
      try {
        await ctx.host("window_resize", { width: 1440, height: 900 });
        await ctx.sleep(600);
        ctx.state.hwpxWindowResized = false;
      } catch (thrown) {
        out.hwpx_authoring_restore_error = String((thrown && thrown.message) || thrown);
      }
    }
    try {
      await closeHwpxAuthoringTab(ctx, out);
      out.hwpx_authoring_disposed = await waitFor(
        ctx, () => !doc.querySelector(".authoring-editor-host iframe"));
      const back = doc.querySelector('#scr-authoring .authoring-head button[aria-label="돌아가기"]');
      if (back) back.click();
      await waitFor(ctx, () => !byId(ctx, "scr-authoring").classList.contains("on"));
      out.hwpx_authoring_screen_on_after_close = byId(ctx, "scr-authoring")
        .classList.contains("on");
      Nav.go("editor", { force: true });
      await settleRender(ctx);
    } catch (thrown) {
      out.hwpx_authoring_restore_error = String((thrown && thrown.message) || thrown);
    }
  }
}

/** 열린 저작 탭을 닫는다 — 미저장 변경이 있으면 3택에서 **버리기**를 고른다(force 닫기). */
async function closeHwpxAuthoringTab(ctx, out) {
  const doc = ctx.doc;
  const close = doc.querySelector('.authoring-tab button[aria-label$="닫기"]');
  if (!close) return;
  close.click();
  const asking = () => !byId(ctx, "chooseModal").classList.contains("hidden");
  if (await waitFor(ctx, asking, 20, 50)) {
    out.hwpx_authoring_close_asks = true;
    byId(ctx, "chooseModalAlt").click();
    settleModal(ctx, "chooseModal");
    await waitFor(ctx, () => !asking());
  }
  out.hwpx_authoring_closed = await waitFor(
    ctx, () => !doc.querySelector(".authoring-tab button[aria-label]"));
}

/** 통과한 문서 하나 위에서 도는 본 밴드(AC01·AC02·AC07·AC23). */
async function runHwpxAuthoringBand(ctx, out, candidate, sid) {
  const doc = ctx.doc;
  const Bridge = service(ctx, "Bridge");
  const Personalization = service(ctx, "Personalization");
  const all = (selector) => Array.prototype.slice.call(doc.querySelectorAll(selector));
  const hit = (selector, label) => all(selector).find((el) => textOf(el).indexOf(label) >= 0) || null;
  const exact = (selector, label) => all(selector).find((el) => textOf(el).trim() === label) || null;
  // 그림 단추(UX-09: 실행 취소·다시 실행)는 보이는 글 대신 이름(aria-label)으로 찾는다.
  const named = (selector, label) => all(selector).find((el) => String(el.getAttribute("aria-label") || "").indexOf(label) === 0) || null;
  const snapshot = () => Bridge.initial("authoring");
  const activeTab = (snap) => (((snap || {}).tabs) || []).find(
    (tab) => tab.id === (snap || {}).active_id) || {};
  const fieldsOf = (tab) => (((tab.analysis) || {}).fields) || [];
  const countOf = (tab, name) => {
    const found = fieldsOf(tab).find((field) => field.name === name);
    return found ? found.count : 0;
  };
  const tab = async () => activeTab(await snapshot());
  const content = async () => String(
    (await Bridge.call("authoring", "content", { session_id: sid })).content);
  const undoLabel = () => String((named(".authoring-toolbar button", "문서 실행 취소") || { getAttribute: () => "" }).getAttribute("aria-label") || "").trim();
  const previewText = () => textOf(doc.querySelector(
    ".authoring-properties section.authoring-preview:not(.authoring-refusal)"));
  const affected = () => {
    const found = /사용 위치 (\d+)곳/.exec(previewText());
    return found ? Number(found[1]) : -1;
  };
  /** 속성 폼의 Enter — 이름 칸에서 누른 Enter 의 암묵 제출과 같은 submit 경로다(pressKey 의 Enter 와 같다). */
  const enter = () => {
    const form = doc.querySelector("#scr-authoring form.authoring-properties");
    if (!form) return false;
    form.requestSubmit();
    return true;
  };
  const crumbNow = () => textOf(doc.querySelector(
    '#scr-authoring .authoring-selection .authoring-crumb[aria-current="location"]')).trim();
  const afford = (ms) => ctx.remainingMs() > ms;

  /* 내부 대기 상한은 **짧게** 잡는다(DOM 2초 · 백엔드 왕복 2.5초). 어느 국면이 서지
     않으면 사유를 적고 곧장 나간다 — 아홉 자리에서 각자 길게 기다리면 합이 프로브 시한을
     넘고, 그때는 감시견이 프로브째 죽여 TXT 단언까지 증거를 잃는다. */
  const DOM_TRIES = 20;
  const DOM_MS = 100;
  const WIRE_TRIES = 20;
  const WIRE_MS = 125;
  /* 중단 사유와 함께 **표면이 그 순간 보이던 오류**를 싣는다 — 제품이 거절·예외를 오류
     띠(`.authoring-error`)로 그렸는데 프로브가 사유만 적으면, 「반영되지 않음」이 대기 부족인지
     제품의 거절인지가 증거에서 갈리지 않는다. */
  const give = (reason) => {
    out.hwpx_authoring_aborted = reason;
    out.hwpx_authoring_abort_alerts = all("#scr-authoring .authoring-error")
      .map((el) => textOf(el).trim().slice(0, 200)).filter(Boolean);
    return false;
  };

  const mount = await content();                        // 디스크 바이트(아직 편집기 발신 전)
  out.hwpx_authoring_base_field_count = fieldsOf(await tab()).length;

  /* ── ④ 서식 있는 본문 문구를 고르고 필드로 만든다 ─────────────────────────────
     본문 범위 선택은 iframe **안**의 사건이라 게이트가 직접 끌 수 없다. 제품이 같은
     선택을 만드는 두 번째 실경로가 검색 적중 클릭이다(controller.select → locate). */
  exact('.authoring-dock [role="tab"]', "검색").click();
  if (!await waitFor(ctx, () => !!doc.querySelector('.authoring-bottom input[name="query"]'),
    DOM_TRIES, DOM_MS)) return give("검색 패널 미개방");
  typeValue(ctx, doc.querySelector('.authoring-bottom input[name="query"]'), candidate.query);
  exact(".authoring-bottom button", "찾기").click();
  const found = await waitFor(
    ctx, () => !!hit(".authoring-bottom button", candidate.context), WIRE_TRIES, WIRE_MS);
  out.hwpx_authoring_search_hit = found
    ? textOf(hit(".authoring-bottom button", candidate.context)).trim() : "";
  if (!found) return give("본문 검색 적중 없음");
  hit(".authoring-bottom button", candidate.context).click();
  /* 검색 적중은 독에서 시작한 선택이다(NG-06 keepDock): 선택이 옮겨 가고(「필드로 만들기」 판정이 그 범위로 켜진다)
     독의 검색 탭과 적중 목록은 그대로이며 속성 패널은 열리지 않는다. 속성은 이어서 「필드로 만들기」가 연다. */
  const createReady = () => {
    const button = exact(".authoring-toolbar button", "필드로 만들기");
    return !!(button && !button.disabled && button.getAttribute("aria-disabled") !== "true");
  };
  if (!await waitFor(ctx, createReady, WIRE_TRIES, WIRE_MS)) return give("검색 적중 선택 뒤 필드로 만들기 미개방");
  const searchTab = exact('.authoring-dock [role="tab"]', "검색");
  out.hwpx_authoring_hit_dock_kept = !!searchTab && searchTab.getAttribute("aria-selected") === "true"
    && !!hit(".authoring-bottom button", candidate.context);
  out.hwpx_authoring_hit_no_properties = !doc.querySelector(".authoring-properties");
  // 일반 문서로 연(저장 경로 없는) 새 템플릿에는 연결된 작업이 없다 — 「변경 영향·작업 적용」 문맥 탭이 서지 않는다(NG-09).
  out.hwpx_authoring_impact_tab = !!exact('.authoring-dock [role="tab"]', "변경 영향·작업 적용");
  const create = exact(".authoring-toolbar button", "필드로 만들기");
  out.hwpx_authoring_create_enabled = !!(create && !create.disabled && create.getAttribute("aria-disabled") !== "true");
  if (!out.hwpx_authoring_create_enabled) return give("필드로 만들기 비활성");
  create.click();
  if (!await waitFor(ctx, () => !!doc.querySelector(".authoring-properties input"),
    DOM_TRIES, DOM_MS)) return give("속성 입력 없음");
  /* 만들기 진입(IDE-03 NG-04·NG-05): 「명령」 선택이 없고 제출 단추가 명령 이름 하나다. 이름 칸은 Python 제안값으로
     열린다 — 이 표본 문구(「1. 입찰개요」)에는 「라벨:」이 없어 빈 칸이다(진단용으로 싣는다). */
  out.hwpx_authoring_create_form_select = !!doc.querySelector(".authoring-properties select");
  out.hwpx_authoring_create_submit_label = textOf(doc.querySelector('.authoring-properties button[type="submit"]')).trim();
  out.hwpx_authoring_create_suggested = doc.querySelector(".authoring-properties input").value;
  out.hwpx_authoring_create_new_field = candidate.newField;
  typeValue(ctx, doc.querySelector(".authoring-properties input"), candidate.newField);
  /* 새 이름 한 자리의 필드 만들기는 확인 등급 none 이다(P-01): 명령 단추 한 번(= Enter 한 번)에 적용되고
     미리보기 구획은 한 프레임도 서지 않는다. 그 사이 구획이 섰는지는 DOM 변화를 지켜 잰다. */
  let previewFlashed = false;
  const Observer = ctx.win.MutationObserver;
  const flashes = new Observer(() => {
    if (doc.querySelector(".authoring-properties section.authoring-preview:not(.authoring-refusal)")) previewFlashed = true;
  });
  flashes.observe(byId(ctx, "scr-authoring"), { childList: true, subtree: true });
  const submit = exact(".authoring-properties button", "필드로 만들기");
  if (!submit) { flashes.disconnect(); return give("필드로 만들기 제출 단추 없음"); }
  submit.click();
  const appliedAt = Date.now();
  if (!await pollFor(ctx, async () => countOf(await tab(), candidate.newField) === 1,
    WIRE_TRIES, WIRE_MS)) {
    const late = await tab();
    out.hwpx_authoring_create_late = {
      ms: Date.now() - appliedAt, revision: late.revision, dirty: late.dirty,
      field_count: fieldsOf(late).length, new_count: countOf(late, candidate.newField),
    };
    flashes.disconnect();
    out.hwpx_authoring_create_refusal = textOf(
      doc.querySelector(".authoring-properties .authoring-reason[role=alert], .authoring-refusal")).trim().slice(0, 160);
    return give("필드 생성이 분석에 반영되지 않음");
  }
  out.hwpx_authoring_create_ms = Date.now() - appliedAt;
  /* 적용 뒤(결정 2·NG-14): 속성 패널이 닫히고 선택이 새 필드에 서서 위치 줄이 「필드 · 이름」이 된다. */
  out.hwpx_authoring_create_panel_closed = await waitFor(
    ctx, () => !doc.querySelector(".authoring-properties"), WIRE_TRIES, WIRE_MS);
  await waitFor(ctx, () => crumbNow() === `필드 · ${candidate.newField}`, WIRE_TRIES, WIRE_MS);
  flashes.disconnect();
  out.hwpx_authoring_create_preview_flashed = previewFlashed;
  out.hwpx_authoring_create_crumb = crumbNow();
  const created = await content();
  out.hwpx_authoring_create_field_count = fieldsOf(await tab()).length;
  out.hwpx_authoring_create_label = undoLabel();
  out.hwpx_authoring_create_changed_content = created !== mount;

  /* ── ⑤ 한 번의 문서 실행 취소가 원래 본문을 되돌린다 ───────────────────────── */
  named(".authoring-toolbar button", "문서 실행 취소").click();
  if (!await pollFor(ctx, async () => countOf(await tab(), candidate.newField) === 0,
    WIRE_TRIES, WIRE_MS)) return give("실행 취소가 필드를 되돌리지 않음");
  const undone = await content();
  out.hwpx_authoring_undo_field_count = fieldsOf(await tab()).length;
  out.hwpx_authoring_undo_changed_content = undone !== created;
  /* 진단용(단언하지 않는다): 마운트 시점 기준선은 **디스크 바이트**라, 되돌린 뒤 편집기가
     내보낸 바이트와 동일하지 않을 수 있다. 원본 동일의 확정은 ⑧의 제품 비교기가 진다. */
  out.hwpx_authoring_undo_content_equals_mount = undone === mount;
  out.hwpx_authoring_undo_label_cleared = undoLabel() === "문서 실행 취소";
  named(".authoring-toolbar button", "문서 다시 실행").click();
  if (!await pollFor(ctx, async () => countOf(await tab(), candidate.newField) === 1,
    WIRE_TRIES, WIRE_MS)) return give("다시 실행이 필드를 되살리지 않음");
  out.hwpx_authoring_redo_field_count = fieldsOf(await tab()).length;
  out.hwpx_authoring_redo_content_equals_create = (await content()) === created;
  named(".authoring-toolbar button", "문서 실행 취소").click();
  if (!await pollFor(ctx, async () => countOf(await tab(), candidate.newField) === 0,
    WIRE_TRIES, WIRE_MS)) return give("두 번째 실행 취소 미반영");
  out.hwpx_authoring_undo2_content_equals_undo = (await content()) === undone;

  /* ── ⑥ 이름 변경은 **모든 사용 위치**를 함께 옮긴다(AC07) ───────────────────── */
  if (!afford(8000)) return give("예산 부족: 이름 변경");
  // 필드 목록은 구조 패널의 「필드」 보기다(UX-09) — 그 보기를 열고, 필드 줄(treeitem)을 이름으로 찾는다
  // (「필드 · 이름 · 사용 위치 n곳」 — 화면 읽기가 읽는 그 이름).
  const fieldsView = doc.querySelector("#authoring-outline-fields");
  if (fieldsView) fieldsView.click();
  await settleRender(ctx);
  const summary = all('#authoring-outline-fields-panel [role="treeitem"]').find(
    (el) => String(el.getAttribute("aria-label") || "").indexOf(`필드 · ${candidate.field} · 사용 위치 ${candidate.occurrences}곳`) === 0);
  out.hwpx_authoring_rename_target = summary ? String(summary.getAttribute("aria-label")).trim() : "";
  if (!summary) return give("구조 목록에 사용 위치 2곳 필드가 없음");
  summary.click();
  /* 입력창의 존재로는 선택이 끝났는지 알 수 없다 — 선택(controller.select → locate)이 끝나야
     명령이 「필드 이름 변경」으로 바뀌고 이름 칸이 그 필드의 이름으로 채워진다. 그 전에 쓰면
     직전 명령이 옛 선택 위에서 미리보기를 낸다(게이트 4차 재실행에서 실제로 났다). 구조 목록 줄이 연
     폼은 「명령」 선택을 둔다(NG-05). */
  const settled = () => {
    const kind = doc.querySelector(".authoring-properties select");
    const input = doc.querySelector(".authoring-properties input");
    return !!kind && kind.value === "rename_field" && !!input && input.value === candidate.field;
  };
  if (!await waitFor(ctx, settled, WIRE_TRIES, WIRE_MS)) return give("필드 선택 뒤 이름 변경 속성 미정착");
  typeValue(ctx, doc.querySelector(".authoring-properties input"), candidate.renamed);
  /* 이름 변경은 확인 등급 enter 다(P-01): 첫 Enter 가 영향 구획을 세우고, 같은 주 단추에 Enter 표기가 선다.
     입력이 그대로면 두 번째 Enter 가 적용이다. */
  if (!enter()) return give("이름 변경 폼 없음");
  if (!await waitFor(ctx, () => affected() >= 0, WIRE_TRIES, WIRE_MS)) {
    out.hwpx_authoring_rename_refusal = textOf(
      doc.querySelector(".authoring-refusal")).trim().slice(0, 160);
    return give("이름 변경 미리보기 미도착");
  }
  out.hwpx_authoring_rename_affected = affected();
  out.hwpx_authoring_rename_preview_text = previewText().trim().slice(0, 160);
  const armed = doc.querySelector('.authoring-properties button[type="submit"][aria-keyshortcuts="Enter"]');
  out.hwpx_authoring_rename_enter_armed = !!armed && textOf(armed).trim() === "필드 이름 변경Enter";
  if (!enter()) return give("이름 변경 Enter 확정 불가");
  if (!await pollFor(ctx, async () => countOf(await tab(), candidate.renamed) > 0,
    WIRE_TRIES, WIRE_MS)) return give("이름 변경이 분석에 반영되지 않음");
  const renamed = await tab();
  out.hwpx_authoring_rename_new_count = countOf(renamed, candidate.renamed);
  out.hwpx_authoring_rename_old_count = countOf(renamed, candidate.field);
  out.hwpx_authoring_rename_field_total = fieldsOf(renamed).length;
  named(".authoring-toolbar button", "문서 실행 취소").click();
  if (!await pollFor(ctx, async () => countOf(await tab(), candidate.field) > 0,
    WIRE_TRIES, WIRE_MS)) return give("이름 변경 실행 취소 미반영");
  const restored = await tab();
  out.hwpx_authoring_rename_undo_old_count = countOf(restored, candidate.field);
  out.hwpx_authoring_rename_undo_new_count = countOf(restored, candidate.renamed);

  /* ── ⑦ 표시 방식 전환은 내용도 미저장 상태도 건드리지 않는다(AC23) ───────────── */
  const beforeModes = await tab();
  const contentBeforeModes = await content();
  const modeButton = (value) => doc.querySelector(`.authoring-toolbar .authoring-mode button[value="${value}"]`);
  if (!modeButton("document")) return give("표시 방식 선택이 없음");
  const applied = [];
  for (const value of ["document", "structure", "template"]) {
    modeButton(value).click();
    await settleRender(ctx);
    await ctx.sleep(120);                               // 장식 왕복(iframe) 반영
    applied.push((doc.querySelector('.authoring-toolbar .authoring-mode button[aria-pressed="true"]') || {}).value || "");
  }
  out.hwpx_authoring_modes = applied;
  const afterModes = await tab();
  out.hwpx_authoring_mode_dirty_before = beforeModes.dirty;
  out.hwpx_authoring_mode_dirty_after = afterModes.dirty;
  out.hwpx_authoring_mode_content_stable = (await content()) === contentBeforeModes;

  /* ── ⑦-b §10 키보드만으로 구조 목록의 필드를 고르고 F2 로 이름 칸에 간다(HWPX) ─────
     실 rhwp iframe 이 초점을 가져가도 셸의 F6·F2·Escape 가 선다는 것을 잰다. 좌표 클릭 없음. */
  if (afford(9000)) {
    const kbStart = Date.now();
    const nav = keyboardNav(ctx);
    const nameInput = () => doc.querySelector(".authoring-properties input");
    const prefix = `필드 · ${candidate.field} · 사용 위치 ${candidate.occurrences}곳`;
    out.hwpx_kbd_outline = await nav.cycleTo(".authoring-outline");
    /* 진단(단언하지 않는다): 첫 Tab 한 번의 사건 판정과 탭 순서 안의 위치를 싣는다 — 닿지 못했을 때
       「키가 막혔다」와 「순서에 없다」를 증거에서 가른다. */
    const before = nav.active();
    const order = tabbables(ctx);
    const first = out.hwpx_kbd_outline ? pressKey(ctx, "Tab") : { prevented: null };
    out.hwpx_kbd_first_tab = { prevented: first.prevented, order: order.length,
      at: order.indexOf(before), moved: nav.active() !== before, now: nav.nameOf(nav.active()).slice(0, 60) };
    out.hwpx_kbd_field = out.hwpx_kbd_outline && await nav.treeTo((el) => nav.nameOf(el).indexOf(prefix) === 0, 80);
    out.hwpx_kbd_field_label = nav.nameOf(nav.active());
    if (out.hwpx_kbd_field) {
      pressKey(ctx, "Enter");
      await waitFor(ctx, settled, WIRE_TRIES, WIRE_MS);
      pressKey(ctx, "F2");
      out.hwpx_kbd_f2_focus = await waitFor(ctx, () => !!nameInput() && nav.active() === nameInput()
        && nameInput().value === candidate.field, WIRE_TRIES, WIRE_MS);
      /* Escape 는 두 단계다(§6.2·§10): 작성 중인 값이 적용값과 다르면 먼저 되돌리고, 다음 Escape 가
         패널을 닫는다. rhwp 는 초점 이동 뒤 자기 커서를 300ms 주기로 다시 보고하므로 그 사이 선택
         대상이 바뀌면 첫 Escape 가 「되돌리기」가 될 수 있다 — 단계 수와 그때의 대상을 함께 싣는다. */
      const target = () => textOf(doc.getElementById("authoring-properties-target")).trim();
      const gone = () => !doc.querySelector(".authoring-properties");
      out.hwpx_kbd_escape_target_before = target();
      out.hwpx_kbd_escape_presses = 0;
      for (let press = 0; press < 2 && !gone(); press += 1) {
        pressKey(ctx, "Escape");
        out.hwpx_kbd_escape_presses += 1;
        await waitFor(ctx, gone, 8, 100);
      }
      out.hwpx_kbd_escape_closes = gone();
      /* UX-07 — 편집면 iframe **안**에서 누른 Escape·F6 도 셸에 닿는다. 스튜디오 입력칸은 같은 출처라
         contentDocument 로 닿고, 합성 키도 스튜디오의 키 처리기를 실물로 지난다(셸로 넘기는 것은 그 처리기다). */
      const frame = doc.querySelector(".authoring-document:not([hidden]) .authoring-editor-host iframe");
      const studio = frame && frame.contentDocument;
      const input = studio && studio.querySelector('[aria-label="문서 편집 입력"]');
      out.hwpx_kbd_iframe_input = !!input;
      if (out.hwpx_kbd_escape_closes && input) {
        const pressInside = (key, init) => input.dispatchEvent(new frame.contentWindow.KeyboardEvent("keydown",
          Object.assign({ key, bubbles: true, cancelable: true }, init || {})));
        frame.focus();
        pressKey(ctx, "F2");                                   // 셸이 속성 패널을 다시 연다
        out.hwpx_kbd_iframe_panel_open = await waitFor(ctx, () => !gone(), WIRE_TRIES, WIRE_MS);
        pressInside("Escape");
        out.hwpx_kbd_iframe_escape_closes = await waitFor(ctx, gone, 20, 100);
        frame.focus();
        pressInside("F6");
        await settleRender(ctx);
        out.hwpx_kbd_iframe_f6_to = nav.nameOf(nav.active()).slice(0, 60);
        out.hwpx_kbd_iframe_f6_left = nav.active() !== frame && !nav.within(".authoring-canvas")
          && nav.within(".authoring-toolbar,.authoring-outline,.authoring-properties,.authoring-dock");
      }
    }
    out.hwpx_kbd_ms = Date.now() - kbStart;
  } else {
    out.hwpx_kbd_skipped = "예산 부족";
  }

  /* ── 좁은 창(760×600)·150% 배율에서도 편집면이 서고 가로 스크롤이 없다 ───────── */
  const fits = () => {
    const root = doc.documentElement;
    const face = doc.querySelector(".authoring-canvas");
    return {
      scroll_w: root.scrollWidth, client_w: root.clientWidth,
      canvas_h: face ? face.clientHeight : 0,
      ok: root.scrollWidth <= root.clientWidth && !!face && face.clientHeight > 100,
    };
  };
  if (afford(6000)) {
    ctx.state.hwpxWindowResized = true;
    await ctx.host("window_resize", { width: 760, height: 600 });
    await ctx.sleep(600);                               // OS resize → relayout(grid_narrow 와 같은 값)
    const narrow = fits();
    out.hwpx_authoring_min_window_ok = narrow.ok;
    out.hwpx_authoring_min_window_scroll_w = narrow.scroll_w;
    out.hwpx_authoring_min_window_client_w = narrow.client_w;
    out.hwpx_authoring_min_window_canvas_h = narrow.canvas_h;
    await ctx.host("window_resize", { width: 1440, height: 900 });
    await ctx.sleep(600);
    ctx.state.hwpxWindowResized = false;
    /* 배율은 제품의 개인화 동사로 올린다(설정 모달이 부르는 그 함수) — 150% = `larger`.
       그 동사는 **폭도 함께 다시 쓴다**(`apply` 가 현재 계산값을 읽어 되쓴다). 그래서 그
       값이 아직 서지 않은 대역에서 부르면 하한(180px)이 심어지고, 그 자취는 뒤따르는
       개인화 프로브의 `master_width == 240` 실패로 나타난다 — 서지 않았으면 부르지 않고
       사유를 싣는다(원인이 이 밴드가 아니라 저쪽 프로브로 보이는 경로를 만들지 않는다). */
    const app = doc.querySelector(".app");
    const masterBefore = app
      ? ctx.win.getComputedStyle(app).getPropertyValue("--master-width").trim() : "";
    if (!masterBefore) {
      out.hwpx_authoring_font_scale_skipped = "개인화가 아직 폭을 적용하지 않았습니다";
    } else {
      const real = ctx.win.alert;
      ctx.win.alert = function () {
        out.hwpx_authoring_alerts = (out.hwpx_authoring_alerts || 0) + 1;
      };
      /* 되돌릴 값은 「normal」이 아니라 **이 부팅이 들고 있던 배율**이다 — 배율 영속 검사가
         env 로 large/larger 를 심은 부팅에서 normal 로 되돌리면 그 검사의 재시작 되읽기가
         normal 을 읽는다(게이트 3차에서 실제로 났다). */
      const scaleBefore = doc.documentElement.getAttribute("data-font-scale") || "normal";
      const pxBefore = ctx.win.getComputedStyle(doc.documentElement).fontSize;
      out.hwpx_authoring_font_scale_before = scaleBefore;
      try {
        Personalization.setFontScale("larger");
        await settleRender(ctx);
        await ctx.sleep(200);
        const large = fits();
        out.hwpx_authoring_font_scale = String(
          doc.documentElement.getAttribute("data-font-scale") || "");
        out.hwpx_authoring_font_scale_px = ctx.win.getComputedStyle(doc.documentElement).fontSize;
        out.hwpx_authoring_font_scale_ok = large.ok;
        out.hwpx_authoring_font_scale_scroll_w = large.scroll_w;
        out.hwpx_authoring_font_scale_client_w = large.client_w;
        out.hwpx_authoring_font_scale_canvas_h = large.canvas_h;
      } finally {
        Personalization.setFontScale(scaleBefore);
        await settleRender(ctx);
        ctx.win.alert = real;
      }
      out.hwpx_authoring_font_scale_restored = ctx.win.getComputedStyle(
        doc.documentElement).fontSize === pxBefore;
      out.hwpx_authoring_master_width_stable = ctx.win.getComputedStyle(app)
        .getPropertyValue("--master-width").trim() === masterBefore;
    }
  }

  /* ── ⑧ 한 번도 저장하지 않은 문서의 첫 저장은 **경로를 묻는다**(AC01) ────────── */
  if (!afford(4000)) return give("예산 부족: 저장 판정");
  const asked = { count: 0 };
  const saveStub = stubBridgeInvoke(ctx, "saveAuthoringDocument", "save_authoring_document",
    () => async () => { asked.count += 1; return null; });   // 취소 = 아무 파일도 쓰지 않는다
  try {
    exact(".authoring-head button", "저장").click();
    await pollFor(ctx, async () => asked.count > 0, DOM_TRIES, DOM_MS);
  } finally { saveStub.restore(); }
  out.hwpx_authoring_save_asked_for_path = asked.count === 1;
  const current = await tab();
  const refusal = await Bridge.call("authoring", "save",
    { session_id: sid, revision: current.revision });
  out.hwpx_authoring_save_needs_path = refusal.needs_path === true && refusal.needs_save_as === true;
  out.hwpx_authoring_save_path_after = String((await tab()).save_path || "");

  /* 되돌린 문서가 **디스크의 원본과 같은가** — 제품의 보존 비교기로 확정한다(바이트 비교로는
     rhwp 직렬화 차이와 진짜 손실을 가를 수 없다). 이 자리가 마지막인 이유: 비교 결과가
     `rhwp_editable` 을 다시 쓰므로, 실패하면 문서가 읽기 전용이 된다. */
  const source = await Bridge.call("authoring", "external_content", { session_id: sid });
  const verdict = await Bridge.call("authoring", "rhwp_roundtrip_preflight",
    { session_id: sid, revision: (await tab()).revision, content: source.content });
  out.hwpx_authoring_undone_matches_source = verdict.editable === true;
  out.hwpx_authoring_undone_diagnostics = (verdict.diagnostics || []).slice(0, 6);
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

/** 좌 열 행 하나 — 키 집합은 `webapp/pool_column.POOL_ROW_KEYS` 그대로다.
 *
 *  픽스처가 **열 행을 직접 쓴다**: 옛 밴드(`hwpx`/`txt`)가 퇴역해(슬라이스 ⑤) 유도할 원본이
 *  없고, 유도가 남아 있으면 프로브가 제 손으로 접은 모양을 되읽는 무동작 측정이 된다. */
function tplRow(extra) {
  return Object.assign({
    key: "a.hwpx", name: "a", sub: "필드 3개", reason: "", warns: [],
    badge_label: "누름틀", badge_level: "ok", icon: "hwpx",
    selectable: true, path: "C:/lib/a.hwpx", actions: [],
  }, extra || {});
}

/** `tpl` 채널 스냅샷 — 고르기 단계 좌 열의 **정본**이다(U6-B #976).
 *
 *  종전에는 편집기 스냅샷의 `library` 존이 같은 목록을 한 번 더 실어 왔고 프로브도 거기에
 *  값을 심었다. 그 존이 퇴역했으므로 프로브도 실제 채널로 민다 — 심는 자리와 그리는 자리가
 *  어긋나면 프로브가 자기 값을 못 보고 조용히 0 을 읽는다. 좌 열이 그리는 것은 공용 열 존
 *  (`column`) 하나이고, `rows`(열 행 목록)와 `result` 로 그 존을 세운다. */
function tplBase(overrides) {
  const opts = Object.assign({}, overrides || {});
  const rows = opts.rows || [];
  delete opts.rows;
  const result = opts.result || { text: "", level: "muted" };
  const snapshot = Object.assign({
    templates_root: {
      directory: "C:/lib", source: "settings", source_label: "설정", notice: "",
    },
    detail: null,
    examples: { installed: false, removable: false, remove_label: "", remove_hint: "" },
  }, opts);
  if (snapshot.column === undefined) {
    snapshot.column = {
      rows, notices: [],
      empty_hint: rows.length ? "" : "서식 폴더에 템플릿이 없습니다: C:/lib",
      count_label: `${rows.length}개`, result,
    };
  }
  return snapshot;
}

/** `pool` 채널 스냅샷 — 고르기 단계 우 열의 정본(데이터 선택 다이얼로그와 같은 값).
 *
 *  좌 열과 같다: 우 열이 그리는 것은 공용 열 존(`column`) 하나이고 `rows` 는 그 존의 행
 *  목록(열 계약)이다. 옛 목록 키는 소비자 0 으로 퇴역했다(슬라이스 ⑤). */
function poolBase(rows, extra) {
  const list = rows || [];
  return {
    pclm: { default_db: "C:/d/pclm.db", views: [] },
    /* 항목 상세 존(고르기 열 공용 ④) — 검토 전에는 `null` 이 정상이다. */
    detail: (extra || {}).detail || null,
    column: {
      rows: list, notices: [],
      empty_hint: list.length ? "" : "고정한 데이터가 없습니다.",
      count_label: `${list.length}개`, result: { text: "", level: "muted" },
    },
  };
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

/** 3단계 「이름·저장」 폼의 실물 확인(U6-D #978) — `editor_save_gate` 의 뒷단계.
 *
 *  **새 창을 늘리지 않는다**: 이미 선 편집기 세션 위에 단계를 얹는다(실창 게이트 규율).
 *  재는 것 넷은 전부 정적 계약이 못 보는 것들이다.
 *
 *  ① 이름 입력이 **본문에** 서고 머리에는 없다 — 옮김은 양성·음성을 함께 재야 성립한다.
 *  ② 힌트는 **Python 표지**(`job_name_is_derived`)를 따른다: 표지를 끄면 사라진다.
 *     웹이 「이름이 도출값과 같은가」로 되유추하면 이 음성이 초록으로 뒤집힌다.
 *  ③ 저장 폴더 칸이 값·출처를 받고 「설정에서 바꾸기」가 **실제로** 설정 모달을 연다
 *     (막다른 재진술 금지 — 바꿀 길이 없는 읽기 전용 칸은 그 자체로 결함이다).
 *  ④ 「저장하고 문서 만들기로」가 `save` → `prefer_work` **순서로** 보내고 작업 화면에
 *     착지한다. 순서가 뒤집히면 저장되지 않은 작업을 착석시키려 든다. */
async function measureNameSaveStage(ctx, baseSnap, out) {
  const Nav = service(ctx, "Nav");
  const stage = Object.assign({}, baseSnap, {
    section: "filename", dirty: true,
    name: "공고서 · 대장", job_name_is_derived: true,
    name_hint: "템플릿과 데이터 이름에서 미리 채웠습니다. 고쳐도 됩니다.",
    pattern: "공고서-{{seq:001}}",
    pattern_preview: "공고서-001.hwpx · 002 · 003",
    output_folder: {
      directory: "D:/문서/Results", source: "remembered",
      source_label: "설정한 저장 폴더", notice: "",
    },
  });
  ctx.push("editor", stage);
  await settleRender(ctx);
  out.name_in_body = !!ctx.doc.querySelector("#editor-body #editorName");
  out.name_in_head = !!ctx.doc.querySelector(".editor-head #editorName");
  const nameEl = byId(ctx, "editorName");
  out.derived_name_value = nameEl ? nameEl.value : null;
  out.name_hint_shown = !!byId(ctx, "editorNameHint");
  out.seq_example = textOf(byId(ctx, "editorPatternPreview")).trim();
  const dirEl = byId(ctx, "editorOutDir");
  out.out_dir_value = dirEl ? dirEl.value : null;
  out.out_dir_readonly = !!(dirEl && dirEl.readOnly);
  out.out_dir_source = textOf(byId(ctx, "editorOutDirSource")).trim();
  /* 표지를 끄면 힌트가 사라진다(음성) — 같은 스냅샷의 다른 한 키만 움직인다. */
  ctx.push("editor", Object.assign({}, stage, {
    job_name_is_derived: false, name_hint: "", name: "손으로 지은 이름",
  }));
  await settleRender(ctx);
  out.name_hint_gone_when_edited = !byId(ctx, "editorNameHint");
  ctx.push("editor", stage);
  await settleRender(ctx);
  /* 「설정에서 바꾸기」 — 여는 것만 잰다(모달의 내용·잠금은 설정 면 소관). */
  const gate = byId(ctx, "editorOpenFolderSettings");
  out.folder_settings_trigger = !!gate;
  if (gate) {
    gate.click();
    const opened = () => {
      const modal = byId(ctx, "settingsModal");
      return !!modal && !modal.classList.contains("hidden");
    };
    await ctx.waitFor(opened, { what: "설정 모달 열림", timeoutMs: 1500 });
    out.folder_settings_opens = opened();
    service(ctx, "Modal").close("settingsModal");
    settleModal(ctx, "settingsModal");
    await settleRender(ctx);
    const modal = byId(ctx, "settingsModal");
    out.settings_closed_after = !!modal && modal.classList.contains("hidden");
  }
  /* 「저장하고 문서 만들기로」 — 발신 순서와 착지. 나머지 발신은 삼킨다: 실 백엔드가
     응답하면 합성 스냅샷을 덮어 프로브가 자기가 심은 것을 못 본다. */
  const calls = [];
  const stub = stubBridgeCall(ctx, () => function (screen, action) {
    calls.push(`${screen}/${action}`);
    if (screen === "editor" && action === "save") return Promise.resolve({ ok: true });
    if (screen === "job" && action === "prefer_work") {
      return Promise.resolve({ ok: true, reason: "ready" });
    }
    return Promise.resolve({});
  });
  try {
    const openBtn = ctx.doc.querySelector('#editor-foot [data-act="save-and-open"]');
    out.save_and_open_present = !!openBtn;
    if (openBtn) {
      out.save_and_open_enabled = !openBtn.disabled;
      openBtn.click();
      await ctx.waitFor(
        () => calls.indexOf("job/prefer_work") >= 0,
        { what: "저장 뒤 prefer_work 발신", timeoutMs: 2000 },
      );
      out.save_and_open_calls = calls.join(",");
      out.save_before_prefer =
        calls.indexOf("editor/save") >= 0
        && calls.indexOf("editor/save") < calls.indexOf("job/prefer_work");
      await ctx.waitFor(
        () => byId(ctx, "scr-job").classList.contains("on"),
        { what: "문서 만들기 착지", timeoutMs: 2000 },
      );
      out.landed_on_job = byId(ctx, "scr-job").classList.contains("on");
    }
  } finally {
    stub.restore();
  }
  Nav.go("editor", { force: true });   // 뒤 프로브의 전제(편집기 활성)를 되돌려 놓는다
  ctx.push("editor", baseSnap);
  await settleRender(ctx);
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
        /* 축 컨트롤은 `<select>` 가 아니라 표 머리의 스위치다(U4 7번). 값 설정형 조작이
           사라졌으므로 **사용자가 하는 그대로** 누르고, 상태는 `aria-pressed` 로 읽는다.
           2값 고정(F3)은 컨트롤이 `data-order-values` 로 선언한다. */
        const toggle = byId(ctx, "jobOrderToggle");
        out.present = !!toggle;
        if (!toggle) { out.pending = false; return { view_order: out }; }
        out.options = String(toggle.getAttribute("data-order-values") || "")
          .split(",").filter(Boolean);
        const axis = () => (toggle.getAttribute("aria-pressed") === "true"
          ? "sourceAsc" : "sourceDesc");
        const label = () => toggle.textContent.trim();
        try {
          const snap = await Bridge.initial("job");
          out.control_before = axis() === snap.view_order && axis() === "sourceDesc";
          out.label_before = label();
          toggle.click();
          await ctx.sleep(400);                       // 왕복 + push 재렌더 여유(app.py:2685)
          out.after_roundtrip = axis();               // 되돌아왔으면 'sourceDesc'
          out.label_after_roundtrip = label();
          await Bridge.call("job", "set_view_order", { value: "sourceDesc" });
          await ctx.sleep(200);
          out.restored = axis();
          out.label_restored = label();
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
        const ids = ["jobRecsHead", "jobFilterChips", "jobTableHost",
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
          view_order: "sourceDesc",
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
            /* 트리거는 표 머리로 왔고(U4 10번) 면이 열리는 동안 인라인과 **함께 언마운트**된다
               — 그래서 초점 복귀는 캡처해 둔 노드가 아니라 **지금 살아 있는 같은 단추**로
               재야 한다. 옛 노드로 재면 「복귀가 깨졌다」가 아니라 「노드가 바뀌었다」를 재게
               되고, 그것은 이 프로브가 지키려던 사실이 아니다. */
            const back = byId(ctx, "jobDataExpand");
            const focused = done && !!back && ctx.doc.activeElement === back;
            if (focused || tries++ > 40) {
              out.restored = focused;
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

    {
      name: "editor_tab_autodiscard",
      keys: ["editor_tab_autodiscard"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3794,
      deadlineMs: 2500,
      deadlineRationale: "공용 `_probe_late` 예산 2.5초(app.py:3494-3506) 그대로.",
      completionField: "pending",
      after: ["range_draft"],
      afterReason:
        "편집기는 셸을 덮는 화면이라 앞 프로브가 「작업」 화면에서 재는 일을 끝낸 뒤에"
        + " 열어야 한다(구 선행자 preview_drawer 는 #957 에서 퇴역했다).",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = { pending: true, calls: [], payload_keys: [] };
        ctx.state.out = out;

        const stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
          if (screen !== "editor") return real(screen, action, payload);
          out.calls.push(action);
          if (action === "goto_section") {
            out.payload_keys = Object.keys(payload || {}).sort();
            out.target_sent = String((payload || {}).section || "");
          }
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
            sample_rows: [], provenance: null,
          }));
          await settleRender(ctx);
          const tab = ctx.doc.querySelector('#editor-steps button[data-section="filename"]');
          if (!tab) {
            out.why = "탭 버튼 없음";
            out.pending = false;
            return { editor_tab_autodiscard: out };
          }
          tab.click();
          /* 정산 + 발신 왕복 + 모달이 뜬다면 뜨고도 남을 시간. 짧게 재고 「안 떴다」고 말하면
             그 음성 대조는 타이밍이 만든 것이지 계약이 만든 것이 아니다. */
          await ctx.sleep(400);
          const chooseRoot = byId(ctx, "chooseModal");
          out.choose_modal_open = chooseRoot !== null && !chooseRoot.classList.contains("hidden");
          const confirmRoot = byId(ctx, "confirmModal");
          out.confirm_modal_open = confirmRoot !== null
            && !confirmRoot.classList.contains("hidden");
          out.why = "완료";
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, `throw:${thrown && thrown.message}`);
        } finally {
          stub.restore();
        }
        out.pending = false;
        return { editor_tab_autodiscard: out };
      },
      teardown(ctx) {
        if (ctx.state.stub) ctx.state.stub.restore();
        restoreShell(ctx, ctx.state.out || {});
      },
    },

    /* ── editor_discard_immediate (구 editor_discard_cancel 슬롯) ─────────────
       「변경 버리기」의 **즉시 실행**. 확인이 사라졌으므로 이 자리가 재는 것은 취소 뒤 정합이
       아니라 ①확인 모달이 서지 않는다 ②그럼에도 **정산이 먼저**다(U2 §2.17 2R P2 의 순서
       계약은 확인과 무관하게 산다 — blur 가 큐에 넣은 `set_name` 이 버리기 뒤에 도착하면
       방금 되돌린 세션이 그 늦은 편집으로 다시 더러워진다) ③되돌린 스냅샷이 도착하면 이름이
       저장본으로 돌아가고 두 버튼이 함께 잠긴다. */
    {
      name: "editor_discard_immediate",
      keys: ["editor_discard_immediate"],
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
      after: ["editor_tab_autodiscard"],
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
          rows: [], source_fields: [], sample_rows: [], provenance: null,
          default_dataset: null, dataset_name: "", schema_only: true,
          counts: { filled: 0, empty: 0, unmapped: 0 }, preview_empties: [],
          preview_index: 0, preview_count: 0, is_complete: true,
        });
        const dirty = Object.assign({}, clean, {
          dirty: true, dirty_sections: ["template"], name: "공고서 수정",
        });
        const discardOf = () => ctx.doc.querySelector('#editor-foot [data-act="discard-patch"]');

        const stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
          if (screen !== "editor") return real(screen, action, payload);
          out.calls.push(action);
          if (action === "set_name") {
            /* 큐에 든 blur 발신이 **늦게** 도착하는 실제 조건을 그대로 만든다: 응답 전 지연 +
               도착 시 dirty 스냅샷 push(= `#editor-foot` 재구성). */
            return ctx.sleep(120).then(() => { ctx.push("editor", dirty); return {}; });
          }
          if (action === "discard_patch") {
            /* 컨트롤러가 되돌린 뒤 밀어 주는 것을 그대로 흉내낸다 — 확인이 없으니 이 push 가
               사용자가 보는 **유일한** 결과다. */
            ctx.push("editor", clean);
            return Promise.resolve({});
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
            return { editor_discard_immediate: out };
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
            if (out.calls.indexOf("discard_patch") !== -1) {
              await ctx.sleep(300);                 // 되돌린 스냅샷 push 의 재렌더 정착
              /* ③ 확인은 어디에도 서지 않는다(음성) — 열렸다면 클릭 없이는 닫히지 않으므로
                    지금 보이는 것으로 충분하다. */
              const confirmRoot = byId(ctx, "confirmModal");
              out.confirm_modal_open = confirmRoot !== null
                && !confirmRoot.classList.contains("hidden");
              out.call_order = out.calls.join(",");
              out.flushed_before_discard = out.calls.indexOf("set_name") === 0;
              /* ④ 되돌린 뒤 정합: 이름이 저장본으로 돌아오고 두 버튼이 함께 잠긴다. */
              const nm = byId(ctx, "editorName");
              out.name_value_after_discard = nm ? nm.value : null;
              const save = ctx.doc.querySelector('#editor-foot [data-act="save"]');
              out.discard_disabled_after = !!(discardOf() && discardOf().disabled);
              out.save_disabled_after = !!(save && save.disabled);
              out.discarded = true;
              out.why = "완료";
              break;
            }
            if (ticks > 60) { out.why = "버리기 미발신"; break; }
          }
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, `throw:${thrown && thrown.message}`);
        } finally {
          stub.restore();
        }
        out.pending = false;
        return { editor_discard_immediate: out };
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
      deadlineMs: 28000,
      deadlineRationale:
        "공용 `_probe_late` 예산 2.5초에 **린트메모장 단계**가 얹혔다(S10-05 #862): 창 열기 +"
        + " 디바운스 180ms + `authoring` 분석 실왕복 + 이탈 확인 왕복이 한 프로브 안에서 돈다."
        + " 늘린 것은 매달림을 유한 시간에 빨강으로 만드는 상한이지 통과 조건이 아니다 —"
        + " 실측 여유(내부 대기 상한 2×1.2초)를 담되 무한정은 아니게 잡는다."
        + " 여기에 **HWPX 저작 밴드**가 얹힌다: vendor rhwp iframe 마운트 + 실 문서 적재 +"
        + " 왕복 보존 검사(내보내기 → 파이썬 c14n 비교) + 필드 만들기·되돌리기·다시 실행·"
        + " 이름 변경·표시 전환·저장 판정이 한 세션 안에서 돈다. 후보 문서가 보존 검사를"
        + " 통과하지 못하면 다음 후보로 한 번 더 마운트하므로 그 몫도 든다. 밴드는 `ctx"
        + ".remainingMs()` 로 국면마다 예산을 보고 모자라면 사유를 싣고 멈춘다 — 상한이 무는"
        + " 것은 매달림뿐이고, 엔진 총예산(80초)을 지키려면 이 상한이 유계여야 한다.",
      completionField: "pending",
      requiresHost: ["window_resize"],
      after: ["editor_discard_immediate"],
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
            source_fields: [], sample_rows: [], provenance: null,
            pairing: {
              ready: false, template_name: "", data_name: "",
              field_count: 0, column_count: 0, auto_count: 0, confirm_count: 0,
              basis: "", advance_block_reason: "왼쪽에서 템플릿을 고르세요.",
            },
          });
          /* 좌 열의 정본은 **`tpl` 채널**이다(U6-B #976) — 매체는 구획이 아니라 pill 로
             갈린다. hwpx·txt 가 한 목록에 서는지, TXT 항목이 실제로 고를 수 있는지를 잰다. */
          const txtTpl = tplBase({
            rows: [tplRow({
              key: "기안.txt", name: "기안", path: "C:/t/기안.txt",
              badge_label: "TXT", badge_level: "muted", icon: "txt",
            })],
          });
          ctx.push("pool", poolBase([]));
          ctx.push("editor", base);
          ctx.push("tpl", txtTpl);
          /* 고르기 존의 **첫 마운트**는 세 store(editor·tpl·pool)를 한꺼번에 구독하므로
             커밋이 한 turn 에 끝나지 않는다 — 한 turn 만 재면 목록이 아직 없는 순간을 읽고
             「배선이 죽었다」로 착지한다(실측). `ctx.waitFor` 는 **무엇을 기다리다 죽었는지**
             를 남긴다(러너의 `waitState`) — 이름 없는 매달림은 정보가 0 이다. */
          await ctx.waitFor(
            () => ctx.doc.querySelectorAll("#editorTplList .pitem").length > 0,
            { what: "좌 열 템플릿 항목 렌더", timeoutMs: 2000 },
          );
          /* 매체 구획(`HWPX 서식`·`TXT 기안` 캡션)은 U6-B 에서 사라졌다 — **음성 단언**으로
             남긴다(되살아나면 두 열 그림이 다시 갈린다). */
          const caps = Array.prototype.map.call(
            ctx.doc.querySelectorAll("#editor-body .grp .cap"), (el) => el.textContent);
          out.bands = caps.filter((t) => t === "HWPX 서식" || t === "TXT 기안");
          const txtItem = ctx.doc.querySelector(
            '#editorTplList .pitem[data-side="tpl"][data-path="C:/t/기안.txt"]');
          out.txt_pick = !!txtItem;
          out.txt_media_pill = txtItem
            ? (txtItem.querySelector(".pill") || {}).textContent : "";
          await probeLintpad(ctx, out);
          /* TXT 도 3단계다(U6-D #978) — 갈리는 것은 3단계 **안의 문서 파일 이름 행**이다.
             그래서 탭 수만 세면 그 사실이 안 드러난다: 그 단계에 실제로 세워 패턴 입력이
             **없다**는 것을 함께 잰다(양성 없는 음성은 배선이 죽어도 초록이다). */
          const txtSnap = Object.assign({}, base, {
            sections: ["template", "binding", "filename"], template_path: "C:/t/기안.txt",
            template_name: "기안", template_media: "txt",
          });
          ctx.push("editor", txtSnap);
          await settleRender(ctx);
          out.txt_tabs = ctx.doc.querySelectorAll("#editor-steps .wstep-tab").length;
          out.txt_step3_label = textOf(
            ctx.doc.querySelectorAll("#editor-steps .wstep-tab")[2]).trim();
          /* TXT 는 파일을 만들지 않아 **저장 폴더가 축이 아니다**(U6-D #978 리뷰 4) —
             Python 이 존을 `null` 로 내고 표면은 그 행을 세우지 않는다. 합성값도 그대로 `null`
             이어야 프로브가 재는 것이 제품의 계약이 된다(빈 사전을 밀면 없는 상태를 재게 된다). */
          ctx.push("editor", Object.assign({}, txtSnap, {
            section: "filename", name: "기안 · 대장", job_name_is_derived: false,
            name_hint: "", pattern_preview: "", output_folder: null,
          }));
          await settleRender(ctx);
          out.txt_name_input = !!ctx.doc.querySelector("#editor-body #editorName");
          out.txt_pattern_input = !!ctx.doc.querySelector(
            '#editor-body input[data-act="pattern"]');
          out.txt_out_dir_row = !!byId(ctx, "editorOutFolderRow");
          /* HWPX **저작** 밴드는 TXT 밴드 뒤에 선다(같은 부팅·같은 프로브): 실창 게이트는
             창을 늘리지 않고 이미 선 세션에 단계를 얹는다. 합성 tpl 스냅샷을 밀어 둔 뒤라도
             무해하다 — 이 밴드는 DOM 목록이 아니라 실 `tpl` 채널의 스냅샷에서 경로를
             회수한다. 예외는 `hwpx_authoring_error` 에만 실려 TXT 단언 열둘을 끌고 죽지
             않는다(원인 하나가 실패 열셋으로 번지는 것이 #429 의 그 결함류다). */
          await probeHwpxAuthoring(ctx, out);
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
          source_fields: ["수신", "사업명"],
          fmt_options: { text: [{ code: "plain", label: "그대로" }] },
          type_options: [{ code: "text", label: "텍스트" }],
          rows: [
            {
              name: "수신", state: "fill", source: "수신", own: "auto", manual: false,
              value: "회계과", fmt_kind: "text", fmt_code: "plain", suggest: "",
              can_revert: false, confirmed: true, blank_declared: false,
              auto_confirmation_label: "자동확정 · 이름 일치",
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
          out.owner_source_same_line = (() => {
            const pair = ctx.doc.querySelector("#wbMapPanel .mapsrc-primary");
            const dot = pair?.querySelector(".own");
            const select = pair?.querySelector("select");
            return !!dot && !!select
              && Math.abs(dot.getBoundingClientRect().top + dot.getBoundingClientRect().height / 2
                - (select.getBoundingClientRect().top + select.getBoundingClientRect().height / 2)) <= 2;
          })();
          out.exact_badge = textOf(ctx.doc.querySelector("#wbMapPanel .map-auto-exact")).trim();
          out.exact_checked = !!ctx.doc.querySelector('#wbMapPanel [data-name="수신"].mapck:checked');
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
          /* 머리 — 정체(제목)와 저장 상태. 상태는 **상태만** 말한다(#945 F5): 저장 세대
             카운터는 내부 어휘라 머리에서 걷혔고, 손댄 갈래(위 dirty_head)와 여기 두 값으로
             양성·음성을 각각 잰다. */
          draft.name = "공고서";
          draft.dirty_sections = [];
          draft.dirty = false;
          ctx.push("editor", draft);
          await settleRender(ctx);
          /* 머리는 **읽기 전용**이다(U6-D #978) — 이름 입력이 3단계 폼으로 갔다. 옮겼다는
             사실은 양성(제목이 이름을 말한다)과 음성(머리에 입력이 없다)을 함께 재야
             성립한다: 한쪽만 재면 두 자리에 입력이 서 있어도 초록이다. */
          out.head_title = textOf(byId(ctx, "editorTitle")).trim();
          out.name_input_in_head = !!ctx.doc.querySelector(".editor-head #editorName");
          out.save_state = textOf(byId(ctx, "editorSaveState"));
          /* 진입 문맥 배너 — **증거**가 있으면 서고 없으면 침묵한다(사유 문장·복귀 버튼은
             2026-09-03 재판정으로 걷혔다 — 복귀는 `#editorBack` 하나). */
          out.ctx_hidden_when_voluntary = isHidden(ctx, byId(ctx, "editorContext"));
          draft.context = {
            entry_reason: "run_failure", evidence: { "실패한 행": "4 / 12" },
            return_context: { surface: "result" },
          };
          ctx.push("editor", draft);
          await settleRender(ctx);
          out.ctx_shown = !isHidden(ctx, byId(ctx, "editorContext"));
          out.ctx_text = textOf(byId(ctx, "editorContext"));
          out.ctx_return_btn = !!ctx.doc.querySelector('#editorContext [data-act="context-return"]');
          out.back_btn = !!ctx.doc.querySelector("#editorBack");
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
            /* 「지금 쓰는 데이터」는 **작업 스냅샷이 낸 행**이다(③b) — 종전의 카드 값
               (`current`)이 아니라 `pool_row_view` 와 같은 키 집합의 행 하나다. 실 백엔드는
               이 창에서 데이터를 마운트하지 않으므로 그 행을 여기서 합성해 넘긴다. */
            DataPicker.open({
              screen: "job",
              session: () => ({
                data_row: {
                  key: "session", name: "대장.xlsx", sub: "시트: 물품 · 3행", reason: "",
                  warns: [], badge_label: "사용 중", badge_level: "ok", icon: "excel",
                  selectable: true, path: "C:/d/대장.xlsx", actions: [],
                },
                data_pool_key: "",
                sheet: "물품",
              }),
            });
          } finally {
            refreshStub.restore();
          }
          /* controller 외부 스토어는 같은 호출 스택에서 갱신되지만 concurrent React root의
             portal DOM 커밋은 다음 turn일 수 있다. 세션 행·고정 버튼을 읽기 전에
             고정 지연 없이 한 turn만 넘긴다. */
          await ctx.sleep(0);
          out.opened = !byId(ctx, "dataPickerModal").classList.contains("hidden");
          out.pin_offered = !!byId(ctx, "dataPickerPin");
          // 「＋ 직접 등록…」 사망(U2 §2.7 4행) — DOM 자체가 없어야 한다.
          out.register_gone = !byId(ctx, "dataPickerRegister");
          /* 「쓸 수 있는가」와 그 사유는 U6-B(#976)에서 **스냅샷 축**이 됐다 — 종전에는
             이 면의 웹 함수가 `status`·`missing` 으로 문장을 다시 지었고, 그래서 같은 상태가
             편집기 축약 목록과 다른 어휘를 가졌다. 대역도 실 백엔드와 같은 모양을 낸다:
             행 하나가 드는 키는 `webapp/pool_column.POOL_ROW_KEYS` 전부이고 그 이상이 없다. */
          const row = (key, name, status, badge, level, actions) => ({
            key, name, sub: `C:/d/${name}.xlsx (물품)`,
            reason: status === "active"
              ? "" : "보관한 항목입니다. '활성화' 뒤에 쓸 수 있습니다.",
            warns: [], badge_label: badge, badge_level: level, icon: "excel",
            selectable: status === "active", path: `C:/d/${name}.xlsx`,
            actions: [...actions, { key: "relink", label: "다시 연결…" }],
          });
          /* 계약 목록(pclm) 행 — 좌표가 DB+뷰라 「다시 연결」(엑셀 전용 동사)이 서지 않고,
             파일이 살아 있으면 그냥 쓸 수 있다(#937). */
          const pclmRow = {
            key: "k3", name: "계약 목록", sub: "DB: pclm.db · 시트 통합", reason: "",
            warns: [], badge_label: "활성", badge_level: "ok", icon: "pclm",
            selectable: true, path: "C:/d/pclm.db",
            actions: [{ key: "archive", label: "보관" }, { key: "delete", label: "삭제" }],
          };
          ctx.push("pool", {
            /* 목록이 읽는 것은 이 존 하나다(고르기 열 공용) — 통지(손상 격리·중복 등록)도
               여기 실린다. 옛 목록 키(`rows`·`count`·`empty`·`corrupted`·`duplicates`·
               최상위 `result`)는 소비자 0 으로 퇴역했다(슬라이스 ⑤). */
            column: {
              rows: [
                row("k1", "7월 공고목록", "active", "활성", "ok",
                  [{ key: "archive", label: "보관" }, { key: "delete", label: "삭제" }]),
                row("k2", "6월 보관분", "archived", "보관", "muted",
                  [{ key: "activate", label: "활성화" }, { key: "delete", label: "삭제" }]),
                pclmRow,
              ],
              notices: [
                {
                  level: "danger",
                  text: "⚠ 손상된 등록 데이터: broken.dataset.json — JSON 을 읽을 수 없습니다",
                  actions: [],
                },
                {
                  level: "warn",
                  text: "같은 데이터(파일: 대장.xlsx · 시트 물품)를 가리키는 등록이 2건입니다."
                    + " 남길 등록을 골라 정리하세요.",
                  actions: [
                    { key: "resolve_duplicate", label: "'7월 공고목록' 남기기", payload: { keep: "k1" } },
                    { key: "resolve_duplicate", label: "'6월 보관분' 남기기", payload: { keep: "k2" } },
                  ],
                },
              ],
              empty_hint: "", count_label: "3개", result: { text: "", level: "muted" },
            },
            /* 등록 폼이 물어야 할 좌표 — 실 백엔드 `_pclm_block` 과 같은 모양. `views` 는
               새로 고르게 할 것이다(품목 제외 3건). 뷰 전수 제목표(`titles`)는 소비자 0 으로
               퇴역했다 — 이미 선 마운트의 제목화는 Python 이 세션 행 부제에서 끝낸다. */
            pclm: {
              default_db: "C:/AppData/Local/Pclm/pclm.db",
              views: [
                { name: "v_통합_v1", title: "통합", desc: "공고와 계약을 이어 붙인 표" },
                { name: "v_공고_v1", title: "공고", desc: "공고 정보" },
                { name: "v_계약_v1", title: "계약", desc: "계약 정보" },
              ],
            },
            detail: null,
          });
          await ctx.sleep(0);                      // pool external-store → portal DOM 커밋
          const host = byId(ctx, "dataPickerPinned");
          /* 목록은 공용 고르기 열이다(③b) — 카드가 아니라 `.pitem` 행이고, 「지금 쓰는
             데이터」의 세션 행이 맨 위에 함께 선다(3 + 1). */
          out.rows = host.querySelectorAll(".pitem").length;
          out.session_row = textOf(host.querySelector('.pitem[data-key="session"]'));
          const pitem = (key) => host.querySelector(`.pitem[data-key="${key}"]`);
          /* 「고를 수 있는가」는 행 자체가 말한다 — 보관 항목은 숨기지 않고 `aria-disabled`
             이고 `disabled` 가 아니다(눌리지 않으면 사유를 말할 자리가 없다). */
          out.use_active_enabled = !!pitem("k1") && !pitem("k1").hasAttribute("aria-disabled");
          out.use_archived_disabled = !!pitem("k2")
            && pitem("k2").getAttribute("aria-disabled") === "true"
            && !pitem("k2").disabled;
          /* 상태 동사는 행 안 버튼이 아니라 ⋯ 메뉴가 든다(고르기 열과 같은 어포던스).
             실클릭으로 열어 그 목록을 되읽는다 — 목록을 짓는 자리와 여는 자리가 갈리면
             메뉴에 항목을 더하고 배선을 잊은 날이 조용히 지나간다. */
          const rowMenu = async (key) => {
            host.querySelector(`.job-more[data-key="${key}"]`).click();
            await ctx.sleep(0);
            const menu = ctx.doc.getElementById("dataPickerRowMenu");
            const labels = menu
              ? Array.prototype.map.call(menu.querySelectorAll("button"), (b) => textOf(b))
              : [];
            host.querySelector(`.job-more[data-key="${key}"]`).click();  // 같은 트리거 = 닫기
            await ctx.sleep(0);
            return labels;
          };
          const k1Menu = await rowMenu("k1");
          const k2Menu = await rowMenu("k2");
          out.activate_reachable = k2Menu.indexOf("활성화") >= 0;
          out.relink_reachable = k1Menu.indexOf("다시 연결…") >= 0;
          out.reveal_reachable = k1Menu.indexOf("폴더에서 보기") >= 0;
          /* 계약 목록 행(#937) — 종류가 달라도 목록에서 그냥 쓸 수 있고, 엑셀 전용 동사인
             「다시 연결」(경로+시트 좌표)은 그 행에 서지 않는다. */
          const k3Menu = await rowMenu("k3");
          out.pclm_row_usable = !!pitem("k3") && !pitem("k3").hasAttribute("aria-disabled");
          out.pclm_no_relink = k3Menu.join("|").indexOf("다시 연결") < 0;
          /* 행이 슬롯 키를 겨눈다(§5.3 — 이름은 라벨). 키 없는 행은 남의 항목을 겨눈다. */
          out.use_targets_key = host.querySelectorAll(".pitem")[1].dataset.key === "k1";
          /* 손상 격리·중복 등록은 목록 **안**의 존 통지다(문안·수치는 Python). 병합 대상은
             숨김·자동 정리 금지 — 통지와 그 확정 버튼이 같은 자리에 선다. */
          const danger = host.querySelector('[data-notice="danger"]');
          out.corrupt_shown = !!danger && textOf(danger).indexOf("손상") >= 0;
          const dupes = host.querySelector('[data-notice="warn"]');
          out.dupes_shown = !!dupes && textOf(dupes).indexOf("같은 데이터") >= 0
            && dupes.querySelectorAll('[data-notice-act="resolve_duplicate"]').length === 2;
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
          /* 계약 목록 등록 진입 — 파일 피커가 없는 종류라 전용 동사가 「다른 데이터」에 선다.
             가시성까지 단언한다(click 은 hidden 도 통과). 열린 폼은 pclm 모드로 기본 DB
             자리를 프리필하고 **고르게 할 시트 + 빈 placeholder** 를 세운다(시트는 사용자
             확정). 라벨에 저쪽 프로그램 이름이 서지 않는 것도 같이 되읽는다. */
          const pclmEntry = byId(ctx, "dataPickerPclm");
          out.pclm_entry = !!pclmEntry && !isHidden(ctx, pclmEntry)
            && pclmEntry.offsetParent !== null && !pclmEntry.disabled;
          out.pclm_entry_text = textOf(pclmEntry);
          pclmEntry.click();
          await ctx.sleep(0);                      // regModel → 등록 portal DOM 커밋
          const viewSelect = byId(ctx, "poolRegView");
          out.pclm_reg_view_options = viewSelect.options.length;
          out.pclm_reg_db_prefill = byId(ctx, "poolRegDb").value;
          /* 옵션의 **값**은 백엔드 계약(실 뷰 이름)이고 **보이는 글자**는 제목이다. 둘을
             따로 회수해 표면에 내부 이름이 새지 않는 것을 게이트가 잰다. */
          out.pclm_reg_view_values = Array.prototype.map.call(
            viewSelect.options, (o) => o.value).join("|");
          out.pclm_reg_view_text = Array.prototype.map.call(
            viewSelect.options, (o) => textOf(o)).join("|");
          out.pclm_reg_view_label = textOf(viewSelect.closest(".ctl").querySelector(".lbl"));
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
          /* 이번 적재의 증언은 **면 안 문안** 하나다(③b). 세션 행은 이제 작업 스냅샷이 낸
             `data_row` 이고 이 창에서는 브리지가 스텁이라 그 push 가 없다 — 여기서 행이
             바뀌기를 재면 프로브가 제 손으로 세운 값을 되읽는 hollow measurement 가 된다.
             행이 실제 마운트를 따라가는지는 Python 계약(`tests/test_webapp_job.py`)이 진다. */
          out.browse_restated = textOf(byId(ctx, "dataPickerNote")).indexOf("새목록.xlsx") >= 0;
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

    /* ── editor_binding (구 editor_chip · app.py:2221 상수 · 3959 호출) ────────
       2단계 「연결 확인」 표(U6-C #977 · 동결 시안 장면 2). 합성 매핑 스냅샷을 실 render()
       에 흘려 되읽는다: (a) 4열이 서는가, (b) 머리 pill 셋이 Python 수치를 그대로 말하는가,
       (c) 「제안 n건 모두 확인」이 **제안만** 승격하는가(양성·음성 한 쌍), (d) 특수 항목이
       `set_display` 로 갈리고 `set_source` 에는 센티넬이 가지 않는가, (e) 배지
       클릭이 행별 확인을 내는가, (f) 스테퍼가 왕복하는가, (g) 데이터 열 칸 높이가 행마다
       같은가(실렌더 기하 — 구 프로브의 단언 승계). */
    {
      name: "editor_binding",
      keys: ["editor_binding"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3959,
      deadlineMs: 2500,
      deadlineRationale:
        "공용 `_probe_late` 예산 2.5초 그대로. 종전 `editor_chip` 은 동기 evaluate_js 한 번"
        + " 이라 `deadlineMs: 0` 이었지만 이 프로브는 클릭·발신·재렌더를 **기다린다** —"
        + " 감시견 없는 대기는 매달림을 이름 없는 `run_hung` 으로 만든다(U6-B 교훈).",
      after: ["data_picker"],
      afterReason:
        "app.py:3957 의 0.4초 정산이 이 둘 **사이**에 있다 — data_picker 가 닫은 모달의"
        + " 백드롭이 아직 살아 있으면 이 프로브의 첫 클릭이 삼켜진다. 순서를 잃으면 그 대기가"
        + " 아무 데도 걸리지 않는 시간이 된다(cooldownAfterMs 는 data_picker 가 진다).",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = {};
        let stub = null;
        /* `window.alert` 감시는 **러너 공용 층**이 진다(리뷰 10) — 프로브별 방어는 자기
           계약만 지키고 남의 합성 스냅샷이 부른 던짐은 못 막는다. */
        try {
          /* 발신을 가로채 **무엇이 나갔는지**를 센다. 백엔드 왕복을 실제로 태우면 합성
             스냅샷이 실 컨트롤러 상태와 어긋나 이후 단계가 남의 세계를 잰다. */
          const calls = [];
          stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
            if (screen === "editor") {
              calls.push(action + ":" + JSON.stringify(payload || {}));
              return Promise.resolve({});
            }
            return real.call(this, screen, action, payload);
          });
          const COLUMNS = ["품명", "세부품명", "수량", "비고"];
          /* 표시형 select 가 든 **유형 축**(리뷰 1) — 그룹 라벨·항목 값은 Python 이 낸다. */
          const DISPLAY_GROUPS = [
            { label: "텍스트", options: [
              { value: "text:", label: "원문", type: "text", fmt: "" },
              { value: "text:phone", label: "전화", type: "text", fmt: "phone" }] },
            { label: "날짜", options: [
              { value: "date:", label: "표준", type: "date", fmt: "" }] },
            { label: "금액", options: [
              { value: "amount:", label: "원", type: "amount", fmt: "" }] },
          ];
          const OPTIONS = [{ value: "", label: "열을 고르세요", kind: "none", field: "" }]
            .concat(COLUMNS.map((name) => (
              { value: "col:" + name, label: name, kind: "column", field: name })))
            .concat([
              { value: "sp:const", label: "고정값…", kind: "const", field: "" },
              { value: "sp:today", label: "오늘 날짜", kind: "today", field: "" },
            ]);
          /* 행 4개 = 상태 4태 전수. `state_label`·`confirmable`·`preview_kind` 는 전부
             Python 이 낸 값이고 프로브는 그것이 화면에 그대로 서는지만 본다. */
          /* `confirmable`·`revertable` 은 **실 생산자와 같은 규칙**으로 짓는다(리뷰 4·9):
             합성값이 규칙을 따로 지으면 프로브가 제품이 낼 리 없는 세계를 재게 된다. */
          const row = (index, field, state, over) => {
            const confirmed = state === "confirmed";
            const touched = state === "edited";
            const hasContent = state !== "needs_source";
            return Object.assign({
              index, template_field: field, inferred_type: "text", context: "",
              source: "", type: "text", const: "", fmt: "",
              display_options: DISPLAY_GROUPS, display_value: "text:",
              confirmed, touched,
              has_content: hasContent,
              confirmable: hasContent || confirmed,
              revertable: touched && !confirmed,
              suggestion_score: 0, preview: "값", preview_kind: "value",
              preview_empty: false, preview_error: false,
              row_state: state,
              state_label: { suggested: "제안", edited: "확인 필요", confirmed: "확인",
                needs_source: "확인 필요" }[state],
              source_kind: state === "needs_source" ? "" : "column",
              source_value: state === "needs_source" ? "" : "col:품명",
              source_missing_label: "",
            }, over || {});
          };
          const rows = [
            row(0, "품명", "suggested", { source: "품명", source_value: "col:품명" }),
            row(1, "수량", "suggested", { source: "수량", source_value: "col:수량" }),
            row(2, "규격", "edited", { source: "비고", source_value: "col:비고" }),
            row(3, "담당자", "needs_source", {
              preview: "", preview_kind: "none", source_kind: "", source_value: "",
            }),
          ];
          const snap = editorBase({
            section: "binding", notice: null,
            reachable: { template: true, binding: false, filename: false },
            is_draft: false, dirty: false, changes: {}, revisions: {},
            template_path: "C:/t/공고서.hwpx", template_name: "공고서.hwpx", field_count: 4,
            fields: [], raw_block: "", gate: null, gate_error: false,
            data_path: "C:/d/대장.xlsx", data_name: "대장.xlsx", data_sheet: "물품",
            record_count: 3,
            source_fields: COLUMNS,
            data_column_options: OPTIONS,
            sample_rows: [["A", "a", "3", "-"], ["B", "b", "6", "x"], ["C", "c", "1", "-"]],
            name: "", pattern: "x", editing_origin: "",
            provenance: null,
            rows,
            binding_head: {
              suggested: 2, needs_confirm: 2, const: 0,
              promote_label: "제안 2건 모두 확인", promoted_label: "제안을 모두 확인했습니다",
              unused_columns: 1,
            },
            counts: { filled: 3, empty: 0, unmapped: 1 }, preview_empties: [],
            preview_index: 1, preview_count: 3,
            is_complete: false, schema_only: false,
          });
          Nav.go("editor", { force: true });
          ctx.push("editor", snap);
          await settleRender(ctx);
          const root = byId(ctx, "scr-editor");
          /* ① 4열 — 종전 7열의 「확정」·「타입/고정값」·「상태」가 접힌 결과다. */
          out.head_cols = Array.prototype.map.call(
            root.querySelectorAll("table.map thead th"),
            (th) => th.firstChild ? String(th.firstChild.textContent).trim() : "");
          out.foot_text = textOf(root.querySelector("table.map tfoot td")).trim();
          /* ② 머리 pill 셋 — 라벨도 수치도 Python 값 그대로. */
          out.pills = Array.prototype.map.call(
            root.querySelectorAll(".bindbar .pill"), (el) => textOf(el).trim());
          out.promote_label = textOf(root.querySelector('[data-act="confirm-suggested"]')).trim();
          /* ③ 배지 — 상태 4태의 문안과 잠금 규칙(내용 없는 행은 확인할 것이 없다). */
          const badges = () => root.querySelectorAll('table.map [data-act="row-confirm"]');
          out.badges = Array.prototype.map.call(badges(), (b) => textOf(b).trim());
          out.badge_disabled = Array.prototype.map.call(badges(), (b) => !!b.disabled);
          out.badge_hint = badges()[3] ? badges()[3].getAttribute("title") : null;
          /* ④ 무결속 행의 열 칸은 조용하지 않다(경고 테두리 class). */
          out.empty_select = !!root.querySelector('table.map tr:nth-child(4) select.empty');
          /* ⑤ 미리보기 4갈래 중 이 스냅샷이 든 둘 — 값과 「—」. */
          out.preview_none = !!root.querySelector("table.map .pv.none");
          /* ⑥ 데이터 열 칸 높이는 행마다 같다(구 editor_chip 의 실렌더 기하 승계).
             결속 행(3)에는 ↻ 가 서고 제안 행(1)에는 없다 — 그 버튼이 select 를 둘째 줄로
             밀면 여기서만 드러난다(정적 CSS 검사는 못 본다). */
          const cells = root.querySelectorAll("table.map tbody tr td:nth-child(2)");
          out.src_cell_h_suggested = cells[0]
            ? Math.round(cells[0].getBoundingClientRect().height) : -1;
          out.src_cell_h_manual = cells[2]
            ? Math.round(cells[2].getBoundingClientRect().height) : -1;
          out.src_cell_h_unselected = cells[3]
            ? Math.round(cells[3].getBoundingClientRect().height) : -1;
          out.auto_revert_option = !!root.querySelector('table.map [data-act="revert-source"]');
          const wrap = cells[2] && cells[2].querySelector(".srccell");
          const sel = wrap && wrap.querySelector(".sel");
          const btn = wrap && wrap.querySelector('[data-act="revert-source"]');
          if (sel && btn) {
            const a = sel.getBoundingClientRect();
            const b = btn.getBoundingClientRect();
            out.revert_same_line = Math.abs((a.top + a.height / 2) - (b.top + b.height / 2)) < 4;
          } else { out.revert_same_line = null; }
          /* ⑦ 일괄 승격 — **제안만** 오른다. 승격 뒤 스냅샷은 Python 이 낼 것과 같은 모양으로
             직접 밀어 넣는다(합성 세계라 백엔드가 답을 주지 않는다): 양성은 제안 2행이
             「확인」이 되는 것, 음성은 확인 필요 2행이 **그대로**인 것이다. */
          calls.length = 0;
          root.querySelector('[data-act="confirm-suggested"]').click();
          await settleUntil(ctx, () => calls.length > 0);
          out.promote_call = calls[0] || "";
          const promoted = Object.assign({}, snap, {
            rows: [
              Object.assign({}, rows[0], {
                confirmed: true, row_state: "confirmed", state_label: "확인" }),
              Object.assign({}, rows[1], {
                confirmed: true, row_state: "confirmed", state_label: "확인" }),
              rows[2], rows[3],
            ],
            binding_head: Object.assign({}, snap.binding_head, { suggested: 0 }),
          });
          ctx.push("editor", promoted);
          await settleRender(ctx);
          out.badges_after = Array.prototype.map.call(badges(), (b) => textOf(b).trim());
          const exactRow = Object.assign({}, rows[0], {
            confirmed: true, row_state: "confirmed", state_label: "자동확정 · 이름 일치",
          });
          ctx.push("editor", Object.assign({}, snap, { rows: [exactRow, ...rows.slice(1)] }));
          await settleRender(ctx);
          const exactBadge = badges()[0];
          const exactCell = root.querySelector("table.map tbody tr td:nth-child(2)");
          const exactSelect = exactCell && exactCell.querySelector(".srccell .sel");
          out.exact_badge = textOf(exactBadge).trim();
          out.exact_pressed = exactBadge && exactBadge.getAttribute("aria-pressed");
          out.exact_select_width = exactSelect ? Math.round(exactSelect.getBoundingClientRect().width) : 0;
          out.exact_cell_h = exactCell ? Math.round(exactCell.getBoundingClientRect().height) : 0;
          out.exact_badge_inside = !!(exactBadge && exactCell &&
            exactBadge.getBoundingClientRect().right <= exactCell.getBoundingClientRect().right + 1);
          ctx.push("editor", promoted);
          await settleRender(ctx);
          out.promote_disabled_after = !!root.querySelector(
            '[data-act="confirm-suggested"]').disabled;
          out.promoted_label_after = textOf(
            root.querySelector('[data-act="confirm-suggested"]')).trim();
          ctx.push("editor", snap);
          await settleRender(ctx);
          /* ⑧ 특수 항목의 액션 분기 — 「고정값…」·「오늘 날짜」는 `set_display`(유형·표시형
             한 쌍)로 갈린다. `set_source` 에 `sp:` 가 실려 나가면 여기서 빨강이다
             (센티넬 금지의 실측). 「비워 둠」 항목은 퇴역했다 — 비우려는 자리는 고정값에
             아무것도 안 적는 것이고, 아래 `option_values` 가 그 부재를 단언한다. */
          const pick = async (index, value) => {
            calls.length = 0;
            const select = root.querySelectorAll('table.map [data-act="row-source"]')[index];
            typeValue(ctx, select, value);
            fire(ctx, select, "change");
            await settleUntil(ctx, () => calls.length > 0);
            return calls[0] || "";
          };
          out.option_values = Array.prototype.map.call(
            root.querySelectorAll('table.map [data-act="row-source"]')[3].options,
            (o) => o.value);
          out.pick_const = await pick(3, "sp:const");
          out.pick_today = await pick(3, "sp:today");
          out.pick_column = await pick(3, "col:수량");
          out.sentinel_in_set_source = [
            out.pick_const, out.pick_today,
          ].some((call) => call.indexOf("set_source") === 0);
          /* ⑧-b 표시형 select 가 **유형 그룹**을 그리고 한 쌍을 원자적으로 낸다(리뷰 1).
             유형 열이 걷힌 뒤 유일하게 남은 유형 축이라, 여기가 죽으면 이름 추론이 틀린 행은
             날짜·금액 서식을 영영 못 고른다. */
          /* 그룹은 **한 행의 select** 에서 센다 — 표 전체를 훑으면 행 수만큼 곱해져
             「3개」라는 계약이 12개로 읽힌다(측정 대상이 아니라 표본이 바뀐 자리). */
          const fmtSelect = root.querySelectorAll('table.map [data-act="row-fmt"]')[0];
          out.display_groups = Array.prototype.map.call(
            fmtSelect.querySelectorAll("optgroup"), (g) => g.getAttribute("label"));
          calls.length = 0;
          typeValue(ctx, fmtSelect, "date:");
          fire(ctx, fmtSelect, "change");
          await settleUntil(ctx, () => calls.length > 0);
          out.pick_display = calls[0] || "";
          /* ⑨ 행별 확인 — 배지 클릭이 그 행의 토글을 낸다. */
          calls.length = 0;
          badges()[0].click();
          await settleUntil(ctx, () => calls.length > 0);
          out.badge_call = calls[0] || "";
          /* ⑩ 스테퍼 왕복 — 표 머리 안의 ◀ ▶ 가 `step_preview` 를 낸다. */
          calls.length = 0;
          root.querySelector('table.map [data-act="next-rec"]').click();
          await settleUntil(ctx, () => calls.length > 0);
          out.step_next = calls[0] || "";
          calls.length = 0;
          root.querySelector('table.map [data-act="prev-rec"]').click();
          await settleUntil(ctx, () => calls.length > 0);
          out.step_prev = calls[0] || "";
          /* ⑪ 퇴역 좌표의 **음성 단언** — 칩 구획·타입 열·확정 체크가 남아 있지 않다. */
          out.header_chips_gone = !root.querySelector('[data-act="toggle-header"]');
          out.type_column_gone = !root.querySelector('[data-act="row-type"]');
          out.confirm_checkbox_gone = !root.querySelector(
            'table.map input[type="checkbox"]');
          out.error = null;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        } finally {
          if (stub) stub.restore();
        }
        return { editor_binding: out };
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
      deadlineMs: 2500,
      deadlineRationale:
        "종전 0 은 **감시견이 아예 없다는 뜻**이다(runner.js: `deadlineMs <= 0` 이면"
        + " withDeadline 이 그대로 통과시킨다). 레거시가 동기 evaluate_js 한 번이던 시절엔"
        + " 그것이 맞았지만, 이 프로브는 이제 클릭·발신·모달 열림을 **기다린다**(U6-D #978"
        + " 3단계 폼 단계). 조건이 안 서면 러너가 끝나지 않고 프로세스 예산까지 매달리며,"
        + " 그 착지가 `run_hung`(exit 8, 보고서 없음)이라 정보가 0 이다. 공용 `_probe_late`"
        + " 예산 2.5초를 그대로 쓴다 — 늘리는 것이 아니라 **없던 상한을** 세운다.",
      after: ["editor_binding"],
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
            fields: [], raw_block: "", gate: null, gate_error: false,
            data_path: "", data_name: "", data_sheet: "", record_count: 0,
            source_fields: [], sample_rows: [],
            name: "공고서", pattern: "공고서-{{공고번호}}", pattern_preview: "공고서-1.hwpx",
            editing_origin: "공고서",
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
            source_fields: ["품명"], sample_rows: [["A"]],
            data_column_options: [
              { value: "", label: "열을 고르세요", kind: "none", field: "" },
              { value: "col:품명", label: "품명", kind: "column", field: "품명" },
              { value: "sp:const", label: "고정값…", kind: "const", field: "" },
            ],
            binding_head: {
              suggested: 0, needs_confirm: 1, const: 1,
              promote_label: "제안 0건 모두 확인", promoted_label: "확인할 제안이 없습니다",
              unused_columns: 0,
            },
            rows: [{
              index: 0, template_field: "품명", inferred_type: "text", context: "", source: "",
              type: "const", const: "고정값", fmt: "",
              /* const 행의 표시형 후보는 비어 있다(프리셋 없음) — 표면은 비활성 「—」. */
              display_options: [], display_value: "const:",
              confirmed: false, touched: true,
              has_content: true, confirmable: true, revertable: false,
              suggestion_score: 0,
              preview: "고정값", preview_kind: "value", preview_empty: false,
              preview_error: false, row_state: "edited", state_label: "확인 필요",
              source_kind: "const", source_value: "sp:const", source_missing_label: "",
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
          /* ⑨ 3단계 「이름·저장」 폼(U6-D #978) — 폼 셋과 두 동사가 실물로 서는가.
             정적 계약은 「스냅샷 키를 읽는다」까지만 본다: 힌트가 표지와 무관하게 상주해도,
             저장 폴더 칸이 값을 못 받아도, 「설정에서 바꾸기」가 아무 데도 안 열려도 초록이다. */
          await measureNameSaveStage(ctx, snap, out);
          out.error = null;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        }
        return { editor_save_gate: out };
      },
    },

    /* ── editor_lib_manage (app.py:2506 상수 · 3966 호출) ─────────────────────
       고르기 단계 좌 열의 **관리 표면**(F8 승계 → U6-B 재편). 구 `_TPL_LIST_GROUP_PROBE_JS`
       의 후계이고, U6-B 에서 정본이 `tpl` 채널로 옮겨 갔다 — 항목 형은 `.pitem`, 행 동사는
       ⋮ 하나, 바닥 동사 넷. 구획 헤더·＋그룹지정은 U4 §2-30 에서 사라진 뒤로 음성 단언이다. */
    {
      name: "editor_lib_manage",
      keys: ["editor_lib_manage"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3966,
      deadlineMs: 2500,
      deadlineRationale:
        "종전 0 은 **감시견이 아예 없다는 뜻**이다(runner.js: `deadlineMs <= 0` 이면"
        + " withDeadline 이 그대로 통과시킨다). 이 프로브는 목록 렌더·확인 왕복·구간 동사"
        + " 발신을 기다리므로, 조건이 안 서면 러너가 끝나지 않고 프로세스 예산까지 매달린다"
        + " — 그 착지가 `run_hung`(exit 8, 보고서 없음)이라 정보가 0 이다. 공용"
        + " `_probe_late` 예산 2.5초를 그대로 쓴다(늘리는 것이 아니라 **없던 상한을** 세운다).",
      after: ["editor_save_gate"],
      afterReason: "레거시 드라이버 순서 그대로(3961 → 3966).",
      note:
        "**아는 취약점**: 이 프로브의 클릭 3곳에 가시성 단언이 없다(흘리기 body 클릭·행 ⋮ 2회). "
        + "프로브 click 은 hidden 을 통과하므로 눈으로 본 것과 다른"
        + " 결론이 날 수 있다 — 이식에서 고치지 않고 그대로 옮긴다(계약을 바꾸는 별건)."
        + ` 클러스터 전체의 같은 자리는 ${CLICK_SITES_WITHOUT_VISIBILITY.length} 군이다.`,
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = {};
        try {
          Nav.go("editor", { force: true });
          /* 링1 상태 게이트가 드는 것은 **수선 동사**뿐이다(U6-E 리뷰 10) — 검토 왕복은
             웹이 모든 행에 덧붙이는 「자세히…」가 진다. */
          const acts = [{ key: "compile", label: "누름틀·구간 변환" }];
          const H = (name, warns, rowActs, blockedLabel) => tplRow({
            key: name, name, path: `C:/lib/${name}`,
            badge_label: blockedLabel || "누름틀",
            badge_level: blockedLabel === "원문" ? "muted" : blockedLabel ? "warn" : "ok",
            warns: warns || [],
            actions: rowActs === undefined ? acts : rowActs,
            selectable: !blockedLabel,
            reason: blockedLabel ? "누름틀·구간 변환을 해야 고를 수 있습니다." : "",
          });
          const txtRow = (name, error) => tplRow({
            key: name, name: name.replace(/\.txt$/, ""), path: `C:/txt/${name}`,
            sub: error ? `읽기 실패: ${error}` : "필드 2개",
            badge_label: "TXT", badge_level: "muted", icon: "txt",
            selectable: !error,
            reason: error ? `읽을 수 없어 고를 수 없습니다: ${error}` : "",
          });
          const manageTpl = tplBase({
            rows: [
              H("a.hwpx"), H("b.hwpx", null, undefined, "원문"),
              /* COMPILED 의 실제 모양 — U6-B 뒤 동사가 0 이던 행이다. U6-E(#979)가 그
                 자리에 「검토」를 세웠고, 「자세히…」는 어느 행에서든 선다. */
              H("c.hwpx", null, []),
              H("d.hwpx", ["빈 값 2건은 공란으로 채워집니다"],
                [{ key: "compile", label: "마저 변환" }], "부분 변환"),
              /* 「자세히…」의 왕복을 실제로 태울 행 — 검토가 상세를 채운다. */
              H("구간.hwpx", null, []),
              /* 판독 실패 행도 목록에 선다(숨기지 않는다) — 그 행의 ⋮ 는 「자세히…」
                 하나이고, 시트가 답하는 것이 바로 그 사유다. */
              txtRow("메모.txt"), txtRow("깨진.txt", "UTF-8 이 아닙니다"),
            ],
            result: { text: "검토: 문제 없음", level: "ok" },
          });
          /* 「자세히…」가 부른 검토의 착지 — 시트 한 장의 재료 전부가 이 한 존에 온다
             (U6-E #979). 같은 창에 얹는 단계다(새 부팅 0). */
          const detailTpl = tplBase(Object.assign({}, manageTpl, {
            detail: {
              path: "C:/lib/구간.hwpx", name: "구간", media: "hwpx",
              state: "compiled", badge_label: "누름틀", badge_level: "ok",
              field_count: 2, field_summary: "필드 2개",
              fields: [
                { name: "계약명", type_hint: "text" },
                { name: "계약일", type_hint: "date" },
              ],
              actions: [],
              diagnostics: [],
              slots: {
                summary: "항목 1개 · 선택 1개",
                rows: [{
                  id: "특약", label: "특약 사항", option_count: 1,
                  options: ["지체상금 조항"],
                }],
              },
              error: "",
            },
          }));
          ctx.push("pool", poolBase([]));
          const draft = editorBase({
            /* 1단계 게이트 존은 **세션이 스키마를 읽었을 때** 선다 — `field_count` 가 그
               조건이다(U6-E #979). 합성 스냅샷도 그 사실을 실어야 존이 그려진다. */
            template_path: "C:/lib/a.hwpx", template_name: "a.hwpx", field_count: 3,
            /* 시트 문의 가부·사유는 Python 판정이다(리뷰 5) — 합성 스냅샷도 그것을 싣는다. */
            session_detail: { available: true, reason: "" },
            pairing: {
              ready: false, template_name: "a.hwpx", data_name: "",
              field_count: 3, column_count: 0, auto_count: 0, confirm_count: 0,
              basis: "", advance_block_reason: "오른쪽에서 데이터를 고르세요.",
            },
          });
          ctx.push("editor", draft);
          const host = byId(ctx, "scr-editor");
          ctx.push("tpl", manageTpl);
          await ctx.waitFor(
            () => host.querySelectorAll("#editorTplList .pitem").length === 7,
            { what: "좌 열 항목 7건(hwpx 5 + txt 2) 렌더", timeoutMs: 2000 },
          );
          /* 고르기 열은 가져오기·폴더 보기·새로 읽기만 남긴다. */
          /* 「새로 읽기」의 `data-act` 는 좌 열 전용 이름(`lib-refresh`)에서 공용 열의
             `refresh` 로 바뀌었다(고르기 열 공용 ②) — 같은 컴포넌트의 두 인스턴스가
             자기 side 를 `data-side` 로 말한다. */
          out.toolbar = ["import-template", "open-settings", "lib-new-txt", "refresh"]
            .map((a) => !!host.querySelector(`button[data-act="${a}"]`));
          out.retired_folder_import = !host.querySelector('button[data-act="import-folder"]');
          const refreshButton = host.querySelector('[data-act="refresh"][data-side="tpl"]');
          const refreshRect = refreshButton.getBoundingClientRect();
          const refreshIconStyle = styleOf(ctx, refreshButton.querySelector("svg"));
          out.refresh_compact = !isHidden(ctx, refreshButton)
            && Math.abs(refreshRect.width - 28) < .5 && Math.abs(refreshRect.height - 28) < .5
            && refreshIconStyle.width === "14px" && refreshIconStyle.height === "14px";
          let finishRefresh;
          let refreshCalls = 0;
          const refreshResult = new Promise((resolve) => { finishRefresh = resolve; });
          const refreshStub = stubBridgeCall(ctx, (real) => (screen, action, payload) => {
            if (screen !== "tpl" || action !== "refresh") return real(screen, action, payload);
            refreshCalls += 1;
            return refreshResult;
          });
          try {
            ctx.doc.body.click();
            refreshButton.click();
            refreshButton.click();
            await settleRender(ctx);
            out.refresh_locked = refreshButton.disabled
              && refreshButton.getAttribute("aria-busy") === "true" && refreshCalls === 1;
            out.refresh_motion = styleOf(ctx, refreshButton.querySelector("svg")).animationName
              === (ctx.win.matchMedia("(prefers-reduced-motion: reduce)").matches ? "none" : "refresh-spin");
            finishRefresh({ ok: true });
            await settleUntil(ctx, () => !refreshButton.disabled);
            out.refresh_reenabled = refreshButton.getAttribute("aria-busy") === "false";
            out.refresh_completed = refreshButton.getAttribute("data-refresh-done") === "true"
              && refreshButton.getAttribute("aria-label") === "템플릿 새로고침 완료"
              && styleOf(ctx, refreshButton.querySelector("svg")).animationName === "none";
          } finally {
            finishRefresh({ ok: true });
            refreshStub.restore();
          }
          // 구획 헤더·그룹 ⋮·＋그룹지정 칩은 U4 §2-30 에서 사라졌다 — 셋 다 **음성 단언**으로
          // 남긴다(0 이 아니게 되면 걷힌 표면이 되살아났다는 뜻이다).
          out.grp_heads = host.querySelectorAll(".job-grp-head").length;
          out.rows_visible = host.querySelectorAll("#editorTplList .pitem").length;   // 7(hwpx5+txt2)
          out.row_more = host.querySelectorAll('[data-act="lib-more"]').length;  // 모든 가시 행
          /* **모든 행에 「자세히…」가 있다**(U6-E #979) — 그래서 동사 0 인 행이 없고 ⋮ 는
             어떤 행에서도 잠기지 않는다. 종전의 「동사 0 → 비활성 + 사유」(U6-A)가 막던
             무반응은 그대로 막힌다: 어느 행이든 누르면 답할 것이 있다. */
          const moreFor = (key) =>
            host.querySelector(`[data-act="lib-more"][data-key="${key}"]`);
          out.detail_always_available = [
            "a.hwpx", "b.hwpx", "c.hwpx", "d.hwpx", "구간.hwpx", "메모.txt", "깨진.txt",
          ].every((key) => !!moreFor(key) && !moreFor(key).disabled);
          const moreVisibleOnFocus = (key) => {
            const more = moreFor(key);
            const pick = more?.closest(".pitem-wrap")?.querySelector(".pitem");
            pick?.focus();
            return !!more && !!pick && ctx.doc.activeElement === pick
              && styleOf(ctx, more).visibility === "visible"
              && more.offsetParent !== null && !more.disabled;
          };
          out.partial_more_visible = moreVisibleOnFocus("d.hwpx");
          out.raw_more_visible = moreVisibleOnFocus("b.hwpx");
          out.grp_more = host.querySelectorAll(".grp-more").length;
          out.assign_chips = host.querySelectorAll('[data-act="lib-assign"]').length;
          out.fill_warn = /빈 값 2건/.test(host.textContent);                 // #154 사전 고지 승계
          const res = host.querySelector(".run-result");
          out.result_line = !!res && /검토: 문제 없음/.test(res.textContent)
            && res.className.indexOf("ok") !== -1;                            // #tplResult 승계
          /* 결과 줄은 관리 동사가 나가는 **좌 열 안**에 선다(U6-E) — 고르기 존 아래가 아니다. */
          out.result_in_left_column = !!res && !!byId(ctx, "editorTplPool")
            && byId(ctx, "editorTplPool").contains(res);
          out.band_caption = /서식 폴더/.test(host.textContent);
          /* 고르기 존 아래에서 걷힌 표면들 — 되살아나면 같은 사실이 두 자리에서 그려진다.
             셋 다 U6-E 에서 항목 상세 시트로 이주했다. */
          out.retired_zones = {
            slots_band: !host.querySelector("#tplSlots"),
            session_slot_summary: !host.querySelector("#editorSlotSummary"),
            file_chip: !host.querySelector(".filechip"),
            schema_table: !host.querySelector("#scr-editor .schema-fields"),
          };
          /* 게이트 존은 필드 수 한 줄 + 「자세히…」로 접혔다(세션 판정은 1단계에 남는다). */
          const sessionDoor = host.querySelector('[data-act="session-detail"]');
          out.gate_zone = !!byId(ctx, "editorTplGate") && !!sessionDoor
            && !sessionDoor.disabled;
          const folderButtons = host.querySelectorAll('[data-act="open-template-folder"]');
          out.template_folder_single = folderButtons.length === 1
            && !host.querySelector('[data-track-act="reveal"]');
          out.template_folder_visible = !!folderButtons[0] && !isHidden(ctx, folderButtons[0]);
          const folderCalls = [];
          const folderStubs = ["open", "reveal"].map((action) => stubBridgeInvoke(
            ctx, `${action}Path`, `${action}_path`, () => async (path) => {
              folderCalls.push([action, path]);
              return null;
            },
          ));
          try {
            ctx.doc.body.click();
            folderButtons[0].click();
            await settleRender(ctx);
            out.template_folder_calls = folderCalls;
          } finally {
            folderStubs.reverse().forEach((stub) => stub.restore());
          }
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
          const openRowMenu = async (key) => {
            flush();
            host.querySelector(`[data-act="lib-more"][data-key="${key}"]`).click();
            await settleRender(ctx);
            const items = menuActions();
            ctx.doc.body.dispatchEvent(new ctx.win.MouseEvent("pointerdown", { bubbles: true }));
            await settleRender(ctx);
            return items;
          };
          /* 행 ⋮ 의 구성 — 링1 상태 동사 + 「자세히…」. 「이동」은 U4 §2-30 에서, 「삭제」는
             U6-A(#975)에서, `preview`·`make_job` 은 U6-B(#976)에서 사라졌다. */
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
          /* COMPILED 의 실제 모양(동사 0 이던 행) — 이제 「검토」와 「자세히…」가 선다. */
          out.partial_menu_items = await openRowMenu("d.hwpx");
          out.compiled_menu_items = await openRowMenu("c.hwpx");
          out.txt_menu_items = await openRowMenu("메모.txt");
          out.txt_error_menu_items = await openRowMenu("깨진.txt");
          /* 「자세히…」 왕복 — 검토 발신 → 시트 열림 → 시트 안의 필드 표·구간 항목 표·
             밴드 동사·행 동사. 발신은 이 클러스터의 관례대로 가로챈다: 목록 자체가 **합성
             스냅샷**이라 그 경로를 실 백엔드에 보내면 남의 라이브러리를 겨눈다. 새 창은
             만들지 않는다 — 이미 선 창에 시트 한 장을 얹는다. */
          const detailSent = [];
          const detailStub = stubBridgeCall(ctx, () => async (screen, action, payload) => {
            detailSent.push([screen, action, payload]);
            return {};      // 검토는 읽기 전용이라 거절할 것이 없다(시트는 push 로 채운다)
          });
          try {
            flush();
            host.querySelector('[data-act="lib-more"][data-key="구간.hwpx"]').click();
            await settleRender(ctx);
            const detailItem = byId(ctx, "tplRowMenu")
              .querySelector('button[data-context-menu-action="detail"]');
            out.detail_item_visible = !!detailItem && !isHidden(ctx, detailItem);
            detailItem.click();
            await settleUntil(ctx, () => detailSent.length > 0);
            out.detail_dispatch = detailSent.map(([screen, action, payload]) => [
              screen, action, payload.path,
            ]);
            ctx.push("tpl", detailTpl);
            await ctx.waitFor(
              () => {
                const sheet = byId(ctx, "tplDetailModal");
                return !!sheet && !isHidden(ctx, sheet)
                  && !!sheet.querySelector("#tplDetailSlots .slotrow");
              },
              { what: "항목 상세 시트 렌더(#tplDetailModal)", timeoutMs: 2000 },
            );
          } finally {
            detailStub.restore();
          }
          const sheet = byId(ctx, "tplDetailModal");
          out.sheet_open = !!sheet && !isHidden(ctx, sheet);
          out.sheet_fields_table = !!sheet.querySelector("table.schema-fields");
          out.sheet_field_names = Array.prototype.map.call(
            sheet.querySelectorAll("table.schema-fields tbody .fname"),
            (node) => String(node.textContent),
          );
          out.slot_rows = sheet.querySelectorAll("#tplDetailSlots .slotrow").length;
          out.slot_verbs = ["slot-rename", "slot-decompile", "slot-remove"]
            .map((a) => !!sheet.querySelector(`[data-act="${a}"][data-slot="특약"]`));
          const renameBtn = sheet.querySelector('[data-act="slot-rename"][data-slot="특약"]');
          out.slot_rename_visible = !!renameBtn && !isHidden(ctx, renameBtn);
          /* 밴드 동사(U4-E3 #939) — 행 1건에서도 서고, 항목이 아니라 **파일**을 겨눈다
             (`data-slot` 없음). 같은 창에 얹은 좌표 단언 하나다(새 창 0). */
          const bandBtn = sheet.querySelector('[data-act="slot-decompile-all"]');
          out.slot_band_verb_visible = !!bandBtn && !isHidden(ctx, bandBtn);
          out.slot_band_verb_targets_file = !!bandBtn && !bandBtn.hasAttribute("data-slot");
          /* 동사 줄은 행 ⋮ 와 같은 목록에서 「자세히…」만 걷은 것이다. */
          out.sheet_verbs = Array.prototype.map.call(
            sheet.querySelectorAll("#tplDetailVerbs button"),
            (button) => button.dataset.act,
          );
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
            /* 실패는 **시트 안**에 선다(U6-E 리뷰 3): 시트가 스크림으로 화면을 덮는 동안
               `#save-msg` 에 쓴 문장은 그 뒤에 그려진다. 앞선 프로브가 남긴 문안과 섞이지
               않게 우리 사유가 실렸는지로 본다. */
            await settleUntil(ctx, () => {
              const node = byId(ctx, "tplDetailMsg");
              return !!node && node.textContent.indexOf("SLOT_PROBE_REFUSAL") !== -1;
            });
            const notice = byId(ctx, "tplDetailMsg");
            out.slot_notice_inline = !!notice
              && notice.textContent.indexOf("SLOT_PROBE_REFUSAL") !== -1
              && !isHidden(ctx, notice);
            /* 스크림 뒤 채널에는 같은 문장을 쓰지 않는다(같은 사실을 두 자리에 두지 않는다). */
            const behind = byId(ctx, "save-msg");
            out.slot_notice_not_behind_scrim = !behind
              || behind.textContent.indexOf("SLOT_PROBE_REFUSAL") === -1;
          } finally {
            slotStub.restore();
          }
          /* 결과 줄도 시트 안에 선다 — 관리 동사의 성과가 스크림 뒤로 가지 않는다(리뷰 3).
             값은 고르기 열 존의 `result` 그대로이므로 푸시 한 번으로 재현한다(새 창 0). */
          ctx.push("tpl", tplBase(Object.assign({}, detailTpl, {
            column: Object.assign({}, detailTpl.column, {
              result: { text: "SHEET_RESULT_PROBE", level: "warn" },
            }),
          })));
          await settleUntil(ctx, () => {
            const node = byId(ctx, "tplDetailResult");
            return !!node && node.textContent.indexOf("SHEET_RESULT_PROBE") !== -1;
          });
          const sheetResult = byId(ctx, "tplDetailResult");
          out.sheet_result_inside = !!sheetResult
            && sheetResult.textContent.indexOf("SHEET_RESULT_PROBE") !== -1
            && !isHidden(ctx, sheetResult);
          service(ctx, "Modal").close("tplDetailModal");
          settleModal(ctx, "tplDetailModal");
          await settleRender(ctx);
          const closedSheet = byId(ctx, "tplDetailModal");
          out.sheet_closed = !closedSheet || isHidden(ctx, closedSheet);
          /* 퇴화 — 목록 1건 + 상세 없음. 헤더 축은 애초에 없다(음성 단언 유지). */
          const degenerate = tplBase({ rows: [H("d.hwpx")] });
          ctx.push("tpl", degenerate);
          await ctx.waitFor(
            () => host.querySelectorAll("#editorTplList .pitem").length === 1,
            { what: "퇴화 목록 1건 렌더", timeoutMs: 2000 },
          );
          out.flat_heads = host.querySelectorAll(".job-grp-head").length;
          out.flat_rows = host.querySelectorAll("#editorTplList .pitem").length;
          await ctx.waitFor(() => refreshButton.getAttribute("data-refresh-done") === "false", {
            what: "새로고침 완료 표시 자동 복귀", timeoutMs: 1000,
          });
          out.refresh_restored = refreshButton.getAttribute("aria-label") === "템플릿 새로고침";
          out.error = null;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, String((thrown && thrown.message) || thrown));
        } finally {
          }
        return { editor_lib_manage: out };
      },
    },

    /* ── editor_lib (app.py:2608 상수 · 3985 호출) ────────────────────────────
       **고르기 화면 그 자체**(U6-B #976 — 구 「1단계 피커」의 후계). 정적 계약이 못 보는 것을
       넷 잰다: ①두 열이 각자 채널로 실제로 서는가 ②클릭 둘이 연결 카드와 전진 게이트를
       세우는가 ③합성 드래그가 **클릭과 같은 상태**를 만드는가 ④비활성 항목의 클릭·드롭이
       조용히 삼켜지지 않고 사유를 남기는가. 새 창은 만들지 않는다 — 이미 선 창에 얹는다. */
    {
      name: "editor_lib",
      keys: ["editor_lib"],
      cluster: D_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3985,
      deadlineMs: 2500,
      deadlineRationale:
        "종전 0(동기 evaluate_js 한 번)에 **합성 드래그 왕복**이 얹혔다(U6-B): dragstart→"
        + " dragover→drop 뒤 발신이 정착할 때까지 짧게 폴링한다. 늘린 것은 매달림을 유한"
        + " 시간에 빨강으로 만드는 상한이지 통과 조건이 아니다.",
      after: ["editor_lib_manage"],
      afterReason:
        "레거시 드라이버 순서 그대로(3966 → 3985). 사이의 3969~3983 은 다른 클러스터(B)의"
        + " 폭 측정·overlay 프로브라 `after` 로 가리키지 않는다 — legacySite 가 그 순서를 잇는다.",
      async run(ctx) {
        const Nav = service(ctx, "Nav");
        const out = {};
        try {
          Nav.go("editor", { force: true });
          const it = (name, badge, level, blocked) => tplRow({
            key: name, name, path: `C:/lib/${name}`,
            badge_label: badge, badge_level: level,
            selectable: !blocked,
            reason: blocked ? "누름틀·구간 변환을 해야 고를 수 있습니다." : "",
          });
          const pickTpl = tplBase({
            rows: [
              it("a.hwpx", "준비됨", "ok"), it("b.hwpx", "변환 필요", "warn", true),
              it("c.hwpx", "준비됨", "ok"),
            ],
          });
          /* 우 열 — 데이터 선택 다이얼로그와 **같은 스냅샷 모양**(같은 열 계약). 끊긴 항목
             하나를 함께 세워 「숨기지 않고 비활성 + 사유」가 두 표면에서 같은 값으로 서는지
             본다. */
          const datRow = (key, name, blocked) => ({
            key, name, sub: `C:/d/${name}.xlsx (물품)`, warns: [],
            reason: blocked ? "참조가 끊겼습니다. '다시 연결' 뒤에 쓸 수 있습니다." : "",
            badge_label: "활성", badge_level: "ok", icon: "excel",
            selectable: !blocked, path: `C:/d/${name}.xlsx`,
            actions: [{ key: "archive", label: "보관" }],
          });
          const pickPool = poolBase([
            datRow("d1", "7월목록"), datRow("d2", "지난목록", true),
          ]);
          const blank = editorBase({
            pairing: {
              ready: false, template_name: "", data_name: "",
              field_count: 0, column_count: 0, auto_count: 0, confirm_count: 0,
              basis: "", advance_block_reason: "왼쪽에서 템플릿을 고르세요.",
            },
          });
          ctx.push("editor", blank);
          const host = byId(ctx, "scr-editor");
          ctx.push("tpl", pickTpl);
          ctx.push("pool", pickPool);
          await ctx.waitFor(
            () => host.querySelectorAll('.pitem[data-side="tpl"]').length === 3
              && host.querySelectorAll('.pitem[data-side="dat"]').length === 2,
            { what: "고르기 두 열 렌더(좌 3 · 우 2)", timeoutMs: 2000 },
          );

          /* ① 두 열이 각자 채널로 선다 — **같은 컴포넌트의 두 인스턴스**라 문법도 하나다
             (`.pitem[data-side=…]` · 고르기 열 공용 ③a). 구획 헤더는 없다(U4 §2-30 음성 단언). */
          out.grp_heads = host.querySelectorAll(".job-grp-head").length;
          out.tpl_items = host.querySelectorAll('.pitem[data-side="tpl"]').length;
          out.dat_items = host.querySelectorAll('.pitem[data-side="dat"]').length;
          out.import_btn = !!host.querySelector('button[data-act="import-template"]');
          out.browse_btn = !!byId(ctx, "editorPoolBrowse");
          /* 매체 고지 두 줄(F6 PR-B)은 U6-B 에서 사라졌다 — 매체는 pill 하나가 말한다. */
          out.filter_notice = /\.hwpx 문서 파일을 만드는/.test(host.textContent);
          /* 비활성 항목은 **숨기지 않고** 사유를 부제에 진다(양성·음성 대조). */
          const blockedItem = host.querySelector('.pitem[aria-disabled="true"]');
          out.blocked_shown = !!blockedItem;
          out.blocked_reason = blockedItem
            ? /누름틀·구간 변환/.test(blockedItem.textContent) : false;
          out.blocked_not_draggable = !!blockedItem && blockedItem.draggable === false;
          const fn = host.querySelector(".pitem .nm");
          out.fname_ellipsis = fn ? styleOf(ctx, fn).textOverflow : "missing";

          /* ② 클릭 둘 → 등록된 액션 둘. 발신은 가로챈다(합성 스냅샷이라 실 백엔드로
             보내면 남의 서식 폴더·풀을 겨눈다). */
          const sent = [];
          const stub = stubBridgeCall(ctx, () => async (screen, action, payload) => {
            sent.push([screen, action, payload]);
            return {};
          });
          try {
            host.querySelector('.pitem[data-side="tpl"][data-key="a.hwpx"]').click();
            host.querySelector('.pitem[data-side="dat"][data-key="d1"]').click();
            await settleUntil(ctx, () => sent.length >= 2);
            out.click_calls = sent.map((row) => [row[0], row[1]]);

            /* ③ 합성 드래그 — **같은 액션 두 번**이 나와야 한다(새 액션 0). */
            sent.length = 0;
            const transfer = {
              data: {}, effectAllowed: "", dropEffect: "", types: ["text/plain"],
              setData(kind, value) { this.data[kind] = value; this.types = ["text/plain"]; },
              getData(kind) { return this.data[kind] || ""; },
            };
            const fire = (node, type) => {
              const event = new ctx.win.Event(type, { bubbles: true, cancelable: true });
              event.dataTransfer = transfer;
              node.dispatchEvent(event);
              return event;
            };
            const source = host.querySelector('.pitem[data-side="tpl"][data-key="c.hwpx"]');
            const target = host.querySelector('.pitem[data-side="dat"][data-key="d1"]');
            fire(source, "dragstart");
            out.drag_payload = transfer.getData("text/plain");
            const over = fire(target, "dragover");
            out.drag_over_accepted = over.defaultPrevented;
            out.drag_target_marked = target.classList.contains("drop-target");
            fire(target, "drop");
            await settleUntil(ctx, () => sent.length >= 2);
            out.drop_calls = sent.map((row) => [row[0], row[1]]);
            out.drop_matches_click = JSON.stringify(out.drop_calls)
              === JSON.stringify(out.click_calls);
            out.drag_target_cleared = !target.classList.contains("drop-target");

            /* ④ 같은 열끼리는 짝이 아니다 — 발신 0(음성 대조). */
            sent.length = 0;
            const sibling = host.querySelector('.pitem[data-side="tpl"][data-key="a.hwpx"]');
            fire(source, "dragstart");
            fire(sibling, "drop");
            await settleRender(ctx);
            out.same_side_drop_calls = sent.length;

            /* ⑤ 비활성 항목 클릭 → 발신 0 + 인라인 사유(조용한 무시 금지). */
            sent.length = 0;
            host.querySelector('.pitem[data-side="tpl"][data-key="b.hwpx"]').click();
            await settleUntil(ctx, () => {
              const node = byId(ctx, "save-msg");
              return !!node && node.textContent.indexOf("고를 수 없습니다") !== -1;
            });
            out.blocked_click_calls = sent.length;
            const notice = byId(ctx, "save-msg");
            out.blocked_notice = !!notice && !isHidden(ctx, notice)
              && notice.textContent.indexOf("누름틀·구간 변환") !== -1;

            /* ⑥ 이미 고른 항목 재선택 = **무동작**(리뷰 1). 종전 표면에서는 현재 항목이
               클릭 핸들러 없는 span 이라 불가능했고, 통과시키면 세션이 통째로 끊긴다. */
            ctx.push("editor", editorBase({
              template_path: "C:/lib/a.hwpx", template_name: "a.hwpx",
              pairing: {
                ready: false, template_name: "a.hwpx", data_name: "",
                /* 고름 표지의 정본은 **키**다(고르기 열 공용 ①·②) — 표면이 경로를 다시
                   대조하지 않으므로 합성 스냅샷도 그 사실을 실어야 표지가 선다. */
                template_key: "a.hwpx", data_key: "",
                field_count: 3, column_count: 0, auto_count: 0, confirm_count: 0,
                basis: "", advance_block_reason: "오른쪽에서 데이터를 고르세요.",
              },
            }));
            await settleUntil(ctx, () => !!host.querySelector(
              '.pitem[data-side="tpl"][aria-pressed="true"]'));
            sent.length = 0;
            host.querySelector('.pitem[data-side="tpl"][data-key="a.hwpx"]').click();
            await settleRender(ctx);
            out.reselect_calls = sent.length;
            out.reselect_keeps_mark = host.querySelectorAll(
              '.pitem[data-side="tpl"][aria-pressed="true"]').length;

            /* ⑦ 우 열의 관리 동사는 좌 열과 **같은 ⋯ 메뉴**를 지난다(③a) — 종전의 카드
               인라인 버튼은 사라졌다. 링1 이 낸 동사 뒤에 경로 문(「폴더에서 보기」)이 서고,
               고른 항목은 공용 `pool` 채널로 나간다(다이얼로그와 같은 몸통).

               연타 차단(in-flight)은 이 좌표에서 잴 수 없다 — 메뉴는 고르면 닫히므로 같은
               틱의 두 번째 클릭이 존재하지 않는다. 그 몸통 계약은 `tests/js/pool_verbs.test.js`
               가 계속 진다(공용 `createPoolVerbs`). */
            sent.length = 0;
            ctx.doc.body.click();
            const datMore = host.querySelector(
              '[data-act="lib-more"][data-side="dat"][data-key="d1"]');
            out.manage_verb_present = !!datMore;
            if (datMore) {
              datMore.click();
              await settleRender(ctx);
              const datMenu = byId(ctx, "tplRowMenu");
              out.dat_menu_items = datMenu ? Array.prototype.map.call(
                datMenu.querySelectorAll("button[data-context-menu-action]"),
                (button) => button.dataset.contextMenuAction) : [];
              const archive = datMenu && datMenu.querySelector(
                '[data-context-menu-action="act:archive"]');
              if (archive) {
                archive.click();
                await settleUntil(ctx, () => sent.length > 0);
                await settleRender(ctx);
                out.manage_verb_calls = sent
                  .filter((row) => row[0] === "pool" && row[1] === "archive").length;
              }
              ctx.doc.body.dispatchEvent(
                new ctx.win.MouseEvent("pointerdown", { bubbles: true }));
              await settleRender(ctx);
            }

            /* ⑧ 우 열 행의 「자세히…」 → 등록 데이터 상세 시트(고르기 열 공용 ④). 좌 열
               시트와 **같은 골격**(`detail_sheet.ts`)이라 좌표도 접두어만 다르다. 같은
               창에 얹는 단계다(새 부팅 0) — 발신은 위 스텁이 계속 가로챈다.

               상세를 **먼저 push** 하는 것이 실 경로의 재현이다: 실제 백엔드는 `review`
               핸들러 안에서 스냅샷을 밀고 그 뒤에 왕복이 정산되므로, 웹이 상세를 읽을
               때 값은 이미 서 있다. */
            sent.length = 0;
            ctx.push("pool", poolBase(
              [datRow("d1", "7월목록"), datRow("d2", "지난목록", true)],
              {
                detail: {
                  key: "d1", name: "7월목록", kind: "excel", kind_label: "엑셀/CSV",
                  status: "active", badge_label: "활성", badge_level: "ok",
                  path: "C:/d/7월목록.xlsx", sheet: "물품", sheet_title: "물품",
                  header_row: 2, note: "분기 집계",
                  facts: ["종류 엑셀/CSV", "시트: 물품", "헤더 2행", "메모: 분기 집계"],
                  column_count: 3, column_summary: "열 3개",
                  columns: ["공고명", "금액", "기관"],
                  actions: [{ key: "archive", label: "보관" }],
                  error: "",
                },
              },
            ));
            await settleRender(ctx);
            ctx.doc.body.click();
            const detailMore = host.querySelector(
              '[data-act="lib-more"][data-side="dat"][data-key="d1"]');
            detailMore.click();
            await settleRender(ctx);
            const detailItem = byId(ctx, "tplRowMenu")
              .querySelector('button[data-context-menu-action="detail"]');
            out.dat_detail_item_visible = !!detailItem && !isHidden(ctx, detailItem);
            if (detailItem) {
              detailItem.click();
              await settleUntil(ctx, () => sent.length > 0);
              out.dat_detail_dispatch = sent.map(([screen, action, payload]) => [
                screen, action, payload.key,
              ]);
              await ctx.waitFor(
                () => {
                  const node = byId(ctx, "poolDetailModal");
                  return !!node && !isHidden(ctx, node)
                    && !!node.querySelector("#poolDetailColumns tbody tr");
                },
                { what: "등록 데이터 상세 시트 렌더(#poolDetailModal)", timeoutMs: 2000 },
              );
              const poolSheet = byId(ctx, "poolDetailModal");
              out.pool_sheet_open = !!poolSheet && !isHidden(ctx, poolSheet);
              out.pool_sheet_columns = poolSheet
                .querySelectorAll("#poolDetailColumns tbody tr").length;
              out.pool_sheet_column_names = Array.prototype.map.call(
                poolSheet.querySelectorAll("#poolDetailColumns tbody .fname"),
                (node) => String(node.textContent),
              );
              out.pool_sheet_summary = textOf(byId(ctx, "poolDetailColumnSummary"));
              out.pool_sheet_facts = textOf(byId(ctx, "poolDetailFacts"));
              /* 동사 줄은 행 ⋯ 와 같은 목록에서 「자세히…」만 걷은 것이다(좌 열과 같은 규율). */
              out.pool_sheet_verbs = Array.prototype.map.call(
                poolSheet.querySelectorAll("#poolDetailVerbs button"),
                (button) => button.dataset.act,
              );
              service(ctx, "Modal").close("poolDetailModal");
              settleModal(ctx, "poolDetailModal");
              await settleRender(ctx);
              const closedPoolSheet = byId(ctx, "poolDetailModal");
              out.pool_sheet_closed = !closedPoolSheet || isHidden(ctx, closedPoolSheet);
            }
          } finally {
            stub.restore();
          }

          /* ⑥ 둘 다 고른 스냅샷 → 연결 카드 문구·전진 게이트. 수치도 라벨도 Python 이 낸
             값 그대로여야 한다(표면이 다시 세면 두 곳이 같은 상태를 다르게 답한다). */
          ctx.push("editor", editorBase({
            template_path: "C:/lib/a.hwpx", template_name: "a.hwpx",
            data_path: "C:/d/7월목록.xlsx", data_name: "7월목록.xlsx",
            data_sheet: "물품", data_header_row: 1, data_pool_key: "",
            record_count: 12,
            reachable: { template: true, binding: false, filename: false },
            pairing: {
              ready: true, template_name: "a.hwpx", data_name: "7월목록.xlsx",
              /* 파일로 연 데이터라 겨눌 **풀 행**이 없다 — 대신 Python 이 같은 행 계약으로
                 낸 세션 행이 목록 맨 위에 선다(③a). 「현재 데이터」 카드의 승계처다. */
              template_key: "a.hwpx", data_key: "",
              data_row: {
                key: "session", name: "7월목록.xlsx",
                sub: "시트: 물품 · 헤더 1행 · 12행", reason: "", warns: [],
                badge_label: "사용 중", badge_level: "ok", icon: "excel",
                selectable: true, path: "C:/d/7월목록.xlsx", actions: [],
              },
              field_count: 12, column_count: 18, auto_count: 10, confirm_count: 2,
              basis: "preview", advance_block_reason: "",
            },
          }));
          await settleUntil(ctx, () => {
            const card = byId(ctx, "editorLinkCard");
            return !!card && card.textContent.indexOf("⟷") !== -1;
          });
          const card = byId(ctx, "editorLinkCard");
          out.card_text = card.textContent.replace(/\s+/g, " ").trim();
          out.wire_live = byId(ctx, "editorWire").classList.contains("live");
          out.cta_enabled = !host.querySelector('.wfoot [data-act="next"]').disabled;
          out.center_cta_absent = !byId(ctx, "editorLinkCta");
          /* 세션 행이 시트·헤더 행·행 수를 **다시 묻지 않고 재진술**한다 — 문장을 짓는
             자리가 Python 으로 갔고(③a), 여기서 되읽는 것은 그 값이 실제로 서는가다. */
          await ctx.waitFor(
            () => !!host.querySelector('#editorDataList .pitem[data-key="session"]'),
            { what: "세션 행(현재 데이터) 렌더", timeoutMs: 2000 },
          );
          out.current_restated = textOf(
            host.querySelector('#editorDataList .pitem[data-key="session"]'));
          out.pool_current_marked = host.querySelectorAll(
            '.pitem[data-side="dat"][aria-pressed="true"]').length;
          /* 「이 데이터 고정…」은 고정할 것이 있을 때만 선다 — 그 사실을 드는 값이 세션 행이다. */
          out.pin_btn = !!byId(ctx, "editorPoolPin");

          /* ⑦ 반쪽만 고른 스냅샷 → CTA 비활성 + **Python 이 낸 사유**. */
          ctx.push("editor", editorBase({
            template_path: "C:/lib/a.hwpx", template_name: "a.hwpx",
            pairing: {
              ready: false, template_name: "a.hwpx", data_name: "",
              field_count: 12, column_count: 0, auto_count: 0, confirm_count: 0,
              basis: "", advance_block_reason: "오른쪽에서 데이터를 고르세요.",
            },
          }));
          await settleUntil(ctx, () => host.querySelector('.wfoot [data-act="next"]').disabled);
          out.half_cta_disabled = host.querySelector('.wfoot [data-act="next"]').disabled;
          out.half_block_reason = textOf(byId(ctx, "editorLinkBlock"));
          out.error = null;
        } catch (thrown) {
          ctx.fail(ERROR_CODES.PROBE_THREW, `throw:${thrown && thrown.message}`);
        } finally {
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
