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
  const stack = []; // 열린 모달 스택 — {el, returnFocus, onCloseCb}. 최상위가 Escape/트랩 소유.
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
    // Escape → 최상위 모달 닫기. 캡처 단계로 걸어 배경 핸들러보다 먼저 받는다.
    if (e.key === "Escape") {
      e.preventDefault();
      close(t.el.id);
      return;
    }
    if (e.key === "Tab") trapTab(e, t.el);
  }

  function open(id, opts) {
    const el = document.getElementById(id);
    if (!el) return;
    // .modal 없는 대상은 시끄럽게 거절(#132.4) — 이 앱의 숨김 규칙은 `.modal.hidden` 뿐이라
    // .modal 없는 요소에 open 하면 `.hidden` 토글이 조용한 no-op(뜨지도 숨지도 않음)이 된다.
    // confirm-or-alarm: 조용히 삼키지 말고 거절한다. 현 소비자 9개는 전부 .modal 이라 무영향.
    if (!el.classList.contains("modal")) { rejectNonModal("open", id); return; }
    // 같은 모달 이중 open 은 무시(idempotent) — 스택 중복 엔트리로 닫힘 의미가 꼬이는 것 방지.
    for (let i = 0; i < stack.length; i++) if (stack[i].el === el) return;
    stack.push({
      el: el,
      returnFocus: document.activeElement, // 닫을 때 여기로 복귀(#28)
      onCloseCb: (opts && opts.onClose) || null, // Escape·취소 등 어떤 경로로 닫혀도 통지
    });
    el.classList.remove("hidden");
    if (stack.length === 1) document.addEventListener("keydown", onKeydown, true);
    // 초기 포커스: 호출부가 지정한 요소 우선, 없으면 첫 포커스 가능 요소.
    const focusTo =
      (opts && opts.initialFocus) ||
      el.querySelector("input, textarea, select, button, [tabindex]");
    if (focusTo && focusTo.focus) focusTo.focus();
  }

  function close(id) {
    const el = document.getElementById(id);
    if (!el) return;
    // open 과 대칭(#132.4) — .modal 없는 대상은 `.hidden` 을 얹어도 무효라 거절한다.
    if (!el.classList.contains("modal")) { rejectNonModal("close", id); return; }
    el.classList.add("hidden");
    for (let i = stack.length - 1; i >= 0; i--) {
      if (stack[i].el !== el) continue;
      const entry = stack.splice(i, 1)[0]; // 먼저 스택에서 빼고 콜백 — 재차 close() 해도 재진입 안전
      if (!stack.length) document.removeEventListener("keydown", onKeydown, true);
      if (entry.returnFocus && entry.returnFocus.focus) entry.returnFocus.focus(); // 트리거로 복귀(#28)
      if (entry.onCloseCb) entry.onCloseCb();
      break;
    }
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
      if (!els.root || !els.ok || !els.cancel || (spec.inputId && !els.input)) {
        // 골격 부재 = 안전측 거절 + loud(#92 리뷰 #4) — 조용한 no-op 는 confirm-or-alarm 위반.
        console.error("Modal: 다이얼로그 골격 부재 — " + spec.id);
        window.alert(spec.missingText);
        resolve(spec.refusal);
        return;
      }
      if (pendingDialog) {
        // 재진입 거절(#92 리뷰 #1) — 미결 확인 위에 두 번째 확인을 얹지 않는다(native 단일 실행).
        // 조용한 거절이 아니라 loud: 사용자·개발자 둘 다에게 상태를 재진술한다.
        console.error("Modal: promise 다이얼로그 재진입 거절 — " + spec.id);
        window.alert("다른 확인 창이 이미 열려 있습니다. 열려 있는 확인 창을 먼저 끝내 주세요.");
        resolve(spec.refusal);
        return;
      }
      pendingDialog = true;
      spec.prepare(els);
      let settled = false;
      function finish(val) {
        if (settled) return; // 정착 단일화 — close 콜백과 버튼 클릭이 겹쳐도 1회만 해소
        settled = true;
        pendingDialog = false;
        els.ok.removeEventListener("click", onOk);
        els.cancel.removeEventListener("click", onCancel);
        if (els.input) els.input.removeEventListener("keydown", onInputKey);
        close(spec.id);
        resolve(val);
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
      // Escape·프로그램적 close 등 어떤 닫힘 경로도 안전측 거절로 정착.
      open(spec.id, { initialFocus: spec.initialFocus(els), onClose: function () { finish(spec.refusal); } });
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
      missingText: "확인 창을 열 수 없어 요청을 실행하지 않았습니다. 프로그램 오류이니 다시 시도하고, 반복되면 알려 주세요.",
      prepare: function (els) {
        _setText("confirmModalTitle", opts.title || "확인");
        _setText("confirmModalBody", opts.body || "");
        els.ok.textContent = opts.confirmLabel || "확인";
        els.cancel.textContent = opts.cancelLabel || "취소";
      },
      initialFocus: function (els) { return els.cancel; }, // 기본=머무르기, Enter-반사 파괴 차단(F7)
      okValue: function () { return true; },
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
      missingText: "입력 창을 열 수 없어 요청을 실행하지 않았습니다. 프로그램 오류이니 다시 시도하고, 반복되면 알려 주세요.",
      prepare: function (els) {
        _setText("promptModalTitle", opts.title || "입력");
        _setText("promptModalBody", opts.body || "");
        els.input.value = opts.value == null ? "" : String(opts.value);
      },
      initialFocus: function (els) { return els.input; },
      okValue: function (els) { return els.input.value; },
    });
  }

  window.Modal = { open, close, confirm, prompt };
})();
