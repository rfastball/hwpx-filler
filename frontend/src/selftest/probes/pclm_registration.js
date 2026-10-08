/* 계약 목록 등록 진입 되읽기(#937) — `editor_workbench_data.js` 의 데이터 선택 프로브가 부른다.
 *
 * 그 클러스터 모듈은 프로브 정의만 들고, 등록 폼 하나를 재는 잔 단계는 여기 둔다(응집 단위 분리).
 * DOM 헬퍼는 호출자가 넘긴다 — 같은 헬퍼를 두 벌 두지 않는다. 이 모듈은 **비활성**이다: import
 * 만으로는 DOM 을 만지지 않는다 — 전부 호출 시점에 일어난다. */

/** 계약 목록(.db·.pclm)도 「파일 찾아보기…」 한 입구가 받는다 — 따로 선 진입 버튼은 없다.
 *  파일 고르기 브리지를 Python 의 등록 갈래 응답(`contract_list`)으로 갈아 **실클릭**하고, 열린
 *  폼이 pclm 모드로 그 DB 자리를 채운 채 그 자리에서 나열한 **미선택 시트 목록** 을 세우는지
 *  되읽는다(시트는 사용자 확정). 갈래 판정은 Python 이라 이 대역이 그 응답을 흉내 낸다. */
export async function probePclmRegistration(ctx, { byId, textOf, stubBridgeInvoke }) {
  const out = { pclm_entry_gone: !byId(ctx, "dataPickerPclm") };
  const sheetList = () => Array.from(
    ctx.doc.querySelectorAll("#poolRegView .pool-reg-sheet-list input"));
  const pick = stubBridgeInvoke(ctx, "pickDataFile", "pick_data_file",
    () => () => Promise.resolve({ contract_list: true, path: "C:/d/pclm.db" }));
  try {
    byId(ctx, "dataPickerBrowse").click();
    /* 대기는 고정 시간이 아니라 폼이 서고 그 자리의 시트가 나열될 때까지다(호출자의 inspect 대역). */
    for (let i = 0; i < 300 && sheetList().length === 0; i += 1) await ctx.sleep(10);
  } finally {
    pick.restore();
  }
  out.pclm_reg_db_prefill = (byId(ctx, "poolRegDb") || {}).value || "";
  const viewSelect = byId(ctx, "poolRegView");
  const sheetInputs = sheetList();
  out.pclm_reg_view_options = sheetInputs.length;
  if (sheetInputs.length < 2) return out;  // 던지지 않는다 — 게이트가 그 키로 실패한다
  out.pclm_reg_view_text = sheetInputs.map((input) => textOf(input.nextElementSibling)).join("|");
  out.pclm_reg_view_label = textOf(viewSelect.querySelector("legend"));
  out.pclm_reg_initial_empty = sheetInputs.every((input) => !input.checked)
    && byId(ctx, "poolRegOk").disabled;
  sheetInputs[0].click();
  await ctx.sleep(0);
  sheetInputs[1].click();
  await ctx.sleep(0);
  out.pclm_reg_multiple_selected = viewSelect.querySelectorAll(".pool-reg-sheet-list input:checked").length === 2
    && !byId(ctx, "poolRegOk").disabled;
  return out;
}

/** 기존 편집기 창에서 실제 React 탭의 drag·키보드 사건과 저장 왕복 중 초점을 잰다. */
export async function probeSheetReorder(ctx, { editorBase, stubBridgeCall }) {
  const client = ctx.services.Client, realInitial = client.initial;
  const calls = [], rows = ["A", "B", "C"].map((sheet) => ({
    key: "sheet-book", sheet, active: sheet === "A", selectable: true, reason: "",
  }));
  let snapshot = editorBase({ section: "binding", rows: [], data_sheet_tabs: rows,
    record_count: 1, source_fields: ["항목"], sample_rows: [["표본"]] });
  let release = null;
  const tabs = () => Array.from(ctx.doc.querySelectorAll("#scr-editor .data-tab"));
  const order = () => tabs().map((tab) => tab.textContent).join(",");
  const pending = () => ctx.doc.querySelector('#scr-editor .data-tabs[aria-busy="true"]');
  const initial = async (screen) => screen === "editor"
    ? { ok: true, value: snapshot } : realInitial.call(client, screen);
  client.initial = initial;
  const stub = stubBridgeCall(ctx, (real) => async (screen, action, payload) => {
    if (screen !== "pool" || action !== "reorder_sheets") return real(screen, action, payload);
    calls.push([screen, action, payload]);
    snapshot = { ...snapshot, data_sheet_tabs: payload.sheets.map((name) => rows.find((row) => row.sheet === name)) };
    return new Promise((resolve) => { release = resolve; });
  });
  try {
    ctx.push("editor", snapshot);
    await ctx.waitFor(() => order() === "A,B,C", { what: "시트탭 세 장", timeoutMs: 1000 });
    const transfer = new ctx.win.DataTransfer(), source = tabs()[0], target = tabs()[2];
    source.dispatchEvent(new ctx.win.DragEvent("dragstart", { bubbles: true, dataTransfer: transfer }));
    const over = new ctx.win.DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: transfer });
    target.dispatchEvent(over);
    await ctx.waitFor(() => target.dataset.dropTarget === "true", { what: "드롭 대상 강조", timeoutMs: 1000 });
    target.dispatchEvent(new ctx.win.DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer }));
    await ctx.waitFor(() => calls.length === 1 && pending(), { what: "드롭 저장 대기", timeoutMs: 1000 });
    release({ ok: true });
    await ctx.waitFor(() => order() === "B,C,A" && !pending(), { what: "드롭 순서 반영", timeoutMs: 1000 });
    const keyboardTab = tabs()[2];
    keyboardTab.focus();
    const key = new ctx.win.KeyboardEvent("keydown", { key: "ArrowLeft", altKey: true, bubbles: true, cancelable: true });
    keyboardTab.dispatchEvent(key);
    await ctx.waitFor(() => calls.length === 2 && pending(), { what: "키보드 순서 저장 대기", timeoutMs: 1000 });
    const focusWhileSaving = ctx.doc.activeElement === keyboardTab && !keyboardTab.disabled;
    release({ ok: true });
    await ctx.waitFor(() => order() === "B,A,C" && !pending(), { what: "키보드 순서 반영", timeoutMs: 1000 });
    return { calls, dragAccepted: over.defaultPrevented, keyAccepted: key.defaultPrevented,
      focusWhileSaving, focusAfterSaving: ctx.doc.activeElement === keyboardTab,
      markerCleared: !ctx.doc.querySelector('#scr-editor [data-drop-target="true"]') };
  } finally {
    if (release) release({ ok: true });
    stub.restore();
    if (client.initial === initial) client.initial = realInitial;
  }
}
