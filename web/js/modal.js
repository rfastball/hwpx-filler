/* 공유 모달 헬퍼 — 커스텀 모달의 접근성 거동을 한 곳에 모은다(#27/#28).

   각 화면(txt·template)이 classList 로 임시 개폐하던 것을 대체한다: 열 때 초기 포커스를
   모달 안으로 넣고, Escape 로 닫으며, 닫을 때 열기 직전 포커스(트리거)로 복귀시킨다.

   역할 분담: role="dialog"·aria-modal="true"·aria-labelledby 는 index.html 에 정적으로 있고
   (test_web_dom_contract 가 가드), 이 파일은 *동적* 거동만 소유한다. 포커스 트랩(Tab 순환
   가둠)은 이번 범위 밖 — aria-modal 이 AT 에게 바깥을 비활성으로 알리며, #27/#28 잔여 스코프는
   초기포커스·복귀·Escape 세 가지다(범위를 좁게 유지). 덮어쓰기·삭제 확인은 네이티브
   window.confirm 이라 이 헬퍼 대상이 아니다. */
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

  window.Modal = { open, close };
})();
