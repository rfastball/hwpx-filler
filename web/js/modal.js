/* 공유 모달 헬퍼 — 커스텀 모달의 접근성 거동을 한 곳에 모은다(#27/#28/#86).

   각 화면(txt·template)이 classList 로 임시 개폐하던 것을 대체한다: 열 때 초기 포커스를
   모달 안으로 넣고, Escape 로 닫으며, 닫을 때 열기 직전 포커스(트리거)로 복귀시킨다.

   역할 분담: role="dialog"·aria-modal="true"·aria-labelledby 는 index.html 에 정적으로 있고
   (test_web_dom_contract 가 가드), 이 파일은 *동적* 거동만 소유한다.

   confirm()·prompt() 는 네이티브 window.confirm·window.prompt 를 대체하는 Promise 기반 API 다
   (#86, R-flow 부록 B-2). 네이티브 confirm 은 Enter-반사로 파괴 동작이 무의식 통과되는 결함
   클래스(F7)라, 확인은 기본 포커스를 취소(머무르기)에 두고 Escape 도 머무르기로 해소한다
   (결정 27/36/38). 파괴 동작의 수치 재진술은 호출부가 body 문안으로 싣는다.

   직렬화 계약(PR #92 리뷰 #1): 네이티브 다이얼로그의 동기 단일-실행(single-in-flight)을
   비블로킹 세계에서 재구성한다 —
   ① 포커스 트랩: Tab 순환을 최상위 모달 안에 가둔다(배경 버튼에 Tab+Enter 가 닿아
      두 번째 파괴 동작이 발화되는 경로 원천 차단).
   ② 재진입 가드: 확인/입력 다이얼로그(promise 다이얼로그)는 동시 1건 — 미결인 채 두 번째
      요청이 오면 안전측 거절(refusal) + loud(alert). 큐잉은 배제한다: 폼 모달이 confirm
      결과를 기다리며 열려 있는 합법 중첩(pool 재등록)에서 큐잉은 교착이고, 순차 표시는
      첫 확정으로 무효화된 문맥의 다이얼로그를 되살린다.
   ③ 모달 스택: 폼 모달 위 확인 다이얼로그 중첩(pool 재등록 흐름)은 스택으로 지원 —
      Escape·포커스 복귀·트랩 소유권이 최상위에서 아래로 정확히 승계된다.
   리스너는 열 때 부착·정착(settle) 시 해제라 재진입 가드와 함께 이중 바인딩이 불가능하다. */
