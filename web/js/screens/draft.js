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
  function render(s) {
    LAST = s;
    renderMaster(s);
    sess.render(s);   // 세션 4존(데이터·필드 상태·미리보기·완료) + 유래별 열 게이팅·상태 배지
  }

  /* ---- 좌 목록 클릭 위임(⋮·그룹 토글·행 선택) ---- */
  function onMasterClick(e) {
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
      Bridge.call(SCREEN, "select_job", { name: "" });
      return;
    }
    const item = e.target.closest(".job-item[data-job]");
    if (!item) return;
    if (item.getAttribute("aria-current") === "true") return;  // 재클릭 무동작
    Bridge.call(SCREEN, "select_job", { name: item.dataset.job });
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
    const ok = await window.Modal.confirm({
      title: "기안 작업 삭제 확인",
      body: `기안 작업 '${name}' 을(를) 삭제합니다. 템플릿 연결과 매핑 정의가 함께 사라집니다.`,
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
