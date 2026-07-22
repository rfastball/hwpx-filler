/* 홈(대시보드) 화면 — 브리지로 링1 HomeViewModel 과 왕복. 목업 scr-home 이관(#20, 마지막).
   안정 DOM(index.html) + Python 이 window.__push('home', snapshot) 로 값만 채운다(run 패턴).
   표현 계층(KPI 타일·작업 카드·group-by/facet 칩바)만 여기서 만든다 — VM 로직 아님(링2 대체).
   허브 이동은 window.Nav(셸 라우터)로만; 대상 화면의 자체 dispatch 로 미리 겨눈 뒤 전환한다. */
(function () {
  const SCREEN = "home";
  const $ = (id) => document.getElementById(id);

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

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

  /* KPI — 목업 3타일(저장된 작업·템플릿 없는 작업·기안 템플릿). 전부 실재 데이터.
     손상된 등록 데이터(pool_corrupted)는 KPI 가 아니라 경보라 >0 일 때만 danger 타일로
     끼어든다(#45) — 0 은 정상이라 상시 타일은 소음, 손상은 조용히 감추지 않는다. */
  function renderKpis(k) {
    k = k || { job_count: 0, missing_template_count: 0, txt_template_count: 0, pool_corrupted: 0 };
    const warn = k.missing_template_count > 0 ? " warn" : "";
    $("homeKpis").innerHTML =
      tile(k.job_count, "저장된 작업 · HWPX") +
      tile(k.missing_template_count, "템플릿 없는 작업", warn) +
      tile(k.txt_template_count, "기안 템플릿 · txt") +
      (k.pool_corrupted > 0
        ? tile(k.pool_corrupted, "손상된 등록 데이터 — 데이터 관리에서 확인", " danger")
        : "");
  }
  function tile(v, label, cls) {
    return `<div class="kpi${cls || ""}"><div class="v">${v}</div><div class="l">${esc(label)}</div></div>`;
  }

  /* 이어서 실행 — 실행 이력 있는 작업 최근순(있을 때만 노출). 버튼 라벨은 섹션 제목과
     겹치지 않게 "실행"(F14) — 작업 카드의 실행 버튼과 같은 동작·같은 어휘. */
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
        `<button class="btn sm" data-run="${esc(r.name)}"${r.runnable ? "" : " disabled"}>실행</button></div>`
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
        `<div class="jfoot"><span></span><span class="acts">` +
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
        if (res && res.needs_confirm && (await Modal.confirm({ body: res.confirm_text }))) {
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
    // 템플릿 다시 연결(#67) — 파일이 사라진 작업(template_missing)에만 복구 동선 노출.
    const relink = r.template_missing
      ? `<button class="btn sm" data-relink="${nm}">템플릿 다시 연결…</button>` : "";
    return `<div class="jcard">` +
      `<div class="jn">${nm}${badge}</div>` +
      `<div class="jm">${esc(r.meta_line)}</div>` +
      `<div class="jfoot"><span class="jr">${esc(r.last_run_display)}</span>` +
      `<span class="acts">` +
      `<button class="btn primary sm" data-run="${nm}"${runAttr}>실행</button>` +
      `<button class="btn sm" data-edit="${nm}">편집</button>` +
      `<button class="btn sm" data-clone="${nm}">복제</button>` +
      relink +
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
    // 실행 화면 사망(슬라이스 3) → 「작업」 세션 패널이 유일 생성 표면. JobScreen.openJob 이
    // 좌 목록 재클릭 무동작 가드를 승계한다 — 이미 이 작업 세션이 진행 중이면 재구성하지 않아
    // 데이터 겨눔·행 선택·확인이 조용히 소실되지 않는다(리뷰 F1). 그 상태로 화면만 전환.
    // app.js 의 init 가드와 동형으로 전역 참조를 방어한다(리뷰 #99-6): job.js 미로드(정적 순서상
    // 도달 불가)면 uncaught TypeError 대신 화면만 전환한다.
    if (window.JobScreen) { window.JobScreen.openJob(name); return; }
    window.Nav.go("job");
  }
  function openDraft(name) {
    // 「기안」 화면으로 라우팅(#148 슬라이스 6 — 구 txt 흡수). 템플릿을 휘발 세션에 물려 채우게.
    Bridge.call("draft", "select_template", { name });
    window.Nav.go("draft");
  }

  /* '＋ 새 작업'(F10) — 라벨-행동 일치: 이전 에디터 세션을 초기화한 뒤 이동한다.
     종전 bare nav 는 직전 세션을 그대로 복원해 '새'가 '이어서 작성'을 몰래 겸했다.
     미저장 세션은 editJob 과 대칭으로 확인 후 버린다(조용한 복원·조용한 소실 둘 다 금지). */
  async function newJob() {
    // 흐름 전체가 EditorEntry.newDraft 단일 출처(PR-5 리뷰 F2 — 작업 구획 ＋ 와 공유).
    if (window.EditorEntry) { await EditorEntry.newDraft(); return; }
    window.alert("편집 진입 구성 요소(EditorEntry)가 로드되지 않았습니다.");  // #99-6 동형 loud
  }

  /* '＋ 새 기안'(F11) — F10 과 대칭. **무확인 면제 철회(#126)**: 원장 F11 의 근거였던 "txt
     출력은 일회성이라 버릴 durable 상태가 없다"가 블록 3 전-선언 큐 신설로 거짓이 됐다.
     확인·문안은 「기안」 화면(DraftScreen)이 소유한다(같은 T3 술어를 데이터 교체 가드와 공유,
     #148 슬라이스 6 — 구 TxtScreen 승계) — 홈이 큐 사정을 따로 알아 문안을 짓기 시작하면 두
     화면이 같은 상태를 다르게 말한다. */
  async function newDraft() {
    // #99-6 동형 loud — 진입 셔틀 미로드 시 조용한 무가드 파괴가 되지 않게(가드 소실 > 무반응).
    if (!window.DraftScreen) { window.alert("기안 화면 구성 요소(DraftScreen)가 로드되지 않았습니다."); return; }
    if (!(await DraftScreen.confirmNewDraftIfArmed())) return;  // 머무르기 = 큐 불변
    await Bridge.call("draft", "new_draft", {});
    window.Nav.go("draft");
  }

  /* ---- 웹→Python 이벤트(위임) ---- */
  /* 편집 진입(#26) — 미저장 에디터 세션은 조용히 버리지 않고 확인(#25 미러) 후 복원.
     공용 흐름 EditorEntry.openGuarded 에 위임(job.openEditForRepair 와 단일 출처, PR #97 리뷰). */
  function editJob(name) {
    // #99-6 동형 방어(PR-5 리뷰 F4) — 진입 셔틀 미로드 시 동기 ReferenceError 는 조용한
    // 무반응이 된다(unhandledrejection 백스톱은 동기 throw 를 못 받는다). loud 로.
    if (!window.EditorEntry) { window.alert("편집 진입 구성 요소(EditorEntry)가 로드되지 않았습니다."); return; }
    EditorEntry.openGuarded(name);
  }

  /* 작업 복제(F22) — 매핑 재사용의 단일 동선(공유 베이스 프로파일의 대체). 성공은 새
     카드가 목록에 나타나는 것으로 족해 배너를 내지 않고(정상은 조용히), 실패만 loud. */
  async function cloneJob(name) {
    try {
      const r = await Bridge.call(SCREEN, "clone_job", { name });
      if (r && r.ok === false) window.alert(r.error || "작업을 복제할 수 없습니다.");
    } catch (err) {
      window.alert(String((err && err.message) || err));
    }
  }

  /* '축=값, 축=값' 텍스트 → 태그 dict. 형식 오류면 {err: 문제 조각} — 호출부가 loud 처리. */
  function parseTags(text) {
    const tags = {};
    for (const part of text.split(",")) {
      const t = part.trim();
      if (!t) continue;
      const i = t.indexOf("=");
      if (i <= 0 || !t.slice(i + 1).trim()) return { err: t };
      tags[t.slice(0, i).trim()] = t.slice(i + 1).trim();
    }
    return { tags };
  }
  function sameTags(a, b) {
    const ka = Object.keys(a);
    return ka.length === Object.keys(b).length && ka.every((k) => b[k] === a[k]);
  }

  /* 태그 편집(#26 #2·D14) — 현재 태그를 '축=값' 쌍으로 재진술·프리필하고 통째 교체 저장.
     비우면 전체 해제(사용자가 명시적으로 지운 것 — 추측 아님). 형식 오류는 loud. */
  async function editTags(name) {
    let cur = {};
    (LAST && LAST.grouped_rows || []).forEach((sec) =>
      (sec.rows || []).forEach((r) => { if (r.name === name) cur = r.tags || {}; }));
    const ser = Object.entries(cur).map(([k, v]) => `${k}=${v}`).join(", ");
    // 왕복 가드(C9): 직렬화 직후 재파싱해 원본과 대조 — 값에 쉼표, 축에 쉼표/등호가 있으면
    // (백엔드 _do_set_tags 는 허용, 수동 .job.json 편집으로 도달 가능) 이 인라인 프롬프트는
    // 프리필을 그대로 OK 해도 태그를 조용히 쪼개 재작성하거나 형식 오류로 막는다.
    // 왕복 불가면 조용히 진행하지 않고 시끄럽게 중단한다(confirm-or-alarm).
    const rt = parseTags(ser);
    if (rt.err !== undefined || !sameTags(rt.tags, cur)) {
      window.alert(
        `'${name}' 의 태그에 쉼표(값) 또는 등호/쉼표(축)가 포함돼 있어\n` +
        `'축=값, …' 인라인 편집으로는 안전하게 수정할 수 없습니다.\n\n` +
        `현재 태그: ${ser}\n\n작업 파일(.job.json)의 tags 를 직접 수정하세요.`);
      return;
    }
    const input = await Modal.prompt({
      body:
        `'${name}' 의 분류 태그 — '축=값' 쌍을 쉼표로 구분해 입력하세요.\n` +
        `(예: 물품=의약품, 금액구간=소액)\n비우면 태그를 전부 해제합니다.`,
      value: ser,
    });
    if (input === null) return;
    const parsed = parseTags(input);
    if (parsed.err !== undefined) {
      window.alert(`태그 형식 오류: '${parsed.err}' — '축=값' 으로 입력하세요.`);
      return;
    }
    try {
      await Bridge.call(SCREEN, "set_tags", { name, tags: parsed.tags });
    } catch (err) {
      window.alert(String((err && err.message) || err));  // 백엔드 loud 거절 재진술
    }
  }

  /* 템플릿 다시 연결(#67) — 공용 흐름(relink.js)에 위임. 홈은 로그 패널이 없어 커밋
     재진술을 alert 로 병기한다(카드만 조용히 바뀌는 것 방지, PR #70 리뷰) — 사용자
     취소는 본인 행위라 재알림 소음 생략, 실패는 공용 흐름이 이미 alert. */
  function relinkTemplate(name) {
    Relink.relinkTemplate(SCREEN, name, (msg, kind) => {
      if (kind === "ok") window.alert(msg);
    });
  }

  /* 작업 삭제 — 조용한 삭제 금지, 재진술 후 확인 시에만(confirm-or-alarm). onJobsClick 이
     동기라 여기로 뽑아 await 를 쓴다(Modal.confirm 은 Promise 기반). 삭제 호출은 원래처럼
     fire-and-forget — rejection 은 셸 unhandledrejection 백스톱이 loud 재진술한다(#45). */
  async function deleteJob(name) {
    if (await Modal.confirm({ body: `작업 '${name}' 을(를) 삭제할까요? 되돌릴 수 없습니다.` })) {
      Bridge.call(SCREEN, "delete_job", { name });
    }
  }

  function onJobsClick(e) {
    const run = e.target.closest("[data-run]");
    if (run && !run.disabled) { runJob(run.dataset.run); return; }
    const edit = e.target.closest("[data-edit]");
    if (edit) { editJob(edit.dataset.edit); return; }
    const cl = e.target.closest("[data-clone]");
    if (cl) { cloneJob(cl.dataset.clone); return; }
    const rl = e.target.closest("[data-relink]");
    if (rl) { relinkTemplate(rl.dataset.relink); return; }
    const tg = e.target.closest("[data-tags]");
    if (tg) { editTags(tg.dataset.tags); return; }
    const del = e.target.closest("[data-del]");
    if (del) { deleteJob(del.dataset.del); return; }
    const nj = e.target.closest("[data-new-job]");
    if (nj) { newJob(); return; }
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
    // 수동 새로고침 버튼은 제거(F6) — 화면 진입 자동 갱신(app.js REFRESH_ON_NAV)이 유일 경로.
    // 실패 표면화(N1)는 그 경로의 .catch → alert 가 담당한다.
    $("homeNewJob").addEventListener("click", newJob);
    $("homeNewTxt").addEventListener("click", newDraft);
    $("homeJobs").addEventListener("click", onJobsClick);
    $("homeEmpty").addEventListener("click", onJobsClick);
    $("homeContinue").addEventListener("click", onJobsClick);
    $("homeCorrupt").addEventListener("click", onCorruptClick);  // 손상 조치(#26 #8)
    $("homeTxt").addEventListener("click", (e) => {
      const open = e.target.closest("[data-open]");
      if (open) openDraft(open.dataset.open);
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
