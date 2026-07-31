/* 공유 상호작용 보존 헬퍼 — 전체 스냅샷 재렌더(innerHTML 재구성)가 사용자의 포커스·캐럿·
   스크롤을 조용히 뭉개지 않도록 렌더 직전 캡처하고 직후 복원한다(#28).

   설계 결정(전체 스냅샷+복원 vs 부분 패치)의 근거·재고경계는 docs/WEB_RENDER_PRESERVATION.md.
   요지: 이 앱의 푸시는 이산 액션(coarse)이라 타이핑 중 재구성이 없어 복원으로 충분하며,
   "멍청한 뷰·Python 상태 단일소유" 모델을 유지한다. 절차성(confirm-or-alarm)이 키스트로크
   단위 라이브 편집을 구조적으로 배척하므로 부분 패치의 이득은 구조적으로 오지 않는다.

   스크롤은 옵트인(data-preserve-scroll) — 진행로그처럼 바닥고정 의도가 있는 컨테이너를
   건드리지 않기 위함(무차별 보존 금지). 복원 대상은 재구성을 가로질러 같은 id 를 유지해야
   하며, 없으면 no-op(조용한 실패가 아니라 '보존할 것이 사라짐'이라는 정상 귀결). 결과 수명주기
   무효화는 컨트롤러(Python) 소유로 이 헬퍼 범위 밖 — 여기선 포커스·캐럿·스크롤 연속성만. */
(function () {
  function isTextField(el) {
    if (!el) return false;
    if (el.tagName === "TEXTAREA") return true;
    if (el.tagName !== "INPUT") return false;
    // setSelectionRange 가 유효한 타입만(number·email 등은 예외를 던짐).
    return /^(text|search|url|tel|password)$/i.test(el.type || "text");
  }

  /* renderFn 을 실행하되, 그 직전 포커스·캐럿·옵트인 스크롤을 캡처하고 직후 복원한다. */
  function around(renderFn) {
    // ---- 캡처 ----
    var act = document.activeElement;
    var focusId = act && act.id ? act.id : null;
    var selStart = null, selEnd = null, selDir = null;
    if (focusId && isTextField(act)) {
      try {
        selStart = act.selectionStart;
        selEnd = act.selectionEnd;
        selDir = act.selectionDirection;
      } catch (e) { /* 일부 상태에서 접근 불가 — 무시 */ }
    }
    var scrolls = [];
    var marked = document.querySelectorAll("[data-preserve-scroll][id]");
    for (var i = 0; i < marked.length; i++) {
      scrolls.push({ id: marked[i].id, top: marked[i].scrollTop, left: marked[i].scrollLeft });
    }

    // ---- 렌더 ----
    renderFn();

    // ---- 복원 ---- 포커스 먼저(preventScroll 로 컨테이너 스크롤 안 건드림), 스크롤은 그 뒤 확정.
    if (focusId) {
      var el = document.getElementById(focusId);
      if (el && el.focus) {
        try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
        if (selStart !== null && isTextField(el)) {
          try { el.setSelectionRange(selStart, selEnd, selDir || "none"); } catch (e2) { /* 무시 */ }
        }
      }
    }
    for (var j = 0; j < scrolls.length; j++) {
      var box = document.getElementById(scrolls[j].id);
      if (box) { box.scrollTop = scrolls[j].top; box.scrollLeft = scrolls[j].left; }
    }
  }

  window.Preserve = { around: around };
})();
