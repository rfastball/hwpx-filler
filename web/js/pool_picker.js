/* 등록 데이터 선택 헬퍼 — 데이터셋 풀(활성 참조) 겨눔 모달(#26/#6). run·matrix·txt 공유.

   sheet_picker 와 같은 결: 목록을 보여주고 사용자가 명시 클릭으로 확정한다(기본 강등 없음).
   취소·Escape 는 겨눔 전체 중단(null 해소 — 로드가 일어나지 않는다).

   나라장터 항목은 **숨기지 않고 표시**하되, 선택하면 백엔드 관문(load_pool)이 동결 거절
   문구를 돌려주고 모달 안에 시끄럽게 재진술한다 — 다른 항목을 고르거나 취소할 수 있다
   (confirm-or-alarm: 조용한 숨김도, 조용한 실패도 금지).

   모달 DOM 은 첫 사용 때 동적으로 만든다(#26 단위 격리 — index.html 은 통합 단계 소유).
   role/aria 는 정적 모달(sheetModal)과 동형으로 부여한다. 통합 단계에서 정적 DOM 으로
   옮기고 dom_contract 단언을 붙이는 선택지가 있다(그 경우 build() 는 기존 요소를 재사용).

   반환(Promise): 로드된 소스 라벨(성공) · null(취소=중단). 로드 실패는 모달 안 재진술이라
   호출측으로는 성공·취소 둘만 흘러간다. */
(function () {
  const $ = (id) => document.getElementById(id);

  function escHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  /* 모달 골격 — 이미 있으면(정적 이관 후 등) 재사용, 없으면 1회 생성. */
  function build() {
    if ($("poolModal")) return;
    const el = document.createElement("div");
    el.id = "poolModal";
    el.className = "modal hidden";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-labelledby", "poolTitle");
    el.innerHTML =
      `<div class="modal-card">
        <h3 id="poolTitle">등록 데이터 선택</h3>
        <p class="muted" style="font-size:12px;margin:4px 0 8px">활성 상태의 등록 데이터(참조)만
          실행 후보입니다 — 선택하면 지금 시점의 원본을 다시 읽어 옵니다.</p>
        <div id="poolList" class="sheet-list"></div>
        <p id="poolNote" class="note dangerbox" style="display:none;white-space:pre-line"></p>
        <div class="modal-actions">
          <button class="btn" id="poolCancel">취소</button>
        </div>
      </div>`;
    document.body.appendChild(el);
    // 취소 버튼은 그저 모달을 닫는다 — 닫힘이 onClose(취소)로 귀결돼 null 로 해소된다.
    $("poolCancel").addEventListener("click", () => Modal.close("poolModal"));
  }

  /** 활성 풀 목록 모달을 띄워 항목을 확정받고 그 참조로 로드한다. */
  async function choose(screen) {
    build();
    const res = await Bridge.call(screen, "pool_sources", {});
    const items = (res && res.items) || [];
    return new Promise((resolve) => {
      const list = $("poolList");
      const note = $("poolNote");
      note.style.display = "none";
      note.textContent = "";
      list.innerHTML = items.length
        ? items.map((it, i) =>
            `<button type="button" class="btn sheet-opt pool-opt" data-name="${escHtml(it.name)}"` +
            `${i === 0 ? ' data-first="1"' : ""}>` +
            `<span class="mono sheet-name">${escHtml(it.name)}</span>` +
            `<span class="muted sheet-dim">${escHtml(it.kind_label)} · ${escHtml(it.reference)}</span></button>`
          ).join("")
        : `<p class="muted" style="font-size:12px">활성 등록 데이터가 없습니다 — 작업 저장 시
           선언한 데이터가 여기 등록되거나, 데이터 관리 화면에서 추가할 수 있습니다.</p>`;

      let settled = false;
      let loading = false; // 로드 중 추가 클릭 차단(이중 로드 방지)
      function cleanup() {
        list.removeEventListener("click", onPick);
      }
      function finish(val) {
        if (settled) return;
        settled = true;
        cleanup();
        Modal.close("poolModal"); // onClose(=onCancel) 가 재호출돼도 settled 로 무시됨
        resolve(val);
      }
      async function onPick(e) {
        const btn = e.target.closest(".pool-opt");
        if (!btn || loading) return;
        loading = true;
        const r = await Bridge.call(screen, "load_pool", { name: btn.dataset.name });
        loading = false;
        if (r && r.ok) { finish(r.label); return; }
        // 실패(나라 동결·죽은 참조·레코드 0건) — 모달 안에서 시끄럽게 재진술, 재선택 허용.
        note.textContent = "⚠ " + ((r && r.error) || "등록 데이터를 불러올 수 없습니다.");
        note.style.display = "block";
      }
      function onCancel() { finish(null); } // 취소·Escape = 중단(조용한 강등 없음)

      list.addEventListener("click", onPick);
      Modal.open("poolModal", {
        onClose: onCancel, // 취소 버튼·Escape 등 어떤 닫힘도 취소로 귀결
        initialFocus: list.querySelector('[data-first="1"]') || $("poolCancel"),
      });
    });
  }

  window.PoolPicker = { choose };
})();
