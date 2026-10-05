import type { BridgeClient } from "../runtime/client.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import { errorText } from "./authoring_a11y.ts";
import { guideFeed } from "./authoring_guide.ts";

type Obj = Record<string, any>;
export type AuthoringEditor = {
  flush?(): Promise<void>;
  content(): Promise<string>;
  apply(content: string, edits: Obj[], label: string, expectedContent?: string): Promise<void>;
  focus(target: Obj): Promise<void>;
  command(command: "undo" | "redo" | "search"): Promise<void>;
  /** 의미 장식을 다시 얹는다. highlight 는 구조 트리 줄에 마우스·초점이 머문 동안의 강조 대상이다(UX-09) —
   *  `{ kind: "slot"|"option"|"field", id, slot_id?, index? }`(option 의 id 는 선택 id, slot_id 는 소속 항목,
   *  field 의 index 는 사용 위치 한 곳). 없으면 강조 없음. */
  decorate(analysis: Obj, mode: string, highlight?: Obj | null): void;
  /** 범위 고르기(두 번 누름): `false` 끔, `null` 켬(누름이 캐럿을 옮기지 않고 자리를 알린다), 자리는 그 시작에서 포인터
   *  아래까지의 고무줄 범위를 칠한다. 누른 자리는 마운트할 때 건 `pickClick` 으로 온다. */
  rangePick?(state: PickPoint | null | false): void | Promise<void>;
  /** 편집면 배율 방식(IDE-06 P-13) — 폭 맞춤이면 편집기 스스로 쪽 폭을 맞추고, 고정이면 편집기는 100%이고 셸이 키운다.
   *  없으면(TXT) 셸 배율만 쓴다. */
  zoom?(mode: "fit" | "fixed"): Promise<void>;
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
/** 문서 명령(#1078) → 표시 이름. 고른 대상이 아니라 문서 전체의 명령이라 판정은 탭 투영(`document_commands`)이 싣고,
 *  명시 표면인 명령 팔레트에만 선다(문맥 메뉴·속성 명령 선택은 고른 대상의 명령만 싣는다). */
export const DOCUMENT_COMMANDS: [string, string][] = [["revert_template", "원본 템플릿으로 되돌리기"]];
/** 새 문구(사용자 승인 대기)는 이 한 곳에 모은다 — 저작 작업대 화면이 쓴다: 구조 트리 연속 묶음(항목 밖 사용 위치)과 두 번 눌러 범위 고르기. */
export const AUTHORING_COPY = {
  looseUses: "항목 밖 필드",
  rangePick: "범위 고르기",
  rangePickStart: "시작 위치를 누르세요.",
  rangePickEnd: "끝 위치를 누르세요.",
  rangePickCancel: "범위 고르기를 취소했습니다.",
} as const;
/** 확대 값: 「폭 맞춤」(HWPX 기본) 또는 고정 배율(%). */
export type Zoom = "fit" | number;
export const DEFAULT_ZOOM: Zoom = "fit";

/** 미리보기 동안 편집면이 칠할 대상(IDE-06 P-16). 범위 명령은 Python 이 준 실제 포함 범위(`included_location`)를
 *  이름표 없는 합성 표지로(`marker` 는 그 표지의 종류), 필드 명령은 그 필드의 사용 위치 — 필드 전체·전체 이름 변경은
 *  모든 사용 위치, 한 곳의 명령은 그 자리(index)다. 미리보기가 없거나 칠할 자리를 모르면 null. */
export function previewHighlight(preview: Obj | null | undefined, command: Obj | null | undefined, analysis: Obj = {}): Obj | null {
  if (!preview || !command) return null;
  const location = preview.included_location;
  if (location && typeof location === "object")
    return { kind: "range", location, marker: command.type === "create_option" || (command.type !== "create_slot" && command.kind === "option") ? "option" : "slot" };
  if (!["rename_field", "relink_field", "unset_field"].includes(command.type)) return null;
  const name = command.old_name || command.name;
  if (!name) return null;
  if (command.type === "rename_field" || Array.isArray(command.occurrences)) return { kind: "field", id: name };
  const occurrences: Obj[] = (analysis.fields || []).find((field: Obj) => field.name === name)?.occurrences || [];
  const at = occurrences.findIndex((occurrence) => command.occurrence != null
    ? occurrence.entry === command.entry && occurrence.occurrence === command.occurrence
    : occurrence.start === command.start);
  return at < 0 ? null : { kind: "field", id: name, index: at + 1 };
}

/** 두 번 눌러 범위 고르기의 상태 — 시작 위치를 기다리거나(start), 시작을 받아 끝 위치를 기다린다(end). */
export type RangePick = { phase: "start" } | { phase: "end"; start: PickPoint };
/** 고른 한 자리 — 편집기가 누름 한 번에 알린 본문 문단과 그 안의 글자. HWPX 는 셀 안을 누르면 그 표의 닻 본문
 *  문단이다(`cell`). TXT 는 구역·문단 없이 글자 위치(UTF-16)만 쓴다(`entry` "", `paragraph` 0). */
export type PickPoint = { entry: string; paragraph: number; offset: number; cell: boolean };

/** 범위 고르기의 한 걸음(순수) — 누름 한 번의 자리로 다음 상태와(끝을 받았으면) 편집기에 세울 범위를 낸다.
 *  점은 누름에서만 온다(캐럿 이동·키는 점이 아니다). 다른 구역의 끝은 새 시작이다. 셀 안 자리는 표의 닻 문단 전체로
 *  접힌다 — 시작이면 문단 머리, 끝이면 문단 끝(`end` 생략 = 문단 끝). */
export function rangePickStep(pick: RangePick | null, point: PickPoint): { pick: RangePick | null; commit?: Obj } {
  if (!pick) return { pick };
  if (pick.phase === "start" || pick.start.entry !== point.entry) return { pick: { phase: "end", start: point } };
  const a = pick.start;
  const [first, second] = a.paragraph < point.paragraph || (a.paragraph === point.paragraph && a.offset <= point.offset) ? [a, point] : [point, a];
  const whole = first.paragraph === second.paragraph && (first.cell || second.cell);
  return { pick: null, commit: { entry: first.entry, paragraph: first.paragraph, start_paragraph: first.paragraph, end_paragraph: second.paragraph,
    start: whole || first.cell ? 0 : first.offset, ...(whole || second.cell ? {} : { end: second.offset }) } };
}

type Deps = {
  client: BridgeClient;
  runtime: ScreenRuntime;
  modal: { confirm(spec: Obj): Promise<boolean>; choose(spec: Obj): Promise<string | null>; prompt(spec: Obj): Promise<string | null> };
  navigation: { go(screen: string, options?: Obj): void; refresh(screen: string): Promise<unknown> };
};

/** 위치 줄 메시지(IDE-05)의 내용 — locate 가 판정한 `problems_here`(문제 목록 순번) 가운데 첫 문제의 심각도와 Python 문장.
 *  겹침은 Python 이 판정했다. 여기서는 순번으로 문제를 찾을 뿐이다. `source: "problem"` 은 캐럿이 옮길 때 이 메모를
 *  다음 판정까지 남겨 둘지(깜박임 없이) 가르는 표지다. */
export function problemNote(problems: Obj[] | undefined, here: unknown): { message: string; severity?: "error" | "warning"; source: "problem" } | null {
  if (!Array.isArray(here)) return null;
  for (const index of here) {
    const problem = typeof index === "number" ? problems?.[index] : undefined;
    if (!problem?.message) continue;
    const severity = problem.severity === "error" || problem.severity === "warning" ? problem.severity : undefined;
    return { message: String(problem.message), ...(severity ? { severity } : {}), source: "problem" };
  }
  return null;
}

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
  const initialView = (): Obj => ({ error: "", busy: false, trialBusy: false, saveFailed: false, lastCommandLabel: "", notice: "",
    mode: "template", panel: "", selection: {}, selected: null, commands: [], contextMenu: null, palette: 0, refusal: null, syntax: null,
    command: null, preview: null, trial: false, autoTrial: true, query: "", hits: [], searchSummaries: [], values: {}, selectedOptions: {}, zoom: DEFAULT_ZOOM });
  let view = initialView();
  let viewId = "";
  let trialTimer: ReturnType<typeof setTimeout> | undefined;
  let returnScreen = "editor";
  let clipboard: Obj | null = null;
  let previewRequest = 0;
  let searchRequest = 0;
  let applying = false;
  // 오류 띠(§10·UX-04): 새 오류마다 차례 번호를 올린다. 같은 종류의 작업이 성공해야(또는 닫기로) 지워진다 —
  // 다음 키 입력·캐럿 이동이 읽히기 전의 경보를 지우지 않는다.
  let errorSeq = 0;
  const snapshot = (): Obj => model.getSnapshot() || { tabs: [], active_id: "" };
  const tab = (id = snapshot().active_id): Obj => (snapshot().tabs || []).find((item: Obj) => item.id === id) || {};
  // 구조 트리 줄 hover 의 강조(UX-09) — 미리보기 강조(IDE-06 P-16)를 잠시 덮고, 떠나면(null) 미리보기 강조로 돌아온다.
  let hovered: Obj | null = null;
  /** 편집면 강조 — hover 가 있으면 그것, 없으면 서 있는 미리보기의 대상. 다른 탭의 편집기는 강조가 없다. */
  const currentHighlight = (id = viewId): Obj | null => id !== viewId ? null
    : hovered || previewHighlight(view.preview, view.command, tab(id).analysis || {});
  const redecorate = () => { if (viewId) editors.get(viewId)?.decorate(tab(viewId).analysis || {}, view.mode || "template", currentHighlight()); };
  const update = (patch: Obj) => {
    const before = view;
    view = { ...view, ...patch };
    if (viewId) views.set(viewId, view);
    // 미리보기가 서거나 걷히면 편집면 강조도 따라간다 — hover 중이면 hover 가 그대로 앞선다.
    if (viewId && (view.preview !== before.preview || view.command !== before.command) && !hovered) redecorate();
    listeners.forEach((listener) => listener());
  };
  // verdict: Python 이 판정을 세션 상태로 이미 투영한 호출(시험 입력 검증 등) — ok:false 는 오류 띠가 아니라 그 표면이 보인다.
  const dispatch = async (action: string, payload: Obj = {}, verdict = false): Promise<Obj> => {
    const call = deps.client.dispatch as unknown as (screen: string, name: string, body: Obj) => ReturnType<BridgeClient["dispatch"]>;
    const result = expectHostValue(await call("authoring", action, payload), `authoring/${action}`) as Obj;
    // 거절(refusal)은 오류가 아니라 판정이다 — 호출자가 사유와 대안을 그린다(U07·AC08·AC10).
    if (result?.ok === false && !result.refusal && !verdict) throw new Error(result.message || result.detail || result.reason);
    return result || {};
  };
  const invoke = async (method: Parameters<BridgeClient["invoke"]>[0], ...args: unknown[]): Promise<Obj | null> =>
    expectHostValue(await deps.client.invoke(method, ...args), method) as Obj | null;
  const revision = (id: string): number => revisions.get(id) ?? tab(id).revision;
  const fenced = (id: string, payload: Obj = {}): Obj => ({ session_id: id, revision: revision(id), ...payload });

  /** 오류 한 건을 띠에 세운다. kind 는 그 오류를 지울 수 있는 작업의 종류다. */
  function fail(error: unknown, kind = "action") {
    update({ error: errorText(error), errorKind: kind, errorSeq: ++errorSeq });
  }

  /** 작업 하나를 오류 띠로 감싼다. 시작할 때 띠를 지우지 않는다 — 이 작업이 성공했고, 그 사이 새 오류가 서지 않았고,
   *  띠의 오류가 같은 종류일 때만 지운다(같은 종류의 재시도 성공). 나머지는 「닫기」로만 걷힌다. */
  async function guarded(work: () => unknown | Promise<unknown>, kind = "action") {
    const seen = errorSeq;
    try {
      await work();
      if (view.error && view.errorKind === kind && view.errorSeq === seen) update({ error: "", errorKind: "" });
    } catch (error) { fail(error, kind); }
  }

  /** live region 한 줄(UX-04) — 화면이 전이를 판정해 부른다. 같은 문장도 차례 번호로 다시 읽힌다. */
  function announce(text: string) {
    if (text) update({ live: { text, seq: (view.live?.seq || 0) + 1 } });
  }

  /** 위치 줄 메모(IDE-01) — 지금 자리에 대한 제자리 사유 한 줄. 세울 때 단일 live region 이 한 번 읽고, 다음 캐럿 이동과
   *  Escape 에서 걷힌다. 문장·심각도는 호출자가 넘긴 Python 판정 그대로다(F2 불가 사유가 첫 호출자다). */
  function note(message: string, severity?: "error" | "warning" | "info") {
    if (!message) return;
    update({ selectionNote: { message, ...(severity ? { severity } : {}) } });
    announce(message);
  }

  /** 지금 자리의 문제(IDE-05)를 위치 줄에 세운다 — 같은 문제가 그대로면 다시 읽지 않는다(캐럿이 한 자리 안에서
   *  움직일 때마다 읽지 않는다). 문제가 없으면 문제 메모만 걷고 다른 사유(F2 등)는 그대로 둔다. */
  function problemHere(id: string, here: unknown) {
    const next = problemNote(tab(id).problems, here);
    const prior = view.selectionNote;
    if (prior?.source === "rangePick") return;
    if (!next) { if (prior?.source === "problem") update({ selectionNote: null }); return; }
    if (prior?.source === "problem" && prior.message === next.message && prior.severity === next.severity) return;
    update({ selectionNote: next });
    announce(next.message);
  }

  function changed(id: string, content: string): void {
    buffers.set(id, content);
    // 고르던 자리는 편집 전 좌표다 — 편집이 오면 범위 고르기를 조용히 접는다.
    if (id === viewId) { if (view.rangePick) endRangePick(id); update({ preview: null, refusal: null, notice: "" }); }
    void guarded(async () => { await drain(id); scheduleTrial(id); }, "edit");
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
    editor.decorate(tab(id).analysis || {}, views.get(id)?.mode || "template", currentHighlight(id));
    // 좌표는 Python 이 이 bytes 에 대해 유효하다고 판정한 것이다. 그래도 편집기가 거절하면 알리되 문서 열기는 막지 않는다.
    if (pending.selection) await editor.focus(pending.selection).catch((error) => fail(error, "restore"));
  }

  function scheduleRemember(id: string) {
    clearTimeout(rememberTimers.get(id));
    rememberTimers.set(id, setTimeout(() => { void guarded(() => remember(id), "remember"); }, 400));
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

  // 이 화면이 문서를 열고 닫고 옮기는 중이다(그 동작이 끝에 activate 한다) — 그사이 도착한 push 의 활성 문서는 따라가지 않는다.
  let steering = 0;
  function steered<T>(work: () => Promise<T>): Promise<T> {
    steering += 1;
    return work().finally(() => { steering -= 1; });
  }

  /** Python 이 스스로 활성으로 세운 문서(튜토리얼이 연 연습 문서, 작업 공간 전환, 연습 종료 뒤 복원)를 이 화면의 뷰로 받는다.
   *  편집기는 스냅샷의 활성 탭을 그리는데 뷰가 그 탭이 아니면 편집기의 선택 보고가 버려진다(#1146) — 선택해도 판정이 없다. */
  function followActive() {
    const active = snapshot().active_id;
    if (active && active !== viewId && steering === 0) void guarded(() => activate(active), "editor");
  }
  model.subscribe(followActive);

  function activate(id: string): Promise<void> {
    return steered(() => activateNow(id));
  }

  async function activateNow(id: string) {
    clearTimeout(trialTimer);
    if (snapshot().active_id) { await flush(snapshot().active_id); await inputPumps.get(snapshot().active_id); }
    const activated = await dispatch("activate", { session_id: id });
    const current = tab(id);
    viewId = id;
    hovered = null;
    const known = views.get(id);
    const restore = activated.restore ?? current.restore;
    // 범위 고르기는 그 문서의 편집면에서만 뜻이 있다 — 문서를 옮기면 떠나는 편집면의 고르기를 끄고, 새 뷰는 접혀 있다.
    if (viewId && view.rangePick) void Promise.resolve(editors.get(viewId)?.rangePick?.(false)).catch(() => undefined);
    view = { ...(known || restoredView(restore)), rangePick: null };
    if (!known && (restore?.mode || restore?.selection)) pendingRestore.set(id, { selection: restore.selection || null });
    update({
      values: { ...(current.values || {}) }, selectedOptions: { ...(current.selected || {}) } });
    await applyRestore(id);
  }

  function open(path?: string): Promise<void> {
    return steered(async () => {
      await deps.runtime.loadInitial("authoring");
      returnScreen = "editor";
      if (path) {
        const result = await invoke("open_authoring_document", path, true);
        if (!result) return;
        revisions.set(result.session_id, result.revision);
        await activate(result.session_id);
      }
      deps.navigation.go("authoring", { force: true });
    });
  }

  function openFile(): Promise<void> {
    return steered(openFileNow);
  }

  async function openFileNow() {
    const result = await invoke("open_authoring_document", "", false);
    if (!result) return;
    revisions.set(result.session_id, result.revision);
    await activate(result.session_id);
    // 여는 응답의 알림 칸 — Python 이 준 문장만, 다음 편집에서 사라진다. 처음 여는 일반 문서의 첫 안내는 퇴역했다(NG-01):
    // 필드 만들기 안내는 구조 패널의 빈 상태가 늘 보이는 자리에서 맡는다.
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
    if (result?.external_changed || result?.conflict) { update({ panel: "external", saveFailed: true }); fail(result.message || "저장할 파일이 변경되었거나 이미 존재합니다. 다른 이름으로 저장하세요.", "save"); return false; }
    if (!result || result.cancelled) return false;
    update({ saveFailed: false, notice: result.notice || "", panel: view.panel === "external" ? "" : view.panel, ...(view.errorKind === "save" ? { error: "", errorKind: "" } : {}) });
    await deps.navigation.refresh("tpl");
    return true;
  }

  function close(id: string): Promise<boolean> {
    return steered(() => closeNow(id));
  }

  async function closeNow(id: string): Promise<boolean> {
    await flush(id);
    await inputPumps.get(id);
    // 남은 작업 위치를 먼저 보낸다. 실패는 알리되 문서 닫기를 막지 않는다(잃는 것은 위치 기록뿐이다).
    if (rememberTimers.has(id)) await remember(id).catch((error) => fail(error, "remember"));
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

  /** 대상 하나를 고른다 — 편집면 강조·위치 줄·명령 판정이 그 대상으로 옮긴다. 기본은 속성 패널을 그 대상으로 연다.
   *  `keepDock`(NG-06)은 독에서 시작한 선택(문제·검색·결과 시험 행)의 길이다: `view.panel` 을 건드리지 않아 펼친 독 탭이
   *  그대로 남고 속성 패널은 열리지 않는다. 속성은 F2·문맥 메뉴·구조 목록 줄·만들기 명령으로 연다. */
  async function select(target: Obj, options: { keepDock?: boolean } = {}) {
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
      const prior = view.selectionNote?.source === "problem" ? view.selectionNote : null;
      update({ selected: { ...location, ...(located?.selected || target) }, selection: location, matches: located?.matches || [], ...(options.keepDock ? {} : { panel: "properties", formEntry: "" }), refusal: null, preview: null, command: null, selectionNote: prior,
        context: located?.context || view.context || {}, commands: await commandsFor(id, located, location),
        commandType: target.kind === "field" ? "rename_field" : target.kind === "option" ? "rename_option" : target.kind === "slot" ? "rename_slot" : undefined });
      problemHere(id, located?.problems_here);
      if (location.start != null || location.source_start != null || location.paragraph != null || location.start_paragraph != null)
        await editors.get(id)?.focus(place);
    } catch (error) {
      if (explicit === hold) explicit = null;
      throw error;
    } finally { hold.focusing = false; }
  }

  /** 적용한 이름 변경이 가리키는 새 대상(#1069)을 지금 대상으로 받는다 — 패널·초점·편집기 선택은 그대로 두고, 속성 카드·
   *  위치 줄·폼 초기값·명령 판정만 Python 이 되짚은 대상으로 바꾼다(표면은 받은 대상을 쓸 뿐이다). */
  async function adopt(target: Obj) {
    const id = snapshot().active_id;
    if (target.session_id && target.session_id !== id) return;
    const location = target.location || target.occurrences?.[0] || target;
    const identity = semanticTarget(target);
    const located = await dispatch("locate", { session_id: id, revision: target.source_revision, selection: location, ...(identity ? { target: identity } : {}) });
    if (id !== viewId) return;
    const commands = await commandsFor(id, located, location);
    if (id !== viewId) return;
    update({ selected: { ...location, ...(located.selected || target) }, matches: located.matches || [], context: located.context || view.context || {}, commands });
  }

  async function back() {
    const previous = navigationHistory.pop();
    if (!previous) return;
    await activate(previous.id);
    const located = await dispatch("locate", { session_id: previous.id, revision: previous.revision, selection: previous.target });
    update({ selection: previous.target, selected: null, context: located.context || {}, commands: await commandsFor(previous.id, located, previous.target) });
    await editors.get(previous.id)?.focus(previous.target);
  }

  /** 명령 하나를 미리 본다. 돌려주는 값이 준비된 미리보기다(거절이면 refusal 을 실은 결과, 늦었으면 null).
   *  확인 등급(P-01)이 `none` 이면 미리보기 구획을 그리지 않는다 — 호출자가 그 값으로 곧바로 적용한다(번쩍임 없음). */
  async function preview(command: Obj): Promise<Obj | null> {
    const id = snapshot().active_id;
    const request = ++previewRequest;
    await flush(id);
    const editorContent = await editors.get(id)?.content();
    const atRevision = revision(id);
    const result = await previewCommand(id, atRevision, command);
    if (id !== viewId || request !== previewRequest || atRevision !== revision(id)) return null;
    if (result.refusal) { update({ command, preview: null, refusal: result.refusal }); return result; }
    const prepared = { ...result, session_id: id, revision: atRevision, editorContent, command };
    update({ command, preview: result.confirm === "none" ? null : prepared, refusal: null });
    return prepared;
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

  /** 준비된 미리보기를 적용한다 — 인자가 없으면 보이는 미리보기다. 돌려주는 값은 되돌릴 이름과, 만들기 명령이면
   *  Python 이 짚은 만든 대상(created, NG-14)이다. 확정 직전 revision 재검사는 등급과 무관하게 늘 돈다. */
  async function applyPreview(given?: Obj): Promise<{ label: string; created: Obj | null; renamed: Obj | null } | undefined> {
    if (applying) return;
    const prepared = given || view.preview;
    const command = prepared?.command || view.command;
    if (!prepared || !command) return;
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
      const label = prepared.label || result.label || [...COMMANDS, ...DOCUMENT_COMMANDS].find(([type]) => type === command.type)?.[1] || command.type;
      if (id === viewId) update({ command: null, preview: null, lastCommandLabel: label, commandNote: { seq: (view.commandNote?.seq || 0) + 1, kind: "apply", label } });
      scheduleTrial(id);
      // 만든 대상은 적용 뒤의 revision 에서 짚는다 — 호출자가 그 자리를 고를 수 있게(선택·캐럿·이름표).
      const at = { session_id: id, source_revision: revision(id) };
      return { label, created: result.created ? { ...result.created, ...at } : null, renamed: result.renamed ? { ...result.renamed, ...at } : null };
    } finally { applying = false; }
  }

  /** 문서 명령 하나를 실행한다(#1078) — 속성 패널 없이 미리보기 → (확인 등급이 `none` 이 아니면) 파괴 확인 → 적용이다.
   *  확인 창은 제목·확인 단추가 명령 이름, 본문이 Python 이 지은 손실 집합(`message`)이고 기본 초점은 취소다(`button` 등급:
   *  위험 단추 누름만이 적용이다). 적용은 다른 명령과 같은 편집 사슬(applyPreview → 편집기 한 번의 실행 취소 단위)이다.
   *  돌려주는 값은 적용했는가다 — 취소했거나 그사이 문서·탭이 바뀌었으면 false. */
  async function documentCommand(type: string): Promise<boolean> {
    const id = snapshot().active_id;
    await flush(id);
    const editorContent = await editors.get(id)?.content();
    const atRevision = revision(id);
    const command = { type };
    const result = await previewCommand(id, atRevision, command);
    if (result.refusal) throw new Error(result.refusal.message);
    if (id !== viewId || atRevision !== revision(id)) return false;
    const name = DOCUMENT_COMMANDS.find(([value]) => value === type)?.[1] || String(result.label || type);
    if (result.confirm !== "none" && !(await deps.modal.confirm({ title: name, body: String(result.message || ""), confirmLabel: name, danger: true })))
      return false;
    return !!(await applyPreview({ ...result, session_id: id, revision: atRevision, editorContent, command }));
  }

  function scheduleTrial(id: string) {
    clearTimeout(trialTimer);
    const state = views.get(id);
    if (id === viewId && state?.autoTrial && state?.trial) trialTimer = setTimeout(() => { void guarded(() => runTrial(id), "trial"); }, 350);
  }

  /** U03: 고른 문구를 시험값으로 보관한다 — 이미 값이 있으면 덮어쓰지 않고 유지/교체를 묻는다. */
  async function keepTrialValue(name: string, captured: string): Promise<boolean> {
    const values: Obj = { ...(view.values || {}) };
    if (name in values) {
      if (values[name] === captured) return false;
      const answer = await deps.modal.choose({ title: "시험값 보관", body: `‘${name}’ 필드에 시험값이 이미 있습니다.`,
        choices: [{ value: "keep", label: "기존 값 유지" }, { value: "replace", label: "고른 문구로 교체" }] });
      if (answer !== "replace") return false;
    }
    await trialInput({ ...values, [name]: captured }, view.selectedOptions || {}, name);
    return true;
  }

  /** 시험 입력 전이. anchor 는 값을 바꾼 필드 이름이다 — 다음 결과가 그 필드의 출력 자리로 옮겨 간다(IDE-04 닻).
   *  케이스 불러오기·항목 선택처럼 한 필드를 고치지 않는 전이는 닻을 그대로 둔다. */
  async function trialInput(values: Obj, selectedOptions: Obj, anchor?: string) {
    const id = snapshot().active_id;
    update({ values, selectedOptions, ...(anchor ? { trialAnchor: anchor } : {}) });
    const previous = inputPumps.get(id) || Promise.resolve();
    const pump = previous.catch(() => {}).then(async () => {
      await flush(id);
      await dispatch("trial_input", fenced(id, { values, selected: selectedOptions }));
    });
    inputPumps.set(id, pump);
    try { await pump; scheduleTrial(id); }
    finally { if (inputPumps.get(id) === pump) inputPumps.delete(id); }
  }

  /** 「필드 이름 사용」(IDE-01) — 손대지 않은 필드만 그 이름으로 채운다. 채울 대상은 Python 이 정하고(trial_fill_names),
   *  앞선 입력 전이 뒤에 차례로 선다. 돌아온 값이 곧 시험 입력이고 자동 갱신이 켜져 있으면 다시 시험한다. */
  async function fillTrialNames() {
    const id = snapshot().active_id;
    const previous = inputPumps.get(id) || Promise.resolve();
    const pump = previous.catch(() => {}).then(async () => {
      await flush(id);
      const result = await dispatch("trial_fill_names", fenced(id));
      if (id === viewId) update({ values: { ...(result.values || {}) }, selectedOptions: { ...(result.selected || {}) } });
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
    // 시험 입력 검증 실패(예: 시험 선택 미지정)는 시험 패널의 상태 칩·문장(trial_state_message)으로만 선다(UX-10 R3).
    // 오류 띠는 호출 자체의 실패만 — 그래서 성공한 이 호출이 이전의 시험 오류 띠도 걷는다.
    try { await dispatch("trial", fenced(id), true); }
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

  /** 고른 문구와 같은 다른 평문 자리(IDE-07 P-07) — 원시 자리·문맥·판정·위치 줄은 Python 이 짓는다. 돌려주는 값은
   *  찾은 revision 과 자리 목록이다. 탭·revision 이 그사이 바뀌었으면(늦은 응답) null — 표면은 옛 좌표를 보이지 않는다. */
  async function sameText(selection: Obj): Promise<{ revision: number; hits: Obj[]; summary: string | null } | null> {
    const id = viewId;
    await flush(id);
    const atRevision = revision(id);
    const result = await dispatch("same_text", fenced(id, { selection: coordinates(selection) }));
    if (id !== viewId || atRevision !== revision(id)) return null;
    return { revision: atRevision, hits: result.hits || [], summary: result.summary ?? null };
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

  /** 범위 고르기(두 번 누름)를 켜고 끈다. 켜면 시작 자리를 기다린다. 끄는 길은 이 단추·Escape·편집·다른 문서다. */
  function toggleRangePick() {
    if (view.rangePick) { cancelRangePick(); return; }
    const editor = editors.get(viewId);
    if (!editor?.rangePick) return;
    update({ rangePick: { phase: "start" } });
    void guarded(() => editor.rangePick!(null), "editor");
    pickNote(AUTHORING_COPY.rangePickStart);
  }
  /** 고르기의 안내 메모 — 여느 위치 줄 메모와 달리 캐럿 이동·문제 메모에 걷히지 않고 고르기가 끝날 때 걷힌다. */
  function pickNote(message: string) {
    update({ selectionNote: { message, severity: "info", source: "rangePick" } });
    announce(message);
  }
  /** 고르기를 조용히 접는다 — 편집기의 누름 가로채기·고무줄 범위를 끄고 메모를 걷는다(취소 알림은 부른 쪽이 정한다). */
  function endRangePick(id = viewId) {
    update({ rangePick: null, ...(view.selectionNote?.source === "rangePick" ? { selectionNote: null } : {}) });
    void guarded(async () => { await editors.get(id)?.rangePick?.(false); }, "editor");
  }
  function cancelRangePick() {
    if (!view.rangePick) return;
    endRangePick();
    announce(AUTHORING_COPY.rangePickCancel);
  }
  /** 편집기가 알린 누름 한 번(범위 고르기 중에만 온다). 시작이면 고무줄 범위를 켜고, 끝이면 두 자리 사이를 편집기 선택으로
   *  세운다 — 그 선택의 보고가 여느 선택처럼 명령 판정·선택 옆 막대로 간다. */
  async function pickClick(id: string, point: PickPoint) {
    if (id !== viewId || !view.rangePick) return;
    const step = rangePickStep(view.rangePick, point);
    const editor = editors.get(id);
    if (step.commit) {
      endRangePick(id);
      await editor?.focus(step.commit);
      return;
    }
    if (step.pick?.phase === "end") {
      update({ rangePick: step.pick });
      await editor?.rangePick?.(step.pick.start);
      pickNote(AUTHORING_COPY.rangePickEnd);
    }
  }

  async function selection(id: string, selection: Obj) {
    if (id !== viewId) return;
    // 고르기 중 키로 범위를 골랐으면(Shift+화살표) 그 범위가 선다 — 고르기는 접힌다. 캐럿 이동은 점이 아니다.
    if (view.rangePick && Object.keys(selection).length && (selection.start !== selection.end
        || (selection.start_paragraph ?? selection.paragraph) !== (selection.end_paragraph ?? selection.start_paragraph ?? selection.paragraph))) endRangePick(id);
    await caretSelection(id, selection);
  }

  async function caretSelection(id: string, selection: Obj) {
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
    // 캐럿이 옮겨 가면 위치 줄 메모(F2 불가 사유 등)는 걷힌다(IDE-01) — 같은 자리의 재보고는 이동이 아니다.
    // 문제 메모(IDE-05)는 다음 판정이 올 때까지 남는다 — 같은 문제 안의 이동에서 깜박이지 않고, 판정이 걷거나 바꾼다.
    const keepNote = same || view.selectionNote?.source === "rangePick"
      || (view.selectionNote?.source === "problem" && Object.keys(selection).length > 0);
    update({ selection, matches: [], context: {}, ...(keepNote ? {} : { selectionNote: null }) });
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
    // commandsSelection: 이 판정이 선 편집기 선택(같은 객체) — 선택 옆 막대(IDE-08)는 지금 선택의 판정이 도착했을 때만 선다.
    update({ matches, commands, commandsSelection: selection, context: result.context || {}, ...(!retain ? {
      selected: matches.length === 1 && !matches[0].approximate ? { ...matches[0].location, ...matches[0] } : null,
    } : {}) });
    problemHere(id, result.problems_here);
  }

  return {
    model, viewModel: { getSnapshot: () => view, subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; } },
    snapshot, tab, update, guarded, fail, announce, note, changed, flush, flushAll, activate, open, openFile, save, close, leaveTo,
    closeState: () => invoke("close_guard_state"),
    back, select, adopt, preview, applyPreview, documentCommand, trialInput, fillTrialNames, keepTrialValue, runTrial, saveCase, search, sameText,
    /** 활성 탭(또는 그 탭)의 지금 revision — 표면이 제 목록이 옛 문서의 것인지 비교할 뿐이다(판정 아님). */
    revisionOf: (id = snapshot().active_id) => revision(id),
    returnScreen: () => returnScreen,
    create: () => steered(async () => { const result = await dispatch("new", { media: "txt" }); revisions.set(result.session_id, result.revision); await activate(result.session_id); }),
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
    /** 그 탭의 편집면 강조(hover 또는 미리보기 대상) — 편집기가 장식을 다시 보낼 때 함께 싣는다. */
    highlightOf: (id: string) => currentHighlight(id),
    /** 그 탭의 확대 값(IDE-06 P-13) — 뷰가 없으면(마운트가 활성화보다 빠르면) 기본 「폭 맞춤」이다. */
    zoom: (id: string): Zoom => views.get(id)?.zoom ?? DEFAULT_ZOOM,
    /** 확대를 고른다. 폭 맞춤 ↔ 고정 배율이 바뀔 때만 편집기에 알린다(고정 배율 사이는 셸 배율만 바뀐다). */
    setZoom(zoom: Zoom) {
      const before = view.zoom;
      update({ zoom });
      if ((before === "fit") !== (zoom === "fit"))
        void guarded(async () => { await editors.get(viewId)?.zoom?.(zoom === "fit" ? "fit" : "fixed"); }, "editor");
    },
    pending: (id: string) => buffers.has(id),
    selection: (id: string, range: Obj) => { void guarded(() => selection(id, range), "locate"); },
    toggleRangePick, cancelRangePick,
    pickClick: (id: string, point: PickPoint) => { void guarded(() => pickClick(id, point), "locate"); },
    /** 오류 띠의 「닫기」 — 사용자가 읽고 걷는다. */
    dismissError: () => update({ error: "", errorKind: "" }),
    /** 선택 자리로 초점을 돌린다(§10 Escape). 돌릴 선택·편집기가 없으면 false — 화면이 다음 후보로 간다. */
    focusSelection: async (): Promise<boolean> => {
      const editor = editors.get(viewId);
      if (!editor || !Object.keys(view.selection).length) return false;
      await editor.focus(view.selection);
      return true;
    },
    attach(id: string, editor: AuthoringEditor) { editors.set(id, editor); void guarded(() => applyRestore(id), "restore"); return () => { editors.delete(id); }; },
    command: async (command: "undo" | "redo" | "search") => {
      await editors.get(snapshot().active_id)?.command(command);
      // 되돌린 뒤에는 다음에 되돌릴 행동을 모른다 — 이름을 지운다. 빈 patch 도 history 깊이를 다시 읽게 한다.
      // 실행 취소·다시 실행은 live region 이 읽을 표지(commandNote)를 남긴다 — 되돌린 명령의 이름과 함께.
      const note = command === "search" ? {} : { commandNote: { seq: (view.commandNote?.seq || 0) + 1, kind: command, label: command === "undo" ? view.lastCommandLabel : "" } };
      update(command === "undo" ? { lastCommandLabel: "", ...note } : note);
    },
    editorState: (id: string) => editors.get(id)?.state?.() ?? null,
    setMode(mode: string) { update({ mode }); redecorate(); if (viewId) scheduleRemember(viewId); },
    /** 구조 트리 줄이 가리키는 범위를 편집면에서 강조한다(UX-09) — null 이면 걷는다. 선택·초점은 옮기지 않는다.
     *  미리보기가 서 있으면 걷은 자리에 미리보기 대상의 강조가 돌아온다(IDE-06 P-16). */
    highlight(target: Obj | null) { hovered = target; redecorate(); },
    // 튜토리얼 범위 단계가 고르라고 한 범위(#1136) — `guide`·`guideOf`. 바뀐 탭의 편집기에만 장식을 다시 보낸다.
    ...guideFeed((id) => editors.get(id)?.decorate(tab(id).analysis || {}, views.get(id)?.mode || "template", currentHighlight(id))),
    checkExternal: async () => { for (const item of snapshot().tabs || []) await dispatch("check_external", { session_id: item.id }); },
    reload: async () => { const id = snapshot().active_id; await flush(id); if (await deps.modal.confirm({ title: "외부 파일 다시 열기", body: "현재 문서의 미저장 변경을 버리고 외부 파일을 엽니다.", confirmLabel: "다시 열기", danger: true })) await restored(await dispatch("reload", fenced(id, { force: true }))); },
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
