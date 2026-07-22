/* 홈(경보·상태 허브) 화면 — 브리지로 링1 HomeViewModel 과 왕복. 목업 scr-home 이관(#20, 마지막).
   안정 DOM(index.html) + Python 이 window.__push('home', snapshot) 로 값만 채운다(run 패턴).
   표현 계층(조건부 경보·작업 카드·group-by/facet 칩바)만 여기서 만든다 — VM 로직 아님(링2 대체).
   허브 이동은 window.Nav(셸 라우터)로만; 대상 화면의 자체 dispatch 로 미리 겨눈 뒤 전환한다. */
(function () {
  const SCREEN = "home";
  const $ = (id) => document.getElementById(id);

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  let LAST = null;  // 마지막 스냅샷 — 태그 편집 프리필 등 이벤트 핸들러가 참조(#26)
  let menuFor = null;  // 열린 카드 ⋮ 메뉴의 {name, trigger}(#179/H-16) — null=닫힘

  /* 카드 ⋮ 부유 메뉴(복제·태그·삭제) = 공용 팩토리(grouplist.js, job/tpl 과 단일 출처).
     위치잡기·표시만 팩토리 소유; 내용·정체(작업 이름)·바깥닫기 배선은 홈이 주입한다. */
  const rowMenu = window.GroupList.createMenu({ menuId: "homeRowMenu" });

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    LAST = s;
    renderAlerts(s.kpi);
    renderCorrupt(s.corrupt_rows);
    renderBrowser(s.axes, s.group_by, s.facets);
    renderJobs(s.grouped_rows, s.group_by, s.is_empty);
    renderTxt(s.txt_rows);
  }

  /* 정보 위생(#239 결정 8): 개수 타일은 렌더하지 않고 조치가 필요한 조건만 경보로 승계한다. */
  function renderAlerts(k) {
    k = k || { missing_template_count: 0, pool_corrupted: 0 };
    const alerts = [];
    if (k.missing_template_count > 0) {
      alerts.push(`<div class="note warnbox">템플릿이 연결되지 않은 작업 ${k.missing_template_count}건이 있습니다. 작업에서 다시 연결하세요.</div>`);
    }
    if (k.pool_corrupted > 0) {
      alerts.push(`<div class="note dangerbox">손상된 등록 데이터 ${k.pool_corrupted}건이 있습니다. 데이터 관리에서 확인하세요.</div>`);
    }
    $("homeAlerts").innerHTML = alerts.join("");
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

  /* 카드 행동 계층(#179 P0) — 실행=primary·편집=secondary 만 상시 노출, 부차 관리 행동
     (복제·태그·삭제)은 ⋮ 메뉴로 강등해 카드가 5개 동등 버튼으로 평평해지지 않게 한다.
     「템플릿 다시 연결」은 셋 중 하나가 아니라 깨진 상태(template_missing)의 복구 동선이라
     그 상태에서만 인라인 유지 — 막다른 상태의 유일 출구를 ⋮ 안에 숨기지 않는다(confirm-or-alarm). */
  function jobCard(r) {
    const nm = esc(r.name);
    const badge = r.compile_badge
      ? ` <span class="pill ${esc(r.badge_level)}">${esc(r.compile_badge)}</span>` : "";
    const runAttr = r.runnable ? "" : " disabled";
    const relink = r.template_missing
      ? `<button class="btn sm" data-relink="${nm}">템플릿 다시 연결…</button>` : "";
    return `<div class="jcard">` +
      `<div class="jn">${nm}${badge}</div>` +
      `<div class="jm">${esc(r.meta_line)}</div>` +
      `<div class="jfoot"><span class="jr">${esc(r.last_run_display)}</span>` +
      `<span class="acts">` +
      `<button class="btn primary sm" data-run="${nm}"${runAttr}>실행</button>` +
      `<button class="btn sm" data-edit="${nm}">편집</button>` +
      relink +
      `<button class="job-more" data-job-more="${nm}" aria-haspopup="true" aria-label="작업 관리">⋮</button>` +
      `</span></div></div>`;
  }

  /* ---- 카드 ⋮ 메뉴(복제·태그·삭제 — job/tpl 동형 단일 부유 요소) ---- */
  function closeRowMenu() {
    menuFor = null;
    rowMenu.hide();
  }
  function openRowMenu(name, btn) {
    menuFor = { name, trigger: btn };
    rowMenu.show(
      `<button data-menu="clone">복제</button>` +
      `<button data-menu="tags">태그…</button>` +
      `<div class="sep"></div>` +
      `<button data-menu="delete" class="danger">삭제</button>`, btn);
  }
  function toggleRowMenu(name, btn) {
    if (menuFor && menuFor.name === name) { closeRowMenu(); return; }
    openRowMenu(name, btn);
  }
  function onRowMenuClick(e) {
    const btn = e.target.closest("button[data-menu]");
    if (!btn || menuFor === null) return;
    const { name, trigger } = menuFor, act = btn.dataset.menu;
    closeRowMenu();
    if (act === "clone") cloneJob(name);
    else if (act === "tags") editTags(name, trigger);
    else if (act === "delete") deleteJob(name, trigger);
  }

  /* txt 트랙 — 즉시 기안 템플릿 목록(정해진 루트). */
  function renderTxt(rows) {
    const host = $("homeTxt");
    rows = rows || [];
    if (!rows.length) {
      host.innerHTML = `<p class="route">기안 템플릿이 없습니다. ＋ 새 기안으로 시작하세요.</p>`;
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
  async function openDraft(name) {
    // 「기안」 화면으로 라우팅(#148 슬라이스 6 — 구 txt 흡수). 템플릿을 휘발 세션에 물려 채우게.
    // 저장 기안 결속 세션이 진행 중이면 백엔드가 needs_confirm 을 돌려준다(리뷰 F3 — 세션 교체는
    // 저장되지 않은 진행을 폐기하므로 조용히 버리지 않는다). 취소=현 세션 그대로(라우팅 중단).
    let r = await Bridge.call("draft", "select_template", { name });
    if (r && r.needs_confirm) {
      const ok = await window.Modal.confirm({
        title: "진행 중인 기안을 떠납니다",
        body: window.DraftScreen.leaveForTemplateBody(r),  // 두 세션(저장·이전) 무장 반영(F3·리뷰 C)
        confirmLabel: "열기", cancelLabel: "취소",
      });
      if (!ok) return;  // 머무르기 = 현 세션 보존(홈에 남는다)
      r = await Bridge.call("draft", "select_template", { name, confirm: true });
    }
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
  async function editTags(name, returnFocus) {
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
        `'${name}' 의 태그에 쉼표나 등호가 들어 있어 여기서 수정할 수 없습니다.\n` +
        `현재 태그: ${ser}\n\n작업 파일(.job.json)의 tags 를 직접 수정하세요.`);
      return;
    }
    const input = await Modal.prompt({
      body:
        `'${name}' 의 태그를 '축=값' 쌍, 쉼표 구분으로 입력하세요. ` +
        `(예: 물품=의약품, 금액구간=소액)\n비우면 전부 해제합니다.`,
      value: ser,
      returnFocus,
    });
    if (input === null) return;
    const parsed = parseTags(input);
    if (parsed.err !== undefined) {
      window.alert(`태그 형식 오류: '${parsed.err}'. '축=값' 으로 입력하세요.`);
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
  async function deleteJob(name, returnFocus) {
    if (await Modal.confirm({
      body: `작업 '${name}' 을(를) 삭제할까요? 되돌릴 수 없습니다.`, returnFocus,
    })) {
      Bridge.call(SCREEN, "delete_job", { name });
    }
  }

  function onJobsClick(e) {
    const run = e.target.closest("[data-run]");
    if (run && !run.disabled) { runJob(run.dataset.run); return; }
    const edit = e.target.closest("[data-edit]");
    if (edit) { editJob(edit.dataset.edit); return; }
    const rl = e.target.closest("[data-relink]");
    if (rl) { relinkTemplate(rl.dataset.relink); return; }
    // 부차 행동(복제·태그·삭제)은 카드 ⋮ 로 이동(#179) — 여기선 메뉴 개폐만, 실행은 onRowMenuClick.
    const more = e.target.closest("[data-job-more]");
    if (more) { toggleRowMenu(more.dataset.jobMore, more); return; }
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
    $("homeCorrupt").addEventListener("click", onCorruptClick);  // 손상 조치(#26 #8)
    $("homeRowMenu").addEventListener("click", onRowMenuClick);   // 카드 ⋮ 메뉴 항목(#179)
    // ⋮ 메뉴 바깥 닫기(job/tpl 동형) — 캡처 클릭 억제 + 바깥 pointerdown + Escape.
    window.Popover.wireDismiss({
      isOpen: () => menuFor !== null,
      contains: (t) => !!(t.closest("#homeRowMenu") || t.closest(".job-more")),
      close: closeRowMenu,
    });
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
