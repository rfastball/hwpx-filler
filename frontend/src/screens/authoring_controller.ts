import type { BridgeClient } from "../runtime/client.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;
export type AuthoringEditor = {
  flush?(): Promise<void>;
  content(): Promise<string>;
  apply(content: string, edits: Obj[], label: string, expectedContent?: string): Promise<void>;
  focus(target: Obj): Promise<void>;
  command(command: "undo" | "redo" | "search"): Promise<void>;
  decorate(analysis: Obj, mode: string): void;
  /** 편집기 history 의 현재 깊이. 없으면(HWPX) 표면은 두 버튼을 그대로 켜 둔다. */
  state?(): { canUndo: boolean; canRedo: boolean };
};
/** 의미 명령 → 표시 이름. 표면의 버튼·팔레트와 실행 취소 표지가 같은 이름을 쓴다. */
export const COMMANDS: [string, string][] = [
  ["create_field", "필드로 만들기"], ["create_slot", "항목으로 만들기"], ["create_option", "선택으로 만들기"],
  ["rename_field", "필드 이름 변경"], ["relink_field", "필드 연결 변경"], ["unset_field", "필드 의미 해제"],
  ["rename_slot", "항목 속성 변경"], ["rename_option", "선택 속성 변경"], ["adjust_range", "범위 조정"],
  ["unwrap", "의미만 해제"], ["delete", "내용까지 삭제"], ["duplicate", "복제"], ["move", "이동"],
];
type Deps = {
  client: BridgeClient;
  runtime: ScreenRuntime;
  modal: { confirm(spec: Obj): Promise<boolean>; choose(spec: Obj): Promise<string | null>; prompt(spec: Obj): Promise<string | null> };
  navigation: { go(screen: string, options?: Obj): void; refresh(screen: string): Promise<unknown> };
};

/** 편집기 선택 좌표만 남긴다 — 선택 대상 객체(이름·종류 등)가 섞인 뷰 선택을 편집기 좌표 모양으로 되돌린다. */
const COORDINATE_KEYS = ["start", "end", "entry", "paragraph", "start_paragraph", "end_paragraph", "cell_path"];
export function coordinates(selection: Obj | null | undefined): Obj {
  const picked: Obj = {};
  for (const key of COORDINATE_KEYS) if (selection?.[key] !== undefined && selection?.[key] !== null) picked[key] = selection[key];
  return picked.start === undefined || picked.end === undefined ? {} : picked;
}

/** 선택 대상의 정체 — Python 이 좌표가 아니라 대상으로 locate 를 판정한다(§3.3·§6.2). 여기서는 투영이 준 열쇠만 옮긴다.
 *  필드 목록의 필드 전체는 occurrences 를 싣고, 사용 위치·검색 적중·일치 후보는 한 자리다. 정체가 없으면 좌표 선택이다. */
export function semanticTarget(target: Obj): Obj | undefined {
  if (target.kind === "field" && typeof target.name === "string")
    return { kind: Array.isArray(target.occurrences) ? "field" : "occurrence", name: target.name };
  if (target.kind === "slot" && typeof target.slot_id === "string") return { kind: "slot", slot_id: target.slot_id };
  if (target.kind === "option" && typeof target.slot_id === "string" && typeof target.option_id === "string")
    return { kind: "option", slot_id: target.slot_id, option_id: target.option_id };
  return undefined;
}

/** 명시 선택이 편집기를 옮긴 자리의 되울림인가 — 같은 섹션·셀·문단 범위이고, 편집기가 받은 시작(없으면 0)과 끝(있으면)이다. */
function echoes(place: Obj, selection: Obj): boolean {
  if ((place.entry ?? null) !== (selection.entry ?? null)) return false;
  if (JSON.stringify(cellPath(place.cell_path)) !== JSON.stringify(cellPath(selection.cell_path))) return false;
  const first = place.start_paragraph ?? place.paragraph;
  if (first != null) {
    const low = selection.start_paragraph ?? selection.paragraph;
    const high = selection.end_paragraph ?? low;
    if (!(low >= first && high <= (place.end_paragraph ?? first))) return false;
  }
  if (selection.start !== (place.start ?? (first != null ? 0 : undefined))) return false;
  return typeof place.end !== "number" || selection.end === place.end;
}
const cellPath = (path: unknown): unknown[] | null => Array.isArray(path)
  ? path.map((step: Obj) => [step?.parent_paragraph, step?.control, step?.cell, step?.paragraph]) : null;

