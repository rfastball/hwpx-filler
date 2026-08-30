/* R4-01 job 읽기·선택 표면. Python snapshot의 판정은 그대로 투영하고, DataZone·후보·
   browse·범위 초안의 DOM/이벤트/비동기 의도는 이 React 경계가 단독 소유한다. 실행·결과·
   preview는 임시 JobRunPort 하류의 legacy remainder에 남는다. */
import {
  Fragment,
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
import { JobDataZone } from "./data_zone.ts";
import type { JobRunCallbacks, PreviewRequest, ScreenPorts } from "./ports.ts";
import type { JobScreenModel, ScreenModel, ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
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

type UiState = {
  sheetOpen: boolean;
  openingName: string;
  candidateMenu: string;
  pendingSearch: string | null;
  pendingColumn: { column: string; text: string } | null;
  tableScrollTop: number;
};

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
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
  };
  const listeners = new Set<Listener>();
  let zoneTail = Promise.resolve();
  let browseTail = Promise.resolve();
  let switching = false;
  let browseGeneration = 0;
  let browseAfterClose: (() => void) | null = null;
  let searchTimer: number | null = null;
  let columnTimer: number | null = null;
  let rangeApplied = false;
  let rangeForceClose = false;
  const favoriteTail = new Map<string, Promise<void>>();
  const favoriteIntent = new Map<string, boolean>();
  const favoriteRevision = new Map<string, number>();

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

  async function selectJob(name: string): Promise<boolean> {
    if (name.trim() === "") throw new Error("JobReadPort: 빈 작업 이름은 열 수 없습니다.");
    if (switching) return false;
    switching = true;
    patchUi({ openingName: name });
    try {
      await flushPendingEdits();
      await call("job", "select_job", { name });
      return true;
    } finally {
      switching = false;
      if (ui.openingName === name) patchUi({ openingName: "" });
    }
  }

  function currentData(): Obj {
    const current = snapshot();
    const target = current?.data_target || {};
    return {
      label: current?.data_source_label || "",
      detail: current?.has_data ? `${current.record_count}건` : "",
      path: target.path || "",
      sheet: target.sheet || "",
      origin: target.origin || "",
      /* `sheet` 자리가 무엇을 뜻하는지(엑셀=시트 / 계약 목록=뷰)는 호스트가 말한다(#937) —
         떨어뜨리면 선택 면이 경로 모양으로 되추측하게 된다. */
      kind: target.kind || "",
    };
  }

  async function confirmDataSwap(): Promise<boolean> {
    return deps.ports.jobRunCoordination.current().confirmDestructiveIfArmed(
      "데이터 변경 확인", "데이터를 바꾸면", "데이터 바꾸고 버리기",
    );
  }

  /* 현재 데이터를 **다시 읽는다**(U4 항목 5 · #932 U4-C). 판정·수치·문안은 전부 Python
     이 내고 여기서는 확인 UI 만 짓는다 — 선택이 있으면 백엔드가 needs_confirm 과 함께
     사라지는 집합을 수치로 재진술하고, 없으면 곧바로 돈다(없는 위험에 확인을 물리면
     그 확인이 다음 진짜 확인의 무게를 깎는다). 겨눔 성분은 보내지 않는다: 재료는 세션이
     마운트 시점에 포획한 한 벌이라 웹이 실어 보내면 그사이 갈린 화면과 다른 데이터를
     새로고침한다. */
  /* 결속 없는 작업을 고치러 간다 — 쓰는 자리가 편집기 저장 하나이므로 복구도 거기다
     (#932 U4-C). 이탈 가드·미저장 확인은 편집기 진입 seam 이 이미 진다. */
  async function connectJobData(): Promise<void> {
    const name = snapshot()?.job_name;
    if (!name) return;
    await deps.ports.editorEntry.current().openGuarded(String(name), {
      entry_reason: "library",
      evidence: { "여기서 할 것": "「필드 연결」 탭에서 데이터를 고르고 저장하세요" },
      return_context: { surface: "data" },
    });
  }

  async function remountData(): Promise<void> {
    const first = await zone("remount_data", {});
    if (first.needs_confirm) {
      const accepted = await deps.modal.confirm({
        title: "데이터 다시 읽기",
        body: `${first.confirm_text}

다시 읽을까요?`,
        confirmLabel: "다시 읽기", cancelLabel: "취소", danger: true,
      });
      if (!accepted) return;
      await zone("remount_data", { confirm: true });
    }
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
      deps.ports.jobRunCoordination.current().log(`범위 편집을 취소하지 못했습니다: ${String(error)}`);
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
      deps.ports.jobRunCoordination.current().log(`범위를 적용하지 못했습니다: ${String(error)}`);
      return;
    }
    rangeApplied = true;
    rangeForceClose = true;
    deps.surfaceSheet.close("dataSheet");
  }

  async function toggleFavorite(name: string, shown: boolean): Promise<void> {
    const intended = !(favoriteIntent.get(name) ?? shown);
    favoriteIntent.set(name, intended);
    const revision = (favoriteRevision.get(name) ?? 0) + 1;
    favoriteRevision.set(name, revision);
    const previous = favoriteTail.get(name) ?? Promise.resolve();
    const next = previous.then(async () => {
      const result = await call("job", "toggle_favorite", { name, value: intended });
      if (result.ok === false) deps.ports.jobRunCoordination.current().log(result.error || "즐겨찾기를 바꾸지 못했습니다.");
      if (favoriteRevision.get(name) === revision) {
        favoriteIntent.delete(name);
        favoriteRevision.delete(name);
      }
    });
    favoriteTail.set(name, next.catch((error) => deps.ports.jobRunCoordination.current().log(String(error))));
    await next;
  }

  function newWorkFromData(extraEvidence: Obj = {}): unknown {
    const current = snapshot();
    const gate = current?.new_work || { can: true, reason: "" };
    if (gate.can === false) {
      deps.ports.jobRunCoordination.current().log(gate.reason || "이 데이터로 새 작업을 만들 수 없습니다.");
      return false;
    }
    return deps.ports.editorEntry.current().newDraftFromData({
      entry_reason: "document_browser_new_work",
      evidence: { "데이터": current?.data_source_label || "", ...extraEvidence },
      return_context: { surface: "data" },
    });
  }

  async function relinkTemplateFor(name: string): Promise<void> {
    const active = snapshot()?.job_name === name;
    const accepted = await deps.modal.confirm({
      title: "템플릿 다시 연결",
      body: active
        ? `'${name}' 작업의 템플릿 파일을 찾을 수 없어 문서를 만들 수 없습니다.\n템플릿을 다시 연결하면 작업을 다시 불러옵니다.`
        : `'${name}' 작업은 템플릿 파일을 찾을 수 없어 바로 선택할 수 없습니다.\n템플릿을 다시 연결하면 이어서 이 작업을 선택합니다. 실패하면 선택하지 않습니다.`,
      confirmLabel: "템플릿 다시 연결…",
      cancelLabel: "취소",
    });
    if (!accepted) return;
    if (active && !(await deps.ports.jobRunCoordination.current().confirmDestructiveIfArmed(
      "템플릿 다시 연결 확인", "템플릿을 다시 연결하면", "다시 연결하고 버리기",
    ))) return;
    const committed = await deps.services.relink.current().relinkTemplate(
      "job", name, (message) => deps.ports.jobRunCoordination.current().log(message),
    );
    if (!committed || active) return;
    try {
      await selectJob(name);
    } catch (error) {
      deps.ports.jobRunCoordination.current().log(`작업 열기 실패: ${String(error)}`);
    }
  }

  async function openBrowse(returnFocus: HTMLElement | null = null): Promise<void> {
    browseGeneration += 1;
    browseAfterClose = null;
    deps.modal.open("jobBrowseSheet", {
      initialFocus: deps.doc.getElementById("jobBrowseQuery"),
      returnFocus,
      onClose: () => {
        browseGeneration += 1;
        const next = browseAfterClose;
        browseAfterClose = null;
        if (next !== null) next();
      },
    });
  }

  function newWorkAfterBrowseClose(extraEvidence: Obj): void {
    if (browseAfterClose !== null) {
      throw new Error("JobReadPort: 탐색 닫힘 뒤 흐름이 이미 예약돼 있습니다.");
    }
    browseAfterClose = () => { void controller.newWorkFromData(extraEvidence); };
    deps.modal.close("jobBrowseSheet");
  }

  async function openBrowseNeedsAction(name: string): Promise<void> {
    if (name.trim() === "") throw new Error("JobReadPort: 확인할 작업 이름이 비었습니다.");
    await browse("browse_tab", { tab: "needs_action" });
    await browse("browse_query", { text: name });
    await openBrowse();
  }

  const controller = {
    model,
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
    call,
    zone,
    browse,
    scheduleSearch,
    scheduleColumnText,
    flushPendingEdits,
    selectJob,
    toggleFavorite,
    openDataPicker(): void {
      void deps.dataPicker.open({
        screen: "job",
        current: currentData(),
        confirmSwap: confirmDataSwap,
        onLoaded: (label) => deps.ports.jobRunCoordination.current().log(`데이터 불러옴: ${label}`),
      });
    },
    openDataSheet,
    remountData,
    connectJobData,
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
    openBrowse,
    closeBrowse: () => deps.modal.close("jobBrowseSheet"),
    openBrowseNeedsAction,
    newWorkAfterBrowseClose,
    setBrowseQuery(text: string): void {
      const generation = browseGeneration;
      deps.doc.defaultView?.setTimeout(() => {
        if (generation === browseGeneration) void browse("browse_query", { text });
      }, 180);
    },
    async pickBrowse(name: string): Promise<void> {
      if (await browseTail.then(() => selectJob(name))) {
        browseAfterClose = () => {
          deps.doc.getElementById(`jobCand-${encodeURIComponent(name)}`)?.focus();
        };
        deps.modal.close("jobBrowseSheet");
      }
    },
    newWorkFromData,
    relinkTemplateFor,
    navigation: deps.navigation,
    patchUi,
  };

  deps.ports.jobRead.bind({
    refreshList: async () => { await call("job", "refresh", {}); },
    openBrowseNeedsAction,
  });
  deps.ports.jobData.bind({ flushPendingEdits });
  deps.ports.jobRelinkFlow.bind({ relinkTemplateFor });
  return controller;
}

