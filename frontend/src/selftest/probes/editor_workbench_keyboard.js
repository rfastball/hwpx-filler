/* `editor_workbench_data.js` 클러스터 D 의 `probeAuthoringKeyboard` 조각 — 책임 분리
 * (복잡도 예산) 전용 사이드카.
 *
 * `probeAuthoringKeyboard` 자체는 `editor_workbench_data.js` 에 그대로 산다(계약 파일의
 * 함수 식별자를 보존한다). 이 모듈은 그 몸체가 쪼개진 단계 함수들만 들고, 그 파일이
 * 가져다 쓴다. 공유 헬퍼(`service`·`settleRender`·`settleUntil`·`pressKey`·`textOf`·
 * `waitFor`·`typeValue`·`probeAuthoringIme`)는 다른 저작 프로브도 쓰므로
 * `editor_workbench_data.js` 에 남아 export 되고, 여기로는 **역수입하지 않는다**
 * (production import 그래프의 순환 금지). 대신 `probeAuthoringKeyboard` 가 한 번 묶은
 * `lib` 객체로 주입한다. */

/** 편집면 캐럿이 선 줄(0부터) — CodeMirror 는 초점을 쥔 동안 제 선택을 DOM 선택으로 쓴다(activeElement 가 편집면이면
 *  창 초점과 무관하다). 속성 패널을 열지 않는 선택(NG-06 keepDock)의 이동은 이 줄로 잰다. */
function authoringCaretLine(doc) {
  const content = doc.querySelector(".authoring-document:not([hidden]) .cm-content");
  const picked = doc.getSelection ? doc.getSelection() : null;
  if (!content || !picked || !picked.anchorNode || !content.contains(picked.anchorNode)) return -1;
  let node = picked.anchorNode;
  if (node === content) node = content.childNodes[Math.min(picked.anchorOffset, content.childNodes.length - 1)];
  const el = node && (node.nodeType === 3 ? node.parentElement : node);
  const line = el && el.closest ? el.closest(".cm-line") : null;
  return line ? Array.prototype.indexOf.call(content.querySelectorAll(".cm-line"), line) : -1;
}

export function authoringKeyboardHelpers(doc, lib) {
  return {
    nameInput: () => doc.querySelector(".authoring-properties input"),
    preview: () => doc.querySelector(
      ".authoring-properties section.authoring-preview:not(.authoring-refusal)"),
    contextText: () => lib.textOf(doc.querySelector(".authoring-properties .authoring-context")).trim(),
    panelGone: () => !doc.querySelector(".authoring-properties"),
    caretLine: () => authoringCaretLine(doc),
  };
}

export async function authoringKeyboardSnapshot(ctx, lib) {
  const snap = await lib.service(ctx, "Bridge").initial("authoring");
  const tab = (((snap || {}).tabs) || []).find((item) => item.id === (snap || {}).active_id) || {};
  const field = ((((tab.analysis || {}).fields) || [])[0] || {});
  const occurrence = (field.occurrences || [])[0] || {};
  const problem = (tab.problems || []).find((item) => item.location) || {};
  return { tab, field, occurrence, problem };
}

/** `.authoring-properties select` 의 현재 값 — 패널이 없으면 `""`. */
function selectedCommandValue(doc) {
  return (doc.querySelector(".authoring-properties select") || {}).value || "";
}

function describedByOf(input) {
  return input ? String(input.getAttribute("aria-describedby") || "") : "";
}

/* 필드 목록은 구조 패널의 두 번째 보기다(UX-09): F6 은 보이는 보기(구조)의 tree 로 들어오므로, 보기 탭 줄로
   올라가(Shift+Tab) → 로 「필드」 보기를 연다(자동 활성화). 이어서 Tab 이 필터를 지나 그 보기의 tree 로 간다.
   구조 목록은 APG tree 다(UX-04): 한 번의 Tab 으로 들어오고 ↓ 로 줄을 옮긴다. */
