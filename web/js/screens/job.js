/* 「작업」 화면 — 좌 master 목록 + 우 세션 패널 4존(R-flow 슬라이스 1~2, #90).
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

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    if (s && s.progress) { renderProgress(s.progress); return; }  // 진행 델타(경량)
    Preserve.around(() => {  // 매핑/레코드 포커스·스크롤 보존(#28)
      LAST = s;
      renderMaster(s);
      const hasJob = !!s.has_job;
      $("jobZones").style.display = hasJob ? "" : "none";
      $("jobEmptyPanel").style.display = hasJob ? "none" : "";
      if (hasJob) {
        renderHeader(s);
        renderData(s);
        renderPreflight(s);
        renderMirror(s);
        renderRecords(s);
        renderRestate(s);
        renderGateAndFolder(s);
      }
      renderStatus(s);
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
      : `템플릿 경로가 비어 있습니다. 에디터에서 템플릿을 지정하세요.`;
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
        `<button class="btn sm" data-act="fix-mapping" data-busy-lock>작업 에디터에서 매핑 확정…</button>` +
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

  function mirrorRow(r) {
    const nm = esc(r.name);
    const val = esc(r.value);
    if (r.state === "filled") {
      return `<tr class="mir-row"><td class="mir-f">${nm}</td><td class="mir-v">${val}</td>` +
        `<td class="mir-s"><span class="st filled">채움${r.formatted ? " · 표시형" : ""}</span></td></tr>`;
    }
    if (r.state === "blank") {
      return `<tr class="mir-row blankd"><td class="mir-f">${nm}</td><td class="mir-v">${val}</td>` +
        `<td class="mir-s"><span class="st blankd">빈칸 선언</span></td></tr>`;
    }
    // missing — 클릭형 행(확인/철회 토글). ack 여부로 색·칩 전환.
    const ack = r.acknowledged;
    const chip = ack ? `<span class="st ackd">확인됨 · 클릭=철회</span>`
                     : `<span class="st miss">미입력 · 클릭=확인</span>`;
    return `<tr class="mir-row miss${ack ? " ackd" : ""}" role="button" tabindex="0" ` +
      `data-f="${nm}" aria-pressed="${ack ? "true" : "false"}">` +
      `<td class="mir-f">${nm}</td><td class="mir-v">${val}</td><td class="mir-s">${chip}</td></tr>`;
  }

  /* ---- 게이트 · 재진술 블록(상시, 결정 36 D1-B) — 선택 유래 + 산출 요약 + 이름 목록.
     이미 보이는 것을 재검증하지 않으므로 모달이 아니라 상시 블록이다. 이름 = 실파일명(정준) ·
     식별 요약(보조, PR-1 identity_summary). 소량(≤3)=전부, 대량=표본 3 + 「외 N건 펼치기」.
     층화 표본(결정 5)은 필터(슬라이스 4) 착지 후 합류 — 지금은 단순 앞 표본. */
  function renderRestate(s) {
    const box = $("jobRestate");
    const sel = (s.records || []).filter((r) => r.selected);
    if (!s.has_data || !sel.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    const shown = (sel.length <= 3 || restateExpanded) ? sel : sel.slice(0, 3);
    const list = shown.map((r) =>
      `<span class="nm"><b>${esc(r.name || "(파일명 미정)")}</b>` +
      (r.summary ? ` · ${esc(r.summary)}` : "") + `</span>`).join("");
    const more = (sel.length > 3)
      ? `<button class="btn sm" data-act="restate-more" data-busy-lock>` +
        (restateExpanded ? "접기" : `⋯ 외 ${sel.length - 3}건 펼치기`) + `</button>`
      : "";
    box.innerHTML =
      `<span class="dl">선택</span><span>직접 선택 ${sel.length}행</span>` +
      `<span class="dl">생성</span><span>문서 ${sel.length}건 · 저장 폴더: ${esc(s.out_dir || "미지정")}` +
      `<div class="namelist">${list}${more}</div></span>`;
  }

  /* ---- 데이터 존: 생성 대상 문서(행 선택) ---- */
  function renderRecords(s) {
    const host = $("jobRecList");
    const recs = s.records || [];
    $("jobSelCount").textContent = `선택 ${s.selected_count}/${s.record_count}`;
    if (!recs.length) {
      host.innerHTML = `<div class="rec muted">데이터를 선택하면 생성 대상 문서가 여기에 표시됩니다.</div>`;
      return;
    }
    // 행 = 체크박스 + 실파일명(선택 행만 — 미선택 행 이름은 지어내지 않는다) + 식별 요약(F33).
    host.innerHTML = recs.map((r) =>
      `<label class="rec"><input type="checkbox" data-i="${r.index}"${r.selected ? " checked" : ""}>` +
      `<span class="rec-no">${r.index + 1}.</span>` +
      `<span class="rec-body">` +
      (r.name ? `<span class="rf">${esc(r.name)}</span>`
              : `<span class="rf rec-off">선택하면 파일명이 정해집니다</span>`) +
      (r.summary ? `<span class="rec-id">${esc(r.summary)}</span>` : "") +
      `</span></label>`).join("");
  }

  /* ---- 본문 존: 게이트·저장 폴더·생성 버튼 ---- */
  function renderGateAndFolder(s) {
    $("jobOutDir").value = s.out_dir || "";
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
  function onMasterClick(e) {
    const item = e.target.closest(".job-item[data-job]");
    if (!item) return;
    // 이미 선택된 작업 재클릭 = 무동작(세션 재구성으로 데이터 겨눔이 날아가지 않게).
    if (item.getAttribute("aria-current") === "true") return;
    Bridge.call(SCREEN, "select_job", { name: item.dataset.job });
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

  /* danger(구조 드리프트) 수리 동선 — 이 작업을 에디터에 열어 매핑을 재확정한다(home.editJob
     대칭: 미저장 에디터 세션은 조용히 버리지 않고 확인 후 이동). 확정 후 복귀하면 세션 재개. */
  async function fixMapping() {
    if (!(LAST && LAST.job_name)) return;
    const busy = await Bridge.editorHasUnsavedWork();
    if (busy && !(await window.Modal.confirm({ body:
      "에디터에 저장하지 않은 작업 세션이 있습니다.\n" +
      `'${LAST.job_name}' 편집을 열면 그 세션의 이름·데이터·매핑이 사라집니다.\n\n계속할까요?` }))) return;
    const r = await Bridge.openJobInEditor(LAST.job_name);
    if (typeof r === "string" && r.startsWith("ERROR:")) { window.alert(r.slice(6).trim()); return; }
    window.Nav.go("editor");
  }

  /* 템플릿 다시 연결(#67) — 공용 흐름(relink.js)에 위임, 결과 재진술 채널만 log 주입. */
  function doRelinkTemplate() {
    if (!(LAST && LAST.job_name)) return;
    Relink.relinkTemplate(SCREEN, LAST.job_name, (msg) => log(msg));
  }

  function onRecChange(e) {
    const cb = e.target.closest('input[type="checkbox"][data-i]');
    if (!cb) return;
    Bridge.call(SCREEN, "toggle_record", { index: Number(cb.dataset.i), value: cb.checked });
  }

  function wire() {
    $("jobListHwpx").addEventListener("click", onMasterClick);
    $("jobSelAll").addEventListener("click", () => Bridge.call(SCREEN, "set_all", {}));
    $("jobSelNone").addEventListener("click", () => Bridge.call(SCREEN, "set_none", {}));
    $("jobRecList").addEventListener("change", onRecChange);
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
        if (LAST) renderRestate(LAST);
      }
    });
    $("jobGenBtn").addEventListener("click", () => doGenerate(false));

    $("jobBtnPickData").addEventListener("click", async () => {
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

  window.JobScreen = { init };
})();
