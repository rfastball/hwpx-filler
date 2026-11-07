/* R4-01 job 읽기·선택 표면. Python snapshot의 판정은 그대로 투영하고, DataZone·후보·
   browse·범위 초안의 DOM/이벤트/비동기 의도는 이 React 경계가 단독 소유한다. */
import {
  createElement,
  useEffect,
  useRef,
  /* R5-02: 미사용 useState import 제거. */
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";

import { SCREEN_ACTIONS } from "../contract/contract.gen.ts";
import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import type { BridgeClient } from "../runtime/client.ts";
import type { DataPickerController } from "./data_picker.ts";
import { PathActions } from "./path_actions.ts";
import { saveSheetOrder } from "./sheet_tabs.ts";
import { createLatestIntentQueue } from "./latest_intent.ts";
import type { ScreenPorts } from "./ports.ts";
import type { JobScreenModel, ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import { NewWorkButton } from "./job_read_views.ts";
import { createJobReadActions } from "./job_read_actions.ts";
import { createJobReadBrowse } from "./job_read_browse.ts";
import type { BrowseSession } from "./job_read_browse.ts";

export type Obj = Record<string, any>;
type Listener = () => void;

export type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
  prompt(spec: Obj): Promise<string | null>;
  open(id: string, spec?: Obj): void;
  close(id: string): void;
};

type SurfaceSheetPort = {
  open(spec: Obj): void;
  close(id: string): void;
  isOpen(id: string): boolean;
};

/** 공용 팝오버의 **배치 계산만** 쓴다 — dismissal registry 는 이 화면의 관심사가 아니다. */
type PopoverPort = {
  place(
    el: HTMLElement,
    anchor: HTMLElement,
    options?: Readonly<{ gap?: number; margin?: number; offsetParent?: HTMLElement }>,
  ): unknown;
};

export type JobReadControllerDeps = {
  runtime: ScreenRuntime;
  client: BridgeClient;
  ports: ScreenPorts;
  services: ServiceHandoffPorts;
  modal: ModalPort;
  popover: PopoverPort;
  surfaceSheet: SurfaceSheetPort;
  dataPicker: DataPickerController;
  navigation: { go(screen: string): void };
  doc: Document;
  notify(message: string): void;
};

export type UiState = {
  sheetOpen: boolean;
  openingName: string;
  candidateMenu: string;
  pendingSearch: string | null;
  pendingColumn: { column: string; text: string } | null;
  tableScrollTop: number;
  switchingData: string;
};

export function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function asObject(value: unknown, label: string): Obj {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}: snapshot 객체가 아닙니다.`);
  }
  return value as Obj;
}

function fullSnapshot(model: JobScreenModel): Obj | null {
  if (model.full === null) return null;
  const snapshot = asObject(model.full, "job");
  if (typeof snapshot.has_data !== "boolean" || typeof snapshot.has_job !== "boolean") {
    throw new Error("job snapshot: has_data/has_job 판정이 없습니다.");
  }
  return snapshot;
}

function hostValue(result: Awaited<ReturnType<BridgeClient["dispatch"]>>, label: string): Obj {
  return (expectHostValue(result, label) ?? {}) as Obj;
}

export function createJobReadController(deps: JobReadControllerDeps) {
  const model = deps.runtime.model<JobScreenModel>("job");
  let ui: UiState = {
    sheetOpen: false,
    openingName: "",
    candidateMenu: "",
    pendingSearch: null,
    pendingColumn: null,
    tableScrollTop: 0,
    switchingData: "",
  };
  const listeners = new Set<Listener>();
  let zoneTail = Promise.resolve();
  let browseTail = Promise.resolve();
  /* 연속 데이터 전환은 마지막 대상 하나로 착지한다(편집기 시트 탭과 같은 큐). */
  const dataSwitches = createLatestIntentQueue();
  let browseGeneration = 0;
  let searchTimer: number | null = null;
  let columnTimer: number | null = null;
  let rangeApplied = false;
  let rangeForceClose = false;

  const call = async (screen: string, action: string, payload: Obj = {}): Promise<Obj> => {
    const dispatch = deps.client.dispatch as unknown as (
      channel: string, name: string, body: Obj,
    ) => ReturnType<BridgeClient["dispatch"]>;
    return hostValue(await dispatch(screen, action, payload), `${screen}/${action}`);
  };

  function snapshot(): Obj | null {
    return fullSnapshot(model.getSnapshot());
  }

  function emit(): void {
    for (const listener of [...listeners]) listener();
  }

  function patchUi(patch: Partial<UiState>): void {
    ui = { ...ui, ...patch };
    emit();
  }

  function zone(action: string, payload: Obj = {}, query = false): Promise<Obj> {
    const current = snapshot();
    const schema = (SCREEN_ACTIONS.job as Record<
      string, { required: readonly string[]; optional: readonly string[] }
    >)[action];
    const acceptsEpoch = schema !== undefined
      && (schema.required.includes("epoch") || schema.optional.includes("epoch"));
    /* epoch는 "모든 쓰기" 장식이 아니라 생성 계약이 허용한 zone mutation의 키다.
       범위 초안 open/apply/cancel은 무페이로드 명시 사건이라 epoch를 붙이면 Python이
       스키마 불일치로 loud 거절한다. 손 액션 목록 대신 생성 계약에서 허용 여부를 읽는다. */
    const body = query || !acceptsEpoch || current?.zone_epoch === undefined
      ? payload : { ...payload, epoch: current.zone_epoch };
    const send = () => call("job", action, body);
    if (query) return send();
    const next = zoneTail.then(send, send);
    zoneTail = next.then(() => undefined, () => undefined);
    return next;
  }

  function browse(action: string, payload: Obj): Promise<Obj> {
    const generation = browseGeneration;
    const send = async (): Promise<Obj> => {
      if (generation !== browseGeneration) return { stale: true };
      return call("job", action, payload);
    };
    const next = browseTail.then(send, send);
    browseTail = next.then(() => undefined, () => undefined);
    return next;
  }

  async function flushPendingEdits(): Promise<void> {
    if (searchTimer !== null) {
      deps.doc.defaultView?.clearTimeout(searchTimer);
      searchTimer = null;
    }
    if (columnTimer !== null) {
      deps.doc.defaultView?.clearTimeout(columnTimer);
      columnTimer = null;
    }
    const pendingColumn = ui.pendingColumn;
    const pendingSearch = ui.pendingSearch;
    patchUi({ pendingColumn: null, pendingSearch: null });
    if (pendingColumn !== null) await zone("filter_col_text", pendingColumn);
    const committed = snapshot()?.filter?.search || "";
    if (pendingSearch !== null && pendingSearch !== committed) {
      await zone("filter_search", { text: pendingSearch });
    }
    await zoneTail;
  }

  function scheduleSearch(text: string): void {
    patchUi({ pendingSearch: text });
    if (searchTimer !== null) deps.doc.defaultView?.clearTimeout(searchTimer);
    searchTimer = deps.doc.defaultView?.setTimeout(() => {
      searchTimer = null;
      const pending = ui.pendingSearch;
      patchUi({ pendingSearch: null });
      if (pending !== null) void zone("filter_search", { text: pending });
    }, 200) ?? null;
  }

  function scheduleColumnText(column: string, text: string): void {
    patchUi({ pendingColumn: { column, text } });
    if (columnTimer !== null) deps.doc.defaultView?.clearTimeout(columnTimer);
    columnTimer = deps.doc.defaultView?.setTimeout(() => {
      columnTimer = null;
      const pending = ui.pendingColumn;
      patchUi({ pendingColumn: null });
      if (pending !== null) void zone("filter_col_text", pending);
    }, 200) ?? null;
  }

  /* 선택·즐겨찾기·새 작업·재연결·데이터 연결 — `zone(...)` 을 쓰지 않는 컨트롤러 헬퍼
     묶음은 job_read_actions.ts가 쥔다(module_statements 분리). `switching` 가드도 함께
     옮겨 `actions.isSwitchingJob()` 으로 읽는다. */
  const actions = createJobReadActions({
    deps, call, snapshot, patchUi, getUi: () => ui, flushPendingEdits,
  });

  /** 이미 그 데이터·시트를 쓰고 있으면 전환은 아무 일도 하지 않는다. */
  function isSameData(current: Obj | null, key: string, sheet?: string): boolean {
    return current?.data_pool_key === key && (sheet === undefined || current?.data_target?.sheet === sheet);
  }

  async function performDataSwitch(isCurrent: () => boolean, key: string, sheet?: string): Promise<void> {
    try {
      if (isSameData(snapshot(), key, sheet) || !(await actions.confirmDataSwap())) return;
      await flushPendingEdits();
      if (!isCurrent()) return;
      const result = await call("job", "load_pool", { key, ...(sheet === undefined ? {} : { sheet }) });
      if (result.ok === false) deps.notify(String(result.error));
    } catch (error) {
      deps.notify(String((error as Obj)?.message || error));
    } finally {
      if (isCurrent()) patchUi({ switchingData: "" });
    }
  }

  function switchData(key: string, sheet?: string): Promise<void> {
    if (actions.isSwitchingJob()) return Promise.resolve();
    patchUi({ switchingData: sheet ?? key });
    return dataSwitches.run((isCurrent) => performDataSwitch(isCurrent, key, sheet), undefined);
  }

  /* 현재 데이터를 **다시 읽는다**(U4 항목 5 · #932 U4-C). 판정·수치·문안은 전부 Python
     이 내고 여기서는 확인 UI 만 짓는다 — 선택이 있으면 백엔드가 needs_confirm 과 함께
     사라지는 집합을 수치로 재진술하고, 없으면 곧바로 돈다(없는 위험에 확인을 물리면
     그 확인이 다음 진짜 확인의 무게를 깎는다). 겨눔 성분은 보내지 않는다: 재료는 세션이
     마운트 시점에 포획한 한 벌이라 웹이 실어 보내면 그사이 갈린 화면과 다른 데이터를
     새로고침한다. */
  async function remountData(): Promise<Obj | false> {
    const first = await zone("remount_data", {});
    if (first.needs_confirm) {
      const accepted = await deps.modal.confirm({
        title: "데이터 다시 읽기",
        body: `${first.confirm_text}

다시 읽을까요?`,
        confirmLabel: "다시 읽기", cancelLabel: "취소", danger: true,
      });
      if (!accepted) return false;
      return zone("remount_data", { confirm: true });
    }
    return first;
  }

  async function openDataSheet(trigger: HTMLElement | null): Promise<void> {
    await flushPendingEdits();
    await zone("range_draft_open", {});
    rangeApplied = false;
    rangeForceClose = false;
    const wrap = deps.doc.getElementById("jobTableWrap");
    patchUi({ sheetOpen: true, tableScrollTop: wrap?.scrollTop || 0 });
    deps.surfaceSheet.open({
      modalId: "dataSheet",
      returnFocus: trigger,
      initialFocus: deps.doc.getElementById("dataSheetClose"),
      beforeClose: () => guardRangeClose(),
      onClose: () => {
        patchUi({ sheetOpen: false });
        const draft = snapshot()?.range_draft;
        if (!rangeApplied && draft?.open) void zone("range_draft_cancel", {});
        // 면을 연 단추는 그 면과 **함께 언마운트됐다**(U4 10번 — 트리거가 표 머리로 왔고,
        // 인라인/시트는 한쪽만 렌더된다). 저장해 둔 노드는 죽었으므로 오버레이의 복귀는
        // 화면으로 착지한다(`restoreFocusTo` 의 대안 착지). 그 뒤 인라인이 다시 마운트되면
        // **살아 있는 같은 단추**로 초점을 돌린다 — 「누른 자리로 돌아온다」는 계약은 그
        // 자리가 옮겨졌다고 없어지지 않는다. 복귀는 `restoreFocus` → `onClose` 순서라
        // 여기서 거는 초점이 나중이고, 재마운트를 기다려야 하므로 한 프레임 뒤에 건다.
        const view = deps.doc.defaultView;
        const back = () => deps.doc.getElementById("jobDataExpand");
        if (view) view.requestAnimationFrame(() => { back()?.focus(); });
        else back()?.focus();
      },
    });
  }

  function dropPendingEdits(): void {
    if (searchTimer !== null) deps.doc.defaultView?.clearTimeout(searchTimer);
    if (columnTimer !== null) deps.doc.defaultView?.clearTimeout(columnTimer);
    searchTimer = null;
    columnTimer = null;
    patchUi({ pendingSearch: null, pendingColumn: null });
  }

  async function discardRange(): Promise<void> {
    dropPendingEdits();
    try {
      await zone("range_draft_cancel", {});
    } catch (error) {
      deps.notify(`범위 편집을 취소하지 못했습니다: ${String(error)}`);
      return;
    }
    rangeForceClose = true;
    deps.surfaceSheet.close("dataSheet");
  }

  function guardRangeClose(): boolean {
    if (rangeForceClose) {
      rangeForceClose = false;
      return true;
    }
    const draft = snapshot()?.range_draft;
    if (!draft?.open) return true;
    if (!draft.dirty && ui.pendingSearch === null && ui.pendingColumn === null) {
      void discardRange();
      return false;
    }
    void deps.modal.confirm({
      title: "편집한 범위를 버릴까요?",
      body: "적용하지 않은 변경이 있습니다. 버리면 문서 만들기 화면의 범위는 그대로 남습니다.",
      confirmLabel: "버리고 닫기",
      cancelLabel: "계속 편집",
      danger: true,
      returnFocus: deps.doc.getElementById("jobRangeCancel"),
    }).then((accepted) => { if (accepted) void discardRange(); });
    return false;
  }

  async function applyRange(): Promise<void> {
    try {
      await flushPendingEdits();
      await zone("range_draft_apply", {});
    } catch (error) {
      deps.notify(`범위를 적용하지 못했습니다: ${String(error)}`);
      return;
    }
    rangeApplied = true;
    rangeForceClose = true;
    deps.surfaceSheet.close("dataSheet");
  }

  /* 「문서 작업 찾기」 탐색 흐름(세대·대기·후속) — job_read_browse.ts가 쥔다. `browse(...)`
     디스패처 자체는 여기 남고, 세대·꼬리는 아래 session 접근자로만 건네준다. */
  const browseSession: BrowseSession = {
    bumpGeneration: () => { browseGeneration += 1; },
    generation: () => browseGeneration,
    afterTail: (fn) => browseTail.then(fn),
  };
  const browseFlow = createJobReadBrowse({
    modal: deps.modal, doc: deps.doc, browse, session: browseSession, getUi: () => ui,
    selectJob: actions.selectJob, newWorkFromData: actions.newWorkFromData,
  });

  const controller = {
    model,
    poolModel: deps.runtime.model<Obj | null>("pool"),
    switchData,
    reorderSheets: (key: string, sheets: string[]) => saveSheetOrder(key, sheets, call,
      () => call("job", "refresh", {}), deps.notify),
    uiModel: {
      getSnapshot: () => ui,
      subscribe(listener: Listener): () => void {
        listeners.add(listener);
        return () => { listeners.delete(listener); };
      },
    },
    snapshot,
    client: deps.client,
    doc: deps.doc,
    notify: deps.notify,
    /** 저장한 필터 칩의 이름 입력·삭제 확인 — 공용 modal 을 그대로 쓴다(새 다이얼로그 없음). */
    prompt: (spec: Obj): Promise<string | null> => deps.modal.prompt(spec),
    confirm: (spec: Obj): Promise<boolean> => deps.modal.confirm(spec),
    call,
    zone,
    browse,
    scheduleSearch,
    scheduleColumnText,
    flushPendingEdits,
    selectJob: actions.selectJob,
    toggleFavorite: actions.toggleFavorite,
    /** 불러온 사실은 「현재 데이터」 존의 라벨이 이미 보인다 — 성공에 따로 착지를 두지
     *  않는다(실패는 피커 자신이 그 자리에서 말한다). */
    openDataPicker(): void {
      if (ui.switchingData) return;
      void deps.dataPicker.open({
        screen: "job",
        session: actions.currentData,
        confirmSwap: actions.confirmDataSwap,
      });
    },
    openDataSheet,
    remountData,
    connectJobData: actions.connectJobData,
    /** 데이터 통지 닫기(U4 §2.12 · #945) — 통지는 Python 소유라 지우는 것도 Python 이
     *  한다. 존 변이가 아니므로 세대(`epoch`)를 싣지 않는 `call` 경로다. */
    dismissDataNotice: (): Promise<Obj> => call("job", "dismiss_data_notice", {}),
    closeDataSheet: () => deps.surfaceSheet.close("dataSheet"),
    /** 열 필터 패널을 **트리거 아래**에 붙인다(U4 계열1-9). 배치 규칙은 공용
     *  `Popover.place` 하나가 소유한다 — 문맥 메뉴와 같은 진실이라 화면이 자기 좌표를
     *  다시 지으면 같은 규칙이 두 곳에 산다. `.colpanel` 은 `position:fixed` 이고
     *  offsetParent 를 주지 않으므로 viewport 좌표로 clamp·flip 된다. */
    placePopover(el: HTMLElement, anchor: HTMLElement): void {
      deps.popover.place(el, anchor);
    },
    applyRange,
    discardRange,
    openBrowse: browseFlow.openBrowse,
    closeBrowse: () => deps.modal.close("jobBrowseSheet"),
    openBrowseNeedsAction: browseFlow.openBrowseNeedsAction,
    newWorkAfterBrowseClose: browseFlow.newWorkAfterBrowseClose,
    setBrowseQuery: browseFlow.setBrowseQuery,
    pickBrowse: browseFlow.pickBrowse,
    newWorkFromData: actions.newWorkFromData,
    relinkTemplateFor: actions.relinkTemplateFor,
    navigation: deps.navigation,
    patchUi,
  };

  deps.ports.jobRead.bind({
    refreshList: async () => { await call("job", "refresh", {}); },
    openBrowseNeedsAction: browseFlow.openBrowseNeedsAction,
  });
  deps.ports.jobData.bind({ flushPendingEdits });
  deps.ports.jobRelinkFlow.bind({ relinkTemplateFor: actions.relinkTemplateFor });
  return controller;
}

export type JobReadController = ReturnType<typeof createJobReadController>;

export function useJob(controller: JobReadController): Obj | null {
  /* 세 번째 인자는 정적 렌더의 스냅샷이다 — 같은 출처를 준다(다른 화면의 관례와 동일).
     없으면 `renderToStaticMarkup` 이 이 화면에서만 던져 정적 렌더 계약을 못 세운다. */
  const model = useSyncExternalStore(
    controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot);
  return fullSnapshot(model);
}

export function useUi(controller: JobReadController): UiState {
  return useSyncExternalStore(controller.uiModel.subscribe, controller.uiModel.getSnapshot, controller.uiModel.getSnapshot);
}

export {
  JobDataHeader, JobDataBody, JobDataTabs, JobNoDataExit, JobReadEffects,
} from "./job_read_views.ts";

function CandidateCard(props: { row: Obj; snapshot: Obj; controller: JobReadController }): ReactNode {
  const { row, snapshot, controller } = props;
  const ui = useUi(controller);
  const active = row.name === snapshot.job_name;
  const missing = row.template_missing === true;
  const key = encodeURIComponent(row.name);
  const menu = active && row.template_path;
  return h("div", { className: `job-cand-card${active ? " active" : ""}${row.suggested ? " suggested" : ""}${missing ? " warn" : ""}` },
    h("button", { className: "cand-fav", type: "button", id: `jobFav-${key}`, "data-fav": row.name,
      "aria-pressed": row.favorited ? "true" : "false", "aria-label": `${row.name} ${row.favorited ? "즐겨찾기에서 제거" : "즐겨찾기에 추가"}`,
      onClick: () => { void controller.toggleFavorite(row.name, !!row.favorited); } }, row.favorited ? "★" : "☆"),
    h("button", { className: "cand-pick", type: "button", id: `jobCand-${key}`, "data-cand": row.name,
      disabled: !!ui.switchingData,
      "data-missing": missing ? "1" : undefined, "data-busy-lock": true, "aria-pressed": active ? "true" : "false",
      onClick: () => {
        if (missing) { void controller.relinkTemplateFor(row.name); return; }
        if (!active) void controller.selectJob(row.name);
      } }, h("span", { className: "cand-nm" }, row.name,
        ui.openingName === row.name ? h("span", { className: "openingMark" }, " · 여는 중…") : null),
      h("span", { className: "cand-meta" },
        row.suggested ? h("span", { className: "cand-sug" }, "추천") : null,
        h("span", { className: "cand-mode" }, row.mode_label || ""),
        row.conn_label ? h("span", { className: "cand-conn" }, row.conn_label) : null),
      active && row.template_name ? h("span", { className: "cand-tpl mono" }, row.template_name) : null),
    menu ? h("button", { className: "cand-menu", type: "button", id: "jobCandMenuBtn", "data-cand-menu": true,
      "data-path": row.template_path, "data-busy-lock": true, "aria-haspopup": "menu",
      onClick: () => controller.patchUi({ candidateMenu: ui.candidateMenu === row.name ? "" : row.name }) }, "⋮") : null,
    menu && ui.candidateMenu === row.name ? h("span", { className: "cand-inline-menu", role: "menu" },
      h(PathActions as any, {
        client: controller.client, path: row.template_path, notify: controller.notify, labels: true,
      })) : null);
}

export function JobCandidates(props: { controller: JobReadController }): ReactNode {
  const snapshot = useJob(props.controller);
  const ui = useUi(props.controller);
  if (snapshot === null || !snapshot.has_data) return null;
  const candidates = snapshot.candidates || { top: [], more: 0, needs_count: 0, sections: [] };
  const top = candidates.top || [];
  const byName = new Map(top.map((row: Obj) => [row.name, row]));
  const sections = candidates.sections || [];
  let cards: ReactNode[];
  if (sections.length > 1) {
    cards = sections.map((section: Obj) => h("div", { className: "cand-sec", "data-cand-mode": section.mode, key: section.mode },
      h("h3", { className: "cand-sec-cap" }, section.mode_label),
      ...(section.names || []).map((name: string) => byName.has(name)
        ? h(CandidateCard as any, { key: name, row: byName.get(name), snapshot, controller: props.controller }) : null)));
  } else {
    cards = top.map((row: Obj) => h(CandidateCard as any, { key: row.name, row, snapshot, controller: props.controller }));
  }
  const bits: ReactNode[] = [];
  if (candidates.more > 0) bits.push(h("span", { key: "more" }, "연결된 작업 ", h("b", null, candidates.more), "건 더"));
  if (candidates.needs_count > 0) bits.push(h("span", { key: "needs" }, "확인 필요 ", h("b", null, candidates.needs_count), "건"));
  return h("div", { className: "job-read-side-content" }, h("div", { className: "zone-cap" }, "이 데이터에 사용할 문서"),
    h("div", { className: "job-cands", id: "jobCandidates", role: "group", "aria-label": "문서 작업 후보" },
      !top.length && !candidates.needs_count
        // 여기 있던 「「문서 작업」에서 고르기」 단추는 걷혔다(간소화 라운드): 그 자리에서
        // 할 수 있는 일은 아래 「＋ 이 데이터로 새 작업」 하나이고, 상단 탭이 이미 그 화면으로
        // 가는 유일한 참 경로다 — 같은 동사를 두 번 그리면 어느 쪽이 진짜인지가 흐려진다.
        ? h("span", { className: "muted" }, "이 데이터에 연결된 문서 작업이 없습니다.")
        : cards,
      bits.length ? h("span", { className: "cand-more muted" }, ...bits, " — ",
        h("button", { className: "btn sm", type: "button", id: "jobBrowseOpen", "data-browse-open": true,
          disabled: !!ui.switchingData,
          "data-busy-lock": true, onClick: (event: Obj) => { void props.controller.openBrowse(event.currentTarget); } }, "문서 작업 찾기…")) : null,
      h("span", { className: "cand-newwork" }, h(NewWorkButton as any, { snapshot, controller: props.controller })),
      candidates.txt_note ? h("details", {
        className: "cand-sec cand-txt-help", "data-cand-mode": "text",
        open: !snapshot.has_job,
      }, h("summary", { className: "cand-sec-cap" }, "온나라 기안"),
      h("span", { className: "muted" }, candidates.txt_note)) : null));
}

function BrowseRow(props: { row: Obj; needs: boolean; snapshot: Obj; controller: JobReadController }): ReactNode {
  const { row, needs, snapshot, controller } = props;
  const ui = useUi(controller);
  const key = encodeURIComponent(row.name);
  if (needs) {
    const gate = snapshot.new_work || { can: true, reason: "" };
    const cols = (row.missing || []).join(", ");
    return h("button", { className: "browse-row needs", type: "button", id: `jobBrowseNeeds-${key}`,
      "data-browse-new": gate.can === false ? undefined : row.name, "data-missing-cols": cols,
      "data-busy-lock": gate.can === false ? undefined : true, disabled: gate.can === false,
      title: gate.reason || "", onClick: () => {
        controller.newWorkAfterBrowseClose({ "확인 필요였던 작업": row.name, "현재 데이터에 없는 열": cols });
      } }, h("span", { className: "browse-nm" }, row.name),
      h("span", { className: "browse-why muted" }, `현재 데이터에 없는 열: ${cols} — ${gate.can === false ? gate.reason : "이 데이터로 새 작업 만들기"}`));
  }
  const active = row.name === snapshot.job_name;
  return h("button", { className: "browse-row", type: "button", id: `jobBrowseRow-${key}`,
    "data-browse-pick": row.name, "data-busy-lock": true, "aria-pressed": active ? "true" : "false",
    onClick: () => { if (!active) void controller.pickBrowse(row.name); } },
  h("span", { className: "browse-nm" }, row.name,
    ui.openingName === row.name ? h("span", { className: "openingMark" }, " · 여는 중…") : null),
  h("span", { className: "browse-why muted" },
    `${row.mode_label || ""}${active ? " · 지금 선택된 작업" : ""}`));
}

export function JobBrowseDialog(props: { controller: JobReadController }): ReactNode {
  const snapshot = useJob(props.controller);
  const queryRef = useRef<HTMLInputElement | null>(null);
  const snapshotQuery = String(snapshot?.browse?.query || "");
  useEffect(() => {
    const input = queryRef.current;
    if (input !== null && props.controller.doc.activeElement !== input) input.value = snapshotQuery;
    /* 같은 서버 query를 재전달해도 포커스 상태는 달라질 수 있다. 값 의존으로 줄이면
       focused push 뒤 blur + 동일값 push가 빠지므로, model delivery가 만든 매 render에서 잰다. */
  });
  if (snapshot === null) return h("div", { className: "modal-card sheet-card" }, "작업 목록을 읽는 중…");
  const browse = snapshot.browse || { tab: "available", query: "", rows: [], available_count: 0, needs_count: 0, filtered_out: 0 };
  const needs = browse.tab === "needs_action";
  const rows = browse.rows || [];
  const byName = new Map(rows.map((row: Obj) => [row.name, row]));
  const content = browse.sections?.length > 1
    ? browse.sections.map((section: Obj) => h("div", { className: "browse-sec", "data-browse-mode": section.mode, key: section.mode },
      h("h3", { className: "browse-sec-cap" }, section.mode_label),
      ...(section.names || []).map((name: string) => byName.has(name)
        ? h(BrowseRow as any, { key: name, row: byName.get(name), needs, snapshot, controller: props.controller }) : null)))
    : rows.map((row: Obj) => h(BrowseRow as any, { key: row.name, row, needs, snapshot, controller: props.controller }));
  return h("div", { className: "modal-card sheet-card browse-sheet" },
    h("div", { className: "sheet-head" }, h("h2", { id: "jobBrowseTitle" }, "문서 작업 찾기"),
      h("button", { className: "btn", id: "jobBrowseClose", type: "button", "data-busy-lock": true,
        onClick: props.controller.closeBrowse }, "닫기")),
    h("div", { className: "browse-tabs", id: "jobBrowseTabs", role: "tablist" },
      ...[["available", `사용 가능 ${browse.available_count}`], ["needs_action", `확인 필요 ${browse.needs_count}`]].map(([key, label]) =>
        h("button", { className: "browse-tab", type: "button", role: "tab", id: `jobBrowseTab-${key}`,
          "data-browse-tab": key, "data-busy-lock": true, "aria-selected": browse.tab === key ? "true" : "false",
          onClick: () => { if (browse.tab !== key) void props.controller.browse("browse_tab", { tab: key }); } }, label))),
    h("input", { className: "field", id: "jobBrowseQuery", type: "search", ref: queryRef, defaultValue: browse.query || "",
      "data-busy-lock": true,
      placeholder: "작업 이름 검색", onInput: (event: Obj) => props.controller.setBrowseQuery(event.currentTarget.value),
      onBlur: (event: Obj) => { event.currentTarget.value = String(browse.query || ""); } }),
    h("p", { className: "muted capnote", id: "jobBrowseNote" }, browse.filtered_out > 0 ? `검색으로 ${browse.filtered_out}건이 목록에서 빠졌습니다.` : ""),
    h("div", { className: "browse-rows", id: "jobBrowseRows", "data-preserve-scroll": true },
      rows.length ? content : h("p", { className: "muted capnote" }, browse.query ? "이름이 일치하는 작업이 없습니다."
        : needs ? "확인이 필요한 작업이 없습니다." : "이 데이터에 연결된 작업이 없습니다.")));
}