export async function probeAuthoringKeyboardOutline(ctx, out, nav, field, lib) {
  out.kbd_outline_reached = await nav.cycleTo(".authoring-outline");
  if (!out.kbd_outline_reached) return false;
  const outlineTab = (el) => !!el && el.getAttribute("role") === "tab" && !!el.closest(".authoring-outline");
  const fieldsViewTarget = (el) => outlineTab(el) && lib.textOf(el).trim().indexOf("필드") === 0;
  out.kbd_fields_view = nav.tabTo(outlineTab, 6, true) && nav.arrowTo(fieldsViewTarget, "ArrowRight", 2);
  await lib.settleRender(ctx);
  // 초점만이 아니라 보기가 실제로 바뀌었는가 — 아니면 다음 Tab 이 숨지 않은 구조 tree 로 들어가 같은 이름의 사용 위치 줄을 고른다.
  out.kbd_fields_view = out.kbd_fields_view && nav.active().getAttribute("aria-selected") === "true";
  if (!out.kbd_fields_view) return false;
  const fieldTarget = (el) => nav.nameOf(el).indexOf(`필드 · ${field.name} · `) === 0;
  out.kbd_field_focused = await nav.treeTo(fieldTarget, 16);
  out.kbd_field_label = nav.nameOf(nav.active());
  return out.kbd_field_focused;
}

/** 속성 패널(필드 이름 작업) — 되읽기·IME·이름 바꾸기 예고·Escape 두 단계·F2 재진입. */
export async function probeAuthoringKeyboardProperties(ctx, out, nav, helpers, field, priorOk, lib) {
  const { nameInput, preview, panelGone } = helpers;
  if (!priorOk) return false;
  lib.pressKey(ctx, "Enter");
  const propertiesFocused = () => !!nameInput() && nav.active() === nameInput()
    && nameInput().value === field.name;
  out.kbd_properties_focus = await lib.waitFor(ctx, propertiesFocused, 40, 50);
  out.kbd_properties_command = selectedCommandValue(ctx.doc);
  out.kbd_name_described_by = describedByOf(nameInput());
  out.kbd_properties_target = lib.textOf(ctx.doc.getElementById("authoring-properties-target")).trim();
  out.kbd_properties_context = lib.textOf(ctx.doc.getElementById("authoring-properties-context")).trim();
  if (!out.kbd_properties_focus) return false;

  await lib.probeAuthoringIme(ctx, out, nameInput());

  lib.typeValue(ctx, nameInput(), "공고제목");
  lib.pressKey(ctx, "Enter");
  const renamePreviewShown = () => lib.textOf(preview()).indexOf("‘공고제목’으로 변경됩니다") >= 0;
  out.kbd_rename_preview = await lib.waitFor(ctx, renamePreviewShown, 40, 50);
  out.kbd_rename_preview_text = lib.textOf(preview()).trim().slice(0, 120);
  lib.pressKey(ctx, "Escape");                               // 1단계: 작성 중인 값만 되돌린다
  const nameReverted = () => !!nameInput() && nameInput().value === field.name;
  await lib.settleUntil(ctx, nameReverted);
  out.kbd_escape_reverts = nameReverted();
  out.kbd_escape_keeps_panel = !panelGone();
  lib.pressKey(ctx, "Escape");                               // 2단계: 패널을 닫고 선택으로 돌아간다
  out.kbd_escape_closes = await lib.waitFor(ctx, panelGone, 20, 50);
  out.kbd_escape_focus_editor = await lib.waitFor(ctx, () => nav.within(".cm-editor"), 20, 50);
  lib.pressKey(ctx, "F2");                                   // 선택한 의미 요소의 이름 작업
  const f2Focused = () => !!nameInput() && nav.active() === nameInput();
  out.kbd_f2_focus = await lib.waitFor(ctx, f2Focused, 20, 50);
  out.kbd_f2_command = selectedCommandValue(ctx.doc);
  lib.pressKey(ctx, "Escape");
  await lib.waitFor(ctx, panelGone, 20, 50);
  return true;
}

/* 문제는 하단 독(보조 패널)의 탭이다(§3.1): F6 으로 독에 들어가 「문제 N」 탭을 Enter 로 펼친다.
   탭 이름의 수는 Python 스냅샷의 problems 수와 같아야 하고, 펼친 뒤 독에는 탭 패널이 하나만 선다. */
