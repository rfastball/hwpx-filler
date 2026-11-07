/* `editor_workbench_data.js` 클러스터 D 의 `runHwpxAuthoringBand` 조각 — 책임 분리
 * (복잡도 예산) 전용 사이드카.
 *
 * `runHwpxAuthoringBand` 자체는 `editor_workbench_data.js` 에 그대로 산다(계약 파일의
 * 함수 식별자를 보존한다). 이 모듈은 그 몸체가 쪼개진 단계 함수들만 들고, 그 파일이
 * 가져다 쓴다. 공유 헬퍼(`textOf`·`waitFor`·`typeValue`·`byId`·`pollFor`·`keyboardNav`·
 * `pressKey`·`tabbables`·`settleRender`·`stubBridgeInvoke`)는 다른 저작 프로브도 쓰므로
 * `editor_workbench_data.js` 에 남아 export 되고, 여기로는 **역수입하지 않는다**
 * (production import 그래프의 순환 금지). 대신 `runHwpxAuthoringBand` 가 한 번 묶은
 * `lib` 객체로 주입한다. */

/** `runHwpxAuthoringBand` 의 공용 되읽기·판정 헬퍼 다발 — `doc`/`Bridge`/`sid` 를 닫고 쥔다.
 *  내부 대기 상한은 **짧게** 잡는다(DOM 2초 · 백엔드 왕복 2.5초). 어느 국면이 서지
 *  않으면 사유를 적고 곧장 나간다 — 아홉 자리에서 각자 길게 기다리면 합이 프로브 시한을
 *  넘고, 그때는 감시견이 프로브째 죽여 TXT 단언까지 증거를 잃는다. */
export function hwpxAuthoringHelpers(ctx, out, doc, Bridge, sid, lib) {
  const all = (selector) => Array.prototype.slice.call(doc.querySelectorAll(selector));
  const hit = (selector, label) => all(selector).find((el) => lib.textOf(el).indexOf(label) >= 0) || null;
  const exact = (selector, label) => all(selector).find((el) => lib.textOf(el).trim() === label) || null;
  // 그림 단추(UX-09: 실행 취소·다시 실행)는 보이는 글 대신 이름(aria-label)으로 찾는다.
  const named = (selector, label) => all(selector).find((el) => String(el.getAttribute("aria-label") || "").indexOf(label) === 0) || null;
  const snapshot = () => Bridge.initial("authoring");
  const activeTab = (snap) => (((snap || {}).tabs) || []).find(
    (tab) => tab.id === (snap || {}).active_id) || {};
  const fieldsOf = (tab) => (((tab.analysis) || {}).fields) || [];
  const countOf = (tab, name) => {
    const found = fieldsOf(tab).find((field) => field.name === name);
    return found ? found.count : 0;
  };
  const tab = async () => activeTab(await snapshot());
  const content = async () => String(
    (await Bridge.call("authoring", "content", { session_id: sid })).content);
  const undoLabel = () => String((named(".authoring-toolbar button", "문서 실행 취소") || { getAttribute: () => "" }).getAttribute("aria-label") || "").trim();
  const previewText = () => lib.textOf(doc.querySelector(
    ".authoring-properties section.authoring-preview:not(.authoring-refusal)"));
  const affected = () => {
    const found = /사용 위치 (\d+)곳/.exec(previewText());
    return found ? Number(found[1]) : -1;
  };
  /** 속성 폼의 Enter — 이름 칸에서 누른 Enter 의 암묵 제출과 같은 submit 경로다(pressKey 의 Enter 와 같다). */
  const enter = () => {
    const form = doc.querySelector("#scr-authoring form.authoring-properties");
    if (!form) return false;
    form.requestSubmit();
    return true;
  };
  const crumbNow = () => lib.textOf(doc.querySelector(
    '#scr-authoring .authoring-selection .authoring-crumb[aria-current="location"]')).trim();
  const afford = (ms) => ctx.remainingMs() > ms;
  /* 중단 사유와 함께 **표면이 그 순간 보이던 오류**를 싣는다 — 제품이 거절·예외를 오류
     띠(`.authoring-error`)로 그렸는데 프로브가 사유만 적으면, 「반영되지 않음」이 대기 부족인지
     제품의 거절인지가 증거에서 갈리지 않는다. */
  const give = (reason) => {
    out.hwpx_authoring_aborted = reason;
    out.hwpx_authoring_abort_alerts = all("#scr-authoring .authoring-error")
      .map((el) => lib.textOf(el).trim().slice(0, 200)).filter(Boolean);
    return false;
  };
  const fits = () => {
    const root = doc.documentElement;
    const face = doc.querySelector(".authoring-canvas");
    return {
      scroll_w: root.scrollWidth, client_w: root.clientWidth,
      canvas_h: face ? face.clientHeight : 0,
      ok: root.scrollWidth <= root.clientWidth && !!face && face.clientHeight > 100,
    };
  };
  return {
    Bridge, all, hit, exact, named, snapshot, activeTab, fieldsOf, countOf, tab, content,
    undoLabel, previewText, affected, enter, crumbNow, afford, give, fits,
    DOM_TRIES: 20, DOM_MS: 100, WIRE_TRIES: 20, WIRE_MS: 125,
  };
}

