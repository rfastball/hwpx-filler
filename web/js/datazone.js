/* 데이터 존 공용 팩토리 — 필터 테이블 표면(열 필터 패널·행 선택/Shift 범위·칩 줄·필터 밖
   선택 스트립·자모 하이라이트 세그먼트). 「작업」 화면(블록 4, 슬라이스 4)에서 추출했고
   (슬라이스 6 PR-2a), txt 일괄 큐(블록 3, PR-2b)가 같은 표면을 재사용한다 — 링2 사본을
   두 벌 기르지 않기 위한 단일 출처(#94 의 400줄 중복 클래스와 동형의 상류 차단).

   화면 불가지: DOM id·선두 열(작업=「문서」 파일명, txt=처리 색인)·빈 상태 문안·세션
   지문·로그 채널을 전부 config 로 주입받고, Bridge 디스패치 대상(screen)만 안다. 판정
   (필터·선택·세그먼트 절단)은 전부 Python — 여기는 받은 스냅샷을 그리고 제스처를
   디스패치할 뿐이다(링2 표현 계층, #87 경계 동일).

   스냅샷 계약(소비 키): has_data · selected_count · record_count ·
     table{columns[{name, kind}], rows[{index, selected, cells[[세그먼트]], …선두열 필드}], visible_count,
           hidden_selected[{index, name, summary}]} ·
     filter{active, search, chips, branches, columns[{active}], reapply_available}
   디스패치 계약(액션): filter_panel · filter_col_text · filter_col_values · filter_clear_col ·
     filter_col_range · filter_search · filter_reapply · filter_prune · filter_clear ·
     toggle_record · select_range · set_all · set_none

   config: {
     screen,                    // Bridge 디스패치 대상
     ids: { selCount, search, reapply, chips, strip, tableHost, tableWrap, tableEmpty,
            tableHead, tableBody, colPanel, selAll, selNone },
     rowIdPrefix,               // 행 안정 id 접두("jobRow-") — preserve.js 가 id 로 복원
     lead: { header, bodyHtml(row) },   // 선두 열 머리 문안·셀 본문(체크박스는 팩토리 소유)
     copy: { emptyNoData, emptyNoRows, emptyFiltered, stripLead(count) },
     tableKey(s),               // 세션 지문 — 앵커·패널·대기 디바운스 리셋 판정
     log(msg),                  // 완료 존 로그 채널(재진술은 화면이 소유)
   }
   반환: { wire, render, sync, flushPendingSearch }
     sync(s)   — 렌더 없이 스냅샷만 관측(화면이 존 렌더를 게이트하는 push 에서도 호출) —
                 flushPendingSearch 판정이 항상-최신 스냅샷을 보게(리뷰: stale LAST 오발 차단)

   패널 바깥닫기(pointerdown·Escape·닫기 클릭 1회 소비)는 공용 Popover.wireDismiss 가
   기제를 소유하고, 인스턴스는 자기 술어(isOpen·contains·close)만 주입한다 — 화면의 다른
   popover(작업 행 ⋮ 메뉴 등)와 suppress 상태를 공유하지 않는다(표면별 인스턴스). */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  function create(cfg) {
    const SCREEN = cfg.screen;
    const ids = cfg.ids;
    let LAST = null;  // 마지막으로 render 에 들어온 스냅샷(가시 순서·필터 상태 판독용)

    /* ---- 열 필터 패널(엑셀식 아이콘 펼침, 결정 25) ----
       열별 부분일치 검색 + 값 체크리스트(같은 열 OR) 동거, 일자·금액 열은 범위 폼(비교 6종
       + 2절 그리고/또는 — 엑셀 사용자 지정 동형). 값 목록은 열릴 때만 당긴다(filter_panel
       질의 — 53열 코퍼스에서 스냅샷 상시 적재 낭비 방지). 범위 오독 피연산자는 패널 안
       인라인 재진술(조용한 강등 금지). */
    let panelCol = null;   // 열린 패널의 열(null=닫힘)
    let panelData = null;  // 패널이 연 시점의 filter_panel 질의 결과(체크 상태 병합용, 리뷰 #4)
    const RANGE_OPS = [["ge", "≥"], ["gt", ">"], ["le", "≤"], ["lt", "<"], ["eq", "="], ["ne", "≠"]];

    function closeColPanel() {
      const p = $(ids.colPanel);
      p.hidden = true;
      p.innerHTML = "";
      panelCol = null;
      panelData = null;
    }

    async function openColPanel(col, anchorBtn) {
      // 앵커 좌표는 await **전에** 캡처한다 — dispatch 가 push 를 먼저 흘리면 head 재렌더로
      // anchorBtn 이 DOM 에서 떨어져 rect 가 0이 되고 패널이 엉뚱한 위치에 뜬다(리뷰 #5).
      const rectBefore = anchorBtn.getBoundingClientRect();
      const d = await Bridge.call(SCREEN, "filter_panel", { column: col });
      panelCol = col;
      panelData = d;
      renderColPanel(d);
      // 재렌더됐을 수 있으니 현 DOM 의 같은 열 버튼을 재조회하고, 없으면 캡처 좌표로.
      // 자기 head 스코프로만 찾는다 — 두 인스턴스(작업·txt)의 .fico 혼선 차단.
      const btnNow = $(ids.tableHead).querySelector(`.fico[data-col="${CSS.escape(col)}"]`);
      positionColPanel(btnNow || rectBefore);
    }

    function positionColPanel(anchor) {
      const p = $(ids.colPanel);
      // 패널은 renderColPanel 뒤라 실측 가능하다. 공용 배치기가 실제 폭·높이로 viewport를
      // clamp하고 위/아래를 flip한다. H-16 overlayRoot 직속 fixed 표면이라 viewport 좌표를 쓴다.
      window.Popover.place(p, anchor);
    }

    function rangeRow(slot, clause) {
      const ops = RANGE_OPS.map(([k, sym]) =>
        `<option value="${k}"${clause && clause.op === k ? " selected" : ""}>${sym}</option>`).join("");
      return `<div class="cp-range-row"><select class="field" data-rop="${slot}" data-busy-lock>${ops}</select>` +
        `<input class="field" data-rval="${slot}" type="text" data-busy-lock ` +
        `value="${clause ? esc(clause.operand) : ""}" placeholder="${slot === 1 ? "값" : "값(선택)"}"></div>`;
    }

    function renderColPanel(d) {
      const p = $(ids.colPanel);
      const isRange = d.kind === "amount" || d.kind === "date";
      const checked = d.checked; // null=(전체)
      const allOn = checked === null;
      const vals = d.options.map((v) => {
        const on = allOn || checked.includes(v);
        return `<label><input type="checkbox" data-val="${esc(v)}" data-busy-lock${on ? " checked" : ""}>` +
          `${esc(v === "" ? "(빈값)" : v)}</label>`;
      }).join("");
      const range = isRange
        ? `<div class="cp-sec"><span class="cp-cap">범위 조건(${d.kind === "amount" ? "금액" : "날짜"})</span>` +
          rangeRow(1, d.range && d.range.first) +
          `<select class="field" data-rjoin data-busy-lock>` +
          `<option value="and"${!d.range || d.range.joiner !== "or" ? " selected" : ""}>그리고</option>` +
          `<option value="or"${d.range && d.range.joiner === "or" ? " selected" : ""}>또는</option></select>` +
          rangeRow(2, d.range && d.range.second) +
          `<div class="cp-err" data-rerr style="display:none"></div>` +
          `<div class="cp-acts"><button class="btn sm" data-act="range-apply" data-busy-lock>범위 적용</button></div>` +
          `</div>`
        : `<div class="cp-sec"><span class="cp-cap">부분일치 검색(자모)</span>` +
          `<input class="field" data-ctext type="text" value="${esc(d.text || "")}" ` +
          `placeholder="치는 동안 바로 좁혀집니다" data-busy-lock></div>`;
      p.innerHTML =
        `<div class="cp-head"><span>'${esc(d.column)}' 필터</span>` +
        `<button data-act="panel-close" aria-label="닫기">✕</button></div>` +
        range +
        `<div class="cp-sec"><span class="cp-cap">값 선택(같은 열 안은 OR)</span>` +
        `<div class="cp-vals">` +
        `<label><input type="checkbox" data-val-all${allOn ? " checked" : ""}><b>(전체)</b></label>` +
        `${vals}</div></div>` +
        `<div class="cp-acts"><button class="btn sm" data-act="col-clear" data-busy-lock>이 열 조건 지우기</button></div>`;
      p.hidden = false;
    }

    function panelValues() {
      // 체크 상태 수집 + **화면에 없는 기체크 값 병합**(리뷰 #4) — 다른 조건 변화로 값 목록에서
      // 사라진 기체크 값('X')은 사용자가 해제한 적이 없으므로 조건에서 조용히 탈락시키지
      // 않는다(조용한 조건 변형 금지). (전체) 토글만이 그것들을 명시적으로 걷는다.
      const boxes = Array.from($(ids.colPanel).querySelectorAll("input[data-val]"));
      const on = boxes.filter((b) => b.checked).map((b) => b.dataset.val);
      const options = boxes.map((b) => b.dataset.val);
      const hidden = ((panelData && panelData.checked) || [])
        .filter((v) => !options.includes(v));
      if (!hidden.length && on.length === boxes.length) return null;  // 전부 체크 = (전체)
      return on.concat(hidden);
    }

    let colTextTimer = 0;
    function onPanelInput(e) {
      if (e.target.matches("[data-ctext]")) {
        clearTimeout(colTextTimer);
        const text = e.target.value;
        const col = panelCol;  // 타이머 발화 시점이 아니라 입력 시점의 열에 결속(리뷰 #0 —
                               // 창 안에 패널을 닫거나 다른 열을 열면 엉뚱한 열에 오발)
        colTextTimer = setTimeout(
          () => Bridge.call(SCREEN, "filter_col_text", { column: col, text }), 200);
      }
    }

    function onPanelChange(e) {
      if (e.target.matches("[data-val-all]")) {
        const all = e.target.checked;
        $(ids.colPanel).querySelectorAll("input[data-val]").forEach((b) => { b.checked = all; });
        Bridge.call(SCREEN, "filter_col_values", { column: panelCol, values: all ? null : [] });
        return;
      }
      if (e.target.matches("input[data-val]")) {
        const values = panelValues();
        const allBox = $(ids.colPanel).querySelector("[data-val-all]");
        if (allBox) allBox.checked = values === null;
        Bridge.call(SCREEN, "filter_col_values", { column: panelCol, values });
      }
    }

    async function onPanelClick(e) {
      if (e.target.closest('[data-act="panel-close"]')) { closeColPanel(); return; }
      if (e.target.closest('[data-act="col-clear"]')) {
        const col = panelCol;
        await Bridge.call(SCREEN, "filter_clear_col", { column: col });
        const btn = $(ids.tableHead).querySelector(`.fico[data-col="${CSS.escape(col)}"]`);
        if (btn) openColPanel(col, btn); else closeColPanel();
        return;
      }
      if (e.target.closest('[data-act="range-apply"]')) {
        const p = $(ids.colPanel);
        const clause = (slot) => {
          const op = p.querySelector(`[data-rop="${slot}"]`).value;
          const operand = p.querySelector(`[data-rval="${slot}"]`).value;
          return operand.trim() ? { op, operand } : null;
        };
        const res = await Bridge.call(SCREEN, "filter_col_range", {
          column: panelCol, first: clause(1), second: clause(2),
          joiner: p.querySelector("[data-rjoin]").value,
        });
        const err = p.querySelector("[data-rerr]");
        if (err) {
          err.style.display = res.ok ? "none" : "";
          err.textContent = res.ok ? "" : res.error;
        }
      }
    }

    function onHeadClick(e) {
      const btn = e.target.closest(".fico[data-col]");
      if (!btn) return;
      const col = btn.dataset.col;
      if (panelCol === col) { closeColPanel(); return; }
      openColPanel(col, btn);
    }

    /* ---- 데이터 존: 필터 테이블(블록 4, 결정 23~25) ----
       선두 열(체크 표지 + 화면 주입 본문 — 작업=실파일명·식별 요약 F33) + 원본 데이터 열.
       셀 텍스트는 Python 이 잘라 보낸 하이라이트 세그먼트를 그리기만 한다(자모 역매핑 —
       매치 인덱스를 받지 않는다, 파생경계 번역오류의 상류 차단). 가시 행만 렌더 —
       필터 밖 선택은 스트립(renderStrip)이 상시 진술한다(결정 3). */
    let selAnchor = null;      // Shift 범위 앵커(행 index) — 세션 전환 시 리셋
    let selAnchorState = null; // 앵커의 **현재** 선택 상태 — 마지막 디스패치 값 기준(리뷰 #2:
                               // LAST 는 왕복 전이라 앵커 자신의 토글이 아직 안 비쳐 stale)
    let lastTableKey = null;   // 앵커 리셋 판정(화면 주입 세션 지문 — cfg.tableKey)
    let searchTimer = 0;       // 전열 검색 디바운스 — 세션 전환 시 취소(리뷰 #1: 다음 세션 오발)

    function segsHtml(segs) {
      if (!segs || !segs.length) return "";
      return segs.map(([t, hit]) => (hit ? `<mark>${esc(t)}</mark>` : esc(t))).join("");
    }

    // production 스냅샷은 {name, kind}. 구 selftest fixture의 문자열 열도 text로 무해하게
    // 받는다. 유형은 Python FilterModel의 기존 판정만 소비하며 웹에서 재판정하지 않는다.
    function columnMeta(column) {
      return typeof column === "string"
        ? { name: column, kind: "text" }
        : { name: column.name, kind: column.kind || "text" };
    }

    function renderTable(s) {
      const tkey = cfg.tableKey(s);
      if (tkey !== lastTableKey) {
        // 세션 전환 — 앵커·패널·대기 중 디바운스 전부 무효(이전 세션의 선언이 새 세션에
        // 오발되지 않게: 필터=세션 휘발, 결정 24). (리뷰 #1)
        selAnchor = null; selAnchorState = null; lastTableKey = tkey;
        clearTimeout(searchTimer); clearTimeout(colTextTimer);
        closeColPanel();
      }
      const hasData = !!s.has_data;
      const t = s.table || { columns: [], rows: [], visible_count: 0 };
      const f = s.filter || { active: false, columns: [] };
      $(ids.selCount).textContent =
        `선택 ${s.selected_count}/${s.record_count}` +
        (f.active ? ` · 표시 ${t.visible_count}` : "");
      const si = $(ids.search);
      si.style.display = hasData ? "" : "none";
      // 타이핑 중엔 스냅샷이 입력값을 덮지 않는다(왕복 경합 — 확정은 다음 blur/재진입 렌더).
      if (document.activeElement !== si) si.value = f.search || "";
      // 직전 필터 재적용(결정 28) — 3연언(슬롯 ∧ **현 필터 빈 상태** ∧ 소스 일치)일 때만
      // 어포던스 노출. 판정은 Python 이 하고 여기선 문안만 — 둘째 연언이 빠지면 조건을 쌓아
      // 둔 필터 위에서 한 번 누르는 것만으로 현 정의가 원자 교체된다(#127).
      const reapplyBtn = $(ids.reapply);
      reapplyBtn.style.display = hasData && f.reapply_available ? "" : "none";
      // 무엇이 설치되는지 업고 있다(목업 칩 문법 승계) — 정의 문안이 없으면 라벨만 남긴다.
      reapplyBtn.title = f.reapply_hint
        ? `직전 필터 재적용: ${f.reapply_hint}`
        : "직전 필터 재적용";
      const wrap = $(ids.tableWrap);
      const empty = $(ids.tableEmpty);
      if (!hasData) {
        wrap.style.display = "none";
        empty.style.display = "";
        empty.textContent = cfg.copy.emptyNoData;
        return;
      }
      wrap.style.display = "";
      if (!t.rows.length) {
        // 전멸도 정직하게 — 이유(정의)는 칩 줄이 재진술한다.
        empty.style.display = "";
        empty.textContent = f.active ? cfg.copy.emptyFiltered : cfg.copy.emptyNoRows;
      } else {
        empty.style.display = "none";
      }
      $(ids.tableHead).innerHTML =
        `<tr><th class="doccol">${esc(cfg.lead.header)}` +
        (cfg.lead.hint ? `<span class="col-hint">${esc(cfg.lead.hint)}</span>` : "") + `</th>` +
        t.columns.map((column, ci) => {
          const c = columnMeta(column);
          const meta = f.columns[ci] || { active: false };
          return `<th class="col-${c.kind}"><span>${esc(c.name)}</span> ` +
            `<button class="fico${meta.active ? " on" : ""}" data-col="${esc(c.name)}" ` +
            `aria-label="${esc(c.name)} 열 필터" aria-expanded="${panelCol === c.name}" ` +
            `data-busy-lock>▾</button></th>`;
        }).join("") + `</tr>`;
      $(ids.tableBody).innerHTML = t.rows.map((r) => {
        return `<tr data-i="${r.index}" id="${cfg.rowIdPrefix}${r.index}" class="${r.selected ? "on" : ""}" ` +
          `aria-selected="${r.selected ? "true" : "false"}" tabindex="0">` +
          `<td class="doccol"><div class="doccell"><input type="checkbox" tabindex="-1" ` +
          `aria-label="${r.index + 1}행 선택"${r.selected ? " checked" : ""}>` +
          `<span class="doc-body">${cfg.lead.bodyHtml(r)}</span></div></td>` +
          r.cells.map((segs, ci) => {
            const c = columnMeta(t.columns[ci]);
            return `<td class="col-${c.kind}">${segsHtml(segs)}</td>`;
          }).join("") + `</tr>`;
      }).join("");
    }

    /* 행 선택 — 클릭 = 개별 토글, Shift = 앵커 상태를 가시 순서 범위에 전파(결정 2).
       앵커 상태는 마지막 디스패치 값(selAnchorState)을 쓴다 — LAST 스냅샷은 왕복 전이라
       앵커 자신의 직전 토글이 아직 안 비쳐, 빠른 클릭+Shift 에서 범위 전체가 반대로
       전파되는 stale 결함이 있다(리뷰 #2). */
    function toggleRow(idx, shift) {
      const rows = (LAST && LAST.table && LAST.table.rows) || [];
      const visOrder = rows.map((r) => r.index);
      if (shift && selAnchor !== null && visOrder.includes(selAnchor) && visOrder.includes(idx)) {
        const a = visOrder.indexOf(selAnchor), b = visOrder.indexOf(idx);
        const range = visOrder.slice(Math.min(a, b), Math.max(a, b) + 1);
        const anchorRow = rows.find((r) => r.index === selAnchor);
        const value = selAnchorState !== null
          ? selAnchorState : !!(anchorRow && anchorRow.selected);
        Bridge.call(SCREEN, "select_range", { indices: range, value });
        return;
      }
      selAnchor = idx;
      const row = rows.find((r) => r.index === idx);
      selAnchorState = !(row && row.selected);  // 이번 디스패치가 만드는 상태 = 앵커의 현재
      Bridge.call(SCREEN, "toggle_record", { index: idx, value: selAnchorState });
    }

    function onTableClick(e) {
      const tr = e.target.closest("tr[data-i]");
      if (!tr) return;
      toggleRow(Number(tr.dataset.i), e.shiftKey);
    }

    function onTableKey(e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      const tr = e.target.closest("tr[data-i]");
      if (!tr) return;
      e.preventDefault();
      toggleRow(Number(tr.dataset.i), e.shiftKey);
    }

    /* ---- 칩 줄 — 정의 재진술(describe_parts 단일 출처) + 가지 칩(× 프루닝) ---- */
    function renderChips(s) {
      const box = $(ids.chips);
      const f = s.filter || { active: false };
      if (!s.has_data || !f.active) { box.style.display = "none"; box.innerHTML = ""; return; }
      box.style.display = "";
      box.innerHTML =
        (f.chips || []).map((c) =>
          `<span class="fchip definition"><span class="chip-role">필터</span>${esc(c)}</span>`
        ).join("") +
        (f.branches || []).map((b) =>
          `<span class="fchip branch"><span class="chip-role">가지</span>${esc(b)}` +
          `<button data-prune="${esc(b)}" aria-label="${esc(b)} 가지 제거" data-busy-lock>×</button></span>`
        ).join("") +
        `<button class="btn sm" data-act="filter-clear" data-busy-lock>필터 지우기</button>`;
    }

    /* ---- 필터 밖 선택 스트립(결정 3) — 선택은 관통, 밖은 상시 가시 ---- */
    function renderStrip(s) {
      const box = $(ids.strip);
      const hs = (s.table && s.table.hidden_selected) || [];
      if (!s.has_data || !hs.length) { box.style.display = "none"; box.innerHTML = ""; return; }
      box.style.display = "";
      // 항목별 × = 개별 해제 어포던스(리뷰 #6 — 구 목록의 행별 체크박스가 지던 의무 승계:
      // 필터를 허물거나 전체 해제하지 않고도 필터 밖 선택 하나만 뺄 수 있어야 한다).
      const chips = hs.map((r) =>
        `<span class="fchip selection"><span class="chip-role">선택</span>` +
        `${esc(r.name || r.summary || `${r.index + 1}행`)}` +
        `<button data-unsel="${r.index}" aria-label="${r.index + 1}행 선택 해제" data-busy-lock>×</button></span>`
      ).join("");
      box.innerHTML = cfg.copy.stripLead(hs.length) + chips;
    }

    /* 대기 중 검색 디바운스 정산 — 세션 전환 시도 **전에** 미적용 검색어를 먼저 적용한다
       (리뷰 #2: 취소만 하면 「머무르기」로 남은 세션에서 마지막 타이핑이 조용히 증발).
       전환이 확정되면 필터째 죽으니 선적용은 무해하고, 머무르면 타이핑이 보존된다. */
    async function flushPendingSearch() {
      clearTimeout(searchTimer);
      const si = $(ids.search);
      if (LAST && LAST.has_data && LAST.filter
          && si.value !== (LAST.filter.search || "")) {
        await Bridge.call(SCREEN, "filter_search", { text: si.value });
      }
    }

    /* 스냅샷 관측만 — 렌더 없이 LAST 를 최신으로 유지한다. 화면이 존 렌더를 게이트하는
       push(작업 미선택 등)에서도 호출해, flushPendingSearch 가 직전 세션의 stale 스냅샷
       (has_data=true·옛 검색어)으로 죽은 세션에 filter_search 를 오발하는 창을 닫는다
       (리뷰: master 의 "무조건 LAST = s" 계약 복원). */
    function sync(s) {
      LAST = s;
    }

    /* 존 렌더 — 화면 render() 가 스냅샷마다 호출(Preserve.around 래핑은 호출측 소유). */
    function render(s) {
      LAST = s;
      renderTable(s);
      renderChips(s);
      renderStrip(s);
    }

    function wire() {
      // 패널 등록/해제·focusout·capture scroll·Escape·닫기 click 소비는 공용 Popover가
      // 소유한다. 여기는 자기 술어만 등록한다. .fico는 자기 head 스코프만 예외다.
      Popover.wireDismiss({
        isOpen: () => panelCol !== null,
        contains: (t) => {
          if (t.closest("#" + ids.colPanel)) return true;
          const ico = t.closest(".fico");
          return !!(ico && $(ids.tableHead).contains(ico));
        },
        close: closeColPanel,
      });
      // 행 클릭 토글 + Shift 범위, 열 머리 필터 아이콘, 전열 검색.
      $(ids.tableBody).addEventListener("click", onTableClick);
      $(ids.tableBody).addEventListener("keydown", onTableKey);
      $(ids.tableHead).addEventListener("click", onHeadClick);
      $(ids.search).addEventListener("input", (e) => {
        clearTimeout(searchTimer);
        const text = e.target.value;
        searchTimer = setTimeout(() => Bridge.call(SCREEN, "filter_search", { text }), 200);
      });
      // 직전 필터 재적용(결정 28) — 정의만 복원(선택 불변), 탈락은 시끄럽게 고지(백스톱).
      $(ids.reapply).addEventListener("click", async () => {
        const res = await Bridge.call(SCREEN, "filter_reapply", {});
        if (!res.ok) { cfg.log("확인 필요: " + res.error); return; }
        cfg.log(`직전 필터를 재적용했습니다 (조건 열: ${res.installed.join(", ") || "검색만"}).`);
        if (res.dropped.length) {
          cfg.log(`확인 필요: 현재 데이터에 없는 조건은 빠졌습니다(${res.dropped.join(", ")})`);
        }
      });
      // 필터 밖 선택 스트립 — 항목별 × 해제(리뷰 #6).
      $(ids.strip).addEventListener("click", (e) => {
        const un = e.target.closest("[data-unsel]");
        if (un) Bridge.call(SCREEN, "toggle_record", { index: Number(un.dataset.unsel), value: false });
      });
      // 칩 줄 — 가지 프루닝 ×·필터 지우기(재렌더 생존 위임).
      $(ids.chips).addEventListener("click", (e) => {
        const pr = e.target.closest("[data-prune]");
        if (pr) { Bridge.call(SCREEN, "filter_prune", { column: pr.dataset.prune }); return; }
        if (e.target.closest('[data-act="filter-clear"]')) Bridge.call(SCREEN, "filter_clear", {});
      });
      // 열 필터 패널 — 내부 위임(바깥 클릭/Escape 닫기는 위 Popover.wireDismiss 주입).
      $(ids.colPanel).addEventListener("input", onPanelInput);
      $(ids.colPanel).addEventListener("change", onPanelChange);
      $(ids.colPanel).addEventListener("click", onPanelClick);
      $(ids.selAll).addEventListener("click", async () => {
        const r = await Bridge.call(SCREEN, "set_all", {});
        // 전멸 필터에서의 무동작은 정직하게 알린다(confirm-or-alarm, 리뷰 #9).
        if (r && r.added === 0) {
          cfg.log("전체 선택: 추가할 행이 없습니다.");
        }
      });
      $(ids.selNone).addEventListener("click", () => Bridge.call(SCREEN, "set_none", {}));
    }

    return { wire, render, sync, flushPendingSearch };
  }

  window.DataZone = { create };
})();