export async function probeAuthoringKeyboardDock(ctx, out, nav, tab, priorOk, lib) {
  const doc = ctx.doc;
  if (!priorOk) return { ok: false, problemsTab: null };
  out.kbd_dock_reached = await nav.cycleTo(".authoring-dock");
  // 독 탭 줄은 APG tabs 다: 들어온 탭에서 Home 으로 첫 탭(문제)까지 간다.
  const dockTab = (el) => !!el && !!el.closest(".authoring-dock") && el.getAttribute("role") === "tab";
  const problemsTabTarget = (el) => dockTab(el) && lib.textOf(el).trim().indexOf("문제") === 0;
  out.kbd_problems_tab = nav.arrowTo(problemsTabTarget, "Home", 2);
  out.kbd_problems_tab_label = out.kbd_problems_tab ? lib.textOf(nav.active()).trim() : "";
  out.kbd_problems_expected = (tab.problems || []).length;
  if (!out.kbd_problems_tab) return { ok: false, problemsTab: null };
  const problemsTab = nav.active();
  lib.pressKey(ctx, "Enter");
  const action = () => doc.querySelector(
    '.authoring-dock [role="tabpanel"] .authoring-bottom[aria-label="문제"] .authoring-problem button');
  const problemFocused = () => !!action() && nav.active() === action();
  out.kbd_problem_focus = await lib.waitFor(ctx, problemFocused, 20, 50);
  out.kbd_problems_selected = problemsTab.getAttribute("aria-selected") === "true";
  out.kbd_dock_panels = doc.querySelectorAll('.authoring-dock [role="tabpanel"]').length;
  out.kbd_problem_action = nav.nameOf(nav.active());
  const problemRow = doc.querySelector('.authoring-bottom[aria-label="문제"] .authoring-problem');
  out.kbd_problem_text = lib.textOf(problemRow).trim().slice(0, 120);
  // 문제 한 건은 행이다(UX-09) — 심각도는 글자 칩, 종류는 흐린 글로 선다(색이 아니라 글).
  out.kbd_problem_severity = lib.textOf(problemRow && problemRow.querySelector(".authoring-badge")).trim();
  out.kbd_problem_category = lib.textOf(problemRow && problemRow.querySelector(".authoring-problem-category")).trim();
  return { ok: out.kbd_problem_focus, problemsTab };
}

/* 문제 행의 Enter 는 독에서 시작한 선택이다(NG-06 keepDock): 편집면 선택이 문제 위치로 옮겨 가고, 독의 활성 탭은
   「문제」 그대로이며 속성 패널은 열리지 않는다. 이동은 편집면 캐럿이 선 줄로 잰다(문제 위치는 Python 스냅샷의 줄). */
export async function probeAuthoringKeyboardPosition(ctx, out, helpers, problemsTab, problem, priorOk, lib) {
  const doc = ctx.doc;
  const { panelGone, caretLine } = helpers;
  if (!priorOk) return false;
  lib.pressKey(ctx, "Enter");
  out.kbd_problem_expected_line = Number((problem.location || {}).line);
  const problemMoved = () => caretLine() === out.kbd_problem_expected_line;
  out.kbd_problem_moved = await lib.waitFor(ctx, problemMoved, 40, 50);
  out.kbd_problem_caret_line = caretLine();
  await lib.settleRender(ctx);
  out.kbd_problem_dock_kept = problemsTab.getAttribute("aria-selected") === "true"
    && !!doc.querySelector('.authoring-dock [role="tabpanel"] .authoring-bottom[aria-label="문제"]');
  out.kbd_problem_no_properties = panelGone();
  return true;
}

/* 「이전 위치로」는 도구 막대 「더보기」 메뉴 안에 있다: 더보기 → Enter → 메뉴 첫 항목에 초점 →
   ↓ 로 「이전 위치로」 → Enter. 도구 막대와 메뉴는 APG toolbar·menu 라 Tab 이 아니라 방향키로 옮긴다. */