/** ── ④ 서식 있는 본문 문구를 고르고 필드로 만든다 ─────────────────────────────
 *  본문 범위 선택은 iframe **안**의 사건이라 게이트가 직접 끌 수 없다. 제품이 같은
 *  선택을 만드는 두 번째 실경로가 검색 적중 클릭이다(controller.select → locate). */
export async function runHwpxAuthoringSearchAndCreate(ctx, out, candidate, helpers, mount, lib) {
  const doc = ctx.doc;
  const {
    hit, exact, tab, content, fieldsOf, countOf, undoLabel, crumbNow, give,
    DOM_TRIES, DOM_MS, WIRE_TRIES, WIRE_MS,
  } = helpers;
  exact('.authoring-dock [role="tab"]', "검색").click();
  if (!await lib.waitFor(ctx, () => !!doc.querySelector('.authoring-bottom input[name="query"]'),
    DOM_TRIES, DOM_MS)) return { ok: give("검색 패널 미개방") };
  lib.typeValue(ctx, doc.querySelector('.authoring-bottom input[name="query"]'), candidate.query);
  exact(".authoring-bottom button", "찾기").click();
  const found = await lib.waitFor(
    ctx, () => !!hit(".authoring-bottom button", candidate.context), WIRE_TRIES, WIRE_MS);
  out.hwpx_authoring_search_hit = found
    ? lib.textOf(hit(".authoring-bottom button", candidate.context)).trim() : "";
  if (!found) return { ok: give("본문 검색 적중 없음") };
  hit(".authoring-bottom button", candidate.context).click();
  /* 검색 적중은 독에서 시작한 선택이다(NG-06 keepDock): 선택이 옮겨 가고(「필드로 만들기」 판정이 그 범위로 켜진다)
     독의 검색 탭과 적중 목록은 그대로이며 속성 패널은 열리지 않는다. 속성은 이어서 「필드로 만들기」가 연다. */
  const createReady = () => {
    const button = exact(".authoring-toolbar button", "필드로 만들기");
    return !!(button && !button.disabled && button.getAttribute("aria-disabled") !== "true");
  };
  if (!await lib.waitFor(ctx, createReady, WIRE_TRIES, WIRE_MS)) return { ok: give("검색 적중 선택 뒤 필드로 만들기 미개방") };
  const searchTab = exact('.authoring-dock [role="tab"]', "검색");
  out.hwpx_authoring_hit_dock_kept = !!searchTab && searchTab.getAttribute("aria-selected") === "true"
    && !!hit(".authoring-bottom button", candidate.context);
  out.hwpx_authoring_hit_no_properties = !doc.querySelector(".authoring-properties");
  // 일반 문서로 연(저장 경로 없는) 새 템플릿에는 연결된 작업이 없다 — 「변경 영향·작업 적용」 문맥 탭이 서지 않는다(NG-09).
  out.hwpx_authoring_impact_tab = !!exact('.authoring-dock [role="tab"]', "변경 영향·작업 적용");
  const create = exact(".authoring-toolbar button", "필드로 만들기");
  out.hwpx_authoring_create_enabled = !!(create && !create.disabled && create.getAttribute("aria-disabled") !== "true");
  if (!out.hwpx_authoring_create_enabled) return { ok: give("필드로 만들기 비활성") };
  create.click();
  if (!await lib.waitFor(ctx, () => !!doc.querySelector(".authoring-properties input"),
    DOM_TRIES, DOM_MS)) return { ok: give("속성 입력 없음") };
  /* 만들기 진입(IDE-03 NG-04·NG-05): 「명령」 선택이 없고 제출 단추가 명령 이름 하나다. 이름 칸은 Python 제안값으로
     열린다 — 이 표본 문구(「1. 입찰개요」)에는 「라벨:」이 없어 빈 칸이다(진단용으로 싣는다). */
  out.hwpx_authoring_create_form_select = !!doc.querySelector(".authoring-properties select");
  out.hwpx_authoring_create_submit_label = lib.textOf(doc.querySelector('.authoring-properties button[type="submit"]')).trim();
  out.hwpx_authoring_create_suggested = doc.querySelector(".authoring-properties input").value;
  out.hwpx_authoring_create_new_field = candidate.newField;
  lib.typeValue(ctx, doc.querySelector(".authoring-properties input"), candidate.newField);
  /* 새 이름 한 자리의 필드 만들기는 확인 등급 none 이다(P-01): 명령 단추 한 번(= Enter 한 번)에 적용되고
     미리보기 구획은 한 프레임도 서지 않는다. 그 사이 구획이 섰는지는 DOM 변화를 지켜 잰다. */
  let previewFlashed = false;
  const Observer = ctx.win.MutationObserver;
  const flashes = new Observer(() => {
    if (doc.querySelector(".authoring-properties section.authoring-preview:not(.authoring-refusal)")) previewFlashed = true;
  });
  flashes.observe(lib.byId(ctx, "scr-authoring"), { childList: true, subtree: true });
  const submit = exact(".authoring-properties button", "필드로 만들기");
  if (!submit) { flashes.disconnect(); return { ok: give("필드로 만들기 제출 단추 없음") }; }
  submit.click();
  const appliedAt = Date.now();
  if (!await lib.pollFor(ctx, async () => countOf(await tab(), candidate.newField) === 1,
    WIRE_TRIES, WIRE_MS)) {
    const late = await tab();
    out.hwpx_authoring_create_late = {
      ms: Date.now() - appliedAt, revision: late.revision, dirty: late.dirty,
      field_count: fieldsOf(late).length, new_count: countOf(late, candidate.newField),
    };
    flashes.disconnect();
    out.hwpx_authoring_create_refusal = lib.textOf(
      doc.querySelector(".authoring-properties .authoring-reason[role=alert], .authoring-refusal")).trim().slice(0, 160);
    return { ok: give("필드 생성이 분석에 반영되지 않음") };
  }
  out.hwpx_authoring_create_ms = Date.now() - appliedAt;
  /* 적용 뒤(결정 2·NG-14): 속성 패널이 닫히고 선택이 새 필드에 서서 위치 줄이 「필드 · 이름」이 된다. */
  out.hwpx_authoring_create_panel_closed = await lib.waitFor(
    ctx, () => !doc.querySelector(".authoring-properties"), WIRE_TRIES, WIRE_MS);
  await lib.waitFor(ctx, () => crumbNow() === `필드 · ${candidate.newField}`, WIRE_TRIES, WIRE_MS);
  flashes.disconnect();
  out.hwpx_authoring_create_preview_flashed = previewFlashed;
  out.hwpx_authoring_create_crumb = crumbNow();
  const created = await content();
  out.hwpx_authoring_create_field_count = fieldsOf(await tab()).length;
  out.hwpx_authoring_create_label = undoLabel();
  out.hwpx_authoring_create_changed_content = created !== mount;
  return { ok: true, created };
}

