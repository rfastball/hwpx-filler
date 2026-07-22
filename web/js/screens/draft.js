/* 「기안」 화면(draft) — TXT 작업-앵커 좌 목록 + 우 상세 껍데기(R-info 3부, #148 슬라이스 2b).
   「작업」(job.js)의 대칭 표면: 좌 목록의 그룹 구획·⋮ 메뉴·이동 다이얼로그는 공용 grouplist.js
   팩토리(3번째 소비자)를 쓰고, 백엔드 판정·목록은 DraftController(screen_draft.py)가 소유한다.
   좌 목록 그룹 스캐폴드(renderMaster/rowHtml)는 job.js 동형이다(순수 템플릿 — 팩토리는 위치잡기·
   다이얼로그만 걷었다). 우 상세는 **휘발 세션 4존**(슬라이스 3a)이고, 그 표면 전부는 공용
   팩토리(draftsession.js — 「기안문 채우기」와 단일 출처)가 소유한다: 이 파일이 주는 것은 화면
   고유 id 맵뿐이다. 저장 기안 선택은 세션을 그 Job 에서 **복원**하고(유래=saved, 슬라이스 5a),
   상시 「이번 세션」 행이 붙여넣던 휘발 세션으로의 귀환구다(두 세션 병존 — 소실 0). */