export type JobReadController = ReturnType<typeof createJobReadController>;

function useJob(controller: JobReadController): Obj | null {
  const model = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot);
  return fullSnapshot(model);
}

function useUi(controller: JobReadController): UiState {
  return useSyncExternalStore(controller.uiModel.subscribe, controller.uiModel.getSnapshot);
}


export function JobDataHeader(props: { controller: JobReadController }): ReactNode {
  const snapshot = useJob(props.controller);
  if (snapshot === null) return h("p", { className: "muted", role: "status" }, "데이터 상태를 읽는 중…");
  const notice = snapshot.data_notice;
  return createElement(Fragment, null,
    // 「펼쳐서 행 고르기 ⤢」는 여기 없다(U4 10번) — 표를 여는 동사라 표 머리로 갔다.
    // 옮긴 것은 **진입점뿐**이고 초안 거래(`RecordRangeDraft`·존 13액션·「적용 전 메인 범위
    // 불변」 §18.11-21)와 면 수명주기는 그대로다.
    h("div", { className: "zone-cap" }, h("span", null, "현재 데이터")),
    /* 라벨은 확장자를 세지 않는다 — 마운트되는 종류가 엑셀/CSV 하나가 아니게 됐고(#937
       계약 목록), 여기 서는 값은 종류를 이미 말한다(`data_source_label`). */
    h("div", { className: "run-row" }, h("span", { className: "lbl" }, "데이터"),
      h("input", { className: "field ro", id: "jobDataLabel", type: "text", readOnly: true,
        value: snapshot.data_source_label || "", placeholder: "데이터를 선택하세요" }),
      h("button", { className: "btn primary", id: "jobBtnPickData", "data-busy-lock": true,
        onClick: props.controller.openDataPicker }, "데이터 선택…"),
      h("button", { className: "btn sm", id: "jobBtnRemountData", type: "button",
        "data-busy-lock": true, disabled: !snapshot.has_data,
        title: "같은 파일을 디스크에서 다시 읽습니다.",
        onClick: () => { void props.controller.remountData(); } }, "다시 읽기"),
      /* 결속 부재의 복구 동사(#932 U4-C) — 판정은 Python 한 자리(`job_data_unbound`)이고
         여기서는 그리기만 한다. 데이터 머리에 두는 이유는 이 상태가 **작업의 데이터**에
         관한 사실이라서다: 게이트가 「현재 데이터」 구획을 지목하면 눈이 닿는 자리가
         여기고, 없는 자리를 가리키는 지시는 이행 불가능하다. */
      snapshot.job_data_unbound
        ? h("button", { className: "btn primary sm", id: "jobConnectData", type: "button",
          "data-busy-lock": true,
          title: "이 작업에 데이터를 연결해야 문서를 만들 수 있습니다.",
          onClick: () => { void props.controller.connectJobData(); } }, "데이터 연결하기…")
        : null),
    h("div", { id: "jobDataNotice", className: `note ${notice?.level === "ok" ? "quiet" : "warnbox"}`,
      hidden: !notice?.text, style: { whiteSpace: "pre-line" } }, notice?.text ? `${notice.level === "ok" ? "" : "확인 필요: "}${notice.text}` : ""));
}