/** ── ⑤ 한 번의 문서 실행 취소가 원래 본문을 되돌린다 ───────────────────────── */
export async function runHwpxAuthoringUndoRedo(ctx, out, candidate, helpers, mount, created, priorOk, lib) {
  const { tab, content, fieldsOf, countOf, named, undoLabel, give, WIRE_TRIES, WIRE_MS } = helpers;
  if (!priorOk) return false;
  named(".authoring-toolbar button", "문서 실행 취소").click();
  if (!await lib.pollFor(ctx, async () => countOf(await tab(), candidate.newField) === 0,
    WIRE_TRIES, WIRE_MS)) return give("실행 취소가 필드를 되돌리지 않음");
  const undone = await content();
  out.hwpx_authoring_undo_field_count = fieldsOf(await tab()).length;
  out.hwpx_authoring_undo_changed_content = undone !== created;
  /* 진단용(단언하지 않는다): 마운트 시점 기준선은 **디스크 바이트**라, 되돌린 뒤 편집기가
     내보낸 바이트와 동일하지 않을 수 있다. 원본 동일의 확정은 ⑧의 제품 비교기가 진다. */
  out.hwpx_authoring_undo_content_equals_mount = undone === mount;
  out.hwpx_authoring_undo_label_cleared = undoLabel() === "문서 실행 취소";
  named(".authoring-toolbar button", "문서 다시 실행").click();
  if (!await lib.pollFor(ctx, async () => countOf(await tab(), candidate.newField) === 1,
    WIRE_TRIES, WIRE_MS)) return give("다시 실행이 필드를 되살리지 않음");
  out.hwpx_authoring_redo_field_count = fieldsOf(await tab()).length;
  out.hwpx_authoring_redo_content_equals_create = (await content()) === created;
  named(".authoring-toolbar button", "문서 실행 취소").click();
  if (!await lib.pollFor(ctx, async () => countOf(await tab(), candidate.newField) === 0,
    WIRE_TRIES, WIRE_MS)) return give("두 번째 실행 취소 미반영");
  out.hwpx_authoring_undo2_content_equals_undo = (await content()) === undone;
  return true;
}

