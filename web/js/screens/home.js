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

  let LAST = null;  // 마지막 스냅샷 — 태그 편집 프리필 등 이벤트 핸들러가 참조(#26)

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    LAST = s;
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

  /* 손상 작업 — 숨기지 않고 시끄러운 위험 카드로(RC-05) + 해소 동선(#26 #8·UD-44):
     폴더 열기(탐색기 표시)·삭제(백엔드 재진술 확인 라운드트립). */
  function renderCorrupt(rows) {
    const box = $("homeCorrupt");
    rows = rows || [];
    if (!rows.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    box.innerHTML =
      `<div class="grp"><span class="cap">손상된 작업 파일</span>` +
      rows.map((c) =>
        `<div class="jcard corrupt"><div class="jn">${esc(c.file_name)} <span class="pill danger">손상됨</span></div>` +
        `<div class="jm">${esc(c.detail_line)}</div>` +
        `<div class="jfoot"><span></span><span class="row">` +
        `<button class="btn sm" data-reveal="${esc(c.path)}">폴더 열기</button>` +
        `<button class="btn sm" data-del-corrupt="${esc(c.path)}">삭제</button>` +
        `</span></div></div>`
      ).join("") + `</div>`;
  }

  /* 손상 파일 조치 핸들러 — 삭제는 백엔드가 재진술한 문구로 확인 후 확정(confirm-or-alarm). */
  async function onCorruptClick(e) {
    const rv = e.target.closest("[data-reveal]");
    if (rv) {
      const r = await Bridge.revealCorruptJob(rv.dataset.reveal);
      if (typeof r === "string" && r.startsWith("ERROR:")) window.alert(r.slice(6).trim());
      return;
    }
    const dc = e.target.closest("[data-del-corrupt]");
    if (dc) {
      const path = dc.dataset.delCorrupt;
      // 백엔드가 거절할 수 있다(목록에 없는 stale 경로 → ValueError, 잠긴 파일 → PermissionError).
      // try/catch 없이는 rejection 이 삼켜져 클릭이 무반응이 된다 — 시끄럽게 재진술한다(editTags 미러).
      try {
        const res = await Bridge.call(SCREEN, "delete_corrupt", { path });
        if (res && res.needs_confirm && window.confirm(res.confirm_text)) {
          await Bridge.call(SCREEN, "delete_corrupt", { path, confirm: true });
        }
      } catch (err) {
        window.alert(String((err && err.message) || err));
      }
    }
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
      `<button class="btn sm" data-edit="${nm}">편집</button>` +
      `<button class="btn sm" data-tags="${nm}">태그</button>` +
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
  /* 편집 진입(#26) — 미저장 에디터 세션은 조용히 버리지 않고 확인(#25 미러) 후 복원. */
  async function editJob(name) {
    const busy = await Bridge.editorHasUnsavedWork();
    if (busy && !window.confirm(
      "에디터에 저장하지 않은 작업 세션이 있습니다.\n" +
      `'${name}' 편집을 열면 그 세션의 이름·데이터·매핑이 사라집니다.\n\n계속할까요?`)) return;
    const r = await Bridge.openJobInEditor(name);
    if (typeof r === "string" && r.startsWith("ERROR:")) {
      window.alert(r.slice(6).trim());   // 손상·템플릿 부재 → loud (조용한 무시 금지)
      return;
    }
    window.Nav.go("editor");
  }

  /* 태그 편집(#26 #2·D14) — 현재 태그를 '축=값' 쌍으로 재진술·프리필하고 통째 교체 저장.
     비우면 전체 해제(사용자가 명시적으로 지운 것 — 추측 아님). 형식 오류는 loud. */
  async function editTags(name) {
    let cur = {};
    (LAST && LAST.grouped_rows || []).forEach((sec) =>
      (sec.rows || []).forEach((r) => { if (r.name === name) cur = r.tags || {}; }));
    const ser = Object.entries(cur).map(([k, v]) => `${k}=${v}`).join(", ");
    const input = window.prompt(
      `'${name}' 의 분류 태그 — '축=값' 쌍을 쉼표로 구분해 입력하세요.\n` +
      `(예: 물품=의약품, 금액구간=소액)\n비우면 태그를 전부 해제합니다.`, ser);
    if (input === null) return;
    const tags = {};
    for (const part of input.split(",")) {
      const t = part.trim();
      if (!t) continue;
      const i = t.indexOf("=");
      if (i <= 0 || !t.slice(i + 1).trim()) {
        window.alert(`태그 형식 오류: '${t}' — '축=값' 으로 입력하세요.`);
        return;
      }
      tags[t.slice(0, i).trim()] = t.slice(i + 1).trim();
    }
    try {
      await Bridge.call(SCREEN, "set_tags", { name, tags });
    } catch (err) {
      window.alert(String((err && err.message) || err));  // 백엔드 loud 거절 재진술
    }
  }

  function onJobsClick(e) {
    const run = e.target.closest("[data-run]");
    if (run && !run.disabled) { runJob(run.dataset.run); return; }
    const edit = e.target.closest("[data-edit]");
    if (edit) { editJob(edit.dataset.edit); return; }
    const tg = e.target.closest("[data-tags]");
    if (tg) { editTags(tg.dataset.tags); return; }
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
    $("homeCorrupt").addEventListener("click", onCorruptClick);  // 손상 조치(#26 #8)
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