export function createAuthoringController(deps: Deps) {
  const model = deps.runtime.model<Obj | null>("authoring");
  const editors = new Map<string, AuthoringEditor>();
  const buffers = new Map<string, string>();
  const revisions = new Map<string, number>();
  const pumps = new Map<string, Promise<void>>();
  const listeners = new Set<() => void>();
  const navigationHistory: { id: string; revision: number; target: Obj }[] = [];
  const views = new Map<string, Obj>();
  const generations = new Map<string, number>();
  const inputPumps = new Map<string, Promise<void>>();
  const selectionRequests = new Map<string, number>();
  // 명시 선택(구조 목록·검색·문제·시험 추적)이 편집기 초점을 옮기면 편집기가 그 선택을 되울린다. 초점 이동 중의
  // 모든 보고와, 끝난 뒤 그 자리의 첫 보고는 되울림이다 — 명시 대상·판정을 덮지 않는다. 다른 자리는 사용자 이동이다.
  let explicit: { id: string; place: Obj; focusing: boolean } | null = null;
  // U02: Python 이 판정한 복원 대상(tab.restore)은 **새 뷰에 한 번** 소비한다 — 표시 방식은 뷰에, 좌표는
  // 편집기가 붙는 순간 초점으로. 바뀐 위치·방식은 잠시 모아 Python 에 보낸다(보관·판정은 Python 몫).
  const pendingRestore = new Map<string, Obj>();
  const rememberTimers = new Map<string, ReturnType<typeof setTimeout>>();
  // commands: Python 이 현재 선택에 대해 판정한 명령 가용성(F40·P07). 표면은 이것을 그리기만 하고 다시 판정하지 않는다.
  const initialView = (): Obj => ({ error: "", busy: false, trialBusy: false, saveFailed: false, lastCommandLabel: "", lastCreatedText: "", notice: "",
    mode: "template", panel: "", selection: {}, selected: null, commands: [], contextMenu: null, refusal: null, syntax: null,
    command: null, preview: null, trial: false, autoTrial: true, query: "", hits: [], searchSummaries: [], values: {}, selectedOptions: {}, zoom: 100 });
  let view = initialView();
  let viewId = "";
  let trialTimer: ReturnType<typeof setTimeout> | undefined;
  let returnScreen = "editor";
  let clipboard: Obj | null = null;
  let previewRequest = 0;
  let searchRequest = 0;
  let applying = false;
  const snapshot = (): Obj => model.getSnapshot() || { tabs: [], active_id: "" };
  const tab = (id = snapshot().active_id): Obj => (snapshot().tabs || []).find((item: Obj) => item.id === id) || {};
  const update = (patch: Obj) => { view = { ...view, ...patch }; if (viewId) views.set(viewId, view); listeners.forEach((listener) => listener()); };
  const dispatch = async (action: string, payload: Obj = {}): Promise<Obj> => {
    const call = deps.client.dispatch as unknown as (screen: string, name: string, body: Obj) => ReturnType<BridgeClient["dispatch"]>;
    const result = expectHostValue(await call("authoring", action, payload), `authoring/${action}`) as Obj;
    // 거절(refusal)은 오류가 아니라 판정이다 — 호출자가 사유와 대안을 그린다(U07·AC08·AC10).
    if (result?.ok === false && !result.refusal) throw new Error(result.message || result.detail || result.reason);
    return result || {};
  };
  const invoke = async (method: Parameters<BridgeClient["invoke"]>[0], ...args: unknown[]): Promise<Obj | null> =>
    expectHostValue(await deps.client.invoke(method, ...args), method) as Obj | null;
  const revision = (id: string): number => revisions.get(id) ?? tab(id).revision;
  const fenced = (id: string, payload: Obj = {}): Obj => ({ session_id: id, revision: revision(id), ...payload });

  async function guarded(work: () => unknown | Promise<unknown>) {
    try { update({ error: "" }); await work(); }
    catch (error) { update({ error: error instanceof Error ? error.message : String(error) }); }
  }

  function changed(id: string, content: string): void {
    buffers.set(id, content);
    if (id === viewId) update({ preview: null, refusal: null, notice: "" });
    void guarded(async () => { await drain(id); scheduleTrial(id); });
  }

  async function flush(id: string): Promise<void> {
    await editors.get(id)?.flush?.();
    await drain(id);
  }

  async function drain(id: string): Promise<void> {
    if (pumps.has(id)) { await pumps.get(id); if (buffers.has(id)) return drain(id); return; }
    const pump = (async () => {
      while (buffers.has(id)) {
        const content = buffers.get(id)!;
        const result = await dispatch("update", fenced(id, { content }));
        revisions.set(id, result.revision);
        if (buffers.get(id) === content) buffers.delete(id);
      }
    })();
    pumps.set(id, pump);
    try { await pump; } finally { pumps.delete(id); if (id === viewId) update({}); }
  }

  async function flushAll(): Promise<void> {
    for (const item of snapshot().tabs || []) { await flush(item.id); await inputPumps.get(item.id); }
    for (const id of [...rememberTimers.keys()]) await remember(id);
  }

  /** 복원 대상이 있는 새 뷰 — 표시 방식과 선택 좌표만 옮긴다. 좌표 없는 복원(stale·unreadable)은 방식만 또는 아무것도. */
  function restoredView(restore: Obj | null | undefined): Obj {
    return { ...initialView(), ...(restore?.mode ? { mode: restore.mode } : {}), ...(restore?.selection ? { selection: restore.selection } : {}) };
  }

  /** 편집기가 붙어 있으면 복원을 적용한다 — 활성화와 편집기 부착 중 늦게 오는 쪽이 적용한다(순서는 경쟁이다). */
  async function applyRestore(id: string) {
    const editor = editors.get(id);
    const pending = pendingRestore.get(id);
    if (!editor || !pending) return;
    pendingRestore.delete(id);
    editor.decorate(tab(id).analysis || {}, views.get(id)?.mode || "template");
    // 좌표는 Python 이 이 bytes 에 대해 유효하다고 판정한 것이다. 그래도 편집기가 거절하면 알리되 문서 열기는 막지 않는다.
    if (pending.selection) await editor.focus(pending.selection).catch((error) => update({ error: error instanceof Error ? error.message : String(error) }));
  }

  function scheduleRemember(id: string) {
    clearTimeout(rememberTimers.get(id));
    rememberTimers.set(id, setTimeout(() => { void guarded(() => remember(id)); }, 400));
  }

  /** 최근 작업 위치·표시 방식을 Python 에 보낸다. 편집기 flush 는 부르지 않는다 — 한글 조합 중에도 경보가 서지 않는다. */
  async function remember(id: string) {
    clearTimeout(rememberTimers.get(id));
    rememberTimers.delete(id);
    const state = views.get(id);
    if (!state || !tab(id).id) return;
    await drain(id);
    await dispatch("remember_view", fenced(id, { selection: coordinates(state.selection), mode: state.mode || "template" }));
  }

  async function activate(id: string) {
    clearTimeout(trialTimer);
    if (snapshot().active_id) { await flush(snapshot().active_id); await inputPumps.get(snapshot().active_id); }
    const activated = await dispatch("activate", { session_id: id });
    const current = tab(id);
    viewId = id;
    const known = views.get(id);
    const restore = activated.restore ?? current.restore;
    view = known || restoredView(restore);
    if (!known && (restore?.mode || restore?.selection)) pendingRestore.set(id, { selection: restore.selection || null });
    update({
      values: { ...(current.values || {}) }, selectedOptions: { ...(current.selected || {}) } });
    await applyRestore(id);
  }

  async function open(path?: string) {
    await deps.runtime.loadInitial("authoring");
    returnScreen = "editor";
    if (path) {
      const result = await invoke("open_authoring_document", path, true);
      if (!result) return;
      revisions.set(result.session_id, result.revision);
      await activate(result.session_id);
    }
    deps.navigation.go("authoring", { force: true });
  }

  async function openFile() {
    const result = await invoke("open_authoring_document", "", false);
    if (!result) return;
    revisions.set(result.session_id, result.revision);
    await activate(result.session_id);
    // 처음 여는 일반 문서의 첫 안내(§13) — Python 이 준 문장만, 다음 편집에서 사라진다.
    if (result.notice && viewId === result.session_id) update({ notice: result.notice });
  }

  async function save(id = snapshot().active_id, saveAs = false): Promise<boolean> {
    await flush(id);
    let result: Obj | null;
    try {
      result = saveAs || !tab(id).path || tab(id).save_as_required
        ? await invoke("save_authoring_document", id, revision(id))
        : await dispatch("save", fenced(id));
    } catch (error) { update({ saveFailed: true }); throw error; }
    if (result?.needs_save_as) return save(id, true);
    // 저장 실패는 변경 상태를 유지한 채 복구 동사(비교·다른 이름·다시 열기·다시 저장)를 남긴다(§9.2).
    if (result?.external_changed || result?.conflict) { update({ panel: "external", saveFailed: true, error: result.message || "저장할 파일이 변경되었거나 이미 존재합니다. 다른 이름으로 저장하세요." }); return false; }
    if (!result || result.cancelled) return false;
    update({ saveFailed: false, notice: result.notice || "", panel: view.panel === "external" ? "" : view.panel });
    await deps.navigation.refresh("tpl");
    return true;
  }

  async function close(id: string): Promise<boolean> {
    await flush(id);
    await inputPumps.get(id);
    // 남은 작업 위치를 먼저 보낸다. 실패는 알리되 문서 닫기를 막지 않는다(잃는 것은 위치 기록뿐이다).
    if (rememberTimers.has(id)) await remember(id).catch((error) => update({ error: error instanceof Error ? error.message : String(error) }));
    let result = await dispatch("close", { session_id: id, force: false });
    if (result.needs_confirm) {
      const answer = await deps.modal.choose({ title: tab(id).name || "문서 닫기",
        body: result.cases_dirty ? "템플릿과 시험 자료의 미저장 변경을 확인하세요." : "템플릿에 저장하지 않은 변경이 있습니다.",
        choices: [{ value: "save", label: "저장하고 닫기" }, { value: "discard", label: "저장하지 않고 닫기", danger: true },
          { value: "cancel", label: "계속 편집" }] });
      if (!answer || answer === "cancel") return false;
      if (answer === "save") {
        if (result.dirty && !(await save(id))) return false;
        if (result.cases_dirty && !(await persistCases(id))) return false;
      }
      result = await dispatch("close", { session_id: id, force: true });
    }
    revisions.delete(id);
    buffers.delete(id);
    views.delete(id);
    generations.delete(id);
    pendingRestore.delete(id);
    clearTimeout(rememberTimers.get(id));
    rememberTimers.delete(id);
    if (snapshot().active_id) await activate(snapshot().active_id);
    return !result.needs_confirm;
  }

  async function leaveTo(to: string) {
    await flushAll();
    // 화면 이동은 문서를 닫지 않는다. 탭과 각 편집기 history는 마운트된 채 유지한다.
    deps.navigation.go(to, { force: true });
  }

  async function select(target: Obj) {
    // A preview belongs to the target it was computed for. Choosing another target retires both
    // the shown preview and any in-flight one — otherwise a late create_field preview for the old
    // range lands under the new target's "필드 이름 변경" label and its apply runs the old command.
    previewRequest += 1;
    const previous = { id: snapshot().active_id, revision: revision(snapshot().active_id), target: view.selection };
    if (target.session_id && target.session_id !== snapshot().active_id) await activate(target.session_id);
    const id = snapshot().active_id;
    const location = target.location || target.occurrences?.[0] || target.source || target;
    const place = { ...location, start: location.source_start ?? location.start, end: location.source_end ?? location.end };
    const hold = { id, place, focusing: true };
    // 이 선택보다 먼저 떠난 캐럿 locate 는 늦게 와도 이 선택을 바꾸지 못한다.
    explicit = hold;
    selectionRequests.set(id, (selectionRequests.get(id) || 0) + 1);
    try {
      await flush(id);
      const identity = semanticTarget(target);
      const located = target.source_revision != null
        ? await dispatch("locate", { session_id: id, revision: target.source_revision, selection: location, ...(identity ? { target: identity } : {}) }) : null;
      navigationHistory.push(previous);
      update({ selected: { ...location, ...(located?.selected || target) }, selection: location, matches: located?.matches || [], panel: "properties", refusal: null, preview: null, command: null,
        context: located?.context || view.context || {}, commands: await commandsFor(id, located, location),
        commandType: target.kind === "field" ? "rename_field" : target.kind === "option" ? "rename_option" : target.kind === "slot" ? "rename_slot" : undefined });
      if (location.start != null || location.source_start != null || location.paragraph != null || location.start_paragraph != null)
        await editors.get(id)?.focus(place);
    } catch (error) {
      if (explicit === hold) explicit = null;
      throw error;
    } finally { hold.focusing = false; }
  }

  async function back() {
    const previous = navigationHistory.pop();
    if (!previous) return;
    await activate(previous.id);
    const located = await dispatch("locate", { session_id: previous.id, revision: previous.revision, selection: previous.target });
    update({ selection: previous.target, selected: null, context: located.context || {}, commands: await commandsFor(previous.id, located, previous.target) });
    await editors.get(previous.id)?.focus(previous.target);
  }

  async function preview(command: Obj) {
    const id = snapshot().active_id;
    const request = ++previewRequest;
    await flush(id);
    const editorContent = await editors.get(id)?.content();
    const atRevision = revision(id);
    const result = await previewCommand(id, atRevision, command);
    if (id !== viewId || request !== previewRequest || atRevision !== revision(id)) return;
    if (result.refusal) update({ command, preview: null, refusal: result.refusal });
    else update({ command, preview: { ...result, session_id: id, revision: atRevision, editorContent }, refusal: null });
  }

  /** 현재 선택의 명령 가용성 — locate 결과가 실어 오면 그것, 아니면 독립 액션 `commands` 로 묻는다. */
  async function commandsFor(id: string, located: Obj | null, selection: Obj): Promise<Obj[]> {
    if (located?.commands) return located.commands;
    const result = await dispatch("commands", fenced(id, { selection, context: located?.context || view.context || {} }));
    return result.commands || [];
  }

  const previewCommand = (id: string, atRevision: number, command: Obj) => command.type === "paste"
    ? dispatch("preview_paste", { session_id: id, revision: atRevision, clipboard_token: command.clipboard_token,
      destination: command.destination, with_meaning: command.with_meaning })
    : dispatch("preview", { session_id: id, revision: atRevision, command });

  async function applyPreview() {
    if (applying) return;
    const prepared = view.preview;
    const command = view.command;
    if (!prepared) return;
    applying = true;
    try {
      const id = prepared.session_id;
      await flush(id);
      // 확정 직전에도 backend가 같은 revision을 검사한다. 늦은 미리보기는 적용하지 않는다.
      const result = await previewCommand(id, prepared.revision, command);
      if (result.refusal) throw new Error(result.refusal.message);
      await flush(id);
      if (revision(id) !== prepared.revision) throw new Error("문서가 변경되었습니다. 변경 미리보기를 다시 실행하세요.");
      const editor = editors.get(id);
      if (!editor) throw new Error("문서 편집기를 다시 여세요.");
      await editor.apply(result.content ?? result.result, result.edits || [], command.type, prepared.editorContent);
      changed(id, await editor.content());
      await flush(id);
      // 다음에 되돌릴 행동의 이름(§9.3). backend 가 label 을 주면 그것, 아니면 명령 표시 이름.
      const label = prepared.label || result.label || COMMANDS.find(([type]) => type === command.type)?.[1] || command.type;
      if (id === viewId) update({ command: null, preview: null, lastCommandLabel: label });
      scheduleTrial(id);
    } finally { applying = false; }
  }

  function scheduleTrial(id: string) {
    clearTimeout(trialTimer);
    const state = views.get(id);
    if (id === viewId && state?.autoTrial && state?.trial) trialTimer = setTimeout(() => { void guarded(() => runTrial(id)); }, 350);
  }

  /** U03: 선택 문구를 시험값으로 보관한다 — 이미 값이 있으면 덮어쓰지 않고 유지/교체를 묻는다. */
  async function keepTrialValue(name: string, captured: string): Promise<boolean> {
    const values: Obj = { ...(view.values || {}) };
    if (name in values) {
      if (values[name] === captured) return false;
      const answer = await deps.modal.choose({ title: "시험값 보관", body: `‘${name}’ 필드에 시험값이 이미 있습니다.`,
        choices: [{ value: "keep", label: "기존 값 유지" }, { value: "replace", label: "선택 문구로 교체" }] });
      if (answer !== "replace") return false;
    }
    await trialInput({ ...values, [name]: captured }, view.selectedOptions || {});
    return true;
  }

  async function trialInput(values: Obj, selectedOptions: Obj) {
    const id = snapshot().active_id;
    update({ values, selectedOptions });
    const previous = inputPumps.get(id) || Promise.resolve();
    const pump = previous.catch(() => {}).then(async () => {
      await flush(id);
      await dispatch("trial_input", fenced(id, { values, selected: selectedOptions }));
    });
    inputPumps.set(id, pump);
    try { await pump; scheduleTrial(id); }
    finally { if (inputPumps.get(id) === pump) inputPumps.delete(id); }
  }

  async function runTrial(id = snapshot().active_id) {
    clearTimeout(trialTimer);
    await inputPumps.get(id);
    await flush(id);
    if (id === viewId) update({ trialBusy: true, trial: true });
    try { await dispatch("trial", fenced(id)); }
    finally { if (id === viewId) update({ trialBusy: false }); }
  }

  async function saveCase(id = snapshot().active_id): Promise<boolean> {
    const name = await deps.modal.prompt({ title: "시험 케이스 저장", body: "이름", value: "" });
    if (!name) return false;
    await flush(id);
    await inputPumps.get(id);
    const state = views.get(id) || tab(id);
    await dispatch("case_upsert", fenced(id, { name, values: state.values || {}, selected: state.selectedOptions || state.selected || {} }));
    return persistCases(id);
  }

  async function persistCases(id: string): Promise<boolean> {
    const result = await dispatch("save_cases", { session_id: id });
    if (result.needs_document_save) return await save(id) && persistCases(id);
    if (result.needs_case_name) return saveCase(id);
    if (result.needs_case_repair) throw new Error(result.message);
    return true;
  }

  async function search(query: string, kind: string, all = false) {
    const request = ++searchRequest;
    const id = viewId;
    const hits: Obj[] = [];
    const searchSummaries: Obj[] = [];
    for (const item of all ? snapshot().tabs : [tab()]) {
      await flush(item.id);
      const requestRevision = revision(item.id);
      const result = await dispatch("search", { session_id: item.id, revision: requestRevision, query, kind });
      hits.push(...(result.hits || result.results || []).map((hit: Obj) => ({ ...hit, session_id: item.id, source_revision: requestRevision, document: item.name })));
      if (result.summary) searchSummaries.push({ document: item.name, summary: result.summary });
    }
    if (id === viewId && request === searchRequest) update({ query, hits, searchSummaries, panel: "search" });
  }

  async function restored(result: Obj) {
    const id = result.session_id;
    buffers.delete(id);
    revisions.set(id, result.revision);
    generations.set(id, (generations.get(id) || 0) + 1);
    await activate(id);
    update({ preview: null, comparison: null });
  }

  async function selection(id: string, selection: Obj) {
    if (id !== viewId) return;
    const hold = explicit?.id === id ? explicit : null;
    if (hold && (hold.focusing || !Object.keys(selection).length || echoes(hold.place, selection))) {
      // 되울림: 편집기 좌표만 받아 두고(위치 기억) 명시 대상·명령 판정은 그대로 둔다. 진행 중인 캐럿 locate 도 물린다.
      if (!Object.keys(selection).length) return;
      if (!hold.focusing) explicit = null;
      selectionRequests.set(id, (selectionRequests.get(id) || 0) + 1);
      update({ selection });
      scheduleRemember(id);
      return;
    }
    if (hold) explicit = null;
    const same = ["entry", "start", "end", "paragraph", "start_paragraph", "end_paragraph"].every((key) => selection[key] === view.selection[key]);
    const request = (selectionRequests.get(id) || 0) + 1;
    selectionRequests.set(id, request);
    update({ selection, matches: [], context: {} });
    scheduleRemember(id);
    if (!Object.keys(selection).length) return;
    await flush(id);
    const atRevision = revision(id);
    const result = await dispatch("locate", fenced(id, { selection }));
    if (id !== viewId || selectionRequests.get(id) !== request || revision(id) !== atRevision) return;
    const matches = result.matches || [];
    const commands = await commandsFor(id, result, selection);
    if (id !== viewId || selectionRequests.get(id) !== request || revision(id) !== atRevision) return;
    // Moving or resizing uses the new caret as a destination; retain its source.
    const retain = same || ["move", "duplicate", "adjust_range"].includes(view.commandType);
    update({ matches, commands, context: result.context || {}, ...(!retain ? {
      selected: matches.length === 1 && !matches[0].approximate ? { ...matches[0].location, ...matches[0] } : null,
    } : {}) });
  }

  return {
    model, viewModel: { getSnapshot: () => view, subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; } },
    snapshot, tab, update, guarded, changed, flush, flushAll, activate, open, openFile, save, close, leaveTo,
    closeState: () => invoke("close_guard_state"),
    back, select, preview, applyPreview, trialInput, keepTrialValue, runTrial, saveCase, search,
    returnScreen: () => returnScreen,
    create: async () => { const result = await dispatch("new", { media: "txt" }); revisions.set(result.session_id, result.revision); await activate(result.session_id); },
    content: (id: string) => dispatch("content", { session_id: id }),
    preflight: (id: string, revision: number, content: string) => dispatch("rhwp_roundtrip_preflight", { session_id: id, revision, content }),
    unverified: (id: string, revision: number, detail: string) => dispatch("rhwp_unverified", { session_id: id, revision, detail }),
    clipboard: () => clipboard,
    copy: async () => {
      const id = snapshot().active_id;
      await flush(id);
      const selected = view.selected;
      const location = selected?.location || selected?.occurrences?.[0] || selected || view.selection;
      clipboard = await dispatch("copy", fenced(id, { selector: { ...location, ...selected, kind: selected?.kind || "text" } }));
      update({ panel: "paste", preview: null });
    },
    paste: (withMeaning: boolean, newId: string, linkExisting: boolean) => preview({ type: "paste", clipboard_token: clipboard?.clipboard_token,
      destination: { ...view.selection, slot_id: view.context?.slot_id, new_id: newId, link_existing: linkExisting }, with_meaning: withMeaning }),
    editorGeneration: (id: string) => generations.get(id) || 0,
    mode: (id: string) => views.get(id)?.mode || "template",
    pending: (id: string) => buffers.has(id),
    selection: (id: string, range: Obj) => { void guarded(() => selection(id, range)); },
    focusSelection: async () => { if (Object.keys(view.selection).length) await editors.get(viewId)?.focus(view.selection); },
    attach(id: string, editor: AuthoringEditor) { editors.set(id, editor); void guarded(() => applyRestore(id)); return () => { editors.delete(id); }; },
    command: async (command: "undo" | "redo" | "search") => {
      await editors.get(snapshot().active_id)?.command(command);
      // 되돌린 뒤에는 다음에 되돌릴 행동을 모른다 — 이름을 지운다. 빈 patch 도 history 깊이를 다시 읽게 한다.
      update(command === "undo" ? { lastCommandLabel: "" } : {});
    },
    editorState: (id: string) => editors.get(id)?.state?.() ?? null,
    setMode(mode: string) { update({ mode }); editors.get(viewId)?.decorate(tab(viewId).analysis || {}, mode); if (viewId) scheduleRemember(viewId); },
    checkExternal: async () => { for (const item of snapshot().tabs || []) await dispatch("check_external", { session_id: item.id }); },
    reload: async () => { const id = snapshot().active_id; await flush(id); if (await deps.modal.confirm({ title: "외부 파일 다시 열기", body: "현재 문서의 미저장 변경을 버리고 외부 파일을 엽니다.", confirmLabel: "다시 열기", danger: true })) await restored(await dispatch("reload", fenced(id, { force: true }))); },
    recover: async (id: string) => { await restored(await (tab(id).id ? dispatch("recover", fenced(id)) : dispatch("recover_draft", { key: id }))); update({ recoveryPreview: null }); },
    compareRecovery: async (key: string) => update({ recoveryPreview: await dispatch("recovery_content", { key }) }),
    discardRecovery: (id: string) => tab(id).id ? dispatch("discard_recovery", { session_id: id }) : dispatch("discard_draft", { key: id }),
    compareExternal: async () => {
      const id = snapshot().active_id;
      await flush(id);
      const current = await editors.get(id)?.content();
      // HWPX 본문 차례(section_entries)는 Python 이 각 내용에서 셈한다 — 현재 작업 쪽은 flush 뒤 세션 내용의 것.
      const session = tab(id).media === "hwpx" ? await dispatch("content", { session_id: id }) : {};
      update({ comparison: { ...await dispatch("external_content", { session_id: id }), current_content: current, current_section_entries: session.section_entries }, panel: "comparison" });
    },
    // 원문 표기(F26)는 Python 이 현재 의미에서 지은 문법 표현이다 — 표면은 읽기 전용으로 보이고 복사만 돕는다.
    raw: async () => { const id = snapshot().active_id; await flush(id); update({ syntax: await dispatch("syntax", { session_id: id }), panel: "raw" }); },
    impact: async () => { const id = snapshot().active_id; await flush(id); update({ impact: await dispatch("impact", fenced(id)), panel: "impact" }); },
    applyJob: async (job_name: string) => {
      const id = snapshot().active_id;
      await flush(id);
      const result = await dispatch("prepare_apply", fenced(id, { job_name }));
      update({ jobApply: { ...result, job_name }, panel: "impact" });
    },
    confirmJob: async () => { const id = snapshot().active_id; const prepared = view.jobApply; await flush(id); await dispatch("apply_job", fenced(id, { job_name: prepared.job_name, change_token: prepared.change_token })); update({ jobApply: null }); },
    loadCase: (item: Obj) => trialInput(item.values, item.selected),
    removeCase: async (name: string) => { const id = snapshot().active_id; if (await deps.modal.confirm({ title: "시험 케이스 삭제", body: name, confirmLabel: "삭제", danger: true })) { await dispatch("case_remove", fenced(id, { name })); await persistCases(id); } },
    exportResult: async () => { const id = snapshot().active_id; await flush(id); await inputPumps.get(id); await invoke("export_authoring_result", id, revision(id)); },
    transferCases: (action: "import" | "export") => invoke("authoring_cases_file", snapshot().active_id, action),
  };
}

export type AuthoringController = ReturnType<typeof createAuthoringController>;