/** ── ⑥ 이름 변경은 **모든 사용 위치**를 함께 옮긴다(AC07) ───────────────────── */
export async function runHwpxAuthoringRename(ctx, out, candidate, helpers, priorOk, lib) {
  const doc = ctx.doc;
  const { all, tab, countOf, fieldsOf, named, enter, affected, previewText, give, afford, WIRE_TRIES, WIRE_MS } = helpers;
  if (!priorOk) return false;
  if (!afford(8000)) return give("예산 부족: 이름 변경");
  // 필드 목록은 구조 패널의 「필드」 보기다(UX-09) — 그 보기를 열고, 필드 줄(treeitem)을 이름으로 찾는다
  // (「필드 · 이름 · 사용 위치 n곳」 — 화면 읽기가 읽는 그 이름).
  const fieldsView = doc.querySelector("#authoring-outline-fields");
  if (fieldsView) fieldsView.click();
  await lib.settleRender(ctx);
  const summary = all('#authoring-outline-fields-panel [role="treeitem"]').find(
    (el) => String(el.getAttribute("aria-label") || "").indexOf(`필드 · ${candidate.field} · 사용 위치 ${candidate.occurrences}곳`) === 0);
  out.hwpx_authoring_rename_target = summary ? String(summary.getAttribute("aria-label")).trim() : "";
  if (!summary) return give("구조 목록에 사용 위치 2곳 필드가 없음");
  summary.click();
  /* 입력창의 존재로는 선택이 끝났는지 알 수 없다 — 선택(controller.select → locate)이 끝나야
     명령이 「필드 이름 변경」으로 바뀌고 이름 칸이 그 필드의 이름으로 채워진다. 그 전에 쓰면
     직전 명령이 옛 선택 위에서 미리보기를 낸다(게이트 4차 재실행에서 실제로 났다). 구조 목록 줄이 연
     폼은 「명령」 선택을 둔다(NG-05). */
  const settled = () => {
    const kind = doc.querySelector(".authoring-properties select");
    const input = doc.querySelector(".authoring-properties input");
    return !!kind && kind.value === "rename_field" && !!input && input.value === candidate.field;
  };
  if (!await lib.waitFor(ctx, settled, WIRE_TRIES, WIRE_MS)) return give("필드 선택 뒤 이름 변경 속성 미정착");
  lib.typeValue(ctx, doc.querySelector(".authoring-properties input"), candidate.renamed);
  /* 이름 변경은 확인 등급 enter 다(P-01): 첫 Enter 가 영향 구획을 세우고, 같은 주 단추에 Enter 표기가 선다.
     입력이 그대로면 두 번째 Enter 가 적용이다. */
  if (!enter()) return give("이름 변경 폼 없음");
  if (!await lib.waitFor(ctx, () => affected() >= 0, WIRE_TRIES, WIRE_MS)) {
    out.hwpx_authoring_rename_refusal = lib.textOf(
      doc.querySelector(".authoring-refusal")).trim().slice(0, 160);
    return give("이름 변경 미리보기 미도착");
  }
  out.hwpx_authoring_rename_affected = affected();
  out.hwpx_authoring_rename_preview_text = previewText().trim().slice(0, 160);
  const armed = doc.querySelector('.authoring-properties button[type="submit"][aria-keyshortcuts="Enter"]');
  out.hwpx_authoring_rename_enter_armed = !!armed && lib.textOf(armed).trim() === "필드 이름 변경Enter";
  if (!enter()) return give("이름 변경 Enter 확정 불가");
  if (!await lib.pollFor(ctx, async () => countOf(await tab(), candidate.renamed) > 0,
    WIRE_TRIES, WIRE_MS)) return give("이름 변경이 분석에 반영되지 않음");
  const renamed = await tab();
  out.hwpx_authoring_rename_new_count = countOf(renamed, candidate.renamed);
  out.hwpx_authoring_rename_old_count = countOf(renamed, candidate.field);
  out.hwpx_authoring_rename_field_total = fieldsOf(renamed).length;
  named(".authoring-toolbar button", "문서 실행 취소").click();
  if (!await lib.pollFor(ctx, async () => countOf(await tab(), candidate.field) > 0,
    WIRE_TRIES, WIRE_MS)) return give("이름 변경 실행 취소 미반영");
  const restored = await tab();
  out.hwpx_authoring_rename_undo_old_count = countOf(restored, candidate.field);
  out.hwpx_authoring_rename_undo_new_count = countOf(restored, candidate.renamed);
  return true;
}

