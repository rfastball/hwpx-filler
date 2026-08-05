/* 공유 모달 파사드 — 커스텀 모달의 접근성 거동을 한 곳에 모은다(#27/#28/#86 → R3-01 #410).
 *
 * 판정(중첩 스택·promise 직렬화·Escape/Tab/복귀 승계·keydown 시점)은 트리-불가지 엔진
 * (`src/overlay/engine.ts`)이 소유한다 — 합법 중첩(폼 모달 위 확인 다이얼로그, pool 재등록)
 * 이 legacy DOM 모달과 React 렌더 다이얼로그를 **한 스택**에 세우므로 판정이 두 벌이면
 * 같은 상태의 두 판정자다. 이 파일이 남아 소유하는 것:
 *
 * - **파사드 표면**(open/close/confirm/prompt/choose/restoreFocus — 소비 12 모듈 무변경)
 * - **legacy 9 모달의 DOM 집행**(hidden·is-closing 토글·160ms 전이 정착·트랩 이동·복귀)
 * - **문안·기본 라벨·danger 판정·거절 재진술** — 파괴 확정 감사(`Modal.confirm(` 라벨
 *   전수)와 문안 그물이 legacy 층 원문 위에서 완전하다는 형제 패킷 판정의 집행이다.
 *
 * confirm/prompt/choose 의 DOM 은 React host(`src/overlay/host.ts`)가 렌더·집행한다 —
 * 여기서는 해석된 spec 을 늦은 결속 슬롯으로 넘긴다. host 부재(부팅 창·마운트 실패)는
 * 조용한 무동작이 아니라 골격 부재와 같은 안전측 거절 + loud 다.
 *
 * 역할 분담: role="dialog"·aria-modal·aria-labelledby 는 legacy 모달은 index.html 이,
 * React 다이얼로그는 host 렌더가 정적으로 소유하고, 이 파일은 *동적* 거동만 소유한다.
 * 네이티브 confirm 의 Enter-반사 결함 클래스(F7)·기본 포커스=취소·Escape=머무르기
 * (결정 27/36/38) 계약은 그대로다. */
import { Popover } from "./popover.js";
import { overlayEngine, overlayDialogHost } from "../src/overlay/instance.ts";

const CLOSE_FALLBACK_MS = 220; // CSS 160ms 전이가 없거나 transitionend가 누락될 때만 쓰는 안전망.

/* .modal 없는 대상 거절의 loud 경로(#132.4) — 조용한 no-op 를 개발자 표면에 재진술한다.
   사용자 표면(alert)은 쓰지 않는다: 이건 잘못된 요소를 넘긴 프로그래밍 오류라 콘솔이 임자다. */
function rejectNonModal(op, id) {
  console.error("Modal." + op + ": 대상 #" + id + " 에 .modal 클래스가 없습니다 — 숨김 규칙은 "
    + ".modal.hidden 전용이라 .hidden 토글이 조용한 no-op 이 됩니다. 거절합니다.");
}

/* Tab 순환을 모달 카드 안에 가둔다(#92 리뷰 #1 트랩). 경계(첫↔끝)와 바깥 이탈에서만
   개입해 모달 내 자연 이동은 브라우저에 맡긴다. 반환은 개입 여부(preventDefault 조건). */
function trapTab(el, backward) {
  const list = Array.prototype.filter.call(
    el.querySelectorAll("button, input, textarea, select, [href], [tabindex]"),
    function (n) { return !n.disabled && n.tabIndex !== -1 && n.offsetParent !== null; });
  if (!list.length) return true;
  const first = list[0], last = list[list.length - 1];
  const cur = document.activeElement;
  const inside = el.contains(cur);
  if (backward) {
    if (!inside || cur === first) { last.focus(); return true; }
    return false;
  }
  if (!inside || cur === last) { first.focus(); return true; }
  return false;
}

/* 닫힘 뒤 초점 착지 — 트리거가 **되돌릴 수 있는 상태일 때만** 그리로 간다.
   `disabled` 요소의 `focus()` 는 조용한 no-op 라 초점이 `<body>` 로 떨어지고, 키보드
   사용자는 문서 맨 앞에서 다시 걸어와야 한다. 트리거가 닫히는 사이 비활성이 되는 건
   정상 경로다(면이 닫히면서 그 행동이 더는 불가능해지는 전이) — 그래서 이 불변식은
   호출자 규율이 아니라 여기서 세운다. 대안 착지는 **지금 서 있는 화면 루트**다:
   초점이 사라지는 것보다 화면 처음이 낫고, 프로그램 초점이라 tabindex 는 -1 이다. */
function restoreFocus(target) {
  // **되돌려 놓고 확인한다**: 어떤 요소가 초점을 받을 수 있는지의 규칙(비활성·분리·숨김·
  // inert·전이 중)을 여기서 재현하려 들면 그 목록이 곧 다음 결함이 된다. 실제로 옮겨
  // 보고 안 옮겨졌으면 대안으로 간다 — 판정을 흉내내지 않고 결과를 읽는다.
  if (target && target.focus && target.isConnected !== false) {
    target.focus();
    if (document.activeElement === target) return;
  }
  const screen = document.querySelector(".scr.on");
  if (!screen) return;
  if (!screen.hasAttribute("tabindex")) screen.setAttribute("tabindex", "-1");
  screen.focus();
}