(function () {
  const SCREEN = "draft";
  const $ = (id) => document.getElementById(id);
  const esc = window.escHtml;
  let LAST = null;
  let RENAMING = null;  // 인라인 이름 변경 중(재렌더 생존용 지역 상태)
  let menuFor = null;   // 열린 ⋮ 메뉴의 대상 {kind:"job"|"group", name}

  /* ---- 그룹 목록 기제 = 공용 팩토리(grouplist.js, 「작업」·「템플릿 관리」와 단일 출처) ---- */
  const rowMenu = window.GroupList.createMenu({ menuId: "draftRowMenu" });
  const moveDialog = window.GroupList.createMoveDialog({
    modalId: "draftMoveModal", listId: "draftMoveList", errId: "draftMoveErr",
    nameId: "draftMoveName", radioName: "draftMove",
    newRadioId: "draftMoveNewRadio", newNameId: "draftMoveNewName",
  });

  /* ---- 우 상세 = 휘발 세션 4존 = 공용 팩토리(draftsession.js, 「기안문 채우기」와 단일 출처).
     화면 고유값은 id 맵뿐이다. 미루기는 두 표면 모두 사망(결정 10 · 슬라이스 3c) — 막힌 카드의
     탈출구는 자유 이동(◀▶·점 클릭)이다(작업점 고정 전제가 깨져 큐 뒤로 보내는 동사가 불필요). ---- */
  const sess = window.DraftSession.create({
    screen: SCREEN,
    rowIdPrefix: "draftRow-",  // preserve.js 포커스 복원 키 — txt/job 행과 전역 유일
    ids: {
      status: "draftStatus", tplSel: "draftTplSel", dataLabel: "draftDataLabel",
      pickBtn: "draftBtnPickData", poolBtn: "draftBtnPoolData", pasteBtn: "draftBtnPaste",
      zoneNote: "draftZoneNote", note: "draftNote", tokPanel: "draftTokPanel",
      selCount: "draftSelCount", search: "draftFilterSearch", reapply: "draftFilterReapply",
      chips: "draftFilterChips", strip: "draftSelStrip",
      tableHost: "draftTableHost", tableWrap: "draftTableWrap", tableEmpty: "draftTableEmpty",
      tableHead: "draftTableHead", tableBody: "draftTableBody", colPanel: "draftColPanel",
      selAll: "draftSelAll", selNone: "draftSelNone",
      card: "draftCard", cardReadout: "draftCardReadout", cardDots: "draftCardDots",
      cardTitle: "draftCardTitle", cardRender: "draftCardRender", cardLint: "draftCardLint",
      lintAction: "draftLintAction", cardPrev: "draftCardPrev", cardNext: "draftCardNext",
      cardCopy: "draftCardCopy", advance: "draftAdvance", targetFont: "draftTargetFont",
      // 맞추기 표 범례 + 원문 뷰 전환(#148 슬라이스 3b) — 뷰 전환 id 는 「기안」만 준다
      // (「기안문 채우기」는 붙여넣기 모달이 겸함 → 팩토리가 id 유무로 가드).
      mapLegend: "draftMapLegend", viewFilled: "draftViewFilled",
      viewSource: "draftViewSource", srcView: "draftSrcView", srcBox: "draftSrcBox",
      // 원문바(#148 슬라이스 5b) — 이름·수정됨 표지·「사본으로 편집」. 「기안문 채우기」는 원문
      // 뷰가 없어 이 id 들을 안 주고 팩토리가 유무로 가드한다(dead control 없음).
      srcName: "draftSrcName", modBadge: "draftModBadge", srcFork: "draftSrcFork",
    },
  });

  /* ---- 좌 목록 렌더(job.js 동형 그룹 구획 — 행 = 이름 버튼 + ⋮) ---- */
  function rowHtml(r) {
    if (RENAMING && RENAMING.name === r.name) {
      return `<div class="job-row"><input class="field job-rename" id="draftRenameInput"` +
        ` data-orig="${esc(r.name)}" value="${esc(RENAMING.value)}" aria-label="새 이름"></div>`;
    }
    return `<div class="job-row">` +
      `<button class="job-item" data-job="${esc(r.name)}" aria-current="${r.selected ? "true" : "false"}">${esc(r.name)}</button>` +
      `<button class="job-more" data-more="${esc(r.name)}" aria-haspopup="true" aria-label="기안 관리">⋮</button></div>`;
  }

  /* 상시 「이번 세션」 행(#148 슬라이스 5a) — 붙여넣기 휘발 세션의 목록 표현(시안). 저장 기안을
     한 번 고른 뒤 붙여넣기 화면으로 돌아오는 **유일한 귀환구**다(행 재클릭·빈 영역 클릭은 해제가
     아니다). 미결속(휘발 모드)일 때 aria-current — 클릭은 겨눔 해제(select_job 빈 이름). */
  function volatileRowHtml(s) {
    return `<div class="draft-vol-sep"></div>` +
      `<div class="job-grp-rows"><div class="job-row">` +
      `<button class="job-item draft-vol" data-volatile aria-current="${s.has_job ? "false" : "true"}">` +
      `이번 세션 <span class="muted">· 저장 안 함</span></button></div></div>`;
  }

  function renderMaster(s) {
    const host = $("draftList");
    const empty = $("draftListEmpty");
    const sections = s.job_sections || [];
    const total = sections.reduce((n, sec) => n + sec.rows.length, 0);
    empty.style.display = total ? "none" : "";
    let html;
    if (s.job_flat) {  // 퇴화 불변식(그룹 0개) — 헤더·들여쓰기 없는 평면.
      html = sections.map((sec) => sec.rows.map(rowHtml).join("")).join("");
    } else {
      html = sections.map((sec) => {
        const label = sec.group || "그룹 없음";
        return `<div class="job-grp">` +
          `<button class="job-grp-head" data-grp-toggle="${esc(sec.group)}" aria-expanded="${sec.collapsed ? "false" : "true"}">` +
          `<span class="grp-name">${esc(label)}</span>` +
          `<span class="grp-count">${sec.count}</span>` +
          `<span class="grp-caret">${sec.collapsed ? "▸" : "▾"}</span></button>` +
          (sec.group
            ? `<button class="job-more grp-more" data-grp-more="${esc(sec.group)}" aria-haspopup="true" aria-label="그룹 관리">⋮</button>`
            : "") +
          `</div>` +
          (sec.collapsed ? "" : `<div class="job-grp-rows">${sec.rows.map(rowHtml).join("")}</div>`);
      }).join("");
    }
    host.innerHTML = html + volatileRowHtml(s);
  }

  /* ---- 우 상세 = 세션 4존(공용 팩토리 sess) — 저장/휘발 **한 패널**(#148 슬라이스 5a). 저장
     기안 선택은 세션을 그 Job 에서 복원하고(유래=saved), 「이번 세션」은 붙여넣던 휘발로 되살린다.
     상태 배지·모드 게이팅은 전부 세션 렌더가 소유한다(껍데기 stub 폐기 — 선택이 실제 복원이다). */
  /* ---- 「기안으로 저장」 승격 버튼 상태(#148 슬라이스 5c, #135) — 라이브러리 배접만 저장 가능.
     붙여넣기·수정 원문은 비활성 + 사유(dead button 금지, #133). 판정은 Python(can_save_job). ---- */
  function renderPromote(s) {
    const btn = $("draftSaveJob");
    const note = $("draftSaveJobNote");
    const can = !!s.can_save_job;
    btn.disabled = !can;
    btn.textContent = s.has_job ? "다른 이름으로 저장" : "기안으로 저장";
    note.hidden = can;
    if (!can) {
      note.textContent =
        "붙여넣거나 고친 원문은 기안으로 저장할 수 없습니다 — 라이브러리 템플릿을 골라 채우거나, " +
        "원문을 「템플릿으로 저장」한 뒤 저장하세요.";
    }
    // 「템플릿으로 저장」(#148 슬라이스 6, #135) — 세션 원문을 TXT 라이브러리로 승격하는 두 번째
    // 동사(구 「빠른 기안」에서 흡수). **휘발 세션 전용**(사용자 결정 · Python can_save_template):
    // 저장 기안 결속(saved) 모드·빈손은 숨긴다(dead button 금지 — hidden 으로 가른다). 위 사유
    // 문구가 이 버튼을 가리키므로, 붙여넣기 세션에서 나란히 살아 안내가 죽은 지시가 되지 않는다.
    const tbtn = $("draftSaveTpl");
    tbtn.hidden = !s.can_save_template;
    if (tbtn.hidden) clearSaveTplNote();
  }

  function clearSaveTplNote() {
    const note = $("draftSaveTplNote");
    if (!note) return;
    note.textContent = "";
    delete note.dataset.level;
  }

  function render(s) {
    LAST = s;
    renderMaster(s);
    sess.render(s);   // 세션 4존(데이터·필드 상태·미리보기·완료) + 유래별 열 게이팅·상태 배지
    renderPromote(s); // ④존 「기안으로 저장」 버튼 상태(승격은 컨트롤러 소유라 여기서 배선)
  }

  /* ---- 「기안으로 저장」(#135) — 이름 입력 → 저장. 동명 덮어쓰기는 확인 왕복(파괴 대상 재진술).
     승격은 제자리(세션 그대로, 저장 모드 전이)라 하던 일이 끊기지 않는다(시안 결정). ---- */
  async function saveJob() {
    const s = LAST || {};
    const name = await window.Modal.prompt({
      title: s.has_job ? "다른 이름으로 저장" : "기안으로 저장",
      body: "이 기안 작업의 이름을 넣으세요. 템플릿·맞추기 정의가 저장됩니다(데이터는 매번 새로 물립니다).",
      value: s.has_job ? "" : (s.template_name || ""),
    });
    if (name === null) return;  // 취소
    let r = await Bridge.call(SCREEN, "save_job", { name });
    // 확인 문안을 **되돌려 보낸다**(confirmed_text) — 백엔드가 잠금 안에서 지금 문안과 대조해,
    // 모달이 열린 사이 대상이 바뀌었으면(TOCTOU) 새 문안으로 다시 묻는다(리뷰 5c P1). while 로
    // 재확인을 받는다(무확인 파괴 금지 — 바뀐 대상은 다시 확인).
    while (r && r.needs_confirm) {
      const confirmedText = r.confirm_text;
      const ok = await window.Modal.confirm({
        title: "덮어쓰기 확인", body: confirmedText,
        confirmLabel: "덮어쓰기", cancelLabel: "머무르기",
      });
      if (!ok) return;
      r = await Bridge.call(SCREEN, "save_job",
        { name, confirm: true, confirmed_text: confirmedText });
    }
    if (r && r.ok === false && r.error) window.alert(r.error);  // 게이트 실패는 시끄럽게
  }

  /* ---- 「템플릿으로 저장」(승격, 결정 33·34 · #135 · #148 슬라이스 6) — 세션 원문을 TXT
     라이브러리로 동결한다(구 「빠른 기안」 openSaveTpl 흡수). 대기·미착지 타건을 먼저 정산해야
     **화면에 보이는 원문**이 저장된다(복사와 같은 규율). 프리필(이름·그룹 후보·현재 그룹)은
     Python 이 지금 판정한다 — JS 캐시(LAST)엔 그룹 지정이 없고, 있어도 관리 화면에서 방금 바뀐
     지정과 갈라진다. 모달 문법은 tplMoveModal 동형(기존 그룹·그룹 없음·새 그룹 동거). ---- */
  async function openSaveTpl() {
    await sess.flush();
    const info = await Bridge.call(SCREEN, "promote_info", {});
    if (!info) return;
    const cur = info.group || "";
    const groups = info.groups || [];
    $("draftSaveTplGroups").innerHTML =
      groups.map((g) =>
        `<label class="grp-opt"><input type="radio" name="draftSaveGrp" value="${esc(g)}"${g === cur ? " checked" : ""}> ${esc(g)}</label>`
      ).join("") +
      `<label class="grp-opt"><input type="radio" name="draftSaveGrp" value=""${cur === "" ? " checked" : ""}> 그룹 없음</label>` +
      `<label class="grp-opt"><input type="radio" name="draftSaveGrp" value="" data-new="1" id="draftSaveGrpNewRadio"> 새 그룹:` +
      ` <input class="field" id="draftSaveGrpNewName" type="text" placeholder="새 그룹 이름"></label>`;
    $("draftSaveTplName").value = info.name || "";
    $("draftSaveTplErr").style.display = "none";
    window.Modal.open("draftSaveTplModal", { initialFocus: $("draftSaveTplName") });
    const nn = $("draftSaveGrpNewName");
    if (nn) nn.addEventListener("focus", () => { const r = $("draftSaveGrpNewRadio"); if (r) r.checked = true; });
  }

  function saveTplGroup() {
    const sel = document.querySelector('input[name="draftSaveGrp"]:checked');
    if (sel && sel.dataset.new) return ($("draftSaveGrpNewName").value || "").trim();
    return sel ? sel.value : "";
  }

  function saveTplErr(msg) {
    const err = $("draftSaveTplErr");
    err.textContent = msg;
    err.style.display = "";
  }

  /* 확정 — 실패는 **모달을 닫지 않고** 인라인 재진술한다(이름을 다시 칠 자리가 사라지지 않게).
     동명은 Python 이 needs_confirm 으로 되묻고, 확인하면 confirm 을 실어 재호출한다(덮어쓰기
     왕복 = 「기안으로 저장」·에디터 저장과 동형). */
  async function confirmSaveTpl(confirmFlag) {
    const name = $("draftSaveTplName").value;
    const group = saveTplGroup();
    const sel = document.querySelector('input[name="draftSaveGrp"]:checked');
    if (sel && sel.dataset.new && !group) { saveTplErr("새 그룹 이름을 입력하세요."); return; }
    const r = await Bridge.call(SCREEN, "save_template", { name, group, confirm: !!confirmFlag });
    if (!r) return;
    if (r.needs_confirm) {
      const go = await window.Modal.confirm({
        title: "덮어쓰기 확인", body: r.confirm_text,
        confirmLabel: "덮어쓰고 저장", cancelLabel: "머무르기",
      });
      if (go) await confirmSaveTpl(true);
      return;
    }
    if (!r.ok) { saveTplErr(r.error || "저장할 수 없습니다."); return; }
    // 새 이름이 콤보에 서야 한다(콤보는 initial 에서 한 번만 채워진다) — 갱신본으로 옵션을 다시
    // 그리고 승격된 정체를 선택한다(뒤이은 push 의 sel.value=template_name 이 맞물린다).
    sess.fillTemplateSelect({ templates: r.templates, template_name: r.name });
    window.Modal.close("draftSaveTplModal");
    const note = $("draftSaveTplNote");
    // 세션 처분을 정직하게 말한다(#135): 세션은 살아 있고, 저장된 것은 원문뿐이다.
    const head = r.overwritten
      ? `「${r.name}」 템플릿을 덮어썼습니다.`
      : `「${r.name}」 템플릿으로 저장했습니다.`;
    // 그룹 지정만 실패한 경우(설정 파일 쓰기 불가) — 일어난 일과 안 일어난 일을 갈라 말한다.
    // 남은 그룹은 **백엔드가 실제로 읽어 준 값**(영속-후-교체라 실패해도 이전 지정이 산다).
    if (r.group_error) {
      note.dataset.level = "warn";
      const where = r.group
        ? `기존 그룹 「${r.group}」이 그대로 유지됩니다`
        : `이 템플릿은 그룹 없이 남습니다`;
      note.textContent = `${head} 다만 요청한 그룹 변경은 저장되지 않았습니다(${r.group_error}) — ${where}.`;
    } else {
      note.dataset.level = "ok";
      note.textContent = `${head} 이 세션은 그대로 이어집니다(값은 저장되지 않았습니다).`;
    }
  }

  /* ---- 좌 목록 클릭 위임(⋮·그룹 토글·행 선택) ---- */
  async function onMasterClick(e) {
    const more = e.target.closest(".job-more[data-more]");
    if (more) { toggleRowMenu("job", more.dataset.more, more); return; }
    const gmore = e.target.closest(".grp-more[data-grp-more]");
    if (gmore) { toggleRowMenu("group", gmore.dataset.grpMore, gmore); return; }
    const grp = e.target.closest(".job-grp-head[data-grp-toggle]");
    if (grp) {
      // 접힘 토글은 보기만 바꾼다 — 선택 무영향. ""=「그룹 없음」.
      Bridge.call(SCREEN, "toggle_group", { group: grp.getAttribute("data-grp-toggle") });
      return;
    }
    const vol = e.target.closest(".job-item[data-volatile]");
    if (vol) {
      // 「이번 세션」 = 겨눔 해제 → 휘발 세션 귀환(스태시 복원). 이미 휘발이면 무동작.
      if (vol.getAttribute("aria-current") === "true") return;
      selectJob("");
      return;
    }
    const item = e.target.closest(".job-item[data-job]");
    if (!item) return;
    if (item.getAttribute("aria-current") === "true") return;  // 재클릭 무동작
    selectJob(item.dataset.job);
  }

  /* ---- 저장 기안 선택/해제 — 진행 보존 가드(리뷰 5a P1) + 복원 실패 가시화(리뷰 5a P2). ----
     저장 세션의 데이터·큐 진행은 Job 에 저장되지 않아 전환·귀환 시 사라진다 — 무장이면 백엔드가
     needs_confirm 을 돌려주고, 파괴를 재진술한 뒤 confirm 으로 재호출한다(T3 왕복). 복원 실패는
     시끄럽게(브리지가 error 를 표시하지 않으므로 여기서 alert). */
  /* 세션 교체(전환·귀환·삭제)로 사라지는 것 재진술 — 술어·수치는 Python(_leave_guard)이 내고
     여기는 문안만 입힌다(guardBody 규율). 데이터/선택·복사 진행에 더해 미저장 매핑 편집도
     함께 말한다(리뷰 5a 3R P1 / 147) — 데이터 미로드라 선택·복사가 0이어도 편집은 사라진다. */
  function leaveLossBody(r) {
    const copied = r.copied_count || 0;
    const parts = [];
    if (r.sel_count) parts.push(`선택 ${r.sel_count}행`);
    if (copied > 0) parts.push(`복사 ${copied}건(되돌릴 수 없음)`);
    if (r.map_dirty) parts.push("미저장 매핑 편집");
    if (r.source_dirty) parts.push("미저장 원문 편집");
    return parts.length
      ? `지금 물린 데이터와 진행(${parts.join(" · ")})은`
      : "지금 진행 중인 세션은";
  }

  async function selectJob(name) {
    let r = await Bridge.call(SCREEN, "select_job", { name });
    if (r && r.needs_confirm) {
      const ok = await window.Modal.confirm({
        title: "진행 중인 기안을 떠납니다",
        body: leaveLossBody(r) + " 저장된 기안에 보관되지 않아, 넘어가면 사라집니다.",
        confirmLabel: "넘어가기", cancelLabel: "머무르기",
      });
      if (!ok) return;
      r = await Bridge.call(SCREEN, "select_job", { name, confirm: true });
    }
    if (r && r.ok === false && r.error) window.alert(r.error);
  }

  /* ---- ⋮ 메뉴(내용은 화면 소유, 위치·표시는 팩토리) ---- */
  function closeRowMenu() { menuFor = null; rowMenu.hide(); }

  function toggleRowMenu(kind, name, btn) {
    if (menuFor && menuFor.kind === kind && menuFor.name === name) { closeRowMenu(); return; }
    openRowMenu(kind, name, btn);
  }

  function openRowMenu(kind, name, btn) {
    menuFor = { kind, name };
    // 복제·이름변경·이동·삭제. 「편집」(저장 기안의 편집 모드 진입)은 저장 세션 복원과 함께
    // 슬라이스 5에서 온다 — 아직 노출하지 않는다(없는 걸 있는 척하지 않는다).
    const html = kind === "job"
      ? `<button data-menu="clone">복제</button>` +
        `<button data-menu="rename">이름 변경</button>` +
        `<div class="sep"></div>` +
        `<button data-menu="move">그룹으로 이동…</button>` +
        `<div class="sep"></div>` +
        `<button data-menu="delete" class="danger">삭제</button>`
      : `<button data-menu="grp-rename">그룹 이름 변경</button>` +
        `<button data-menu="grp-disband">그룹 해산</button>`;
    rowMenu.show(html, btn);
  }

  async function onRowMenuClick(e) {
    const b = e.target.closest("button[data-menu]");
    if (!b || !menuFor) return;
    const act = b.dataset.menu;
    const { kind, name } = menuFor;
    closeRowMenu();
    if (kind === "job") {
      if (act === "clone") { await Bridge.call(SCREEN, "clone_job", { name }); return; }
      if (act === "rename") { startRename(name); return; }
      if (act === "move") { openGroupMove(name); return; }
      if (act === "delete") { deleteJob(name); return; }
    }
    if (act === "grp-rename") { renameGroup(name); return; }
    if (act === "grp-disband") { disbandGroup(name); }
  }

  /* ---- 인라인 이름 변경(job.js 동형) — Enter=확정·Escape=취소·이탈=확정 시도 ---- */
  function startRename(name) {
    RENAMING = { name, value: name };
    if (LAST) renderMaster(LAST);
    const inp = $("draftRenameInput");
    if (inp) { inp.focus(); inp.select(); }
  }

  async function commitRename(restoreOnError) {
    const inp = $("draftRenameInput");
    if (!inp || !RENAMING) return;
    const orig = RENAMING.name;
    const typed = inp.value;
    RENAMING = null;  // 디스패치의 push 재렌더가 입력칸을 되살리지 않게 먼저 걷는다
    if (typed.trim() === orig) { if (LAST) renderMaster(LAST); return; }  // 무변경 = 조용히 복귀
    const r = await Bridge.call(SCREEN, "rename_job", { name: orig, new: typed });
    if (r && r.ok) return;
    window.alert("이름 변경 실패: " + ((r && r.error) || "알 수 없는 오류"));  // 실패는 시끄럽게
    if (restoreOnError) {
      RENAMING = { name: orig, value: typed };
      if (LAST) renderMaster(LAST);
      const again = $("draftRenameInput");
      if (again) { again.focus(); again.select(); }
    } else if (LAST) {
      renderMaster(LAST);
    }
  }

  function cancelRename() { RENAMING = null; if (LAST) renderMaster(LAST); }

  function onMasterKeydown(e) {
    if (e.target.id !== "draftRenameInput") return;
    if (e.isComposing || e.keyCode === 229) return;  // 한글 IME 조합 확정 Enter 는 제출 아님
    if (e.key === "Enter") { e.preventDefault(); commitRename(true); }
    if (e.key === "Escape") { e.preventDefault(); cancelRename(); }
  }

  function onMasterFocusOut(e) {
    if (e.target.id === "draftRenameInput" && RENAMING) commitRename(false);
  }

  /* ---- 그룹 이동(공용 moveDialog 팩토리) ---- */
  function currentGroupOf(name) {
    const sections = (LAST && LAST.job_sections) || [];
    for (const sec of sections) {
      if (sec.rows.some((r) => r.name === name)) return sec.group;
    }
    return "";
  }

  function openGroupMove(name) {
    moveDialog.open({
      nameText: `기안 작업 '${name}' 을(를) 옮길 그룹을 고르세요.`,
      groups: (LAST && LAST.job_group_names) || [],
      current: currentGroupOf(name),
      onConfirm: (group) => Bridge.call(SCREEN, "set_group", { name, group }),
    });
  }

  /* ---- 삭제·그룹 관리(확인 라운드트립 — modal.js, 네이티브 금지) ---- */
  async function deleteJob(name) {
    const res = await Bridge.call(SCREEN, "delete_job", { name });
    if (!(res && res.needs_confirm)) return;
    // 결속 중인 기안을 지우면 그 세션 진행도 사라진다(open_session) — 파괴 전모를 한 모달로
    // 재진술(리뷰 5a 2R P1, job.js 삭제와 동형). 술어·수치는 Python(_guard_state) 판정.
    let body = `기안 작업 '${name}' 을(를) 삭제합니다. 템플릿 연결과 매핑 정의가 함께 사라집니다.`;
    if (res.open_session) {
      body += `\n지금 결속한 세션도 닫힙니다.`;
      if (res.armed) {
        body += ` ${leaveLossBody(res)} 저장된 기안에 보관되지 않아 함께 사라집니다.`;
      }
    }
    const ok = await window.Modal.confirm({
      title: "기안 작업 삭제 확인", body,
      confirmLabel: "삭제", cancelLabel: "머무르기",
    });
    if (!ok) return;
    await Bridge.call(SCREEN, "delete_job", { name, confirm: true });
  }

  async function renameGroup(old) {
    const val = await window.Modal.prompt({
      title: "그룹 이름 변경", body: `그룹 '${old}' 의 새 이름을 넣으세요.`, value: old,
    });
    if (val === null) return;
    const r = await Bridge.call(SCREEN, "rename_group", { name: old, new: val });
    if (r && r.needs_confirm) {
      // 기존 그룹으로의 개명 = 병합 — 수치 재진술 후 확정(지금 기준 관측, #149).
      const ok = await window.Modal.confirm({
        title: "그룹 병합 확인",
        body: `'${r.new}' 그룹이 이미 있습니다. '${old}' 의 작업 전부를 '${r.new}' 에 ` +
          `합칩니다(지금 기준 ${r.count}개 → 현재 ${r.target_count}개인 그룹). 그룹은 하나가 됩니다.`,
        confirmLabel: "합치기", cancelLabel: "머무르기",
      });
      if (!ok) return;
      await Bridge.call(SCREEN, "rename_group", { name: old, new: val, confirm: true, seen: r.count });
    } else if (r && r.error) {
      window.alert(r.error);
    }
  }

  async function disbandGroup(name) {
    const res = await Bridge.call(SCREEN, "disband_group", { name });
    if (!(res && res.needs_confirm)) return;
    const ok = await window.Modal.confirm({
      title: "그룹 해산 확인",
      body: `그룹 '${name}' 을(를) 해산합니다. 해산 시점의 소속 작업 전부가 「그룹 없음」으로 ` +
        `이동합니다(지금 기준 ${res.count}개). 작업 자체는 삭제되지 않습니다.`,
      confirmLabel: "해산", cancelLabel: "머무르기",
    });
    if (!ok) return;
    await Bridge.call(SCREEN, "disband_group", { name, confirm: true, seen: res.count });
  }

  function wire() {
    $("draftList").addEventListener("click", onMasterClick);
    $("draftList").addEventListener("keydown", onMasterKeydown);
    $("draftList").addEventListener("focusout", onMasterFocusOut);
    $("draftRowMenu").addEventListener("click", onRowMenuClick);
    // ⋮ 메뉴 바깥 닫기 — 기제는 공용 Popover.wireDismiss, 여기는 술어만 주입(표면별 인스턴스).
    window.Popover.wireDismiss({
      isOpen: () => menuFor !== null,
      contains: (t) => !!(t.closest("#draftRowMenu") || t.closest(".job-more")),
      close: closeRowMenu,
    });
    // 목록 스크롤 시 fixed 메뉴가 트리거와 어긋난다 — 어긋난 채 남기지 말고 닫는다.
    document.querySelector("#scr-draft .job-master").addEventListener("scroll", () => {
      if (menuFor !== null) closeRowMenu();
    }, true);
    // 휘발 세션 귀환은 상시 「이번 세션」 행이 진다(onMasterClick) — 껍데기 stub 의 back
    // 버튼을 승계했다(선택이 실제 복원이 되며 stub 이 사라졌다). 세션은 파괴하지 않고 겨눔만 푼다.
    $("draftSaveJob").addEventListener("click", saveJob);  // 승격(#135) — 컨트롤러 소유(JobRegistry)
    // 「템플릿으로 저장」 승격(#148 슬라이스 6) — 세션 원문을 TXT 라이브러리로(구 「빠른 기안」 흡수).
    $("draftSaveTpl").addEventListener("click", openSaveTpl);
    $("draftSaveTplCancel").addEventListener("click", () => window.Modal.close("draftSaveTplModal"));
    $("draftSaveTplOk").addEventListener("click", () => confirmSaveTpl(false));
    moveDialog.wire("draftMoveOk", "draftMoveCancel");
    sess.wire();  // 세션 4존 배선(데이터 존·카드 동사·글꼴·린트·붙여넣기) — 팩토리 소유
  }

  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    const initState = await Bridge.initial(SCREEN);
    sess.fillTemplateSelect(initState);  // 템플릿 콤보(부팅 1회) — 재조회는 화면 진입 때
    render(initState);
  }

  // 화면 진입마다 재동기(txt 와 같은 규율) — 다른 표면이 저장한 템플릿·바꾼 전역 글꼴 선언이
  // 앱 재시작 없이 여기에 반영된다.
  window.DraftScreen = { init, refreshOnEnter: sess.refreshOnEnter };
})();