/** ── ⑦ 표시 방식 전환은 내용도 미저장 상태도 건드리지 않는다(AC23) ───────────── */
export async function runHwpxAuthoringModes(ctx, out, helpers, priorOk, lib) {
  const doc = ctx.doc;
  const { tab, content, give } = helpers;
  if (!priorOk) return false;
  const beforeModes = await tab();
  const contentBeforeModes = await content();
  const modeButton = (value) => doc.querySelector(`.authoring-toolbar .authoring-mode button[value="${value}"]`);
  if (!modeButton("document")) return give("표시 방식 선택이 없음");
  const applied = [];
  for (const value of ["document", "structure", "template"]) {
    modeButton(value).click();
    await lib.settleRender(ctx);
    await ctx.sleep(120);                               // 장식 왕복(iframe) 반영
    applied.push((doc.querySelector('.authoring-toolbar .authoring-mode button[aria-pressed="true"]') || {}).value || "");
  }
  out.hwpx_authoring_modes = applied;
  const afterModes = await tab();
  out.hwpx_authoring_mode_dirty_before = beforeModes.dirty;
  out.hwpx_authoring_mode_dirty_after = afterModes.dirty;
  out.hwpx_authoring_mode_content_stable = (await content()) === contentBeforeModes;
  return true;
}

