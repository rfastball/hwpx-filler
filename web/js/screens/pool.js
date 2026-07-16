/* 데이터 관리(pool) 화면 — 브리지로 링1 DatasetPoolViewModel 과 왕복(#26 단위 A, #4).
   안정 DOM(index.html) + Python 이 window.__push('pool', snapshot) 로 값만 채운다(tpl 패턴).
   표현 계층(카드 렌더·확인 라운드트립·등록 모달)만 여기서 만든다 — VM 로직 아님.

   확인 라운드트립 2곳(confirm-or-alarm): 삭제(파괴)·동명 재등록(조용한 참조 재지정 함정).
   나라장터 등록은 동결로 미노출(기존 nara 항목 표시는 유지 — 숨김 금지).

   기대 DOM(통합 단계에서 index.html 에 추가):
   #scr-pool 섹션 안에 #poolCount #poolList #poolResult #btnPoolRegister,
   등록 모달 #poolRegModal(#poolRegName #poolRegPath #poolRegSheet #poolRegNote
   #poolRegCancel #poolRegOk). 파일 선택은 통합 단계에서 브리지 메서드 추가 예정
   (제안: pick_pool_data_file() — 경로만 반환, 컨트롤러 로드 없음) — 그때까지 경로 직접 입력. */
(function () {
  const SCREEN = "pool";
  const $ = (id) => document.getElementById(id);

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    $("poolCount").textContent = s.count || "";
    renderRows(s);
    renderResult(s);
  }

  /* 풀 카드 — 이름 + 종류 + 상태 배지 + 참조 요약 + 상태별 게이트 액션(불투명 div). */
  function renderRows(s) {
    const host = $("poolList");
    const rows = s.rows || [];
    if (!rows.length) {
      host.innerHTML =
        `<div class="tplcard muted">등록된 데이터가 없습니다 — [데이터 등록]으로 추가하거나, 작업 저장 시 선언한 데이터가 여기 모입니다.</div>`;
      return;
    }
    host.innerHTML = rows.map((r) => {
      const acts = (r.actions || []).map((a) =>
        `<button class="btn sm" data-act="${esc(a.key)}" data-name="${esc(r.name)}">${esc(a.label)}</button>`
      ).join("");
      const note = r.note ? `<div class="tplcard-meta muted">${esc(r.note)}</div>` : "";
      return `<div class="tplcard">
        <div class="tplcard-top"><span class="tplcard-name" title="${esc(r.reference)}">${esc(r.name)}</span>
          <span class="pill muted">${esc(r.kind_label)}</span>
          <span class="pill ${esc(r.badge_level)}">${esc(r.badge_label)}</span></div>
        <div class="tplcard-meta muted">${esc(r.reference)}</div>${note}
        <div class="tplcard-acts">${acts}</div></div>`;
    }).join("");
  }

  function renderResult(s) {
    const r = s.result || { text: "", level: "muted" };
    const el = $("poolResult");
    el.textContent = r.text || "";
    el.className = "run-result " + (r.level === "muted" ? "" : r.level);
  }

  /* ---- 상태/삭제 액션 ---- */
  async function onListClick(e) {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    const name = btn.dataset.name;
    if (act === "delete") {
      // 파괴 확정 — 1차=재진술(needs_confirm), 확인 시에만 2차 삭제(조용한 소실 금지).
      const res = await Bridge.call(SCREEN, "delete", { name });
      if (res && res.needs_confirm && window.confirm(res.confirm_text + "\n\n삭제할까요?")) {
        Bridge.call(SCREEN, "delete", { name, confirm: true });
      }
    } else {
      Bridge.call(SCREEN, act, { name });  // archive/retire/activate — 비파괴 즉시
    }
  }

  /* ---- 등록 모달(참조만 — 경로 포인터) ---- */
  function openRegModal() {
    $("poolRegName").value = "";
    $("poolRegPath").value = "";
    $("poolRegSheet").value = "";
    $("poolRegNote").value = "";
    window.Modal.open("poolRegModal", { initialFocus: $("poolRegName") });
  }

  function closeRegModal() { window.Modal.close("poolRegModal"); }

  async function submitRegModal() {
    const payload = {
      name: $("poolRegName").value,
      path: $("poolRegPath").value,
      sheet: $("poolRegSheet").value,
      note: $("poolRegNote").value,
    };
    let res = await Bridge.call(SCREEN, "register_excel", payload);
    if (res && res.needs_confirm) {
      // 동명 재등록 = 기존 참조 재지정 — 조용히 덮지 않고 확인 승격.
      if (!window.confirm(res.confirm_text + "\n\n계속할까요?")) return;
      res = await Bridge.call(SCREEN, "register_excel", { ...payload, confirm: true });
    }
    if (res && res.ok === false) {
      // confirm-or-alarm: 검증·충돌 실패는 조용히 삼키지 않고 시끄럽게(결과줄에도 재진술됨).
      window.alert(res.error);
      return;
    }
    closeRegModal();
  }

  function wire() {
    $("poolList").addEventListener("click", onListClick);
    $("btnPoolRegister").addEventListener("click", openRegModal);
    $("poolRegCancel").addEventListener("click", closeRegModal);
    $("poolRegOk").addEventListener("click", submitRegModal);
    // 네이티브 피커(경로만 — 로드 없음). 취소(null)면 입력 유지.
    $("poolRegBrowse").addEventListener("click", async () => {
      const p = await Bridge.pickPoolDataFile();
      if (p) $("poolRegPath").value = p;
    });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    render(await Bridge.initial(SCREEN));
  }

  window.PoolScreen = { init };
})();
