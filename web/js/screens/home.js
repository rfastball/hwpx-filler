/* 홈(대시보드) 화면 — 브리지로 링1 HomeViewModel 과 왕복. 목업 scr-home 이관(#20, 마지막).
   안정 DOM(index.html) + Python 이 window.__push('home', snapshot) 로 값만 채운다(run 패턴).
   표현 계층(KPI 타일·작업 카드·group-by/facet 칩바)만 여기서 만든다 — VM 로직 아님(링2 대체).
   허브 이동은 window.Nav(셸 라우터)로만; 대상 화면의 자체 dispatch 로 미리 겨눈 뒤 전환한다. */
(function () {
  const SCREEN = "home";
  const $ = (id) => document.getElementById(id);

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    renderKpis(s.kpi);
    renderContinue(s.continue_runs);
    renderCorrupt(s.corrupt_rows);
    renderBrowser(s.axes, s.group_by, s.facets);
    renderJobs(s.grouped_rows, s.group_by, s.is_empty);
    renderTxt(s.txt_rows);
  }

  /* KPI — 목업 3타일(저장된 작업·템플릿 없는 작업·기안 템플릿). 전부 실재 데이터. */
  function renderKpis(k) {
    k = k || { job_count: 0, missing_template_count: 0, txt_template_count: 0 };
    const warn = k.missing_template_count > 0 ? " warn" : "";
    $("homeKpis").innerHTML =
      tile(k.job_count, "저장된 작업 · HWPX") +
      tile(k.missing_template_count, "템플릿 없는 작업", warn) +
      tile(k.txt_template_count, "기안 템플릿 · txt");
  }
  function tile(v, label, cls) {
    return `<div class="kpi${cls || ""}"><div class="v">${v}</div><div class="l">${esc(label)}</div></div>`;
  }

  /* 이어서 실행 — 실행 이력 있는 작업 최근순(있을 때만 노출). */
  function renderContinue(rows) {
    const box = $("homeContinue");
    rows = rows || [];
    if (!rows.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    box.innerHTML =
      `<div class="cr-head">이어서 실행</div>` +
      rows.map((r) =>
        `<div class="continue-run"><span class="name">${esc(r.name)}</span>` +
        `<span class="when">${esc(r.last_run_display)}</span>` +
        `<button class="btn sm" data-run="${esc(r.name)}"${r.runnable ? "" : " disabled"}>이어서 실행</button></div>`
      ).join("");
  }

  /* 손상 작업 — 숨기지 않고 시끄러운 위험 카드로(RC-05). 조치(열기·삭제)는 이관 보류. */
  function renderCorrupt(rows) {
    const box = $("homeCorrupt");
    rows = rows || [];
    if (!rows.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    box.innerHTML =
      `<div class="grp"><span class="cap">손상된 작업 파일</span>` +
      rows.map((c) =>
        `<div class="jcard corrupt"><div class="jn">${esc(c.file_name)} <span class="pill danger">손상됨</span></div>` +
        `<div class="jm">${esc(c.detail_line)}</div></div>`
      ).join("") + `</div>`;
  }

  /* 작업 브라우저 바 — group-by 렌즈 드롭다운 + facet 칩. 태그 없으면(axes 빈) 렌더 안 함
     (퇴화-코퍼스 불변식 — 첫 실행이 오늘과 동일한 평면 목록). */
  function renderBrowser(axes, groupBy, facets) {
    const box = $("homeBrowser");
    axes = axes || [];
    if (!axes.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    const opts =
      `<option value=""${groupBy ? "" : " selected"}>그룹 없음</option>` +
      axes.map((a) =>
        `<option value="${esc(a)}"${a === groupBy ? " selected" : ""}>그룹: ${esc(a)}</option>`).join("");
    let html = `<label class="ctl"><span class="lbl">보기</span>` +
      `<select class="field sm" id="homeGroupBy">${opts}</select></label>`;
    const chips = (facets || []).flatMap((fa) =>
      fa.values.map((v) =>
        `<button class="pill${v.active ? "" : " muted"}" data-axis="${esc(fa.axis)}" data-val="${esc(v.value)}"` +
        `${v.count === 0 && !v.active ? " disabled" : ""}>${esc(fa.axis)}: ${esc(v.value)} · ${v.count}</button>`
      )
    );
    if (chips.length) {
      html += `<span class="facets">${chips.join("")}` +
        `<button class="btn sm" id="homeClearFacets">필터 해제</button></span>`;
    }
    box.innerHTML = html;
  }

  /* 작업 카드(그룹 섹션) — group-by 활성 시에만 섹션 헤더. 빈 상태는 온보딩 안내. */
  function renderJobs(sections, groupBy, isEmpty) {
    const host = $("homeJobs");
    const empty = $("homeEmpty");
    sections = sections || [];
    if (isEmpty) {
      host.innerHTML = "";
      empty.style.display = "";
      empty.innerHTML =
        `<div class="empty"><div class="heading">저장된 작업이 없습니다</div>` +
        `<p>템플릿과 매핑을 묶어 첫 작업을 만드세요.\n데이터·행은 실행할 때 고릅니다.</p>` +
        `<button class="btn primary" data-new-job>＋ 새 작업 만들기</button></div>`;
      return;
    }
    empty.style.display = "none";
    empty.innerHTML = "";
    host.innerHTML = sections.map((sec) => {
      const head = groupBy
        ? `<div class="jm groupsec">▾ ${esc(sec.value)} · ${sec.count}</div>` : "";
      return head + sec.rows.map(jobCard).join("");
    }).join("");
  }

  function jobCard(r) {
    const nm = esc(r.name);
    const badge = r.compile_badge
      ? ` <span class="pill ${esc(r.badge_level)}">${esc(r.compile_badge)}</span>` : "";
    const runAttr = r.runnable ? "" : " disabled";
    return `<div class="jcard">` +
      `<div class="jn">${nm}${badge}</div>` +
      `<div class="jm">${esc(r.meta_line)}</div>` +
      `<div class="jfoot"><span class="jr">${esc(r.last_run_display)}</span>` +
      `<span class="row">` +
      `<button class="btn primary sm" data-run="${nm}"${runAttr}>실행</button>` +
      `<button class="btn sm" disabled title="편집 모드는 아직 웹으로 이관되지 않았습니다(신규 작성은 ＋ 새 작업).">편집</button>` +
      `<button class="btn sm" data-del="${nm}">삭제</button>` +
      `</span></div></div>`;
  }

  /* txt 트랙 — 즉시 기안 템플릿 목록(정해진 루트). */
  function renderTxt(rows) {
    const host = $("homeTxt");
    rows = rows || [];
    if (!rows.length) {
      host.innerHTML = `<p class="route">기안 템플릿이 없습니다 — ＋ 새 기안으로 시작하세요.</p>`;
      return;
    }
    host.innerHTML = rows.map((t) =>
      `<div class="titem"><div><div class="tn">${esc(t.name)}.txt</div>` +
      `<div class="tm">필드 ${t.field_count}개</div></div>` +
      `<button class="btn primary sm" data-open="${esc(t.name)}">기안 열기 →</button></div>`
    ).join("") + `<p class="route">템플릿 루트 ~/.hwpxfiller/text_templates/</p>`;
  }

  /* ---- 허브 이동: 대상 화면을 미리 겨눈 뒤 셸 라우터로 전환 ---- */
  function runJob(name) {
    Bridge.call("run", "select_job", { name });   // run 컨트롤러가 스냅샷 푸시 → run.js 렌더
    window.Nav.go("run");
  }
  function openTxt(name) {
    Bridge.call("txt", "select_template", { name });
    window.Nav.go("txt");
  }

  /* ---- 웹→Python 이벤트(위임) ---- */
  function onJobsClick(e) {
    const run = e.target.closest("[data-run]");
    if (run && !run.disabled) { runJob(run.dataset.run); return; }
    const del = e.target.closest("[data-del]");
    if (del) {
      const name = del.dataset.del;
      // 조용한 삭제 금지 — 재진술 후 확인 시에만(confirm-or-alarm).
      if (window.confirm(`작업 '${name}' 을(를) 삭제할까요? 되돌릴 수 없습니다.`)) {
        Bridge.call(SCREEN, "delete_job", { name });
      }
      return;
    }
    const nj = e.target.closest("[data-new-job]");
    if (nj) { window.Nav.go("editor"); return; }
  }

  function onBrowserChange(e) {
    if (e.target.id === "homeGroupBy") {
      Bridge.call(SCREEN, "set_group_by", { axis: e.target.value });
    }
  }
  function onBrowserClick(e) {
    const chip = e.target.closest("[data-axis]");
    if (chip && !chip.disabled) {
      Bridge.call(SCREEN, "toggle_facet", { axis: chip.dataset.axis, value: chip.dataset.val });
      return;
    }
    if (e.target.id === "homeClearFacets") { Bridge.call(SCREEN, "clear_facets", {}); }
  }

  function wire() {
    $("homeNewJob").addEventListener("click", () => window.Nav.go("editor"));
    $("homeMatrix").addEventListener("click", () => window.Nav.go("matrix"));
    $("homeNewTxt").addEventListener("click", () => window.Nav.go("txt"));
    $("homeJobs").addEventListener("click", onJobsClick);
    $("homeEmpty").addEventListener("click", onJobsClick);
    $("homeContinue").addEventListener("click", onJobsClick);
    $("homeTxt").addEventListener("click", (e) => {
      const open = e.target.closest("[data-open]");
      if (open) openTxt(open.dataset.open);
    });
    $("homeBrowser").addEventListener("change", onBrowserChange);
    $("homeBrowser").addEventListener("click", onBrowserClick);
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    render(await Bridge.initial(SCREEN));
  }

  window.HomeScreen = { init };
})();