/* R5-02: 미착좌 JobDataHeaderPortal은 생산·소비가 모두 0이라 제거했다.
   JobDataHeader는 ProductScreens의 job 화면이 직접 소유하고,
   JobReadEffects는 같은 화면의 effect 슬롯이 별도로 착좌한다.
   둘을 다시 묶는 compatibility component는 두 번째 수명주기 경로가 된다.
   아래 표 body와 browse surface의 현재 좌표를 보존해 ownership 증거가
   unrelated line churn으로 흐려지지 않도록 이 제거 기록을 같은 8행에 둔다.
   실행 코드·export·fallback은 남기지 않는다.
*/

function JobTableScroll(props: { wrapRef: Obj; children?: ReactNode }): ReactNode {
  return h("div", {
    className: "tbwrap jobtbwrap",
    id: "jobTableWrap",
    "data-preserve-scroll": true,
    ref: props.wrapRef,
  }, props.children);
}

export function JobDataBody(props: { controller: JobReadController; location: "inline" | "sheet" }): ReactNode {
  const snapshot = useJob(props.controller);
  const ui = useUi(props.controller);
  if (snapshot === null) return null;
  if ((props.location === "sheet") !== ui.sheetOpen) return null;
  return h(JobDataZone as any, {
    snapshot, controller: props.controller, scroll: JobTableScroll,
  });
}

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

