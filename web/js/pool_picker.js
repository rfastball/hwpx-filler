/* 등록 데이터 선택 헬퍼 — 데이터셋 풀(활성 참조) 겨눔 모달(#26/#6). run·txt 공유.

   sheet_picker 와 같은 결: 목록을 보여주고 사용자가 명시 클릭으로 확정한다(기본 강등 없음).
   취소·Escape 는 겨눔 전체 중단(null 해소 — 로드가 일어나지 않는다). 단 **로드 중에는
   취소·Escape 를 막고 그 사실을 표기**한다(r3 C8): load_pool 은 백엔드 화면 VM 을 즉시
   갈아끼우는 호출이라 중간 취소가 불가능하다 — '취소됐다'면서 화면 데이터가 바뀌는
   조용한 거짓말 대신, 완료(성공 또는 실패 표시)까지 닫힘을 차단한다(confirm-or-alarm).

   나라장터 항목은 **숨기지 않고 표시**하되, 선택하면 백엔드 관문(load_pool)이 동결 거절
   문구를 돌려주고 모달 안에 시끄럽게 재진술한다 — 다른 항목을 고르거나 취소할 수 있다
   (confirm-or-alarm: 조용한 숨김도, 조용한 실패도 금지).

   손상 데이터셋(C5): 백엔드가 격리 수집해 corrupted_note 로 병기한 "손상 N건 — 데이터
   관리에서 확인"을 목록 아래 상주 렌더한다 — 피커에서 무표시 증발 금지(조치는 데이터
   관리 화면 몫).

   모달 골격(#poolModal)은 index.html 정적 DOM 이 소유한다(r3 K12 — role/aria-labelledby 는
   test_web_dom_contract 가 가드). build() 는 골격이 없을 때(비정상 임베딩 등)만 1회 생성하는
   방어 분기와, 골격 출처와 무관한 취소 버튼 1회 배선만 담당한다.

   반환(Promise): 로드된 소스 라벨(성공) · null(취소=중단). 로드 실패는 모달 안 재진술이라
   호출측으로는 성공·취소 둘만 흘러간다. */
