/* 「작업」 화면 — 좌 master 목록 + 우 상세 패널 **두 모드**(R-flow #90 · 블록 2 개정 39~41).
   실행 모드(기본)=세션 패널 4존, 편집 모드=정의 호스트(#jobEditHost — editor.js 가 렌더).
   안정 DOM(index.html) + Python 이 window.__push('job', snapshot) 로 값만 채운다(run/txt 패턴).
   표현 계층(거울 테이블·재진술 블록·게이트·진행/로그)만 여기서 만든다 — VM 로직 아님(링2 대체, #87).
   덮어쓰기 확인은 공용 Modal.confirm(수치 합성 본문)으로 — 네이티브 다이얼로그 무사용이라 #86
   재유입 가드에 처음부터 부합한다. 존 배치(헤더·데이터·본문·완료)는 여기서 안정 DOM 에 값을 채운다. */
(function () {
  const SCREEN = "job";
  const $ = (id) => document.getElementById(id);
  let LAST = null;
  let generating = false;
  let lastSessionKey = null;  // 완료 존 세션 스코프 판정(결정 7) — 세션 변경 시에만 리셋
  let restateExpanded = false;  // 재진술 블록 이름 목록 펼침(대량 표본+「외 N건」, 결정 36)
  let lastRestateKey = null;    // 펼침 리셋 판정 — 작업/데이터 전환 시 펼침을 끈다(세션 누수 방지)
  /* 패널 모드(결정 39·40) — "run"(행 클릭=실행 세션, 기본) | "edit"(정의 편집·신규 마법사).
     모드는 표시 상태일 뿐: 실행 세션은 JobController, 정의 세션은 EditorController 가 각자
     소유해 전환이 어느 쪽도 파괴하지 않는다. 파괴 가능 지점은 진입 가드가 지킨다 —
     T1(세션 전환)=selectJobGuarded, 미저장 정의 덮어쓰기=EditorEntry.openGuarded. */
  let MODE = "run";

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    if (s && s.progress) { renderProgress(s.progress); return; }  // 진행 델타(경량)
    Preserve.around(() => {  // 매핑/레코드 포커스·스크롤 보존(#28)
      LAST = s;
      renderMaster(s);
      const hasJob = !!s.has_job;
      syncModeDisplay(hasJob);
      if (hasJob) {
        renderHeader(s);
        renderData(s);
        renderPreflight(s);
        renderMirror(s);
        renderTable(s);
        renderChips(s);
        renderStrip(s);
        renderRestate(s);
        renderGateAndFolder(s);
      }
      renderStatus(s);
      if (MODE === "edit") setEditStatus();  // 편집 모드 표지는 세션 상태 pill 을 덮는다
      // 완료 존(생성 결과·로그)은 세션 스코프로 보존한다(결정 7) — 매 push 가 아니라 세션이
      // 실제로 바뀔 때만 무효화한다. 레일 이탈 후 복귀(REFRESH_ON_NAV 재push)는 세션 불변이라
      // 결과가 살아남고(리뷰 #3: 결정 7 위배 봉합), 작업·데이터·선택 변경(#28 UD-10)에서만
      // 이전 결과를 지운다. nav 는 CSS 토글이라 DOM 은 어차피 살아있다.
      const key = sessionKey(s);
      if (!generating && key !== lastSessionKey) resetGenResult();
      lastSessionKey = key;
      setBusy(generating);
    });
  }

  /* 이전 생성 결과(요약·진행바·로그)를 기본 상태로 되돌린다(오래된 성공 잔존 방지, #28). */
  function resetGenResult() {
    $("jobGenBar").style.width = "0%";
    const r = $("jobGenResult");
    r.textContent = "";
    r.className = "run-result";
    $("jobGenLog").textContent = "";
    logStarted = false;
  }

  /* 세션 지문 — 완료 존 보존 판정(결정 7). 작업·데이터·저장 폴더·선택 집합이 그대로면 같은
     세션이라 이전 생성 결과가 유효하다. 선택은 정확한 인덱스 집합으로(개수만으론 행 교체를
     놓친다). 작업 미선택이면 빈 문자열 = 세션 없음. */
  function sessionKey(s) {
    if (!s.has_job) return "";
    const sel = (s.records || []).filter((r) => r.selected).map((r) => r.index).join(",");
    return [s.job_name, s.data_source_label, s.out_dir, sel].join("|");
  }

  /* ---- 패널 두 모드(결정 39·40) ---- */
  function syncModeDisplay(hasJob) {
    const edit = MODE === "edit";
    $("jobZones").style.display = (!edit && hasJob) ? "" : "none";
    $("jobEmptyPanel").style.display = (edit || hasJob) ? "none" : "";
    $("jobEditHost").style.display = edit ? "" : "none";
  }

  function setEditStatus() {
    const st = $("jobStatus");
    st.dataset.level = "idle";
    st.textContent = "편집 모드";
  }

  /* 편집 모드 진입 — 미저장 정의 확인은 호출측 단일 출처가 이미 지킨다(기존 작업=
     EditorEntry.openGuarded, 신규=home.newJob 대칭 확인). 여기는 표시 전환만. */
  function showEditMode() {
    MODE = "edit";
    syncModeDisplay(!!(LAST && LAST.has_job));
    setEditStatus();
    $("jobEditExitNote").style.display = "none";  // 편집 재진입 = 복귀 고지 소임 종료
  }

  /* 실행 복귀(T2 재정의, 블록 2 개정 결정 45) — 가드 대상이 화면 인계에서 "편집 중 행 클릭"
     으로 이동했다. 전환은 **비파괴**다: 정의 세션은 EditorController 에 그대로 살고, 미저장
     정의를 덮을 수 있는 유일한 경로(다른 작업 편집·새 작업)는 openGuarded/newJob 확인이
     지킨다. 그래서 묻지 않고 **고지**만 한다(T2 종결 해석과 동형 — 물을 파괴가 없으면 확인
     모달은 소음이다). 반환 = 미저장 편집 존재 여부(호출측이 고지 표면을 켠다). */
  async function exitEditToRun() {
    if (MODE === "run") return false;
    let busy = false;
    try {
      busy = await Bridge.editorHasUnsavedWork();
    } catch (err) {
      log("편집 상태 확인 실패: " + String((err && err.message) || err));
    }
    MODE = "run";
    syncModeDisplay(!!(LAST && LAST.has_job));
    if (LAST) renderStatus(LAST);
    return busy;
  }

  /* T2 고지 표면(PR-2 리뷰 F4) — 완료 존 log() 는 세션 전환 리셋(resetGenResult)·존 은닉에
     증발했다. 이 요소는 어떤 렌더 함수도 쓰지 않는 JS 소유라 push·세션 리셋을 관통해
     살아남고, 사용자가 확인 버튼으로 걷거나 편집 재진입 때 걷힌다(고지=읽힐 때까지). */
  function showExitNote() {
    const el = $("jobEditExitNote");
    el.innerHTML =
      `저장하지 않은 편집이 있습니다 — 편집으로 돌아가면 그대로 있고, ` +
      `저장 전에는 실행에 반영되지 않습니다. ` +
      `<button class="btn sm" data-act="dismiss-exit-note">확인</button>`;
    el.style.display = "";
  }

  /* 좌 목록 갱신 — 편집 저장 직후 새/개명 작업이 바로 보이게(editor.js doSave 가 호출).
     실패 재진술은 모드를 따른다(PR-2 리뷰 F10): 편집 모드에선 완료 존 log 가 숨어 있어
     조용한 실패가 된다 — 그때는 alert 로 loud. */
  function refreshList() {
    Bridge.call(SCREEN, "refresh", {}).catch((err) => {
      const msg = "목록 갱신 실패: " + String((err && err.message) || err);
      if (MODE === "edit") window.alert(msg);
      else log(msg);
    });
  }

  /* ---- 좌 master 목록(HWPX 구획) ---- */
  function renderMaster(s) {
    const host = $("jobListHwpx");
    const empty = $("jobListHwpxEmpty");
    const rows = s.job_rows || [];
    empty.style.display = rows.length ? "none" : "";
    host.innerHTML = rows.map((r) =>
      `<button class="job-item" data-job="${esc(r.name)}" aria-current="${r.selected ? "true" : "false"}">` +
      `${esc(r.name)}</button>`).join("");
  }

  /* ---- 헤더 존 — 작업 정체(이름·템플릿·재연결 동선) ---- */
  function renderHeader(s) {
    $("jobHeadTitle").textContent = s.job_name || "";
    const tpl = $("jobHeadTpl");
    tpl.innerHTML = s.template_name
      ? `템플릿 <span class="mono">${esc(s.template_name)}</span> ${PathTrack.affordances(s.template_path)}`
      : `템플릿 경로가 비어 있습니다. 편집 모드의 템플릿 탭에서 지정하세요.`;
    // 템플릿 다시 연결(#67)은 복구 동선 — 파일이 실제로 없을 때만 노출(F30, "정상은 조용히").
    const relink = $("jobRelink");
    if (s.template_missing) {
      relink.style.display = "block";
      relink.className = "note warnbox";
      relink.innerHTML =
        `템플릿 파일을 찾을 수 없습니다. ` +
        `<button class="btn sm" data-act="relink-template" data-busy-lock>템플릿 다시 연결…</button>`;
    } else {
      relink.style.display = "none";
      relink.innerHTML = "";
    }
  }

  /* ---- 데이터 존 — 겨눔 라벨·자동 조준 재진술 ---- */
  function renderData(s) {
    $("jobDataLabel").value = s.data_source_label || "";
    const note = $("jobDataNotice");
    const n = s.data_notice;
    if (n && n.text) {
      note.style.display = "block";
      // 실패(warn)만 시끄럽게, 성공(ok)은 muted 한 줄(F32: 정상 초록 배너는 노이즈).
      note.className = "note " + (n.level === "ok" ? "quiet" : "warnbox");
      note.textContent = (n.level === "ok" ? "" : "확인 필요: ") + n.text;
    } else {
      note.style.display = "none";
      note.textContent = "";
    }
  }

  function renderPreflight(s) {
    const box = $("jobPreflight");
    const p = s.preflight || { level: "", text: "" };
    if (!s.has_data || !p.text) { box.style.display = "none"; return; }
    box.style.display = "block";
    const cls = p.level === "ok" ? "quiet" : p.level === "danger" ? "dangerbox" : "warnbox";
    box.className = "preflight note " + cls;
    box.style.whiteSpace = "pre-line";
    box.textContent = p.text;
  }

  /* ---- 본문 존 거울 = 필드 채움 테이블(결정 36 ⓑ) ----
     hwpx 본문은 앱에서 렌더 못 하므로 거울이 비추는 것은 "생성될 문서의 채움 상태"다. ADR-E
     배지는 별도 UI가 아니라 거울의 행: 미입력 행 클릭=확인, 재클릭=철회(UD-19). danger(드리프트)는
     ack 로 안 풀리므로 같은 표에 섞지 않고 거울 자리 차단 배너 + 행동 링크로 분리한다(결정 36·S9). */
  function renderMirror(s) {
    const host = $("jobMirror");
    const drift = s.drift || [];
    if (drift.length) {
      // danger = 차단 배너 + 상시 행동 링크(막다른 경보 금지 — 경보 어포던스는 숨지 않는다).
      host.innerHTML =
        `<div class="mir-drift" role="alert">` +
        `<p>템플릿 구조가 확정 매핑과 달라졌습니다. 어긋난 필드: <b>${esc(drift.join(", "))}</b>. ` +
        `매핑을 다시 확정해야 문서를 생성할 수 있습니다.</p>` +
        `<button class="btn sm" data-act="fix-mapping" data-busy-lock>편집에서 매핑 확정…</button>` +
        `</div>`;
      return;
    }
    const rows = s.mirror || [];
    if (!rows.length) {  // 선택 0(또는 데이터 미겨눔) = 생성될 문서 없음
      host.innerHTML = `<p class="mirempty muted capnote">행을 선택하면 이 문서에 들어갈 값이 여기 비칩니다.</p>`;
      return;
    }
    host.innerHTML =
      `<div class="tbwrap"><table class="tb mir"><tbody>` +
      rows.map(mirrorRow).join("") + `</tbody></table></div>`;
  }

  function mirrorRow(r, i) {
    const nm = esc(r.name);
    const val = esc(r.value);
    // 안정 id — 클릭형 미입력 행이 ack 재렌더를 가로질러 포커스를 잃지 않게(preserve.js 는 id 로
    // 복원). 행 index 는 필드 집합이 안정인 세션 내에서 안정하다(이름 특수문자 회피).
    const id = `jobMirF-${i}`;
    if (r.state === "filled") {
      return `<tr class="mir-row" id="${id}"><td class="mir-f">${nm}</td><td class="mir-v">${val}</td>` +
        `<td class="mir-s"><span class="st filled">채움${r.formatted ? " · 표시형" : ""}</span></td></tr>`;
    }
    if (r.state === "blank") {
      return `<tr class="mir-row blankd" id="${id}"><td class="mir-f">${nm}</td><td class="mir-v">${val}</td>` +
        `<td class="mir-s"><span class="st blankd">빈칸 선언</span></td></tr>`;
    }
    // missing — 클릭형 행(확인/철회 토글). ack 여부로 색·칩 전환.
    const ack = r.acknowledged;
    const chip = ack ? `<span class="st ackd">확인됨 · 클릭=철회</span>`
                     : `<span class="st miss">미입력 · 클릭=확인</span>`;
    return `<tr class="mir-row miss${ack ? " ackd" : ""}" id="${id}" role="button" tabindex="0" ` +
      `data-f="${nm}" aria-pressed="${ack ? "true" : "false"}">` +
      `<td class="mir-f">${nm}</td><td class="mir-v">${val}</td><td class="mir-s">${chip}</td></tr>`;
  }

  /* ---- 열 필터 패널(엑셀식 아이콘 펼침, 결정 25) ----
     열별 부분일치 검색 + 값 체크리스트(같은 열 OR) 동거, 일자·금액 열은 범위 폼(비교 6종
     + 2절 그리고/또는 — 엑셀 사용자 지정 동형). 값 목록은 열릴 때만 당긴다(filter_panel
     질의 — 53열 코퍼스에서 스냅샷 상시 적재 낭비 방지). 범위 오독 피연산자는 패널 안
     인라인 재진술(조용한 강등 금지). */
  let panelCol = null;   // 열린 패널의 열(null=닫힘)
  let panelData = null;  // 패널이 연 시점의 filter_panel 질의 결과(체크 상태 병합용, 리뷰 #4)
  const RANGE_OPS = [["ge", "≥"], ["gt", ">"], ["le", "≤"], ["lt", "<"], ["eq", "="], ["ne", "≠"]];

  function closeColPanel() {
    const p = $("jobColPanel");
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
    const btnNow = document.querySelector(`.fico[data-col="${CSS.escape(col)}"]`);
    positionColPanel(btnNow ? btnNow.getBoundingClientRect() : rectBefore);
  }

  function positionColPanel(rect) {
    const p = $("jobColPanel");
    const host = $("jobTableHost").getBoundingClientRect();
    const left = Math.max(0, Math.min(rect.left - host.left, host.width - 260));
    p.style.left = `${left}px`;
    p.style.top = `${rect.bottom - host.top + 4}px`;
  }

  function rangeRow(slot, clause) {
    const ops = RANGE_OPS.map(([k, sym]) =>
      `<option value="${k}"${clause && clause.op === k ? " selected" : ""}>${sym}</option>`).join("");
    return `<div class="cp-range-row"><select class="field" data-rop="${slot}" data-busy-lock>${ops}</select>` +
      `<input class="field" data-rval="${slot}" type="text" data-busy-lock ` +
      `value="${clause ? esc(clause.operand) : ""}" placeholder="${slot === 1 ? "값" : "값(선택)"}"></div>`;
  }

  function renderColPanel(d) {
    const p = $("jobColPanel");
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
      `<div class="cp-head"><span>「${esc(d.column)}」 필터</span>` +
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
    const boxes = Array.from($("jobColPanel").querySelectorAll("input[data-val]"));
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
      $("jobColPanel").querySelectorAll("input[data-val]").forEach((b) => { b.checked = all; });
      Bridge.call(SCREEN, "filter_col_values", { column: panelCol, values: all ? null : [] });
      return;
    }
    if (e.target.matches("input[data-val]")) {
      const values = panelValues();
      const allBox = $("jobColPanel").querySelector("[data-val-all]");
      if (allBox) allBox.checked = values === null;
      Bridge.call(SCREEN, "filter_col_values", { column: panelCol, values });
    }
  }

  async function onPanelClick(e) {
    if (e.target.closest('[data-act="panel-close"]')) { closeColPanel(); return; }
    if (e.target.closest('[data-act="col-clear"]')) {
      const col = panelCol;
      await Bridge.call(SCREEN, "filter_clear_col", { column: col });
      const btn = document.querySelector(`.fico[data-col="${CSS.escape(col)}"]`);
      if (btn) openColPanel(col, btn); else closeColPanel();
      return;
    }
    if (e.target.closest('[data-act="range-apply"]')) {
      const p = $("jobColPanel");
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

  function onDocPointerDown(e) {
    if (panelCol === null) return;
    if (e.target.closest("#jobColPanel") || e.target.closest(".fico")) return;
    closeColPanel();
    // 닫기 제스처가 그 클릭의 원래 동사(행 토글·버튼)로 새지 않게 다음 click 하나를
    // 캡처 단계에서 소비한다(리뷰 #3 — 패널을 닫으려는 행 클릭이 생성 집합을 바꿨다).
    suppressNextClick = true;
  }

  function onDocKeydown(e) {
    if (e.key === "Escape" && panelCol !== null) closeColPanel();
  }

  function onHeadClick(e) {
    const btn = e.target.closest(".fico[data-col]");
    if (!btn) return;
    const col = btn.dataset.col;
    if (panelCol === col) { closeColPanel(); return; }
    openColPanel(col, btn);
  }

  /* ---- 게이트 · 재진술 블록(상시, 결정 36 D1-B) — 선택 유래 + 산출 요약 + 이름 목록.
     이미 보이는 것을 재검증하지 않으므로 모달이 아니라 상시 블록이다. 이름 = 실파일명(정준) ·
     식별 요약(보조, PR-1 identity_summary). 소량(≤3)=전부, 대량=층화 표본(결정 5 —
     Python restate.sample, 광의 OR 의 소수 가지가 반드시 등장) + 「외 N건 펼치기」.
     선택 유래(결정 4) = 집합 비교 무상태 판정(restate.origin): 정의-유래면 정의줄을
     재진술하고, 이탈이면 매치/밖 수치를 병기한다(S4 델타). */
  function renderRestate(s) {
    const box = $("jobRestate");
    // 펼침 상태는 작업/데이터 전환에 리셋한다(모듈 전역이 다른 세션으로 새지 않게). 선택 토글은
    // 유지 — 같은 세션 내 편집이므로. 세션 지문(선택 제외)으로 판정.
    const rkey = (s.job_name || "") + "|" + (s.data_source_label || "");
    if (rkey !== lastRestateKey) { restateExpanded = false; lastRestateKey = rkey; }
    const sel = (s.records || []).filter((r) => r.selected);
    // danger 차단(드리프트·미해소 파일명 토큰) 중엔 재진술을 숨긴다 — "생성 불가"인데 "N건 생성"을
    // 동시에 진술하면 모순(confirm-or-alarm, 리뷰). '차단' 판정은 게이트 단일 출처를 소비한다
    // (drift 를 독립 재유도하지 않는다 — 백엔드 RC-23 서열이 danger 를 이미 합성; 토큰 danger 도 포섭).
    const blocked = !!(s.gate && s.gate.level === "danger");
    if (!s.has_data || !sel.length || blocked) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    const rs = s.restate || { origin: null, filter_active: false, sample: [] };
    const byIndex = {};
    sel.forEach((r) => { byIndex[r.index] = r; });
    // 표본 = 층화(Python) — 펼침·소량은 전부.
    const sampleIdx = (sel.length <= 3 || restateExpanded)
      ? sel.map((r) => r.index)
      : (rs.sample || []).filter((i) => byIndex[i]);
    const shown = sampleIdx.map((i) => byIndex[i]).filter(Boolean);
    const list = shown.map((r) =>
      `<span class="nm"><b>${esc(r.name || "(파일명 미정)")}</b>` +
      (r.summary ? ` · ${esc(r.summary)}` : "") + `</span>`).join("");
    const more = (sel.length > 3)
      ? `<button class="btn sm" id="jobRestateMore" data-act="restate-more" data-busy-lock>` +
        (restateExpanded ? "접기" : `⋯ 외 ${sel.length - shown.length}건 펼치기`) + `</button>`
      : "";
    // 선택 유래 문안(결정 4·S4) — 정의-유래 = 정의줄 재진술이 「전체 선택」의 담보.
    // 직접 선택 문안은 가드 모달과 공유 합성기(selectionLine, 리뷰 #9)로 단일 출처.
    const selLine = (rs.origin === "definition")
      ? `정의 매치 전체 ${sel.length}행 — ${esc((s.filter && s.filter.definition) || "")}`
      : esc(selectionLine(sel.length, rs.filter_active, rs.in_def, rs.extra));
    box.innerHTML =
      `<span class="dl">선택</span><span>${selLine}</span>` +
      `<span class="dl">생성</span><span>문서 ${sel.length}건 · 저장 폴더: ${esc(s.out_dir || "미지정")}` +
      `<div class="namelist">${list}${more}</div></span>`;
  }

  /* ---- 데이터 존: 필터 테이블(블록 4, 결정 23~25) ----
     선두 「문서」 열(체크 표지 + 실파일명 + 식별 요약, F33 승계) + 원본 데이터 열.
     셀 텍스트는 Python 이 잘라 보낸 하이라이트 세그먼트를 그리기만 한다(자모 역매핑 —
     매치 인덱스를 받지 않는다, 파생경계 번역오류의 상류 차단). 가시 행만 렌더 —
     필터 밖 선택은 스트립(renderStrip)이 상시 진술한다(결정 3). */
  let selAnchor = null;      // Shift 범위 앵커(행 index) — 세션 전환 시 리셋
  let selAnchorState = null; // 앵커의 **현재** 선택 상태 — 마지막 디스패치 값 기준(리뷰 #2:
                             // LAST 는 왕복 전이라 앵커 자신의 토글이 아직 안 비쳐 stale)
  let lastTableKey = null;   // 앵커 리셋 판정(작업·데이터 지문)
  let searchTimer = 0;       // 전열 검색 디바운스 — 세션 전환 시 취소(리뷰 #1: 다음 세션 오발)
  let suppressNextClick = false; // 패널 바깥클릭 닫기 제스처가 행 토글로 새지 않게(리뷰 #3)

  function segsHtml(segs) {
    if (!segs || !segs.length) return "";
    return segs.map(([t, hit]) => (hit ? `<mark>${esc(t)}</mark>` : esc(t))).join("");
  }

  function renderTable(s) {
    const tkey = (s.job_name || "") + "|" + (s.data_source_label || "");
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
    $("jobSelCount").textContent =
      `선택 ${s.selected_count}/${s.record_count}` +
      (f.active ? ` · 표시 ${t.visible_count}` : "");
    const si = $("jobFilterSearch");
    si.style.display = hasData ? "" : "none";
    // 타이핑 중엔 스냅샷이 입력값을 덮지 않는다(왕복 경합 — 확정은 다음 blur/재진입 렌더).
    if (document.activeElement !== si) si.value = f.search || "";
    // 직전 필터 재적용(결정 28) — 슬롯 존재 ∧ 소스 일치일 때만 어포던스 노출.
    $("jobFilterReapply").style.display =
      hasData && f.reapply_available ? "" : "none";
    const wrap = $("jobTableWrap");
    const empty = $("jobTableEmpty");
    if (!hasData) {
      wrap.style.display = "none";
      empty.style.display = "";
      empty.textContent = "데이터를 선택하면 생성 대상 문서가 여기에 표시됩니다.";
      return;
    }
    wrap.style.display = "";
    if (!t.rows.length) {
      // 전멸도 정직하게 — 이유(정의)는 칩 줄이 재진술한다.
      empty.style.display = "";
      empty.textContent = f.active
        ? "필터와 일치하는 행이 없습니다. 위 칩의 정의를 확인하세요."
        : "데이터에 행이 없습니다.";
    } else {
      empty.style.display = "none";
    }
    $("jobTableHead").innerHTML =
      `<tr><th class="doccol">문서</th>` +
      t.columns.map((c, ci) => {
        const meta = f.columns[ci] || { active: false };
        return `<th><span>${esc(c)}</span> ` +
          `<button class="fico${meta.active ? " on" : ""}" data-col="${esc(c)}" ` +
          `aria-label="${esc(c)} 열 필터" aria-expanded="${panelCol === c}" ` +
          `data-busy-lock>▾</button></th>`;
      }).join("") + `</tr>`;
    $("jobTableBody").innerHTML = t.rows.map((r) => {
      const doc = r.name
        ? `<span class="doc-name">${esc(r.name)}</span>`
        : `<span class="doc-name doc-off">선택하면 파일명이 정해집니다</span>`;
      const sum = r.summary ? `<span class="doc-sum">${esc(r.summary)}</span>` : "";
      return `<tr data-i="${r.index}" id="jobRow-${r.index}" class="${r.selected ? "on" : ""}" ` +
        `role="checkbox" aria-checked="${r.selected ? "true" : "false"}" tabindex="0">` +
        `<td class="doccol"><input type="checkbox" tabindex="-1"${r.selected ? " checked" : ""}>` +
        `<span class="doc-body">${doc}${sum}</span></td>` +
        r.cells.map((segs) => `<td>${segsHtml(segs)}</td>`).join("") + `</tr>`;
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
    const box = $("jobFilterChips");
    const f = s.filter || { active: false };
    if (!s.has_data || !f.active) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    box.innerHTML =
      (f.chips || []).map((c) => `<span class="fchip">${esc(c)}</span>`).join("") +
      (f.branches || []).map((b) =>
        `<span class="fchip branch">${esc(b)}` +
        `<button data-prune="${esc(b)}" aria-label="${esc(b)} 가지 제거" data-busy-lock>×</button></span>`
      ).join("") +
      `<button class="btn sm" data-act="filter-clear" data-busy-lock>필터 지우기</button>`;
  }

  /* ---- 필터 밖 선택 스트립(결정 3) — 선택은 관통, 밖은 상시 가시 ---- */
  function renderStrip(s) {
    const box = $("jobSelStrip");
    const hs = (s.table && s.table.hidden_selected) || [];
    if (!s.has_data || !hs.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    // 항목별 × = 개별 해제 어포던스(리뷰 #6 — 구 목록의 행별 체크박스가 지던 의무 승계:
    // 필터를 허물거나 전체 해제하지 않고도 필터 밖 선택 하나만 뺄 수 있어야 한다).
    const chips = hs.map((r) =>
      `<span class="fchip">${esc(r.name || r.summary || `${r.index + 1}행`)}` +
      `<button data-unsel="${r.index}" aria-label="${r.index + 1}행 선택 해제" data-busy-lock>×</button></span>`
    ).join("");
    box.innerHTML =
      `필터 밖 선택 <b>${hs.length}행</b> — 화면엔 안 보이지만 생성에 포함됩니다: ${chips}`;
  }

  /* ---- 본문 존: 게이트·저장 폴더·생성 버튼 ---- */
  function renderGateAndFolder(s) {
    $("jobOutDir").value = s.out_dir || "";
    // 저장 폴더 열기/경로 복사 어포던스(#53-B) — 실행 화면에서 승계(리뷰 F3). 생성 후 앱에서
    // 바로 폴더를 열거나 경로를 복사한다(빈 out_dir 이면 PathTrack 이 알아서 아무것도 안 그림).
    const ot = $("jobOutTrack");
    if (ot) ot.innerHTML = PathTrack.affordances(s.out_dir, { only: ["reveal", "copy"] });
    const g = s.gate || { enabled: false, level: "", text: "" };
    $("jobGenBtn").disabled = !g.enabled || generating;
    const gate = $("jobGate");
    gate.textContent = generating ? "" : g.text;
    gate.className = "muted";
    gate.style.color = g.level === "danger" ? "var(--a-danger)"
      : g.level === "warn" ? "var(--a-warn)" : "";
  }

  function renderStatus(s) {
    const pill = $("jobStatus");
    if (!s.has_job) { pill.dataset.level = "idle"; pill.textContent = "작업 선택"; return; }
    if (!s.has_data) { pill.dataset.level = "idle"; pill.textContent = "데이터 선택"; return; }
    if (s.gate && s.gate.enabled) { pill.dataset.level = "ok"; pill.textContent = "생성 준비"; }
    else { pill.dataset.level = "warn"; pill.textContent = "확인 필요"; }
  }

  /* 진행 델타 — 진행바만 갱신(전체 재렌더 없음). */
  function renderProgress(p) {
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    $("jobGenBar").style.width = pct + "%";
    const r = $("jobGenResult");
    r.className = "run-result";
    r.textContent = `생성 중… ${p.done}/${p.total}`;
  }

  /* ---- 로그(완료 존, 세션 스코프) ---- */
  let logStarted = false;
  function log(msg) {
    const box = $("jobGenLog");
    const ts = new Date().toLocaleTimeString("ko-KR", { hour12: false });
    if (!logStarted) { box.textContent = ""; logStarted = true; }
    box.textContent += (box.textContent ? "\n" : "") + `[${ts}] ${msg}`;
    box.scrollTop = box.scrollHeight;
  }

  /* ---- busy 잠금 — [data-busy-lock] 속성 선언(setBusy 누락 회귀 방지, #26) ---- */
  function setBusy(busy) {
    $("scr-job").querySelectorAll("[data-busy-lock]").forEach((el) => { el.disabled = busy; });
    $("jobGenBtn").disabled = busy || !(LAST && LAST.gate && LAST.gate.enabled);
    $("jobGenBtn").textContent = busy ? "생성 중…" : "이 작업으로 문서 생성";
  }

  /* ---- 덮어쓰기 확인 본문 = 수치 합성(A-2-22, 결정 36) — 총량·파괴분·신규분을 종류별로
     재진술한다(블록 4 가드 형식 승계). 별도 재진술 모달을 만들지 않고, 어차피 떠야 하는 RC-02
     덮어쓰기 모달이 수치를 나른다. 공용 modal.js Modal.confirm(기본 포커스=머무르기·Escape=
     머무르기)이 담당한다 — 새 표면은 처음부터 #86 재유입 가드에 부합(window.confirm 무사용). */
  function overwriteBody(res) {
    const names = res.conflict_names || [];
    const more = res.conflict_more ? `\n외 ${res.conflict_more}개` : "";
    return `${res.total}건을 생성합니다. 이 중 ${res.overwrite_count}건이 기존 파일을 덮어씁니다:\n` +
      `${names.join("\n")}${more}\n\n나머지 ${res.new_count}건은 새 파일입니다.`;
  }

  async function doGenerate(confirmOverwriteFlag) {
    generating = true; setBusy(true);
    if (!confirmOverwriteFlag) { $("jobGenBar").style.width = "0%"; log("생성 요청"); }
    // busy-lock 은 덮어쓰기 모달 종료까지 유지한다 — finally 를 needs_overwrite 흐름 뒤에 두어,
    // 모달이 열린 동안 생성 버튼이 재활성돼 두 번째 생성이 첫 확인 미결인 채 시작되는 재진입
    // 경합을 막는다(리뷰 #1: modal.js 는 blocking window.confirm 과 달리 포커스 트랩이 없어
    // 백드롭 뒤 살아있는 버튼에 Tab+Enter 가 닿는다 — run.js 엔 없던 창).
    try {
      const res = await Bridge.generate(SCREEN, confirmOverwriteFlag);
      if (res.ok) { renderResult(res); return; }
      if (res.needs_overwrite) {
        // 조용한 덮어쓰기 금지 — 수치 재진술 후 확인 시에만 재호출(RC-02). 모달 대기 동안 busy 유지.
        const ok = await window.Modal.confirm({
          title: "덮어쓰기 확인", body: overwriteBody(res),
          confirmLabel: "덮어쓰고 생성", cancelLabel: "머무르기",
        });
        if (ok) { await doGenerate(true); }
        else { log("생성 취소. 기존 파일 덮어쓰기를 확정하지 않았습니다."); }
        return;
      }
      warnResult(res.error || "생성할 수 없습니다.", res.level);
    } finally {
      generating = false; setBusy(false);
    }
  }

  function renderResult(res) {
    $("jobGenBar").style.width = "100%";
    const r = $("jobGenResult");
    r.textContent = res.summary;
    r.className = "run-result " + (res.level === "ok" ? "ok" : "danger");
    log(res.summary);
    (res.failures || []).forEach((f) => log("  [실패] " + f));
    log(`저장 폴더: ${res.out_dir}`);
  }

  function warnResult(msg, level) {
    const r = $("jobGenResult");
    r.textContent = "확인 필요: " + msg;
    r.className = "run-result " + (level === "danger" ? "danger" : "warn");
    log(msg);
  }

  /* ---- 웹→Python 이벤트 ---- */
  /* ---- 세션 가드(블록 4, 결정 26·27) — 파괴 전이의 수치 재진술 본문 합성 ----
     술어·수치는 Python(_guard_state)이 판정하고, 여기는 문안만 입힌다. verbPhrase 로
     전이 종류(T1 작업 전환 / 데이터 재겨눔 / 템플릿 재연결)를 구분 — 무엇이 사라지는지 명시. */

  /* 선택 재진술 한 줄 — 재진술 블록(renderRestate)과 가드 모달(guardBody)의 **공유
     합성기**(리뷰 #9): 같은 수치를 두 곳이 따로 조립하면 문안이 갈라져 모달이 화면
     재진술과 모순되는 드리프트 클래스가 생긴다. */
  function selectionLine(count, filterActive, inDef, extra) {
    return filterActive
      ? `직접 선택 ${count}행 (정의 매치 ${inDef} · 정의 밖 ${extra})`
      : `직접 선택 ${count}행`;
  }

  function guardBody(g, verbPhrase) {
    const lost = g.filter_parts > 0
      ? `행 선택과 필터 정의(${g.filter_parts}개 조건)가 사라집니다.`
      : `행 선택이 사라집니다.`;
    return `이 세션에는 다시 만들기 어려운 선택이 있습니다: ` +
      `${selectionLine(g.sel_count, g.filter_active, g.in_def, g.extra)}.\n` +
      `${verbPhrase} ${lost}`;
  }

  /* 파괴 전이 사전 확인(데이터 재겨눔·템플릿 재연결 — T1 동류 세션 재구성). 피커/흐름을
     열기 **전에** 묻는다(파일까지 고른 뒤 "머무르기"는 고른 노동을 또 버리게 한다).
     무장 판정은 guard_state **실시간 질의**(리뷰 #4: 스냅샷 캐시는 generate 무푸시
     경로·왕복 지연에서 stale — 완주 직후 거짓 모달·무장 직후 무확인 통과 양방향 오판).
     true=진행, false=머무르기. */
  async function confirmDestructiveIfArmed(title, verbPhrase, confirmLabel) {
    const g = await Bridge.call(SCREEN, "guard_state", {});
    if (!g || !g.armed) return true;
    return window.Modal.confirm({
      title, body: guardBody(g, verbPhrase),
      confirmLabel, cancelLabel: "머무르기",
    });
  }

  function confirmDataSwapIfArmed() {
    return confirmDestructiveIfArmed(
      "데이터 변경 확인", "다른 데이터를 겨누면", "데이터 바꾸고 버리기");
  }

  /* 대기 중 검색 디바운스 정산 — 세션 전환 시도 **전에** 미적용 검색어를 먼저 적용한다
     (리뷰 #2: 취소만 하면 「머무르기」로 남은 세션에서 마지막 타이핑이 조용히 증발).
     전환이 확정되면 필터째 죽으니 선적용은 무해하고, 머무르면 타이핑이 보존된다. */
  async function flushPendingSearch() {
    clearTimeout(searchTimer);
    const si = $("jobFilterSearch");
    if (LAST && LAST.has_data && LAST.filter
        && si.value !== (LAST.filter.search || "")) {
      await Bridge.call(SCREEN, "filter_search", { text: si.value });
    }
  }

  /* T1 가드 왕복(RC-02 동형): 무변이 needs_confirm → modal.js 이진 확인(기본 포커스=
     머무르기·Escape=머무르기) → 확인 시에만 confirm=true 재호출. 단일 실행(switching)
     — 더블클릭이 두 왕복·두 모달을 만들면 modal.js 재진입 가드가 loud 거절을 띄운다
     (리뷰 #5: 정상 제스처에 오류성 경보). */
  let switching = false;
  async function selectJobGuarded(name) {
    /* 반환 = 전환 성사 여부(false=머무르기/재진입 거절) — 편집 모드 이탈이 이 판정을
       기다린다(가드 선행·전환 후행, PR-2 리뷰 F5: 취소는 무변화여야 한다). */
    if (switching) return false;
    switching = true;
    try {
      const res = await Bridge.call(SCREEN, "select_job", { name });
      if (res && res.needs_confirm) {
        const ok = await window.Modal.confirm({
          title: "작업 전환 확인",
          body: guardBody(res, "작업을 전환하면"),
          confirmLabel: "전환하고 버리기", cancelLabel: "머무르기",
        });
        if (!ok) return false;
        await Bridge.call(SCREEN, "select_job", { name, confirm: true });
      }
      return true;
    } finally {
      switching = false;
    }
  }

  function onMasterClick(e) {
    const item = e.target.closest(".job-item[data-job]");
    if (!item) return;
    const already = item.getAttribute("aria-current") === "true";
    // 편집 중 행 클릭 = 실행 복귀(결정 40 — 복귀 어포던스는 좌 목록이 담당). **가드 선행·
    // 전환 후행**(PR-2 리뷰 F5): T1 확인이 끝나기 전엔 편집 표면을 걷지 않는다 —
    // 「머무르기」=무변화(취소가 편집 화면을 잃게 하면 안 된다). 선택을 먼저 성사시키는
    // 구조라 지연 선택이 뒤늦게 클릭을 추월하는 창도 없다(리뷰 F8). 같은 작업 재클릭이면
    // 진행 중 세션을 그대로 다시 노출한다(재구성 없음 — 아래 무동작 가드와 동근).
    if (MODE === "edit") {
      (async () => {
        if (!already) {
          await flushPendingSearch();
          if ((await selectJobGuarded(item.dataset.job)) === false) return;  // 머무르기
        }
        if (await exitEditToRun()) showExitNote();  // T2 고지(미저장 편집 있을 때만)
      })();
      return;
    }
    // 이미 선택된 작업 재클릭 = 무동작(세션 재구성으로 데이터 겨눔이 날아가지 않게).
    if (already) return;
    // 미적용 검색어는 전환 시도 전에 정산(적용) — 취소만 하면 「머무르기」 세션에서
    // 마지막 타이핑이 증발한다(리뷰 #2). 새 세션 오발도 함께 차단(PR-2b 리뷰 #1).
    flushPendingSearch().then(() => selectJobGuarded(item.dataset.job));
  }

  /* 허브(홈)에서 이 작업을 열기 — 좌 목록 재클릭 무동작 가드(onMasterClick)와 동형.
     이미 이 작업 세션이면 재구성하지 않고(진행 중 데이터 겨눔·행 선택·확인이 조용히 소실되지
     않게 — 리뷰 F1) 그대로 두고 화면만 전환한다. 아니면 겨눠 진입한다. */
  function openJob(name) {
    // 허브발 실행 진입도 행 클릭과 동형 — 가드 선행·전환 후행(리뷰 F5), 미저장 편집은 고지.
    if (MODE === "edit") {
      (async () => {
        if (!(LAST && LAST.job_name === name)) {
          await flushPendingSearch();
          if ((await selectJobGuarded(name)) === false) {
            window.Nav.go(SCREEN);  // 머무르기 — 편집 표면 유지한 채 화면만 노출
            return;
          }
        }
        if (await exitEditToRun()) showExitNote();
        window.Nav.go(SCREEN);
      })();
      return;
    }
    if (!(LAST && LAST.job_name === name)) {
      // 미적용 검색 정산 후 T1 가드 승계 — 허브 진입도 같은 파괴 전이(결정 26).
      flushPendingSearch().then(() => selectJobGuarded(name));
    }
    window.Nav.go(SCREEN);
  }

  /* 거울 미입력 행 = ADR-E 배지 — 클릭=확인·재클릭=철회(UD-19). ackd 클래스로 토글 방향 판정. */
  function mirrorAck(rowEl) {
    const act = rowEl.classList.contains("ackd") ? "unack_field" : "ack_field";
    Bridge.call(SCREEN, act, { field: rowEl.dataset.f });
  }

  function onMirrorClick(e) {
    if (e.target.closest('[data-act="fix-mapping"]')) { fixMapping(); return; }
    const row = e.target.closest(".mir-row.miss");
    if (row) mirrorAck(row);
  }

  function onMirrorKey(e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest(".mir-row.miss");
    if (!row) return;
    e.preventDefault();
    mirrorAck(row);
  }

  /* danger(구조 드리프트) 수리 동선 — 이 작업을 **패널 편집 모드**에 열어 매핑을 재확정한다
     (공용 EditorEntry.openGuarded: 미저장 정의 확인 후 모드 전환 — 에디터 흡수로 화면 이동이
     아니라 제자리 모드 전환이 됐다). 확정·저장 후 좌 목록 행 클릭으로 세션 재개. */
  function fixMapping() {
    if (LAST && LAST.job_name) EditorEntry.openGuarded(LAST.job_name);
  }

  /* 템플릿 다시 연결(#67) — 공용 흐름(relink.js)에 위임, 결과 재진술 채널만 log 주입.
     재연결 확정은 기선택 작업을 재적재해 세션(선택·필터·겨눔)을 재구성한다 — T1 동류
     파괴 전이이므로 무장 시 먼저 확인한다(리뷰 #0: 재연결 확인문은 템플릿 경로만
     재진술해 선택 소실이 조용히 지나갔다). */
  async function doRelinkTemplate() {
    if (!(LAST && LAST.job_name)) return;
    const ok = await confirmDestructiveIfArmed(
      "템플릿 다시 연결 확인", "템플릿을 다시 연결하면", "다시 연결하고 버리기");
    if (!ok) return;
    Relink.relinkTemplate(SCREEN, LAST.job_name, (msg) => log(msg));
  }

  function wire() {
    // 패널 바깥클릭 닫기 제스처의 click 을 캡처 단계에서 1회 소비(리뷰 #3) — 닫기와
    // 행 토글/버튼 실행이 한 클릭에 겹치지 않게.
    document.addEventListener("click", (e) => {
      if (suppressNextClick) {
        suppressNextClick = false;
        e.stopPropagation();
        e.preventDefault();
      }
    }, true);
    $("jobListHwpx").addEventListener("click", onMasterClick);
    $("jobSelAll").addEventListener("click", async () => {
      const r = await Bridge.call(SCREEN, "set_all", {});
      // 전멸 필터에서의 무동작은 정직하게 알린다(confirm-or-alarm, 리뷰 #9).
      if (r && r.added === 0) {
        log("전체 선택: 현재 필터와 일치하는 새로 추가할 행이 없습니다.");
      }
    });
    $("jobSelNone").addEventListener("click", () => Bridge.call(SCREEN, "set_none", {}));
    // 데이터 테이블(블록 4) — 행 클릭 토글 + Shift 범위, 열 머리 필터 아이콘, 전열 검색.
    $("jobTableBody").addEventListener("click", onTableClick);
    $("jobTableBody").addEventListener("keydown", onTableKey);
    $("jobTableHead").addEventListener("click", onHeadClick);
    $("jobFilterSearch").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      const text = e.target.value;
      searchTimer = setTimeout(() => Bridge.call(SCREEN, "filter_search", { text }), 200);
    });
    // 직전 필터 재적용(결정 28) — 정의만 복원(선택 불변), 탈락은 시끄럽게 고지(백스톱).
    $("jobFilterReapply").addEventListener("click", async () => {
      const res = await Bridge.call(SCREEN, "filter_reapply", {});
      if (!res.ok) { log("확인 필요: " + res.error); return; }
      log(`직전 필터를 재적용했습니다 (조건 열: ${res.installed.join(", ") || "검색만"}).`);
      if (res.dropped.length) {
        log(`확인 필요: 현재 데이터에 없는 조건은 빠졌습니다 — ${res.dropped.join(", ")}`);
      }
    });
    // 필터 밖 선택 스트립 — 항목별 × 해제(리뷰 #6).
    $("jobSelStrip").addEventListener("click", (e) => {
      const un = e.target.closest("[data-unsel]");
      if (un) Bridge.call(SCREEN, "toggle_record", { index: Number(un.dataset.unsel), value: false });
    });
    // 칩 줄 — 가지 프루닝 ×·필터 지우기(재렌더 생존 위임).
    $("jobFilterChips").addEventListener("click", (e) => {
      const pr = e.target.closest("[data-prune]");
      if (pr) { Bridge.call(SCREEN, "filter_prune", { column: pr.dataset.prune }); return; }
      if (e.target.closest('[data-act="filter-clear"]')) Bridge.call(SCREEN, "filter_clear", {});
    });
    // 열 필터 패널 — 내부 위임 + 바깥 클릭/Escape 닫기.
    $("jobColPanel").addEventListener("input", onPanelInput);
    $("jobColPanel").addEventListener("change", onPanelChange);
    $("jobColPanel").addEventListener("click", onPanelClick);
    document.addEventListener("pointerdown", onDocPointerDown);
    document.addEventListener("keydown", onDocKeydown);
    // T2 복귀 고지 — 확인 버튼으로 걷는다(읽힐 때까지 존속, 리뷰 F4).
    $("jobEditExitNote").addEventListener("click", (e) => {
      if (e.target.closest('[data-act="dismiss-exit-note"]')) {
        $("jobEditExitNote").style.display = "none";
      }
    });
    // 재렌더에도 살아남게 안정 컨테이너에 위임(#67).
    $("jobRelink").addEventListener("click", (e) => {
      if (e.target.closest('[data-act="relink-template"]')) doRelinkTemplate();
    });
    // 거울(재렌더에도 살아남게 안정 컨테이너에 위임) — 미입력 행 ack + 드리프트 수리 링크.
    $("jobMirror").addEventListener("click", onMirrorClick);
    $("jobMirror").addEventListener("keydown", onMirrorKey);
    // 재진술 블록 이름 목록 펼침/접기(대량 표본).
    $("jobRestate").addEventListener("click", (e) => {
      if (e.target.closest('[data-act="restate-more"]')) {
        restateExpanded = !restateExpanded;
        // Preserve.around 로 감싼다 — 토글 버튼(id=jobRestateMore)이 innerHTML 재구성을
        // 가로질러 포커스를 유지하게(거울-행 ack 경로와 같은 규율, 리뷰). 밖에서 부르면 body 낙하.
        if (LAST) Preserve.around(() => renderRestate(LAST));
      }
    });
    $("jobGenBtn").addEventListener("click", () => doGenerate(false));

    $("jobBtnPickData").addEventListener("click", async () => {
      if (!(await confirmDataSwapIfArmed())) return;  // 데이터 재겨눔 = T1 동류 파괴 전이
      let r = await Bridge.pickDataFile(SCREEN);
      if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
        r = await SheetPicker.choose(SCREEN, r);
        if (r === null) { log("데이터 선택 취소. 시트를 확정하지 않았습니다."); return; }
      }
      if (r === null) return;                       // 취소
      if (typeof r === "string" && r.startsWith("ERROR:")) { log("데이터 오류: " + r.slice(6).trim()); return; }
      log(`데이터 불러옴: ${r}`);
    });
    // 등록 데이터(풀) 겨눔(#26 #6) — 취소=중단, 실패는 모달 안에서 재진술(PoolPicker).
    $("jobBtnPoolData").addEventListener("click", async () => {
      if (!(await confirmDataSwapIfArmed())) return;  // 데이터 재겨눔 = T1 동류 파괴 전이
      const label = await PoolPicker.choose(SCREEN);
      if (label === null) return;                   // 취소 = 겨눔 중단
      log(`등록 데이터 불러옴: ${label}`);
    });
    $("jobBtnPickFolder").addEventListener("click", async () => {
      const r = await Bridge.pickOutputFolder(SCREEN);
      if (r === null) return;                       // 취소
      if (typeof r === "string" && r.startsWith("ERROR:")) { log("폴더 오류: " + r.slice(6).trim()); return; }
      log(`저장 폴더: ${r}`);
    });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    render(await Bridge.initial(SCREEN));
  }

  // overwriteBody·guardBody 는 순수 합성기 — 실앱 게이트가 합성 결과(수치·문안 배치)를
  // 되읽어 회귀를 막는다(파괴적 확인의 조용한 드리프트 금지 — RC-02 판과 가드 판 동형).
  // confirmDataSwapIfArmed 는 배선 존재 핀(리뷰 #6 — JS 전용 가드 지점이라 삭제 회귀를
  // 실앱 게이트가 잡을 표식이 없었다).
  // showEditMode/refreshList 는 편집 모드 seam(EditorEntry·editor.js doSave 가 소비).
  window.JobScreen = {
    init, overwriteBody, guardBody, confirmDataSwapIfArmed, openJob,
    showEditMode, refreshList,
  };
})();