/* legacy 모달 하나의 집행자 — 엔진 판정을 DOM 효과로 잇는다. React 다이얼로그의 집행자
   (host.ts makeExecutor)와 같은 계약 위의 다른 세계다. */
function legacyExecutor(el, opts, returnFocus) {
  let closeTimer = null;
  let card = null;
  let onTransitionEnd = null;
  return {
    show(depth) {
      el.style.setProperty("--modal-depth", String(depth));
      el.classList.remove("is-closing");
      el.classList.remove("hidden");
    },
    focusInitial() {
      // 초기 포커스: 호출부가 지정한 요소 우선, 없으면 첫 포커스 가능 요소.
      const focusTo =
        (opts && opts.initialFocus) ||
        el.querySelector("input, textarea, select, button, [tabindex]");
      if (focusTo && focusTo.focus) focusTo.focus();
    },
    beginClose() {
      // display:none을 즉시 적용하지 않는다. 전이 동안 전면 레이어가 pointer를 계속 막고,
      // 카드 자체만 비활성화되어 이중 확정이 불가능하다.
      el.classList.add("is-closing");
      card = el.querySelector(".modal-card");
      onTransitionEnd = function (e) {
        if (e.target === card && (e.propertyName === "opacity" || e.propertyName === "transform")) {
          overlayEngine.settleClose(el);
        }
      };
      if (card) card.addEventListener("transitionend", onTransitionEnd);
      closeTimer = setTimeout(function () { overlayEngine.settleClose(el); }, CLOSE_FALLBACK_MS);
    },
    finishClose() {
      if (closeTimer) clearTimeout(closeTimer);
      closeTimer = null;
      if (card && onTransitionEnd) card.removeEventListener("transitionend", onTransitionEnd);
      onTransitionEnd = null;
      el.classList.add("hidden");
      el.classList.remove("is-closing");
      el.style.removeProperty("--modal-depth");
    },
    trapTab(backward) { return trapTab(el, backward); },
    restoreFocus() { restoreFocus(returnFocus); },
  };
}

function open(id, opts) {
  const el = document.getElementById(id);
  if (!el) return;
  opts = opts || {};
  // .modal 없는 대상은 시끄럽게 거절(#132.4) — 이 앱의 숨김 규칙은 `.modal.hidden` 뿐이라
  // .modal 없는 요소에 open 하면 `.hidden` 토글이 조용한 no-op(뜨지도 숨지도 않음)이 된다.
  if (!el.classList.contains("modal")) { rejectNonModal("open", id); return; }
  // H-16 개방 순서(바꾸지 말 것): 복귀점을 먼저 붙잡고 → 경량층을 모두 닫고 → 스택 등록 → 초점.
  // 메뉴 항목 자신은 closeAll()에서 사라질 수 있으므로 호출부가 넘긴 원 트리거가 최우선이다.
  const returnFocus = opts.returnFocus || document.activeElement;
  Popover.closeAll();
  // 같은 모달 이중 open 은 엔진이 무시(idempotent) — 스택 중복으로 닫힘 의미가 꼬이는 것 방지.
  overlayEngine.open({
    host: el,
    executor: legacyExecutor(el, opts, returnFocus),
    beforeClose: opts.beforeClose || null, // 폼 dirty 가드: false면 닫기 요청을 소비
    onClose: opts.onClose || null, // Escape·취소 등 어떤 경로로 닫혀도 통지
  });
}

function close(id) {
  const el = document.getElementById(id);
  if (!el) return;
  // .modal 없는 대상엔 `.hidden` 을 얹어도 무효라 loud 고지(#132.4). 단 가드는 `.hidden` 토글만
  // 막고 스택 정리(리스너·포커스 해제)는 **막지 않는다** — 열린 항목이면 정리가 빠질 때
  // Escape/Tab 판정이 낡은 최상위에 갇힌다(리뷰 F1). 열린 항목은 open 가드를 통과했으니
  // 정상적으론 .modal 을 갖지만, 열린 뒤 클래스가 벗겨지는 미래 경로에도 정리는 돈다.
  if (!overlayEngine.isOpen(el)) {
    if (!el.classList.contains("modal")) rejectNonModal("close", id);
    return;
  }
  if (!el.classList.contains("modal")) {
    rejectNonModal("close", id);
    if (overlayEngine.requestClose(el) === "closing") {
      overlayEngine.settleClose(el); // 클래스가 훼손돼도 스택·판정·통지는 반드시 정리.
    }
    return;
  }
  overlayEngine.requestClose(el);
}

/* promise 다이얼로그 공통 관문 — host 부재·재진입의 안전측 거절과 문안·복귀점 포착을
   파사드가 소유하고, DOM 집행은 React host 로 넘긴다(#92 리뷰 #1·#4·#5 계약 승계). */
