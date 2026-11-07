import type { BridgeClient } from "../runtime/client.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { errorText } from "./authoring_a11y.ts";
import { guideFeed } from "./authoring_guide.ts";
import { authoringHost } from "./authoring_host.ts";
import { problemNote } from "./authoring_problem_note.ts";
import { createProposal } from "./authoring_proposal.ts";
import { createLifecycleController } from "./authoring_controller_lifecycle.ts";
import { createApplyController } from "./authoring_controller_apply.ts";
import { createSelectionController } from "./authoring_controller_selection.ts";
import { createTrialController } from "./authoring_controller_trial.ts";

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
  /** 그 자리로 편집면을 옮긴다(구조 패널의 제안 줄, #1156) — HWPX 는 캐럿·초점을 두고 뷰만, TXT 는 캐럿을 자리 머리에 둔다. */
  scrollTo?(target: Obj): Promise<boolean>;
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
  /** 「데이터로 필드 찾기」(#1156)가 데이터가 없을 때 이끄는 기존 데이터 선택 창과, 만든 뒤의 되돌리기 알림. 없으면 그 길만 선다. */
  dataPicker?: { open(options: Obj): Promise<string | null> };
  undo?: { show(message: string, undo: () => unknown, label?: string): void };
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
  const initialView = (): Obj => ({ error: "", busy: false, trialBusy: false, saveFailed: false, lastCommandLabel: "", notice: "",
    mode: "template", panel: "", selection: {}, selected: null, commands: [], contextMenu: null, palette: 0, refusal: null, syntax: null,
    command: null, preview: null, trial: false, autoTrial: true, query: "", hits: [], searchSummaries: [], values: {}, selectedOptions: {}, zoom: DEFAULT_ZOOM });
  let view = initialView();
  let viewId = "";
  let trialTimer: ReturnType<typeof setTimeout> | undefined;
  let returnScreen = "editor";
  let clipboard: Obj | null = null;
  let previewRequest = 0, searchRequest = 0, applying = false;
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
  // Python 왕복 두 길 — Python 이 스스로 세운 활성 문서를 뷰로 따라가기(#1146)도 그 왕복의 진행을 보고 진다.
  const { dispatch, invoke } = authoringHost(deps.client, { activeId: () => snapshot().active_id || "", viewId: () => viewId,
    activate: (id) => activate(id), fail: (error) => fail(error, "editor"), subscribe: (listener) => model.subscribe(listener) });
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
    void guarded(async () => { await drain(id); trialCtl.scheduleTrial(id); }, "edit");
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

  /* 문서 열기/활성화/저장/닫기/복원(수명주기), 대상 고르기/캐럿 보고/범위 고르기(선택),
     명령 미리보기/적용(apply)은 각각 authoring_controller_lifecycle.ts·
     authoring_controller_selection.ts·authoring_controller_apply.ts 로 분리했다(복잡도
     예산 — module_statements/function_statements 상한). 공유 가변 상태는 get/set 또는
     Map 참조로 넘긴다. `echoes`·`previewHighlight`·`rangePickStep` 은 상시 예외라 이 파일에
     남고, 필요한 모듈에는 함수 값으로 건넨다(순환 import 금지). */
  // 수명주기(close)의 「저장하고 닫기」는 케이스도 저장하고(persistCases, 시험 클러스터),
  // 그 케이스 저장은 「문서 저장 필요」로 되물리면 수명주기의 save 를 부른다 — 두 클러스터가
  // 서로를 가리키므로 먼저 세운 쪽은 나중에 세울 참조를 전방 선언으로 받는다.
  let trialCtl: ReturnType<typeof createTrialController>;
  const lifecycle = createLifecycleController({
    runtime: deps.runtime, navigation: deps.navigation, modal: deps.modal,
    editors, buffers, revisions, views, generations, inputPumps, pendingRestore, rememberTimers,
    snapshot, tab,
    getView: () => view, setView: (next: Obj) => { view = next; },
    getViewId: () => viewId, setViewId: (next: string) => { viewId = next; },
    getHovered: () => hovered, setHovered: (next: Obj | null) => { hovered = next; },
    getTrialTimer: () => trialTimer, setTrialTimer: (next) => { trialTimer = next; },
    getReturnScreen: () => returnScreen, setReturnScreen: (next: string) => { returnScreen = next; },
    update, guarded, fail, dispatch, invoke, flush, drain, revision, fenced, currentHighlight,
    initialView,
    persistCases: (id: string) => trialCtl.persistCases(id),
  });

  const apply = createApplyController({
    editors, snapshot,
    getView: () => view, getViewId: () => viewId, update, dispatch, flush, revision,
    modal: deps.modal,
    getApplying: () => applying, setApplying: (next: boolean) => { applying = next; },
    getPreviewRequest: () => previewRequest, bumpPreviewRequest: () => ++previewRequest,
    commandLabel: (type: string) => [...COMMANDS, ...DOCUMENT_COMMANDS].find(([value]) => value === type)?.[1],
    documentCommandLabel: (type: string) => DOCUMENT_COMMANDS.find(([value]) => value === type)?.[1],
    changed: (id: string, content: string) => changed(id, content),
    scheduleTrial: (id: string) => trialCtl.scheduleTrial(id),
  });

  const selectionCtl = createSelectionController({
    editors, selectionRequests, navigationHistory,
    snapshot, getView: () => view, getViewId: () => viewId, update, guarded, dispatch, flush,
    revision, fenced, problemHere, announce,
    scheduleRemember: (id: string) => lifecycle.scheduleRemember(id),
    activate: (id: string) => lifecycle.activate(id),
    bumpPreviewRequest: () => ++previewRequest,
    getExplicit: () => explicit, setExplicit: (next) => { explicit = next; },
    semanticTarget, echoes, rangePickStep,
    copy: { rangePickStart: AUTHORING_COPY.rangePickStart, rangePickEnd: AUTHORING_COPY.rangePickEnd, rangePickCancel: AUTHORING_COPY.rangePickCancel },
  });

  trialCtl = createTrialController({
    views, inputPumps, modal: deps.modal,
    snapshot, tab, getView: () => view, getViewId: () => viewId, update, guarded, dispatch, flush,
    revision, fenced,
    getTrialTimer: () => trialTimer, setTrialTimer: (next) => { trialTimer = next; },
    bumpSearchRequest: () => ++searchRequest, getSearchRequest: () => searchRequest,
    coordinates,
    save: (id: string) => lifecycle.save(id),
  });

  const {
    select, adopt, back, selection, toggleRangePick, cancelRangePick, pickClick, endRangePick,
  } = selectionCtl;
  const { activate, open, openFile, save, close, leaveTo, restored, applyRestore, flushAll } = lifecycle;
  const { preview, applyPreview, documentCommand } = apply;
  const { keepTrialValue, trialInput, fillTrialNames, runTrial, saveCase, sameText, search } = trialCtl;

  return {
    // 「데이터로 필드 찾기」(#1156) — 다섯 액션과 띠·팝오버 상태. 만든 결과는 이 화면의 편집 사슬(편집기 apply → 내용 갱신)을 탄다.
    proposal: createProposal({ dispatch, fenced, flush, editor: (id) => editors.get(id), applyPreview, viewId: () => viewId, tab, view: () => view, update, changed,
      revision, pending: (id) => buffers.has(id), redecorate, scheduleTrial: trialCtl.scheduleTrial, dataPicker: deps.dataPicker, toast: deps.undo }),
    model, viewModel: { getSnapshot: () => view, subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; } },
    snapshot, tab, update, guarded, fail, announce, note, changed, flush, flushAll, activate, open, openFile, save, close, leaveTo,
    closeState: () => invoke("close_guard_state"),
    back, select, adopt, preview, applyPreview, documentCommand, trialInput, fillTrialNames, keepTrialValue, runTrial, saveCase, search, sameText,
    /** 활성 탭(또는 그 탭)의 지금 revision — 표면이 제 목록이 옛 문서의 것인지 비교할 뿐이다(판정 아님). */
    revisionOf: (id = snapshot().active_id) => revision(id),
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
    setMode(mode: string) { update({ mode }); redecorate(); if (viewId) lifecycle.scheduleRemember(viewId); },
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
    removeCase: async (name: string) => { const id = snapshot().active_id; if (await deps.modal.confirm({ title: "시험 케이스 삭제", body: name, confirmLabel: "삭제", danger: true })) { await dispatch("case_remove", fenced(id, { name })); await trialCtl.persistCases(id); } },
    exportResult: async () => { const id = snapshot().active_id; await flush(id); await inputPumps.get(id); await invoke("export_authoring_result", id, revision(id)); },
    transferCases: (action: "import" | "export") => invoke("authoring_cases_file", snapshot().active_id, action),
  };
}

export type AuthoringController = ReturnType<typeof createAuthoringController>;