(function () {
  const $ = (id) => document.getElementById(id);

  const escHtml = window.escHtml;  // 공유 이스케이퍼(esc.js)

  let loading = false; // 로드 중 — 추가 클릭·취소·Escape 차단(C8: choose 회차와 취소 버튼이 공유)
  let wired = false;   // 취소 버튼 1회 배선 가드 — build() 재호출 시 리스너 중복 방지

  // 로드 중 취소 시도에 대한 시끄러운 표기(C8) — 조용한 무시 금지.
  function noteLoadingBlock() {
    const note = $("poolNote");
    note.textContent = "⚠ 불러오는 중입니다 — 완료(성공 또는 실패 표시)까지 취소할 수 없습니다.";
    note.style.display = "block";
  }

  /* 모달 골격 확보 — 정적 골격(index.html)을 재사용하고, 없으면(비정상 임베딩) 1회 생성.
     목록 id 는 #poolPickList — 데이터 관리 화면(#scr-pool)의 정적 #poolList 와 **다른** id 다.
     둘이 같으면 getElementById 가 문서순 첫(정적) 요소로 해소돼 옵션 버튼이 숨은 화면에
     주입되고 피커가 빈 채로 뜬다(등록 데이터 겨눔 전면 사망). id 충돌 금지. */
  function build() {
    if (!$("poolModal")) {
      const el = document.createElement("div");
      el.id = "poolModal";
      el.className = "modal hidden";
      el.setAttribute("role", "dialog");
      el.setAttribute("aria-modal", "true");
      el.setAttribute("aria-labelledby", "poolTitle");
      el.innerHTML =
        `<div class="modal-card">
          <h3 id="poolTitle">등록 데이터 선택</h3>
          <p class="modal-sub">활성 상태의 등록 데이터(참조)만
            실행 후보입니다 — 선택하면 지금 시점의 원본을 다시 읽어 옵니다.</p>
          <div id="poolPickList" class="sheet-list"></div>
          <p id="poolNote" class="note dangerbox" style="display:none;white-space:pre-line"></p>
          <div class="modal-actions">
            <button class="btn" id="poolCancel">취소</button>
          </div>
        </div>`;
      document.body.appendChild(el);
    }
    if (!wired) {
      wired = true;
      // 취소 버튼: 로드 중이면 닫지 않고 그 사실을 표기(C8), 아니면 닫힘→onClose(취소)→null.
      // 골격이 정적(index.html)이어도 반드시 배선돼야 한다 — 과거 '생성 분기 안 배선'은
      // 정적 이관 시 취소 버튼이 죽는 잠복 결함이었다(K12).
      $("poolCancel").addEventListener("click", () => {
        if (loading) { noteLoadingBlock(); return; }
        Modal.close("poolModal");
      });
    }
  }

  /** 활성 풀 목록 모달을 띄워 항목을 확정받고 그 참조로 로드한다. */
  async function choose(screen) {
    build();
    let res;
    try {
      res = await Bridge.call(screen, "pool_sources", {});
    } catch (err) {
      // confirm-or-alarm: 목록 조회 실패(브리지 거절 등)를 조용히 삼키지 않고 시끄럽게
      // 재진술한 뒤 중단(null)으로 해소한다 — 죽은 모달을 남기지 않는다.
      window.alert("등록 데이터 목록을 불러올 수 없습니다:\n" +
        String((err && err.message) || err));
      return null;
    }
    const items = (res && res.items) || [];
    // 손상 병기(C5 소비측) — 백엔드 pool_sources_payload 가 격리 수집해 싣는
    // corrupted_note("손상 N건 — 데이터 관리에서 확인")를 목록에 함께 렌더한다.
    // items 만 소비하면 손상 데이터셋이 피커에서 무표시 증발한다(조용한 드롭 금지).
    // #poolNote 는 로드 오류 재진술과 공유돼 회차마다 리셋되므로, 손상 표지는
    // 목록 영역에 상주시켜 오류 문구에 덮이지 않게 한다.
    const corrupted = (res && res.corrupted_note) || "";
    return new Promise((resolve) => {
      const list = $("poolPickList");
      const note = $("poolNote");
      note.style.display = "none";
      note.textContent = "";
      loading = false; // 회차 시작 — 이전 회차 잔여 상태로 클릭이 무시되지 않게 초기화
      list.innerHTML = (items.length
        ? items.map((it, i) =>
            `<button type="button" class="btn sheet-opt pool-opt" data-name="${escHtml(it.name)}"` +
            `${i === 0 ? ' data-first="1"' : ""}>` +
            `<span class="mono sheet-name">${escHtml(it.name)}</span>` +
            `<span class="muted sheet-dim">${escHtml(it.kind_label)} · ${escHtml(it.reference)}</span></button>`
          ).join("")
        : `<p class="muted capnote">활성 등록 데이터가 없습니다 — 작업 저장 때
           함께 등록한 데이터가 여기 나타나거나, 데이터 관리 화면에서 추가할 수 있습니다.</p>`)
        + (corrupted
            ? `<p class="note dangerbox" style="margin:var(--sp-8) 0 0">⚠ ${escHtml(corrupted)}</p>`
            : "");

      let settled = false;
      // 로드 중 Escape 차단(C8) — Modal 의 캡처 keydown 보다 먼저 등록해(같은 대상의 캡처
      // 리스너는 등록 순) 선행 수신하고, 로드 중이면 닫힘 전파를 끊고 그 사실을 표기한다.
      function onEscCapture(e) {
        if (e.key === "Escape" && loading) {
          e.preventDefault();
          e.stopImmediatePropagation(); // Modal 의 Escape 닫힘 핸들러까지 차단
          noteLoadingBlock();
        }
      }
      function cleanup() {
        list.removeEventListener("click", onPick);
        document.removeEventListener("keydown", onEscCapture, true);
        loading = false;
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
        let r;
        try {
          r = await Bridge.call(screen, "load_pool", { name: btn.dataset.name });
        } catch (err) {
          // confirm-or-alarm(C8): 브리지 거절을 조용히 삼키면 loading 이 영구 고착돼
          // 이후 모든 클릭이 무시된다(재시도 불가·오류 무표시) — 모달 안에 시끄럽게
          // 재진술하고 재선택·취소를 허용한다.
          note.textContent = "⚠ 등록 데이터를 불러올 수 없습니다:\n" +
            String((err && err.message) || err);
          note.style.display = "block";
          return;
        } finally {
          loading = false; // 성공·실패·거절 모든 경로에서 해제(C8: 클릭 영구 무시 방지)
        }
        if (r && r.ok) { finish(r.label); return; }
        // 실패(나라 동결·죽은 참조·레코드 0건) — 모달 안에서 시끄럽게 재진술, 재선택 허용.
        note.textContent = "⚠ " + ((r && r.error) || "등록 데이터를 불러올 수 없습니다.");
        note.style.display = "block";
      }
      function onCancel() { finish(null); } // 취소·Escape = 중단(조용한 강등 없음)

      list.addEventListener("click", onPick);
      document.addEventListener("keydown", onEscCapture, true); // Modal.open 보다 먼저(선행 캡처)
      Modal.open("poolModal", {
        onClose: onCancel, // 취소 버튼·Escape 등 어떤 닫힘도 취소로 귀결
        initialFocus: list.querySelector('[data-first="1"]') || $("poolCancel"),
      });
    });
  }

  window.PoolPicker = { choose };
})();