/** ── ⑦-b §10 키보드만으로 구조 목록의 필드를 고르고 F2 로 이름 칸에 간다(HWPX) ─────
 *  실 rhwp iframe 이 초점을 가져가도 셸의 F6·F2·Escape 가 선다는 것을 잰다. 좌표 클릭 없음. */
export async function runHwpxAuthoringKeyboardNav(ctx, out, candidate, helpers, priorOk, lib) {
  const doc = ctx.doc;
  const { afford, WIRE_TRIES, WIRE_MS } = helpers;
  if (!priorOk) return;
  if (!afford(9000)) { out.hwpx_kbd_skipped = "예산 부족"; return; }
  const kbStart = Date.now();
  const nav = lib.keyboardNav(ctx);
  const nameInput = () => doc.querySelector(".authoring-properties input");
  const prefix = `필드 · ${candidate.field} · 사용 위치 ${candidate.occurrences}곳`;
  out.hwpx_kbd_outline = await nav.cycleTo(".authoring-outline");
  /* 진단(단언하지 않는다): 첫 Tab 한 번의 사건 판정과 탭 순서 안의 위치를 싣는다 — 닿지 못했을 때
     「키가 막혔다」와 「순서에 없다」를 증거에서 가른다. */
  const before = nav.active();
  const order = lib.tabbables(ctx);
  const first = out.hwpx_kbd_outline ? lib.pressKey(ctx, "Tab") : { prevented: null };
  out.hwpx_kbd_first_tab = { prevented: first.prevented, order: order.length,
    at: order.indexOf(before), moved: nav.active() !== before, now: nav.nameOf(nav.active()).slice(0, 60) };
  out.hwpx_kbd_field = out.hwpx_kbd_outline && await nav.treeTo((el) => nav.nameOf(el).indexOf(prefix) === 0, 80);
  out.hwpx_kbd_field_label = nav.nameOf(nav.active());
  if (!out.hwpx_kbd_field) { out.hwpx_kbd_ms = Date.now() - kbStart; return; }
  // 이 줄로 들어오는 두 경로(마우스 필드 고르기 ⑥·키보드 고르기 ⑦-b)가 같은 정착 술어를 쓴다.
  const settled = () => {
    const kind = doc.querySelector(".authoring-properties select");
    const input = doc.querySelector(".authoring-properties input");
    return !!kind && kind.value === "rename_field" && !!input && input.value === candidate.field;
  };
  lib.pressKey(ctx, "Enter");
  await lib.waitFor(ctx, settled, WIRE_TRIES, WIRE_MS);
  lib.pressKey(ctx, "F2");
  out.hwpx_kbd_f2_focus = await lib.waitFor(ctx, () => !!nameInput() && nav.active() === nameInput()
    && nameInput().value === candidate.field, WIRE_TRIES, WIRE_MS);
  /* Escape 는 두 단계다(§6.2·§10): 작성 중인 값이 적용값과 다르면 먼저 되돌리고, 다음 Escape 가
     패널을 닫는다. rhwp 는 초점 이동 뒤 자기 커서를 300ms 주기로 다시 보고하므로 그 사이 선택
     대상이 바뀌면 첫 Escape 가 「되돌리기」가 될 수 있다 — 단계 수와 그때의 대상을 함께 싣는다. */
  const target = () => lib.textOf(doc.getElementById("authoring-properties-target")).trim();
  const gone = () => !doc.querySelector(".authoring-properties");
  out.hwpx_kbd_escape_target_before = target();
  out.hwpx_kbd_escape_presses = 0;
  for (let press = 0; press < 2 && !gone(); press += 1) {
    lib.pressKey(ctx, "Escape");
    out.hwpx_kbd_escape_presses += 1;
    await lib.waitFor(ctx, gone, 8, 100);
  }
  out.hwpx_kbd_escape_closes = gone();
  /* UX-07 — 편집면 iframe **안**에서 누른 Escape·F6 도 셸에 닿는다. 스튜디오 입력칸은 같은 출처라
     contentDocument 로 닿고, 합성 키도 스튜디오의 키 처리기를 실물로 지난다(셸로 넘기는 것은 그 처리기다). */
  const frame = doc.querySelector(".authoring-document:not([hidden]) .authoring-editor-host iframe");
  const studio = frame && frame.contentDocument;
  const input = studio && studio.querySelector('[aria-label="문서 편집 입력"]');
  out.hwpx_kbd_iframe_input = !!input;
  if (out.hwpx_kbd_escape_closes && input) {
    const pressInside = (key, init) => input.dispatchEvent(new frame.contentWindow.KeyboardEvent("keydown",
      Object.assign({ key, bubbles: true, cancelable: true }, init || {})));
    frame.focus();
    lib.pressKey(ctx, "F2");                                   // 셸이 속성 패널을 다시 연다
    out.hwpx_kbd_iframe_panel_open = await lib.waitFor(ctx, () => !gone(), WIRE_TRIES, WIRE_MS);
    pressInside("Escape");
    out.hwpx_kbd_iframe_escape_closes = await lib.waitFor(ctx, gone, 20, 100);
    frame.focus();
    pressInside("F6");
    await lib.settleRender(ctx);
    out.hwpx_kbd_iframe_f6_to = nav.nameOf(nav.active()).slice(0, 60);
    out.hwpx_kbd_iframe_f6_left = nav.active() !== frame && !nav.within(".authoring-canvas")
      && nav.within(".authoring-toolbar,.authoring-outline,.authoring-properties,.authoring-dock");
  }
  out.hwpx_kbd_ms = Date.now() - kbStart;
}