export async function probeAuthoringKeyboardToolbar(ctx, out, nav, helpers, occurrence, problemsTab, priorOk, lib) {
  const doc = ctx.doc;
  const { nameInput, contextText, panelGone, caretLine } = helpers;
  if (!priorOk) return;
  out.kbd_toolbar_again = await nav.cycleTo(".authoring-toolbar");
  /* 흐린 만들기 단추(NG-11): 도구 막대 roving 이 aria-disabled 단추에도 선다. Enter(누름)는 명령을 실행하지 않고
     위치 줄 메모에 그 판정의 Python 사유를 세운다 — hover 사유(title)와 같은 문장이다. 이 문서는 닫히지 않은
     항목(구조 오류)이 있어 「항목으로 만들기」가 어느 자리에서나 불가다. 펼친 독 탭(문제)과 초점은 그대로다. */
  const dimmedSlot = (el) => !!el && !!el.closest(".authoring-toolbar") && lib.textOf(el).trim() === "항목으로 만들기";
  out.kbd_dimmed_reached = nav.arrowTo(dimmedSlot, "ArrowRight", 20);
  if (!out.kbd_dimmed_reached) return;
  const dimmed = nav.active();
  out.kbd_dimmed_aria = dimmed.getAttribute("aria-disabled") === "true" && !dimmed.disabled;
  out.kbd_dimmed_title = String(dimmed.getAttribute("title") || "");
  const noteText = () => lib.textOf(doc.querySelector("#scr-authoring .authoring-selection-note")).trim();
  lib.pressKey(ctx, "Enter");
  const dimmedNoteShown = () => !!noteText() && noteText() === out.kbd_dimmed_title;
  out.kbd_dimmed_note = await lib.waitFor(ctx, dimmedNoteShown, 20, 50);
  out.kbd_dimmed_note_text = noteText();
  out.kbd_dimmed_no_panel = panelGone() && problemsTab.getAttribute("aria-selected") === "true";
  out.kbd_dimmed_focus_kept = nav.active() === dimmed;
  const moreButtonTarget = (el) => !!el && !!el.closest(".authoring-toolbar") && nav.nameOf(el) === "더보기";
  out.kbd_more_button = nav.arrowTo(moreButtonTarget, "ArrowRight", 20);
  if (!out.kbd_more_button) return;
  lib.pressKey(ctx, "Enter");
  const moreMenu = () => doc.querySelector('#scr-authoring [role="menu"][aria-label="더보기"]');
  const moreMenuFocused = () => !!moreMenu() && !!nav.active()
    && nav.active().getAttribute("role") === "menuitem" && moreMenu().contains(nav.active());
  out.kbd_more_menu = await lib.waitFor(ctx, moreMenuFocused, 20, 50);
  if (!out.kbd_more_menu) return;
  const backButtonTarget = (el) => !!el && el.getAttribute("role") === "menuitem"
    && !!moreMenu() && moreMenu().contains(el) && lib.textOf(el).trim() === "이전 위치로";
  out.kbd_back_button = nav.arrowTo(backButtonTarget, "ArrowDown", 8);
  if (!out.kbd_back_button) return;
  lib.pressKey(ctx, "Enter");
  out.kbd_more_menu_closed = await lib.waitFor(ctx, () => !moreMenu(), 20, 50);
  /* 복귀는 편집면 캐럿이 원래 줄(필드 사용 위치)로 돌아온 것으로 잰다. 이어서 F2 로 속성 패널을 열어 그 자리의
     문맥 줄이 원시 offset 이 아니라 사람이 읽는 줄 번호(「N행」)임을 되읽는다(UX-10 R2). */
  out.kbd_back_expected_line = Number(occurrence.line);
  const backRestored = () => caretLine() === out.kbd_back_expected_line;
  out.kbd_back_restored = await lib.waitFor(ctx, backRestored, 40, 50);
  out.kbd_back_focus_editor = await lib.waitFor(ctx, () => nav.within(".cm-editor"), 20, 50);
  // 문맥 줄은 Python 의 사람이 읽는 위치(UX-10 R2: 「N행」)다 — 스냅샷의 줄 번호(0부터)로 기대값을 세운다.
  const range = (place) => `${Number((place || {}).line) + 1}행`;
  out.kbd_back_expected = range(occurrence);
  lib.pressKey(ctx, "F2");
  const backPropertiesShown = () => !!nameInput() && contextText().indexOf(range(occurrence)) >= 0;
  out.kbd_back_properties = await lib.waitFor(ctx, backPropertiesShown, 40, 50);
  out.kbd_back_context = contextText();
  lib.pressKey(ctx, "Escape");
  await lib.waitFor(ctx, panelGone, 20, 50);
  out.kbd_error_band = lib.textOf(doc.querySelector("#scr-authoring .authoring-shell > div.authoring-error")).trim();
}
