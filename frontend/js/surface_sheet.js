/* 전체 화면 펼침 면(#271/#272) — Modal 위에 「펼침 면이 열려 있다」는 사실과 닫힘 정산을 얹는다.
   종전에는 실 DOM 을 슬롯으로 이동/복귀시키는 기계(insertBefore/appendChild/스크롤 복원)를
   함께 들었는데, R4 가 면 내용 렌더를 React 소유로 옮기며 유일 제품 호출부의 이동 목록이
   비었고(R5-99 감사 B2 — 도달 불능 실측), 그 기계는 도착지인 React reconciliation 이 승계했다.
   cloneNode/innerHTML 복제 금지 규율은 그대로다 — 내용은 React 가 面 안에 직접 그린다. */
export function createSurfaceSheet({ modal }) {

const active = {};

function restore(id) {
  const entry = active[id];
  if (!entry) return;
  delete active[id];
  if (entry.afterRestore) entry.afterRestore();
}

function open(spec) {
  if (!spec || active[spec.modalId]) return;
  const modalEl = document.getElementById(spec.modalId);
  if (!modalEl) return;
  if (spec.beforeOpen) spec.beforeOpen();
  active[spec.modalId] = { afterRestore: spec.afterRestore || null };
  modal.open(spec.modalId, {
    initialFocus: spec.initialFocus || modalEl.querySelector("button, input, select, [tabindex]"),
    returnFocus: spec.returnFocus,
    // 이탈 가드(F3): false 를 돌려 닫기 요청을 소비한다 — Escape·닫기 버튼·프로그램 close 가
    // 전부 이 한 관문을 지난다(경로마다 가드를 걸면 하나는 반드시 빠진다).
    beforeClose: spec.beforeClose || null,
    onClose: function () {
      restore(spec.modalId);
      if (spec.onClose) spec.onClose();
    },
  });
}

function close(id) { if (active[id]) modal.close(id); }
function closeAndRestore(id) {
  if (!active[id]) return;
  modal.close(id);
  restore(id);
}
function isOpen(id) { return !!active[id]; }

/* 화면을 떠날 때의 일괄 회수(재작성 F7) — 열린 채 화면이 바뀌면 닫힘 정산(afterRestore·
   onClose)이 빠진 채 남의 화면 위에 면이 떠 있는다. 소유를 화면 전환으로 올려 어느 화면이
   늘어도 같은 회수가 걸리게 한다(가드의 완전성이 표면 수에 비례하지 않게). */
function closeAllAndRestore() {
  Object.keys(active).forEach(closeAndRestore);
}

return {
  open: open, close: close, closeAndRestore: closeAndRestore,
  closeAllAndRestore: closeAllAndRestore,
  isOpen: isOpen, restore: restore,
};
}