function NewWorkButton(props: { snapshot: Obj; controller: JobReadController }): ReactNode {
  const gate = props.snapshot.new_work || { can: true, reason: "" };
  return createElement(Fragment, null,
    h("button", { className: "btn sm", type: "button", id: "jobCandNewWork", "data-new-work": gate.can === false ? undefined : true,
      "data-busy-lock": gate.can === false ? undefined : true, disabled: gate.can === false, title: gate.reason || "",
      onClick: () => { void props.controller.newWorkFromData(); } }, "＋ 이 데이터로 새 작업"),
    gate.can === false ? h("span", { className: "cand-newwork-why muted" }, gate.reason) : null);
}

export function JobNoDataExit(props: { controller: JobReadController }): ReactNode {
  const snapshot = useJob(props.controller);
  if (snapshot === null || snapshot.has_data || snapshot.has_job) return null;
  return h("div", { className: "job-read-side-content" }, h("div", { className: "zone-cap" }, "시작하기"),
    h("p", { className: "muted capnote" }, "데이터를 먼저 고르면 그 데이터로 쓸 수 있는 문서 작업이 여기에 표시됩니다."),
    h("p", { className: "muted capnote" }, "쓸 작업을 이미 알고 있다면 「문서 작업」에서 고른 뒤 문서 만들기에서 사용을 누르세요."),
    h("button", { className: "btn sm", id: "jobPickInLibrary", type: "button",
      onClick: () => props.controller.navigation.go("library") }, "「문서 작업」에서 고르기"));
}

