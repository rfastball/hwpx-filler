/* 시트 선택 헬퍼 — 다중 시트 워크북 확정 게이트(#33). 에디터·실행 두 화면이 공유한다.

   조용한 첫 시트 로드 금지(confirm-or-alarm): pick_data_file 이 {needs_sheet, …} 를
   돌려주면 여기서 사용자에게 시트를 확정받아 load_data_sheet 로 로드한다. 취소·Escape 는
   겨눔 전체 중단(첫 시트 기본값으로 강등하지 않는다) — 로드가 아예 일어나지 않는다.

   반환(Promise): 로드된 파일명(성공) · "ERROR:…"(로드 실패) · null(취소=중단). 호출측은
   pickDataFile 의 일반 반환과 동일하게 처리하면 된다. */
(function () {
  const $ = (id) => document.getElementById(id);

  const escHtml = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /** needs_sheet 페이로드로 모달을 띄워 시트를 확정받고 그 시트로 로드한다. */
  function choose(screen, payload) {
    return new Promise((resolve) => {
      const list = $("sheetList");
      const sheets = payload.sheets || [];
      $("sheetModalFile").textContent = payload.name || "";
      // 첫 옵션에 초기 포커스를 주되(data-first), 선택은 명시 클릭 — 기본 강등 아님.
      list.innerHTML = sheets.map((s, i) =>
        `<button type="button" class="btn sheet-opt" data-sheet="${escHtml(s.name)}"` +
        `${i === 0 ? ' data-first="1"' : ""}>` +
        `<span class="mono sheet-name">${escHtml(s.name)}</span>` +
        `<span class="muted sheet-dim">${s.rows}행 × ${s.cols}열</span></button>`
      ).join("");

      let settled = false;
      function cleanup() {
        list.removeEventListener("click", onPick);
      }
      function finish(val) {
        if (settled) return;
        settled = true;
        cleanup();
        Modal.close("sheetModal"); // onClose(=onCancel) 가 재호출돼도 settled 로 무시됨
        resolve(val);
      }
      async function onPick(e) {
        const btn = e.target.closest(".sheet-opt");
        if (!btn) return;
        cleanup(); // 확정 즉시 추가 클릭 차단(이중 로드 방지)
        const r = await Bridge.loadDataSheet(screen, payload.path, btn.dataset.sheet);
        finish(r); // 파일명 또는 "ERROR:…"
      }
      function onCancel() { finish(null); } // 취소·Escape = 중단(첫 시트 강등 없음)

      list.addEventListener("click", onPick);
      Modal.open("sheetModal", {
        onClose: onCancel, // 취소 버튼·Escape·배경 등 어떤 닫힘도 취소로 귀결
        initialFocus: list.querySelector('[data-first="1"]'),
      });
    });
  }

  // 취소 버튼은 그저 모달을 닫는다 — 닫힘이 onClose(취소)로 귀결돼 null 로 해소된다.
  // 화면 무관 단일 배선(모달은 전역 1개)이라 여기서 1회 건다.
  const cancelBtn = document.getElementById("sheetCancel");
  if (cancelBtn) cancelBtn.addEventListener("click", () => Modal.close("sheetModal"));

  window.SheetPicker = { choose };
})();
