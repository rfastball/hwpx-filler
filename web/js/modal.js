/* 공유 모달 헬퍼 — 커스텀 모달의 접근성 거동을 한 곳에 모은다(#27/#28/#86).

   각 화면(txt·template)이 classList 로 임시 개폐하던 것을 대체한다: 열 때 초기 포커스를
   모달 안으로 넣고, Escape 로 닫으며, 닫을 때 열기 직전 포커스(트리거)로 복귀시킨다.

   역할 분담: role="dialog"·aria-modal="true"·aria-labelledby 는 index.html 에 정적으로 있고
   (test_web_dom_contract 가 가드), 이 파일은 *동적* 거동만 소유한다. 포커스 트랩(Tab 순환
   가둠)은 이번 범위 밖 — aria-modal 이 AT 에게 바깥을 비활성으로 알리며, #27/#28 잔여 스코프는
   초기포커스·복귀·Escape 세 가지다(범위를 좁게 유지).

   confirm()·prompt() 는 네이티브 window.confirm·window.prompt 를 대체하는 Promise 기반 API 다
   (#86, R-flow 부록 B-2). 네이티브 confirm 은 Enter-반사로 파괴 동작이 무의식 통과되는 결함
   클래스(F7)라, 확인은 기본 포커스를 취소(머무르기)에 두고 Escape 도 머무르기로 해소한다
   (결정 27/36/38). 파괴 동작의 수치 재진술은 호출부가 body 문안으로 싣는다. */
(function () {
  let active = null; // 현재 열린 모달 요소(단일 — 동시 다중 모달 없음)
  let returnFocus = null; // 열기 직전 포커스 요소 — 닫을 때 복귀 대상(#28)
  let onCloseCb = null; // 닫힐 때(Escape 포함) 1회 호출 — 시트 선택 취소=중단 판정용(#33)

  function onKeydown(e) {
    // Escape → 활성 모달 닫기. 캡처 단계로 걸어 배경 핸들러보다 먼저 받는다.
    if (e.key === "Escape" && active) {
      e.preventDefault();
      close(active.id);
    }
  }

  function open(id, opts) {
    const el = document.getElementById(id);
    if (!el) return;
    returnFocus = document.activeElement; // 닫을 때 여기로 복귀
    onCloseCb = (opts && opts.onClose) || null; // Escape·취소 등 어떤 경로로 닫혀도 통지
    el.classList.remove("hidden");
    active = el;
    document.addEventListener("keydown", onKeydown, true);
    // 초기 포커스: 호출부가 지정한 요소 우선, 없으면 첫 포커스 가능 요소.
    const focusTo =
      (opts && opts.initialFocus) ||
      el.querySelector("input, textarea, select, button, [tabindex]");
    if (focusTo && focusTo.focus) focusTo.focus();
  }

  function close(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add("hidden");
    if (active === el) {
      document.removeEventListener("keydown", onKeydown, true);
      active = null;
      if (returnFocus && returnFocus.focus) returnFocus.focus(); // 트리거로 복귀(#28)
      returnFocus = null;
      const cb = onCloseCb; // 널로 먼저 비운 뒤 호출 — 콜백이 재차 close() 해도 재진입 안전
      onCloseCb = null;
      if (cb) cb();
    }
  }

  function _setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text == null ? "" : String(text);
  }

  /* 네이티브 window.confirm 대체(#86) — Promise<boolean>. 기본 포커스=취소(머무르기),
     Escape·복귀=머무르기(false). 골격이 없으면 안전측으로 거절(false) — 조용한 파괴 금지.
     opts: { body, title?, confirmLabel?, cancelLabel? }. */
  function confirm(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      const el = document.getElementById("confirmModal");
      const okBtn = document.getElementById("confirmModalOk");
      const cancelBtn = document.getElementById("confirmModalCancel");
      if (!el || !okBtn || !cancelBtn) {
        resolve(false); // 골격 부재 = 안전측 거절(파괴 동작이 조용히 통과하지 않게)
        return;
      }
      _setText("confirmModalTitle", opts.title || "확인");
      _setText("confirmModalBody", opts.body || "");
      okBtn.textContent = opts.confirmLabel || "확인";
      cancelBtn.textContent = opts.cancelLabel || "취소";
      let settled = false;
      function finish(val) {
        if (settled) return;
        settled = true;
        okBtn.removeEventListener("click", onOk);
        cancelBtn.removeEventListener("click", onCancel);
        close("confirmModal");
        resolve(val);
      }
      function onOk() { finish(true); }
      function onCancel() { finish(false); }
      okBtn.addEventListener("click", onOk);
      cancelBtn.addEventListener("click", onCancel);
      // 초기 포커스=취소, Escape·복귀 콜백=머무르기(false). Enter-반사 파괴 차단(F7).
      open("confirmModal", { initialFocus: cancelBtn, onClose: function () { finish(false); } });
    });
  }

  /* 네이티브 window.prompt 대체(#86) — Promise<string|null>. 확인=입력 문자열(빈 문자열 포함),
     취소·Escape·복귀=null. 기본 포커스=입력칸, Enter=확인. opts: { body, value?, title? }. */
  function prompt(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      const el = document.getElementById("promptModal");
      const okBtn = document.getElementById("promptModalOk");
      const cancelBtn = document.getElementById("promptModalCancel");
      const input = document.getElementById("promptModalInput");
      if (!el || !okBtn || !cancelBtn || !input) {
        resolve(null); // 골격 부재 = 취소로 해소(조용한 진행 금지)
        return;
      }
      _setText("promptModalTitle", opts.title || "입력");
      _setText("promptModalBody", opts.body || "");
      input.value = opts.value == null ? "" : String(opts.value);
      let settled = false;
      function finish(val) {
        if (settled) return;
        settled = true;
        okBtn.removeEventListener("click", onOk);
        cancelBtn.removeEventListener("click", onCancel);
        input.removeEventListener("keydown", onKey);
        close("promptModal");
        resolve(val);
      }
      function onOk() { finish(input.value); }
      function onCancel() { finish(null); }
      function onKey(e) {
        if (e.key === "Enter") { e.preventDefault(); finish(input.value); }
      }
      okBtn.addEventListener("click", onOk);
      cancelBtn.addEventListener("click", onCancel);
      input.addEventListener("keydown", onKey);
      open("promptModal", { initialFocus: input, onClose: function () { finish(null); } });
    });
  }

  window.Modal = { open, close, confirm, prompt };
})();