export function JobCandidates(props: { controller: JobReadController }): ReactNode {
  const snapshot = useJob(props.controller);
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
        ? h("span", { className: "muted" }, "이 데이터에 연결된 문서 작업이 없습니다.",
          h("button", { className: "btn sm", type: "button", "data-cands-exit": true,
            onClick: () => props.controller.navigation.go("library") }, "「문서 작업」에서 고르기"))
        : cards,
      bits.length ? h("span", { className: "cand-more muted" }, ...bits, " — ",
        h("button", { className: "btn sm", type: "button", id: "jobBrowseOpen", "data-browse-open": true,
          "data-busy-lock": true, onClick: (event: Obj) => { void props.controller.openBrowse(event.currentTarget); } }, "문서 작업 찾기…")) : null,
      h("span", { className: "cand-newwork" }, h(NewWorkButton as any, { snapshot, controller: props.controller })),
      candidates.txt_note ? h("div", { className: "cand-sec", "data-cand-mode": "text" },
        h("h3", { className: "cand-sec-cap" }, "온나라 기안"), h("span", { className: "muted" }, candidates.txt_note)) : null));
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
  if (snapshot === null) return h("div", { className: "sheet-card" }, "작업 목록을 읽는 중…");
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
  return h("div", { className: "sheet-card browse-sheet" },
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

/** static data-sheet shell의 닫기 버튼을 React 수명주기에 결속한다. */
export function JobReadEffects(props: { controller: JobReadController; closeButton: HTMLElement }): null {
  useEffect(() => {
    const close = () => props.controller.closeDataSheet();
    props.closeButton.addEventListener("click", close);
    return () => props.closeButton.removeEventListener("click", close);
  }, [props.controller, props.closeButton]);
  return null;
}

/** raw store 하류 model 하나를 legacy run remainder에 fan-out하는 임시 포트. */
export function createJobRunAdapter(args: {
  model: ScreenModel<JobScreenModel>;
  beforePreview(): Promise<void>;
  openPreview(request?: PreviewRequest): Promise<void>;
}) {
  let callbacks: JobRunCallbacks | null = null;
  let release: (() => void) | null = null;
  let lastFull: unknown = null;
  let lastProgress: unknown = null;

  function acceptFull(snapshot: unknown): void {
    if (callbacks === null) throw new Error("JobRunPort: attach 전 full 전달입니다.");
    callbacks.onFull(snapshot);
  }

  function acceptProgress(progress: unknown): void {
    if (callbacks === null) throw new Error("JobRunPort: attach 전 progress 전달입니다.");
    callbacks.onProgress(progress);
  }

  function pump(): void {
    const next = args.model.getSnapshot();
    if (next.full !== null && next.full !== lastFull) {
      lastFull = next.full;
      lastProgress = null;
      acceptFull(next.full);
    }
    if (next.progress !== null && next.progress !== lastProgress) {
      lastProgress = next.progress;
      acceptProgress(next.progress);
    }
  }

  return {
    attach(next: JobRunCallbacks): () => void {
      if (callbacks !== null || release !== null) throw new Error("JobRunPort: run callback은 정확히 한 번 attach합니다.");
      callbacks = next;
      release = args.model.subscribe(pump);
      pump();
      return () => {
        if (release === null) throw new Error("JobRunPort: attach release는 정확히 한 번입니다.");
        release();
        release = null;
        callbacks = null;
      };
    },
    acceptFull,
    acceptProgress,
    async openPreview(request?: PreviewRequest): Promise<void> {
      if (request !== undefined) {
        const keys = Object.keys(request);
        if (keys.some((key) => key !== "at" && key !== "focusTarget")) {
          throw new Error(`JobRunPort: 알 수 없는 preview 요청 키입니다: ${keys.join(", ")}`);
        }
      }
      await args.beforePreview();
      await args.openPreview(request);
    },
    dispose(): void {
      if (release !== null) release();
      release = null;
      callbacks = null;
    },
  };
}
