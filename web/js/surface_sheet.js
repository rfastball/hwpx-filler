/* 전체 화면 펼침 면(#271/#272) — 이미 배선된 실 DOM을 슬롯으로 이동하고 정확히 복귀시킨다.
   cloneNode/innerHTML 복제는 입력값·스크롤·리스너·서버 push의 목적지를 갈라놓으므로 금지한다. */
(function () {
  const active = {};

  function restore(id) {
    const entry = active[id];
    if (!entry) return;
    entry.moves.forEach(function (m) {
      if (m.next && m.next.parentNode === m.parent) m.parent.insertBefore(m.el, m.next);
      else m.parent.appendChild(m.el);
      // 펼친 면에서 내부 오버플로가 사라지면 Chromium이 scrollTop을 0으로 클램프한다.
      // 원 그릇으로 돌아와 크기가 복구된 뒤 개방 직전 위치를 다시 적용한다.
      m.scrolls.forEach(function (s) { s.el.scrollTop = s.top; s.el.scrollLeft = s.left; });
    });
    delete active[id];
    if (entry.afterRestore) entry.afterRestore();
  }

  function open(spec) {
    if (!spec || active[spec.modalId]) return;
    const modal = document.getElementById(spec.modalId);
    if (!modal) return;
    if (spec.beforeOpen) spec.beforeOpen();
    const moves = [];
    (spec.moves || []).forEach(function (pair) {
      const el = document.getElementById(pair.id);
      const slot = document.getElementById(pair.slotId);
      if (!el || !slot) return;
      const scrollEls = [el].concat(Array.prototype.slice.call(el.querySelectorAll("[data-preserve-scroll]")));
      const scrolls = scrollEls.map(function (s) {
        return { el: s, top: s.scrollTop, left: s.scrollLeft };
      });
      moves.push({ el: el, parent: el.parentNode, next: el.nextSibling, scrolls: scrolls });
      slot.appendChild(el);
    });
    active[spec.modalId] = { moves: moves, afterRestore: spec.afterRestore || null };
    window.Modal.open(spec.modalId, {
      initialFocus: spec.initialFocus || modal.querySelector("button, input, select, [tabindex]"),
      returnFocus: spec.returnFocus,
      onClose: function () { restore(spec.modalId); },
    });
  }

  function close(id) { if (active[id]) window.Modal.close(id); }
  function isOpen(id) { return !!active[id]; }

  window.SurfaceSheet = { open: open, close: close, isOpen: isOpen, restore: restore };
})();