function dialogGate(kind, refusal, missingText) {
  const host = overlayDialogHost();
  if (host === null) {
    // 골격 부재/불량 = 안전측 거절 + loud(#92 리뷰 #4) — 조용한 no-op 는 confirm-or-alarm 위반.
    console.error("Modal: 다이얼로그 host 부재 — " + kind);
    window.alert(missingText);
    return { refuse: refusal };
  }
  if (overlayEngine.isDialogPending()) {
    // 재진입 거절(#92 리뷰 #1) — 미결 확인 위에 두 번째 확인을 얹지 않는다(native 단일 실행).
    // 조용한 거절이 아니라 loud: 사용자·개발자 둘 다에게 상태를 재진술한다.
    console.error("Modal: promise 다이얼로그 재진입 거절 — " + kind);
    window.alert("다른 확인 창이 이미 열려 있습니다. 먼저 끝내세요.");
    return { refuse: refusal };
  }
  return { host: host };
}

/* 네이티브 window.confirm 대체(#86) — Promise<boolean>. 기본 포커스=취소(머무르기),
   Escape·복귀=머무르기(false). opts: { body, title?, confirmLabel?, cancelLabel?, danger? }.
   danger 는 영구 파일/정의 삭제·덮어쓰기처럼 내구 파괴인 확정에만 쓴다(#219). */
function confirm(opts) {
  opts = opts || {};
  const gate = dialogGate("confirmModal", false,
    "확인 창을 열 수 없어 요청을 실행하지 않았습니다. 다시 시도하세요.");
  if (!gate.host) return Promise.resolve(gate.refuse);
  const returnFocus = opts.returnFocus || document.activeElement;
  Popover.closeAll();
  return gate.host.confirm({
    title: opts.title || "확인",
    body: opts.body || "",
    confirmLabel: opts.confirmLabel || "확인",
    cancelLabel: opts.cancelLabel || "취소",
    // 같은 안정 버튼을 재사용하므로 host 가 양방향 토글한다 — danger 뒤 중립 confirm 이
    // 빨갛게 남거나 primary 뒤 danger 가 파란색으로 남는 상태 누수 차단.
    danger: !!opts.danger,
    returnFocus: returnFocus,
  });
}

/* 네이티브 window.prompt 대체(#86) — Promise<string|null>. 확인=입력 문자열(빈 문자열 포함),
   취소·Escape·복귀=null. 기본 포커스=입력칸, Enter=확인(IME 조합 확정 Enter 제외).
   opts: { body, value?, title? }. */
function prompt(opts) {
  opts = opts || {};
  const gate = dialogGate("promptModal", null,
    "입력 창을 열 수 없어 요청을 실행하지 않았습니다. 다시 시도하세요.");
  if (!gate.host) return Promise.resolve(gate.refuse);
  const returnFocus = opts.returnFocus || document.activeElement;
  Popover.closeAll();
  return gate.host.prompt({
    title: opts.title || "입력",
    body: opts.body || "",
    value: opts.value == null ? "" : String(opts.value),
    validate: opts.validate,
    returnFocus: returnFocus,
  });
}

/* 답이 셋인 자리(재작성 F7 — patch 처분). Promise<string>: 주 행동·보조 행동·거절.
   Escape·복귀·프로그램적 close = **거절 값**(머무르기)이라 창을 닫아 편집을 잃는 경로가
   없다. 라벨은 호출부가 준다 — 이 골격은 "셋 중 하나"라는 형상만 소유한다.
   opts: { title?, body, choices: [주, 보조, 거절] }(각 {value,label}). */
function choose(opts) {
  opts = opts || {};
  const list = opts.choices || [];
  const primary = list[0] || { value: "ok", label: "확인" };
  const alt = list[1] || { value: "alt", label: "" };
  const refusal = list[2] || { value: "cancel", label: "취소" };
  const gate = dialogGate("chooseModal", refusal.value,
    "선택 창을 열 수 없어 요청을 실행하지 않았습니다. 다시 시도하세요.");
  if (!gate.host) return Promise.resolve(gate.refuse);
  const returnFocus = opts.returnFocus || document.activeElement;
  Popover.closeAll();
  return gate.host.choose({
    title: opts.title || "선택",
    body: opts.body || "",
    primary: primary,
    alt: alt,
    refusal: refusal,   // 기본 포커스=거절(안전측, confirm 과 같은 규율)은 host 계약이다.
    returnFocus: returnFocus,
  });
}

// `restoreFocus` 도 내보낸다(9R P2) — 몰입 편집기 이탈도 「띄운 자리로 초점을 되돌린다」는
// 같은 사건이다(면을 닫는 것과 화면을 되돌리는 것의 차이일 뿐). 규칙을 저쪽에서 다시
// 쓰면 되돌림 판정이 두 벌이 되고, 이 함수가 일부러 피한 함정(분리·비활성 요소 흉내내기)을
// 그 두 번째 사본이 되풀이한다.
export const Modal = { open, close, confirm, prompt, choose, restoreFocus };