(function () {
  const stack = []; // 열린 모달 스택 — {el, returnFocus, onCloseCb, closing}. 최상위가 Escape/트랩 소유.
  const CLOSE_FALLBACK_MS = 220; // CSS 160ms 전이가 없거나 transitionend가 누락될 때만 쓰는 안전망.
  let pendingDialog = false; // 진행 중 promise 다이얼로그(confirm/prompt) — 단일 실행 직렬화(#92 리뷰 #1)

  function top() { return stack.length ? stack[stack.length - 1] : null; }

  /* .modal 없는 대상 거절의 loud 경로(#132.4) — 조용한 no-op 를 개발자 표면에 재진술한다.
     사용자 표면(alert)은 쓰지 않는다: 이건 잘못된 요소를 넘긴 프로그래밍 오류라 콘솔이 임자다. */
  function rejectNonModal(op, id) {
    console.error("Modal." + op + ": 대상 #" + id + " 에 .modal 클래스가 없습니다 — 숨김 규칙은 "
      + ".modal.hidden 전용이라 .hidden 토글이 조용한 no-op 이 됩니다. 거절합니다.");
  }

  /* Tab 순환을 모달 카드 안에 가둔다(#92 리뷰 #1 트랩). 경계(첫↔끝)와 바깥 이탈에서만
     개입해 모달 내 자연 이동은 브라우저에 맡긴다. */
  function trapTab(e, el) {
    const list = Array.prototype.filter.call(
      el.querySelectorAll("button, input, textarea, select, [href], [tabindex]"),
      function (n) { return !n.disabled && n.tabIndex !== -1 && n.offsetParent !== null; });
    if (!list.length) { e.preventDefault(); return; }
    const first = list[0], last = list[list.length - 1];
    const cur = document.activeElement;
    const inside = el.contains(cur);
    if (e.shiftKey) {
      if (!inside || cur === first) { e.preventDefault(); last.focus(); }
    } else {
      if (!inside || cur === last) { e.preventDefault(); first.focus(); }
    }
  }

  function onKeydown(e) {
    const t = top();
    if (!t) return;
    // IME 조합 중 Escape는 조합 취소가 먼저다. keyCode 229는 구 WebView/IME 호환 경로.
    if (e.isComposing || e.keyCode === 229) return;
    if (t.closing && (e.key === "Escape" || e.key === "Tab")) {
      e.preventDefault();
      e.stopImmediatePropagation();
      return;
    }
    // Escape → 최상위 모달 닫기. 캡처 단계로 걸어 배경 핸들러보다 먼저 받는다.
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation(); // 같은 document의 전역 Escape가 아래 층까지 걷지 않게 한 겹 소비.
      close(t.el.id);
      return;
    }
    if (e.key === "Tab") trapTab(e, t.el);
  }

  function open(id, opts) {
    const el = document.getElementById(id);
    if (!el) return;
    opts = opts || {};
    // .modal 없는 대상은 시끄럽게 거절(#132.4) — 이 앱의 숨김 규칙은 `.modal.hidden` 뿐이라
    // .modal 없는 요소에 open 하면 `.hidden` 토글이 조용한 no-op(뜨지도 숨지도 않음)이 된다.
    // confirm-or-alarm: 조용히 삼키지 말고 거절한다. 현 소비자 9개는 전부 .modal 이라 무영향.
    if (!el.classList.contains("modal")) { rejectNonModal("open", id); return; }
    // 같은 모달 이중 open 은 무시(idempotent) — 스택 중복 엔트리로 닫힘 의미가 꼬이는 것 방지.
    for (let i = 0; i < stack.length; i++) if (stack[i].el === el) return;

    // H-16 개방 순서(바꾸지 말 것): 복귀점을 먼저 붙잡고 → 경량층을 모두 닫고 → 스택 등록 → 초점.
    // 메뉴 항목 자신은 closeAll()에서 사라질 수 있으므로 호출부가 넘긴 원 트리거가 최우선이다.
    const returnFocus = opts.returnFocus || document.activeElement;
    window.Popover.closeAll();
    stack.push({
      el: el,
      returnFocus: returnFocus, // 닫을 때 여기로 복귀(#28/H-16 메뉴 seam)
      onCloseCb: opts.onClose || null, // Escape·취소 등 어떤 경로로 닫혀도 통지
      closing: false,
    });
    el.style.setProperty("--modal-depth", String(stack.length - 1));
    el.classList.remove("is-closing");
    el.classList.remove("hidden");
    if (stack.length === 1) document.addEventListener("keydown", onKeydown, true);
    // 초기 포커스: 호출부가 지정한 요소 우선, 없으면 첫 포커스 가능 요소.
    const focusTo =
      opts.initialFocus ||
      el.querySelector("input, textarea, select, button, [tabindex]");
    if (focusTo && focusTo.focus) focusTo.focus();
  }

  function finishClose(entry) {
    if (!entry || !entry.closing) return;
    entry.closing = false;
    if (entry.closeTimer) clearTimeout(entry.closeTimer);
    if (entry.card && entry.onTransitionEnd) {
      entry.card.removeEventListener("transitionend", entry.onTransitionEnd);
    }
    entry.el.classList.add("hidden");
    entry.el.classList.remove("is-closing");
    entry.el.style.removeProperty("--modal-depth");
    const wasTop = top() === entry;
    const i = stack.indexOf(entry);
    if (i !== -1) stack.splice(i, 1);
    if (!stack.length) document.removeEventListener("keydown", onKeydown, true);
    // 제거/재렌더된 트리거는 focus()해도 복귀가 되지 않는다. 연결된 원 트리거만 되돌린다.
    // 하위 모달을 프로그램적으로 닫는 동안 새 최상위가 열린 경우에는 그 초점을 빼앗지 않는다.
    if (wasTop && entry.returnFocus && entry.returnFocus.focus && entry.returnFocus.isConnected !== false) {
      entry.returnFocus.focus();
    }
    if (entry.onCloseCb) entry.onCloseCb();
  }

  function close(id) {
    const el = document.getElementById(id);
    if (!el) return;
    // .modal 없는 대상엔 `.hidden` 을 얹어도 무효라 loud 고지(#132.4). 단 가드는 `.hidden` 토글만
    // 막고 스택 정리(리스너·포커스 해제)는 **막지 않는다** — 이미 열린 항목이면 정리가 빠질 때
    // keydown 캡처가 남아 Escape/Tab 이 앱 전역에서 갇힌다(리뷰 F1). 열린 항목은 open 가드를
    // 통과했으니 정상적으론 .modal 을 갖지만, 열린 뒤 클래스가 벗겨지는 미래 경로에도 정리는 돈다.
    let found = false;
    for (let i = stack.length - 1; i >= 0; i--) {
      if (stack[i].el !== el) continue;
      found = true;
      const entry = stack[i];
      if (entry.closing) return; // 퇴장 중 버튼/Escape 재입력은 한 번만 정착.
      if (!el.classList.contains("modal")) {
        rejectNonModal("close", id);
        entry.closing = true;
        finishClose(entry); // 클래스가 훼손돼도 스택/리스너/Promise는 반드시 정리.
        return;
      }
      // display:none을 즉시 적용하지 않는다. 전이 동안 전면 레이어가 pointer를 계속 막고,
      // 카드 자체만 비활성화되어 이중 확정이 불가능하다.
      entry.closing = true;
      el.classList.add("is-closing");
      entry.card = el.querySelector(".modal-card");
      entry.onTransitionEnd = function (e) {
        if (e.target === entry.card && (e.propertyName === "opacity" || e.propertyName === "transform")) {
          finishClose(entry);
        }
      };
      if (entry.card) entry.card.addEventListener("transitionend", entry.onTransitionEnd);
      entry.closeTimer = setTimeout(function () { finishClose(entry); }, CLOSE_FALLBACK_MS);
      break;
    }
    if (!found && !el.classList.contains("modal")) rejectNonModal("close", id);
  }

  function _setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text == null ? "" : String(text);
  }

  /* confirm/prompt 공용 스캐폴딩(#92 리뷰 #5) — 정착 단일화(settle-once)·리스너 부착/해제·
     골격 부재/재진입 거절을 한 번만 구현한다. spec:
       id/okId/cancelId  다이얼로그 골격 id 3종
       inputId           입력 다이얼로그면 입력칸 id(없으면 확인 다이얼로그)
       refusal           안전측 거절값(confirm=false, prompt=null)
       missingText       골격 부재 시 loud 문안(사용자 표면)
       prepare(els)      본문/라벨/초기값 채우기
       initialFocus(els) 초기 포커스 대상(confirm=취소, prompt=입력칸)
       okValue(els)      확인 시 resolve 값 */
  function _promiseModal(spec) {
    return new Promise(function (resolve) {
      const els = {
        root: document.getElementById(spec.id),
        ok: document.getElementById(spec.okId),
        cancel: document.getElementById(spec.cancelId),
        input: spec.inputId ? document.getElementById(spec.inputId) : null,
      };
      // 골격 부재(요소 결측)에 더해 root 의 .modal 결여도 여기서 거른다(Codex P2) — open 가드는
      // .modal 없는 root 를 조용히 early-return 하는데, 여기선 이미 pendingDialog 를 세우기 *전*이라
      // 그 전에 걸러야 onClose 미발화로 pendingDialog 가 영영 true 로 갇히는 교착을 피한다(이후 모든
      // confirm/prompt 가 재진입으로 거절되고 Escape 로도 못 푼다). root 가 .modal 을 잃는 건 정적
      // 계약(index.html class="modal")상 도달 불가하나, 가드가 그 가정에 기대지 않게 명시적으로 막는다.
      if (!els.root || !els.root.classList.contains("modal")
          || !els.ok || !els.cancel || (spec.inputId && !els.input)) {
        // 골격 부재/불량 = 안전측 거절 + loud(#92 리뷰 #4) — 조용한 no-op 는 confirm-or-alarm 위반.
        console.error("Modal: 다이얼로그 골격 부재/불량 — " + spec.id);
        window.alert(spec.missingText);
        resolve(spec.refusal);
        return;
      }
      if (pendingDialog) {
        // 재진입 거절(#92 리뷰 #1) — 미결 확인 위에 두 번째 확인을 얹지 않는다(native 단일 실행).
        // 조용한 거절이 아니라 loud: 사용자·개발자 둘 다에게 상태를 재진술한다.
        console.error("Modal: promise 다이얼로그 재진입 거절 — " + spec.id);
        window.alert("다른 확인 창이 이미 열려 있습니다. 먼저 끝내세요.");
        resolve(spec.refusal);
        return;
      }
      pendingDialog = true;
      spec.prepare(els);
      let settled = false;
      let closing = false;
      let closeValue = spec.refusal;
      function cleanup() {
        els.ok.removeEventListener("click", onOk);
        els.cancel.removeEventListener("click", onCancel);
        if (els.input) els.input.removeEventListener("keydown", onInputKey);
      }
      function settle(val) {
        if (settled) return; // 정착 단일화 — close 콜백과 버튼 클릭이 겹쳐도 1회만 해소
        settled = true;
        pendingDialog = false;
        resolve(val);
      }
      function finish(val) {
        if (settled || closing) return;
        closing = true;
        closeValue = val;
        cleanup();
        close(spec.id);
      }
      function onOk() { finish(spec.okValue(els)); }
      function onCancel() { finish(spec.refusal); }
      function onInputKey(e) {
        // 한글 IME 조합 확정 Enter 는 제출이 아니다(#92 리뷰 #3) — isComposing/229 선-가드.
        // 없으면 마지막 음절 확정 Enter 가 조합 중 문자열로 조기 제출돼 잘린 값이 조용히 저장된다.
        if (e.isComposing || e.keyCode === 229) return;
        if (e.key === "Enter") { e.preventDefault(); finish(spec.okValue(els)); }
      }
      els.ok.addEventListener("click", onOk);
      els.cancel.addEventListener("click", onCancel);
      if (els.input) els.input.addEventListener("keydown", onInputKey);
      // Escape·프로그램적 close는 안전측 거절, 버튼은 선택값. Promise는 160ms 퇴장 정착 뒤 해소해
      // 같은 공유 골격이 퇴장 중 재개방되는 경합을 막는다.
      open(spec.id, {
        initialFocus: spec.initialFocus(els),
        returnFocus: spec.returnFocus,
        onClose: function () {
          if (!closing) { closing = true; closeValue = spec.refusal; cleanup(); }
          settle(closeValue);
        },
      });
    });
  }

  /* 네이티브 window.confirm 대체(#86) — Promise<boolean>. 기본 포커스=취소(머무르기),
     Escape·복귀=머무르기(false). opts: { body, title?, confirmLabel?, cancelLabel? }. */
  function confirm(opts) {
    opts = opts || {};
    return _promiseModal({
      id: "confirmModal",
      okId: "confirmModalOk",
      cancelId: "confirmModalCancel",
      refusal: false,
      missingText: "확인 창을 열 수 없어 요청을 실행하지 않았습니다. 다시 시도하세요.",
      prepare: function (els) {
        _setText("confirmModalTitle", opts.title || "확인");
        _setText("confirmModalBody", opts.body || "");
        els.ok.textContent = opts.confirmLabel || "확인";
        els.cancel.textContent = opts.cancelLabel || "취소";
      },
      initialFocus: function (els) { return els.cancel; }, // 기본=머무르기, Enter-반사 파괴 차단(F7)
      okValue: function () { return true; },
      returnFocus: opts.returnFocus,
    });
  }

  /* 네이티브 window.prompt 대체(#86) — Promise<string|null>. 확인=입력 문자열(빈 문자열 포함),
     취소·Escape·복귀=null. 기본 포커스=입력칸, Enter=확인(IME 조합 확정 Enter 제외).
     opts: { body, value?, title? }. */
  function prompt(opts) {
    opts = opts || {};
    return _promiseModal({
      id: "promptModal",
      okId: "promptModalOk",
      cancelId: "promptModalCancel",
      inputId: "promptModalInput",
      refusal: null,
      missingText: "입력 창을 열 수 없어 요청을 실행하지 않았습니다. 다시 시도하세요.",
      prepare: function (els) {
        _setText("promptModalTitle", opts.title || "입력");
        _setText("promptModalBody", opts.body || "");
        els.input.value = opts.value == null ? "" : String(opts.value);
      },
      initialFocus: function (els) { return els.input; },
      okValue: function (els) { return els.input.value; },
      returnFocus: opts.returnFocus,
    });
  }

  window.Modal = { open, close, confirm, prompt };
})();
