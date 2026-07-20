/* 템플릿 관리(tpl) 화면 — 브리지로 링1 TemplateManagerViewModel + 코어 TextTemplateRegistry 와 왕복.
   목업 scr-tpl 이관(#13). 안정 DOM(index.html) + Python 이 window.__push('tpl', snapshot) 로 값만
   채운다(run 패턴). 표현 계층(카드 렌더·확인 라운드트립·모달)만 여기서 만든다 — VM 로직 아님.

   [B] 61C7ADF8: Qt 카드 하이라이트 비침 렌더 버그는 여기서 불투명 배경 div 카드로 그려 구성상
   소멸(숨긴 아이템 텍스트 레이어 자체가 없음). 결정: 미리보기 액션 미노출(10F2FF98-B, Python 이
   이미 제외)·TXT 동등 관리(10F2FF98-C)·드리프트 UI 미노출(10F2FF98-D). */
(function () {
  const SCREEN = "tpl";
  const $ = (id) => document.getElementById(id);
  // 편집 모달 상태 — mode: "new" | "edit", path: 편집 대상(신규는 빈 문자열).
  let editMode = "new";
  let editPath = "";

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    renderHwpx(s);
    renderTxt(s);
    renderResult(s);
  }

  /* HWPX 카드 — 이름 + 상태 배지 + 상세 + 상태별 게이트 액션(불투명 div, 비침 없음). */
  function renderHwpx(s) {
    $("tplHwpxCount").textContent = s.hwpx_count || "";
    $("tplLibDir").textContent = s.library_dir || "";
    const host = $("tplHwpxList");
    const rows = s.hwpx_rows || [];
    if (!rows.length) {
      host.innerHTML = `<div class="tplcard muted">${esc(s.empty_hint || "표시할 템플릿이 없습니다.")}</div>`;
      return;
    }
    host.innerHTML = rows.map((r) => {
      const badge = r.is_error
        ? `<span class="pill danger">${esc(r.badge_label)}</span>`
        : `<span class="pill ${esc(r.badge_level)}">${esc(r.badge_label)}</span>`;
      const acts = (r.actions || []).map((a) =>
        `<button class="btn sm" data-act="${esc(a.key)}" data-path="${esc(r.path)}">${esc(a.label)}</button>`
      ).join("");
      return `<div class="tplcard">
        <div class="tplcard-top"><span class="tplcard-name" title="${esc(r.path)}">${esc(r.name)}</span>${badge}</div>
        <div class="tplcard-meta muted">${esc(r.detail)}</div>
        <div class="tplcard-acts">${acts}</div></div>`;
    }).join("");
  }

  /* TXT 카드 — HWPX와 동등 관리(열기·편집·삭제). 손상 파일도 삭제 가능한 loud 행으로. */
  function renderTxt(s) {
    const rows = s.txt_rows || [];
    $("tplTxtCount").textContent = `${rows.length}건`;
    $("tplTxtDir").textContent = s.txt_dir || "";
    const host = $("tplTxtList");
    if (!rows.length) {
      host.innerHTML =
        `<div class="tplcard muted">표시할 TXT 템플릿이 없습니다 — [새 TXT 템플릿]으로 만드세요.</div>`;
      return;
    }
    host.innerHTML = rows.map((r) => {
      const err = !!r.error;
      const badge = err
        ? `<span class="pill danger">읽기 실패</span>`
        : `<span class="pill muted">TXT</span>`;
      const meta = err ? `파일을 읽을 수 없습니다: ${esc(r.error)}` : `토큰 ${r.field_count}개`;
      const edit = err ? ""
        : `<button class="btn sm" data-txt="edit" data-path="${esc(r.path)}" data-name="${esc(r.name)}">내용 편집</button>` +
          `<button class="btn sm" data-txt="open" data-name="${esc(r.name)}">기안문 채우기에서 열기</button>`;
      return `<div class="tplcard">
        <div class="tplcard-top"><span class="tplcard-name" title="${esc(r.path)}">${esc(r.name)}</span>${badge}</div>
        <div class="tplcard-meta muted">${meta}</div>
        <div class="tplcard-acts">
          <button class="btn sm" data-txt="delete" data-path="${esc(r.path)}">삭제</button>${edit}</div></div>`;
    }).join("");
  }

  function renderResult(s) {
    const r = s.result || { text: "", level: "muted" };
    const el = $("tplResult");
    el.textContent = r.text || "";
    el.className = "run-result " + (r.level === "muted" ? "" : r.level);
  }

  /* ---- HWPX 액션 ---- */
  async function doCompile(path) {
    // 1차: 스캔(dry-run). needs_confirm 이면 재진술 후 확인 시에만 적용(조용한 파괴 금지).
    const res = await Bridge.call(SCREEN, "compile", { path });
    if (res && res.needs_confirm) {
      if (await Modal.confirm({ body: res.confirm_text + "\n\n지금 변환할까요?" })) {
        await Bridge.call(SCREEN, "compile", { path, confirm: true });
      }
    }
  }

  async function makeJob(path) {
    // 새 템플릿 진입 = 새 작업 세션 → 미저장 편집(정의) 세션은 조용히 버리지 않고 확인(#25).
    if (await Bridge.editorHasUnsavedWork() && !(await Modal.confirm({ body:
      "저장하지 않은 편집(정의) 세션이 있습니다.\n" +
      "새 템플릿으로 시작하면 이전의 이름·데이터·매핑이 사라집니다.\n\n계속할까요?" }))) return;
    const r = await Bridge.loadTemplateIntoEditor(path);
    if (typeof r === "string" && r.startsWith("ERROR:")) { window.alert(r); return; }
    // 에디터 흡수(결정 39·41) — 착지 = 「작업」 패널 편집 모드(셸 라우터 단일 경로 P3 유지).
    window.Nav.go("job");
    if (window.JobScreen && window.JobScreen.showEditMode) window.JobScreen.showEditMode();
  }

  function onHwpxClick(e) {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const path = btn.dataset.path;
    const act = btn.dataset.act;
    if (act === "compile") doCompile(path);
    else if (act === "review") Bridge.call(SCREEN, "review", { path });
    else if (act === "make_job") makeJob(path);
  }

  /* ---- TXT 액션 ---- */
  async function onTxtClick(e) {
    const btn = e.target.closest("button[data-txt]");
    if (!btn) return;
    const act = btn.dataset.txt;
    if (act === "open") {
      Bridge.call("txt", "select_template", { name: btn.dataset.name });
      window.Nav.go("txt");   // 셸 라우터 단일 경로(P3)
    } else if (act === "delete") {
      const res = await Bridge.call(SCREEN, "txt_delete", { path: btn.dataset.path });
      if (res && res.needs_confirm && (await Modal.confirm({ body: res.confirm_text + "\n\n삭제할까요?" }))) {
        Bridge.call(SCREEN, "txt_delete", { path: btn.dataset.path, confirm: true });
      }
    } else if (act === "edit") {
      const res = await Bridge.call(SCREEN, "txt_content", { path: btn.dataset.path });
      openEditModal("edit", btn.dataset.path, btn.dataset.name, (res && res.content) || "");
    }
  }

  /* ---- 편집/생성 모달(네이티브 입력 대체) ---- */
  function openEditModal(mode, path, name, content) {
    editMode = mode;
    editPath = path || "";
    $("txtEditTitle").textContent = mode === "new" ? "새 TXT 템플릿" : `TXT 템플릿 편집 — ${name}`;
    $("txtNameRow").style.display = mode === "new" ? "" : "none";
    $("txtEditName").value = "";
    $("txtEditContent").value = content || "";
    // 초기 포커스: 새 템플릿은 이름, 편집은 내용. 복귀·Escape 는 Modal 헬퍼가 소유(#27/#28).
    const focusTo = mode === "new" ? $("txtEditName") : $("txtEditContent");
    window.Modal.open("txtEditModal", { initialFocus: focusTo });
  }

  function closeEditModal() { window.Modal.close("txtEditModal"); }

  async function submitEditModal() {
    const content = $("txtEditContent").value;
    try {
      if (editMode === "new") {
        await Bridge.call(SCREEN, "txt_new", { name: $("txtEditName").value, content });
      } else {
        await Bridge.call(SCREEN, "txt_edit", { path: editPath, content });
      }
      closeEditModal();
    } catch (err) {
      // confirm-or-alarm: 이름 검증·중복 실패는 조용히 삼키지 않고 시끄럽게.
      window.alert(String((err && err.message) || err));
    }
  }

  function wire() {
    // 새로고침 실패(브리지 예외)도 fire-and-forget 로 삼키지 않는다(N1).
    $("tplRefresh").addEventListener("click", async () => {
      try { await Bridge.call(SCREEN, "refresh", {}); }
      catch (err) { window.alert(String((err && err.message) || err)); }
    });
    $("tplHwpxList").addEventListener("click", onHwpxClick);
    $("tplTxtList").addEventListener("click", onTxtClick);
    $("btnTplNewTxt").addEventListener("click", () => openEditModal("new", "", "", ""));
    $("txtEditCancel").addEventListener("click", closeEditModal);
    $("txtEditOk").addEventListener("click", submitEditModal);
    $("btnTplLibDir").addEventListener("click", async () => {
      const r = await Bridge.pickLibraryFolder();
      if (typeof r === "string" && r.startsWith("ERROR:")) window.alert(r);
      // 성공/취소는 푸시 스냅샷이 목록을 갱신한다(취소는 무변).
    });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    render(await Bridge.initial(SCREEN));
  }

  window.TemplateScreen = { init };
})();
