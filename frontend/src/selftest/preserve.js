/* selftest 전용 상호작용 보존 헬퍼 — 종전 legacy 렌더러의 innerHTML 재구성이 포커스·캐럿·
   스크롤을 뭉개지 않게 하던 제품 헬퍼(#28)였다. R4 가 렌더 소유를 React reconciliation 으로
   옮기며 제품 소비자가 0 이 됐고(서브트리 재구성 자체가 없어 되찾을 포커스가 생기지 않는다),
   R5-99 감사 B2 가 그 0 을 실측해 제품 트리(frontend/js/)에서 selftest 소유로 옮겼다.

   남은 소비자는 `probes/boot_routing_overlay.js` 의 `preserve` 프로브 하나다 — 합성 픽스처로
   「innerHTML 재구성을 가로지르는 보존」 기제 자체를 검사한다. 실화면 보존 회귀는 이 헬퍼를
   쓰지 않는 `preserve_real` 프로브(React 렌더 경로)가 진다. 설계 결정 원문·재고경계는
   docs/WEB_RENDER_PRESERVATION.md.

   스크롤은 옵트인(data-preserve-scroll). 복원 대상은 재구성을 가로질러 같은 id 를 유지해야
   하며, 없으면 no-op(조용한 실패가 아니라 '보존할 것이 사라짐'이라는 정상 귀결). */
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

export const Preserve = { around: around };
