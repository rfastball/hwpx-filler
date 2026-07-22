/* 템플릿 관리(tpl) 화면 — 브리지로 링1 TemplateManagerViewModel + 코어 TextTemplateRegistry 왕복.
   R-info 2부 개편(#108): 매체(HWPX/TXT) 2구획 + 그 안 **작업 목록과 같은 그룹+접힘 모델**.
   그룹 헤더·행 ⋮ 메뉴·이동 다이얼로그·＋그룹지정 칩·「가져오기」는 job.js 기계를 이식한다.
   안정 DOM(index.html) + Python 이 window.__push('tpl', snapshot) 로 값만 채운다(판정은 Python).

   [B] 61C7ADF8: 불투명 배경 div 카드라 Qt 카드 하이라이트 비침 렌더 버그가 구성상 소멸. */
(function () {
  const SCREEN = "tpl";
  const $ = (id) => document.getElementById(id);
  const esc = window.escHtml;

  let LAST = { hwpx: {}, txt: {} };   // 스냅샷 캐시 — 그룹명·현 그룹·행 조회(메뉴/다이얼로그).
  let editMode = "new", editPath = "";
  let menuFor = null;                 // 열린 ⋮ 메뉴: {media, kind:"row"|"group", key?, group?, item?}

  /* 그룹 목록 기제(부유 ⋮ 메뉴·이동 다이얼로그) = 공용 팩토리(grouplist.js, job.js 와 단일 출처).
     위치잡기·다이얼로그 조립은 팩토리 소유. 여기는 매체 축·메뉴 내용·확정 디스패치만 주입한다. */
  const rowMenu = window.GroupList.createMenu({ menuId: "tplRowMenu" });
  const moveDialog = window.GroupList.createMoveDialog({
    modalId: "tplMoveModal", listId: "tplMoveList", errId: "tplMoveErr",
    nameId: "tplMoveName", radioName: "tplMove",
    newRadioId: "tplMoveNewRadio", newNameId: "tplMoveNewName",
  });

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    LAST = s || { hwpx: {}, txt: {} };
    renderBand("hwpx", s.hwpx, $("tplHwpxGroups"), $("tplHwpxCount"), $("tplLibDir"));
    renderBand("txt", s.txt, $("tplTxtGroups"), $("tplTxtCount"), $("tplTxtDir"));
    renderResult(s);
  }

  function renderBand(media, band, host, countEl, dirEl) {
    band = band || {};
    countEl.textContent = band.count ? `${band.count}개` : "";
    if (dirEl) { dirEl.textContent = band.dir || ""; dirEl.title = band.dir || ""; }
    if (!band.count) {
      // 전용 빈 상태(#179 슬라이스 6) — 설명 + 단일 CTA(문안 속 대괄호 지시 대신 실 버튼).
      // 홈 빈 상태와 같은 .empty 컴포넌트. hwpx=가져오기(자작 불가)·txt=새 TXT 저작.
      host.innerHTML = media === "hwpx"
        ? `<div class="empty"><div class="heading">HWPX 템플릿이 없습니다</div>` +
          `<p>${esc(band.empty_hint || "누름틀 서식(.hwpx)을 가져와 문서 작업의 원본으로 삼으세요.")}</p>` +
          `<button class="btn primary" data-empty="import">가져오기…</button></div>`
        : `<div class="empty"><div class="heading">TXT 템플릿이 없습니다</div>` +
          `<p>평문 {{필드}} 템플릿을 만들어 온나라 기안 등에 바로 채워 붙여넣으세요.</p>` +
          `<button class="btn primary" data-empty="new">새 TXT 템플릿…</button></div>`;
      return;
    }
    const sections = band.sections || [];
    if (band.flat) {
      // 퇴화 불변식(그룹 0개) — 헤더·들여쓰기 없는 평면.
      host.innerHTML = sections.map((sec) =>
        `<div class="tpl-grp-rows flat">${sec.items.map((it) => cardHtml(media, it)).join("")}</div>`
      ).join("");
      return;
    }
    host.innerHTML = sections.map((sec) => sectionHtml(media, sec)).join("");
  }

  /* 그룹 구획(job.js 동형) — 헤더(접힘 화살표·이름·개수·그룹 ⋮) + 접히면 바디 생략. */
  function sectionHtml(media, sec) {
    const label = sec.group || "그룹 없음";
    const head =
      `<div class="job-grp">` +
        `<button class="job-grp-head" data-grp-toggle="${esc(sec.group)}" data-media="${media}"` +
        ` aria-expanded="${sec.collapsed ? "false" : "true"}">` +
          `<span class="grp-name">${esc(label)}</span>` +
          `<span class="grp-count">${sec.count}</span>` +
          `<span class="grp-caret">${sec.collapsed ? "▸" : "▾"}</span></button>` +
        (sec.group
          ? `<button class="job-more grp-more" data-grp-more="${esc(sec.group)}" data-media="${media}"` +
            ` aria-haspopup="true" aria-label="그룹 관리">⋮</button>`
          : "") +
      `</div>`;
    const body =
      `<div class="tpl-grp-rows"${sec.collapsed ? " hidden" : ""}>` +
      `${sec.items.map((it) => cardHtml(media, it)).join("")}</div>`;
    return head + body;
  }

  function cardHtml(media, it) {
    return media === "hwpx" ? hwpxCard(it) : txtCard(it);
  }

  /* 카드 상단 우측 어포던스 — 「그룹 없음」이면 ＋그룹지정 칩(결정 2), 늘 ⋮ 메뉴. */
  function cardTail(media, it) {
    const chip = it.group ? "" :
      `<button class="tpl-assign" data-assign="${esc(it.key)}" data-media="${media}">＋ 그룹 지정</button>`;
    return `<span class="spacer"></span>${chip}` +
      `<button class="job-more tplcard-more" data-tpl-more="${esc(it.key)}" data-media="${media}"` +
      ` aria-haspopup="true" aria-label="템플릿 관리">⋮</button>`;
  }

  function hwpxCard(it) {
    const badge = it.is_error
      ? `<span class="pill danger">${esc(it.badge_label)}</span>`
      : `<span class="pill ${esc(it.badge_level)}">${esc(it.badge_label)}</span>`;
    // 소비 CTA(make_job)는 공용 ⋮ 메뉴 첫 항목이 소유한다(#236). 카드 표면에는 상태 수선만 둔다.
    const acts = (it.actions || []).filter((a) => a.key !== "make_job").map((a) =>
      `<button class="btn sm" data-act="${esc(a.key)}" data-path="${esc(it.path)}">${esc(a.label)}</button>`
    ).join("");
    // 채움 완화 사전 고지(#154) — 문안은 Python(describe_precheck_note)이 확정.
    const warns = (it.fill_warns || []).map(
      (w) => `<div class="tplcard-meta warn">${esc(w)}</div>`
    ).join("");
    return `<div class="tplcard">
      <div class="tplcard-top"><span class="tplcard-name" title="${esc(it.path)}">${esc(it.name)}</span>${badge}${cardTail("hwpx", it)}</div>
      <div class="tplcard-meta muted">${esc(it.detail)}</div>${warns}
      <div class="tplcard-acts">${acts}</div></div>`;
  }

  function txtCard(it) {
    const err = !!it.error;
    const badge = err
      ? `<span class="pill danger">읽기 실패</span>`
      : `<span class="pill muted">TXT</span>`;
    const meta = err ? `파일을 읽을 수 없습니다: ${esc(it.error)}` : `토큰 ${it.field_count}개`;
    // 사용·편집 동사는 ⋮ 메뉴에서 CTA → 구분선 → 관리 순서로 제공한다(#236).
    const acts = "";
    return `<div class="tplcard">
      <div class="tplcard-top"><span class="tplcard-name" title="${esc(it.path)}">${esc(it.name)}</span>${badge}${cardTail("txt", it)}</div>
      <div class="tplcard-meta muted">${meta}</div>
      <div class="tplcard-acts">${acts}</div></div>`;
  }

  function renderResult(s) {
    const r = s.result || { text: "", level: "muted" };
    const el = $("tplResult");
    el.textContent = r.text || "";
    el.className = "run-result " + (r.level === "muted" ? "" : r.level);
  }

  /* ---- 스냅샷 조회(메뉴/다이얼로그가 현 그룹·경로 필요) ---- */
  function findItem(media, key) {
    const band = LAST[media] || {};
    for (const sec of band.sections || []) {
      for (const it of sec.items || []) if (it.key === key) return it;
    }
    return null;
  }

  /* ---- 공유 ⋮ 컨텍스트 메뉴(job.js 동형 — 단일 부유 요소) ---- */
  function closeRowMenu() {
    menuFor = null;
    rowMenu.hide();
  }

  function openRowMenu(media, kind, id, btn) {
    let html;
    if (kind === "group") {
      html =
        `<button data-menu="grp-rename">그룹 이름 변경</button>` +
        `<button data-menu="grp-disband">그룹 해산</button>`;
      menuFor = { media, kind, group: id, trigger: btn };
    } else {
      const it = findItem(media, id);
      // 소비 CTA가 첫 항목, 관리 동사는 구분선 아래(#236). 무그룹 이동은 ＋그룹지정 칩이 담당.
      const useLabel = media === "hwpx" ? "이 서식으로 새 작업" : "이 서식으로 기안 시작";
      html = `<button data-menu="use"${it && !it.is_error && !it.error ? "" : " disabled"}>${useLabel}</button>` +
        `<div class="sep"></div>` +
        (media === "txt" && it && !it.error ? `<button data-menu="edit">내용 편집</button>` : "") +
        (it && it.group ? `<button data-menu="move">그룹으로 이동…</button>` : "") +
        `<button data-menu="delete" class="danger">삭제</button>`;
      menuFor = { media, kind, key: id, item: it, trigger: btn };
    }
    rowMenu.show(html, btn);  // 위치잡기·표시는 팩토리 소유(job.js 와 단일 출처)
  }

  function toggleRowMenu(media, kind, id, btn) {
    const same = menuFor && menuFor.kind === kind && menuFor.media === media &&
      (kind === "group" ? menuFor.group === id : menuFor.key === id);
    if (same) { closeRowMenu(); return; }
    openRowMenu(media, kind, id, btn);
  }

  async function onRowMenuClick(e) {
    const btn = e.target.closest("button[data-menu]");
    if (!btn || !menuFor) return;
    const m = menuFor, act = btn.dataset.menu;
    closeRowMenu();
    if (act === "use" && m.media === "hwpx") makeJob(m.item.path, m.trigger);
    else if (act === "use") openDraftTemplate(m.item.name, m.trigger);
    else if (act === "edit") {
      Bridge.call(SCREEN, "txt_content", { path: m.item.path }).then((res) =>
        openEditModal("edit", m.item.path, m.item.name, (res && res.content) || "", m.trigger));
    } else if (act === "move") openMoveDialog(m.media, m.item, m.trigger);
    else if (act === "delete") deleteTemplate(m.media, m.item, m.trigger);
    else if (act === "grp-rename") renameGroup(m.media, m.group, m.trigger);
    else if (act === "grp-disband") disbandGroup(m.media, m.group, m.trigger);
  }

  /* ---- 그룹 이동 다이얼로그(job.js 와 공용 moveDialog 팩토리) ---- */
  function openMoveDialog(media, item, returnFocus) {
    if (!item) return;
    moveDialog.open({
      nameText: item.name,
      groups: (LAST[media] && LAST[media].group_names) || [],
      current: item.group || "",
      returnFocus,
      onConfirm: (group) => Bridge.call(SCREEN, "set_group", { media, key: item.key, group }),
    });
  }

  /* ---- 그룹 헤더 ⋮ 동작(개명 병합 확인 · 해산 확인) ---- */
  async function renameGroup(media, old, returnFocus) {
    const val = await window.Modal.prompt({
      title: "그룹 이름 변경", body: `'${old}' 의 새 이름`, value: old, returnFocus,
    });
    if (val === null) return;
    const r = await Bridge.call(SCREEN, "rename_group", { media, group: old, new: val });
    if (r && r.needs_confirm) {
      if (await window.Modal.confirm({
        body: `'${r.new}' 그룹이 이미 있습니다. '${old}' 의 ${r.count}개를 '${r.new}'(${r.target}개)에 합칠까요?`,
        returnFocus,
      })) {
        await Bridge.call(SCREEN, "rename_group", { media, group: old, new: val, confirm: true });
      }
    } else if (r && r.error) {
      window.alert(r.error);
    }
  }

  async function disbandGroup(media, name, returnFocus) {
    const r = await Bridge.call(SCREEN, "disband_group", { media, group: name });
    if (r && r.needs_confirm && (await window.Modal.confirm({
      body: `'${name}' 그룹을 해산하면 ${r.count}개가 '그룹 없음'으로 이동합니다. 해산할까요?`, returnFocus,
    }))) {
      await Bridge.call(SCREEN, "disband_group", { media, group: name, confirm: true });
    }
  }

  /* ---- 삭제(HWPX·TXT 공통 · 확인 라운드트립) ---- */
  async function deleteTemplate(media, item, returnFocus) {
    if (!item) return;
    const r = await Bridge.call(SCREEN, "delete", { media, path: item.path });
    if (r && r.needs_confirm && (await window.Modal.confirm({
      body: r.confirm_text + "\n\n삭제할까요?", returnFocus,
    }))) {
      await Bridge.call(SCREEN, "delete", { media, path: item.path, confirm: true });
    }
  }

  /* ---- HWPX 상태 게이트 액션 ---- */
  async function doCompile(path) {
    const res = await Bridge.call(SCREEN, "compile", { path });
    if (res && res.needs_confirm) {
      if (await window.Modal.confirm({ body: res.confirm_text + "\n\n지금 변환할까요?" })) {
        await Bridge.call(SCREEN, "compile", { path, confirm: true });
      }
    }
  }

  async function makeJob(path, returnFocus) {
    // 새 템플릿 진입 = 새 작업 세션 → 폐기 확인은 EditorEntry.confirmDiscard 단일 출처(F9).
    if (!(await EditorEntry.confirmDiscard(
      "새 템플릿으로 시작하면 저장하지 않은 편집 세션이 사라집니다.\n" +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?", returnFocus))) return;
    const r = await Bridge.loadTemplateIntoEditor(path);
    if (typeof r === "string" && r.startsWith("ERROR:")) { window.alert(r); return; }
    EditorEntry.land();  // 에디터 흡수(결정 39·41) — 「작업」 패널 편집 모드 단일 착지.
  }

  /* 「가져오기」 = 라이브러리 복사(네이티브 다이얼로그). 툴바 버튼과 빈 상태 CTA 공용 단일 출처. */
  async function importTemplate() {
    const r = await Bridge.importLibraryTemplate();
    if (typeof r === "string" && r.startsWith("ERROR:")) window.alert(r);
    // 성공/취소는 푸시 스냅샷이 목록을 갱신한다(취소는 무변).
  }

  /* ---- 밴드 클릭 위임(토글·메뉴 트리거·칩·카드 액션) ---- */
  function onBandClick(media, e) {
    // 빈 상태 CTA(#179 슬라이스 6) — 툴바 버튼과 같은 흐름으로 합류.
    const emptyCta = e.target.closest("button[data-empty]");
    if (emptyCta) {
      if (emptyCta.dataset.empty === "new") openEditModal("new", "", "", "", emptyCta);
      else if (emptyCta.dataset.empty === "import") importTemplate();
      return;
    }
    const toggle = e.target.closest(".job-grp-head[data-grp-toggle]");
    if (toggle) {
      GroupList.toggleGroup(
        toggle,
        () => Bridge.call(SCREEN, "toggle_group", {
          media, group: toggle.getAttribute("data-grp-toggle"),
        }),
        "템플릿 그룹 접힘 상태를 저장하지 못했습니다."
      );
      return;
    }
    const grpMore = e.target.closest(".grp-more[data-grp-more]");
    if (grpMore) { toggleRowMenu(media, "group", grpMore.getAttribute("data-grp-more"), grpMore); return; }
    const rowMore = e.target.closest(".tplcard-more[data-tpl-more]");
    if (rowMore) { toggleRowMenu(media, "row", rowMore.getAttribute("data-tpl-more"), rowMore); return; }
    const assign = e.target.closest(".tpl-assign[data-assign]");
    if (assign) { openMoveDialog(media, findItem(media, assign.getAttribute("data-assign")), assign); return; }
    if (media === "hwpx") {
      const act = e.target.closest("button[data-act]");
      if (!act) return;
      const path = act.dataset.path, key = act.dataset.act;
      if (key === "compile") doCompile(path);
      else if (key === "review") Bridge.call(SCREEN, "review", { path });
      else if (key === "make_job") makeJob(path);
    }
  }

  /* 라이브러리 템플릿을 「기안」 화면에서 연다(#148 슬라이스 6 — 구 txt 흡수). 저장 기안 결속
     세션이 진행 중이면 백엔드가 needs_confirm 을 돌려준다(리뷰 F3 — 홈 openDraft 와 같은 규약):
     세션 교체는 저장되지 않은 진행을 폐기하므로 조용히 버리지 않는다. 취소=현 세션 그대로. */
  async function openDraftTemplate(name, returnFocus) {
    let r = await Bridge.call("draft", "select_template", { name });
    if (r && r.needs_confirm) {
      const ok = await window.Modal.confirm({
        title: "진행 중인 기안을 떠납니다",
        body: window.DraftScreen.leaveForTemplateBody(r),  // 두 세션 무장 반영(단일 출처, 리뷰 C)
        confirmLabel: "열기", cancelLabel: "취소", returnFocus,
      });
      if (!ok) return;
      r = await Bridge.call("draft", "select_template", { name, confirm: true });
    }
    window.Nav.go("draft");
  }

  /* ---- 편집/생성 모달(네이티브 입력 대체) ---- */
  function openEditModal(mode, path, name, content, returnFocus) {
    editMode = mode;
    editPath = path || "";
    $("txtEditTitle").textContent = mode === "new" ? "새 TXT 템플릿" : `TXT 템플릿 편집: ${name}`;
    $("txtNameRow").style.display = mode === "new" ? "" : "none";
    $("txtEditName").value = "";
    $("txtEditContent").value = content || "";
    const focusTo = mode === "new" ? $("txtEditName") : $("txtEditContent");
    window.Modal.open("txtEditModal", { initialFocus: focusTo, returnFocus });
  }

  async function submitEditModal() {
    const content = $("txtEditContent").value;
    try {
      if (editMode === "new") {
        await Bridge.call(SCREEN, "txt_new", { name: $("txtEditName").value, content });
      } else {
        await Bridge.call(SCREEN, "txt_edit", { path: editPath, content });
      }
      window.Modal.close("txtEditModal");
    } catch (err) {
      window.alert(String((err && err.message) || err));  // confirm-or-alarm: 검증 실패 시끄럽게.
    }
  }

  function wire() {
    $("tplRefresh").addEventListener("click", async () => {
      try { await Bridge.call(SCREEN, "refresh", {}); }
      catch (err) { window.alert(String((err && err.message) || err)); }
    });
    $("tplHwpxGroups").addEventListener("click", (e) => onBandClick("hwpx", e));
    $("tplTxtGroups").addEventListener("click", (e) => onBandClick("txt", e));
    $("tplRowMenu").addEventListener("click", onRowMenuClick);
    $("btnTplNewTxt").addEventListener("click", (e) => openEditModal("new", "", "", "", e.currentTarget));
    $("txtEditCancel").addEventListener("click", () => window.Modal.close("txtEditModal"));
    $("txtEditOk").addEventListener("click", submitEditModal);
    moveDialog.wire("tplMoveOk", "tplMoveCancel");
    $("btnTplImport").addEventListener("click", importTemplate);
    // ⋮ 메뉴 바깥 닫기(job.js 동형) — 캡처 클릭 억제 + 바깥 pointerdown + Escape.
    window.Popover.wireDismiss({
      isOpen: () => menuFor !== null,
      contains: (t) => !!(t.closest("#tplRowMenu") || t.closest(".job-more")),
      close: closeRowMenu,
    });
  }

  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    render(await Bridge.initial(SCREEN));
  }

  window.TemplateScreen = { init };
})();
