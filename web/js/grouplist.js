/* 그룹 목록 공용 팩토리 — 부유 ⋮ 메뉴 위치잡기 + 그룹 이동 다이얼로그.
   job.js(원본)·template.js(이식본)가 이 두 기제를 손수 2벌 들고 있었고(＋#148 「기안」이
   3번째 소비자로 합류), datazone.js·popover.js 선례처럼 **기제**를 단일 출처로 걷는다.
   표면별로 정당하게 다른 것(행/카드 본문·메뉴 내용·인라인 이름변경·확인 문안·디스패치
   페이로드·menuFor 정체)은 화면이 소유하고 주입한다. 여기가 걷는 건 손수 2벌일 때 좌표·
   소구획이 조용히 갈라지던 기제뿐이다:
   - 메뉴: 위치 계산(아래 공간 없으면 위로·화면 안 클램프·첫 항목 포커스) + 표시/숨김.
   - 이동 다이얼로그: 라디오 목록 조립(기존 그룹 + 「그룹 없음」 + 「새 그룹」 data-new) +
     포커스=새 그룹 자동선택 + 빈 새 이름 인라인 재진술(모달 유지).
   바깥닫기(Popover.wireDismiss)는 화면이 자기 술어로 직접 배선한다 — menuFor 정체가 화면
   소유라 여기서 대신 들지 않는다(표면별 suppress 인스턴스 원칙 유지). */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /* 부유 ⋮ 메뉴(.ctx-menu) — 내용·정체는 화면이 만들고, 위치·표시/숨김만 팩토리가 소유. */
  function createMenu(cfg) {
    function show(html, btn) {
      const m = $(cfg.menuId);
      m.innerHTML = html;
      // .ctx-menu 는 display 미지정 div — block 로 노출(job 은 "", tpl 은 "block" 를 쓰던 걸
      // 통일; 둘 다 CSS 기본이 block 라 결과 동형). 측정 전에 보여야 offsetHeight 가 잡힌다.
      m.style.display = "block";
      // position:fixed 좌표 — 트리거 rect 기준, 아래 공간이 없으면 위로 편다(overflow 클리핑 회피).
      const r = btn.getBoundingClientRect();
      const below = r.bottom + 4 + m.offsetHeight <= window.innerHeight;
      m.style.top = (below ? r.bottom + 4 : Math.max(4, r.top - m.offsetHeight - 4)) + "px";
      m.style.left = Math.max(4, Math.min(r.left, window.innerWidth - m.offsetWidth - 4)) + "px";
      const first = m.querySelector("button");
      if (first) first.focus();
    }
    function hide() {
      const m = $(cfg.menuId);
      m.style.display = "none";
      m.innerHTML = "";
    }
    return { show, hide };
  }

  /* 그룹 이동 다이얼로그 — 기존 그룹 라디오 + 「그룹 없음(해제)」 + 「새 그룹」(data-new 로 값
     센티넬 충돌 봉쇄, 포커스하면 자동 선택). 빈 새 이름은 조용히 넘기지 않고 인라인 재진술
     (모달 유지). 대상 이름 문안·확정 디스패치는 화면이 open() 인자로 주입한다. */
  function createMoveDialog(cfg) {
    let onConfirm = null;  // open 시 주입되는 확정 콜백(group) — 닫히면 걷는다.

    function open(opts) {
      onConfirm = opts.onConfirm;
      const groups = opts.groups || [];
      const cur = opts.current || "";
      $(cfg.listId).innerHTML =
        groups.map((g) =>
          `<label class="grp-opt"><input type="radio" name="${cfg.radioName}" value="${esc(g)}"${g === cur ? " checked" : ""}> ${esc(g)}</label>`
        ).join("") +
        `<label class="grp-opt"><input type="radio" name="${cfg.radioName}" value=""${cur === "" ? " checked" : ""}> 그룹 없음(해제)</label>` +
        `<label class="grp-opt"><input type="radio" name="${cfg.radioName}" value="" data-new="1" id="${cfg.newRadioId}"> 새 그룹:` +
        ` <input class="field" id="${cfg.newNameId}" type="text" placeholder="새 그룹 이름"></label>`;
      if (cfg.nameId && opts.nameText != null) $(cfg.nameId).textContent = opts.nameText;
      const err = $(cfg.errId);
      err.style.display = "none";
      err.textContent = "";
      // 새 그룹 이름을 만지면 새 그룹 라디오가 자동 선택된다(입력=의도).
      const nn = $(cfg.newNameId);
      if (nn) nn.addEventListener("focus", () => { const rr = $(cfg.newRadioId); if (rr) rr.checked = true; });
      window.Modal.open(cfg.modalId, { onClose: () => { onConfirm = null; } });
    }

    function confirm() {
      if (!onConfirm) return;
      const sel = document.querySelector(`input[name="${cfg.radioName}"]:checked`);
      if (!sel) return;
      let group = sel.value;
      if (sel.dataset.new) {
        group = ($(cfg.newNameId).value || "").trim();
        if (!group) {
          const err = $(cfg.errId);
          err.textContent = "새 그룹 이름이 비어 있습니다. 이름을 넣거나 다른 항목을 고르세요.";
          err.style.display = "";
          return;  // 조용한 무동작 금지 — 열린 채 재진술
        }
      }
      const cb = onConfirm;
      window.Modal.close(cfg.modalId);
      cb(group);
    }

    function wire(okId, cancelId) {
      $(okId).addEventListener("click", confirm);
      $(cancelId).addEventListener("click", () => window.Modal.close(cfg.modalId));
    }

    return { open, wire };
  }

  window.GroupList = { createMenu, createMoveDialog };
})();