/** ── 좁은 창(760×600)·150% 배율에서도 편집면이 서고 가로 스크롤이 없다 ───────── */
export async function runHwpxAuthoringNarrowWindow(ctx, out, helpers, priorOk, Personalization, lib) {
  const doc = ctx.doc;
  const { fits, afford } = helpers;
  if (!priorOk) return;
  if (!afford(6000)) return;
  ctx.state.hwpxWindowResized = true;
  await ctx.host("window_resize", { width: 760, height: 600 });
  await ctx.sleep(600);                               // OS resize → relayout(grid_narrow 와 같은 값)
  const narrow = fits();
  out.hwpx_authoring_min_window_ok = narrow.ok;
  out.hwpx_authoring_min_window_scroll_w = narrow.scroll_w;
  out.hwpx_authoring_min_window_client_w = narrow.client_w;
  out.hwpx_authoring_min_window_canvas_h = narrow.canvas_h;
  await ctx.host("window_resize", { width: 1440, height: 900 });
  await ctx.sleep(600);
  ctx.state.hwpxWindowResized = false;
  /* 배율은 제품의 개인화 동사로 올린다(설정 모달이 부르는 그 함수) — 150% = `larger`.
     그 동사는 **폭도 함께 다시 쓴다**(`apply` 가 현재 계산값을 읽어 되쓴다). 그래서 그
     값이 아직 서지 않은 대역에서 부르면 하한(180px)이 심어지고, 그 자취는 뒤따르는
     개인화 프로브의 `master_width == 240` 실패로 나타난다 — 서지 않았으면 부르지 않고
     사유를 싣는다(원인이 이 밴드가 아니라 저쪽 프로브로 보이는 경로를 만들지 않는다). */
  const app = doc.querySelector(".app");
  const masterBefore = app
    ? ctx.win.getComputedStyle(app).getPropertyValue("--master-width").trim() : "";
  if (!masterBefore) {
    out.hwpx_authoring_font_scale_skipped = "개인화가 아직 폭을 적용하지 않았습니다";
    return;
  }
  const real = ctx.win.alert;
  ctx.win.alert = function () {
    out.hwpx_authoring_alerts = (out.hwpx_authoring_alerts || 0) + 1;
  };
  /* 되돌릴 값은 「normal」이 아니라 **이 부팅이 들고 있던 배율**이다 — 배율 영속 검사가
     env 로 large/larger 를 심은 부팅에서 normal 로 되돌리면 그 검사의 재시작 되읽기가
     normal 을 읽는다(게이트 3차에서 실제로 났다). */
  const scaleBefore = doc.documentElement.getAttribute("data-font-scale") || "normal";
  const pxBefore = ctx.win.getComputedStyle(doc.documentElement).fontSize;
  out.hwpx_authoring_font_scale_before = scaleBefore;
  try {
    Personalization.setFontScale("larger");
    await lib.settleRender(ctx);
    await ctx.sleep(200);
    const large = fits();
    out.hwpx_authoring_font_scale = String(
      doc.documentElement.getAttribute("data-font-scale") || "");
    out.hwpx_authoring_font_scale_px = ctx.win.getComputedStyle(doc.documentElement).fontSize;
    out.hwpx_authoring_font_scale_ok = large.ok;
    out.hwpx_authoring_font_scale_scroll_w = large.scroll_w;
    out.hwpx_authoring_font_scale_client_w = large.client_w;
    out.hwpx_authoring_font_scale_canvas_h = large.canvas_h;
  } finally {
    Personalization.setFontScale(scaleBefore);
    await lib.settleRender(ctx);
    ctx.win.alert = real;
  }
  out.hwpx_authoring_font_scale_restored = ctx.win.getComputedStyle(
    doc.documentElement).fontSize === pxBefore;
  out.hwpx_authoring_master_width_stable = ctx.win.getComputedStyle(app)
    .getPropertyValue("--master-width").trim() === masterBefore;
}

/** ── ⑧ 한 번도 저장하지 않은 문서의 첫 저장은 **경로를 묻는다**(AC01) ────────── */
export async function runHwpxAuthoringSavePath(ctx, out, sid, helpers, priorOk, lib) {
  const { Bridge, tab, exact, give, afford, DOM_TRIES, DOM_MS } = helpers;
  if (!priorOk) return;
  if (!afford(4000)) { give("예산 부족: 저장 판정"); return; }
  const asked = { count: 0 };
  const saveStub = lib.stubBridgeInvoke(ctx, "saveAuthoringDocument", "save_authoring_document",
    () => async () => { asked.count += 1; return null; });   // 취소 = 아무 파일도 쓰지 않는다
  try {
    exact(".authoring-head button", "저장").click();
    await lib.pollFor(ctx, async () => asked.count > 0, DOM_TRIES, DOM_MS);
  } finally { saveStub.restore(); }
  out.hwpx_authoring_save_asked_for_path = asked.count === 1;
  const current = await tab();
  const refusal = await Bridge.call("authoring", "save",
    { session_id: sid, revision: current.revision });
  out.hwpx_authoring_save_needs_path = refusal.needs_path === true && refusal.needs_save_as === true;
  out.hwpx_authoring_save_path_after = String((await tab()).save_path || "");

  /* 되돌린 문서가 **디스크의 원본과 같은가** — 제품의 보존 비교기로 확정한다(바이트 비교로는
     rhwp 직렬화 차이와 진짜 손실을 가를 수 없다). 이 자리가 마지막인 이유: 비교 결과가
     `rhwp_editable` 을 다시 쓰므로, 실패하면 문서가 읽기 전용이 된다. */
  const source = await Bridge.call("authoring", "external_content", { session_id: sid });
  const verdict = await Bridge.call("authoring", "rhwp_roundtrip_preflight",
    { session_id: sid, revision: (await tab()).revision, content: source.content });
  out.hwpx_authoring_undone_matches_source = verdict.editable === true;
  out.hwpx_authoring_undone_diagnostics = (verdict.diagnostics || []).slice(0, 6);
}
