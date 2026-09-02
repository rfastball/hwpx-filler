/* R4-01 데이터 선택·pool registration React 표면. session/loading/status와 settle-once는
   controller가 소유하고, 두 modal의 content DOM과 모든 이벤트는 React가 소유한다. */
import { createElement, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import type { BridgeClient } from "../runtime/client.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import { PCLM_UNAVAILABLE, PoolSections, createPoolVerbs } from "./pool_list.ts";
import type { PoolListHost } from "./pool_list.ts";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
  open(id: string, spec?: Obj): void;
  close(id: string): void;
};

export type DataPickerOpenOptions = {
  screen: string;
  current?: Obj;
  confirmSwap?: () => Promise<boolean>;
  onLoaded?: (label: string) => void;
  trigger?: HTMLElement;
};

type Session = {
  screen: string;
  current: Obj;
  confirmSwap: () => Promise<boolean>;
  onLoaded: ((label: string) => void) | null;
  mounted: string;
  resolve: (label: string | null) => void;
};

type PickerState = {
  session: Session | null;
  loading: boolean;
  status: string;
  level: "" | "ok" | "danger";
};

/* 등록면은 종류를 **명시로** 든다(#937). `mode` 가 없으면 표면이 어느 좌표를 물어야 할지를
   path 유무 같은 모양으로 되추측하게 되고, 그러면 같은 판정이 두 곳에 산다. 엑셀은
   경로+시트, 계약 목록은 DB+뷰 — 좌표가 다를 뿐 확인 왕복(needs_confirm/basis)은 한 벌이다. */
type RegState = {
  title: string;
  okLabel: string;
  mode: "excel" | "pclm";
  name: string;
  path: string;
  sheet: string;
  db: string;
  view: string;
  note: string;
  targetKey: string;
  pinMode: boolean;
  error: string;
};

/** 시트 미선택 placeholder — 목록 첫 항목을 기본으로 세우지 않는다(사용자가 확정할 값이다). */
const PCLM_VIEW_PLACEHOLDER = "시트를 고르세요";

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

export function createDataPickerController(args: {
  doc: Document;
  runtime: ScreenRuntime;
  client: BridgeClient;
  services: ServiceHandoffPorts;
  modal: ModalPort;
  notify(message: string): void;
}) {
  const { client, services, modal, notify } = args;
  const poolModel = args.runtime.model<Obj | null>("pool");
  let state: PickerState = { session: null, loading: false, status: "", level: "" };
  let reg: RegState | null = null;
  const listeners = new Set<Listener>();
  const regListeners = new Set<Listener>();

  function emit(): void { for (const listener of [...listeners]) listener(); }
  function emitReg(): void { for (const listener of [...regListeners]) listener(); }
  function patch(next: Partial<PickerState>): void { state = { ...state, ...next }; emit(); }
  function patchReg(next: Partial<RegState>): void {
    if (reg === null) return;
    reg = { ...reg, ...next };
    emitReg();
  }

  const dispatch = async (screen: string, action: string, payload: Obj = {}): Promise<Obj> => {
    const call = client.dispatch as unknown as (
      channel: string, name: string, body: Obj,
    ) => ReturnType<BridgeClient["dispatch"]>;
    return (expectHostValue(await call(screen, action, payload), `${screen}/${action}`) ?? {}) as Obj;
  };

  async function invoke(method: Parameters<BridgeClient["invoke"]>[0], ...payload: unknown[]): Promise<any> {
    return expectHostValue(await client.invoke(method, ...payload), method);
  }

  function finish(label: string | null): void {
    const session = state.session;
    if (session === null) return;
    patch({ session: null, loading: false, status: "", level: "" });
    modal.close("dataPickerModal");
    if (label && session.onLoaded) session.onLoaded(label);
    session.resolve(label);
  }

  async function mountPinned(key: string, name: string): Promise<void> {
    const session = state.session;
    if (state.loading || session === null) return;
    if (!(await session.confirmSwap())) return;
    patch({ loading: true, status: `${name} 읽는 중…`, level: "" });
    try {
      const result = await dispatch(session.screen, "load_pool", { key });
      if (result.ok) { finish(result.label || name); return; }
      patch({ status: `⚠ ${result.error || "등록 데이터를 불러올 수 없습니다."}`, level: "danger" });
    } catch (error) {
      patch({ status: `⚠ 등록 데이터를 불러올 수 없습니다:\n${String(error)}`, level: "danger" });
    } finally {
      if (state.session !== null) patch({ loading: false });
    }
  }

  async function browseFile(): Promise<void> {
    const session = state.session;
    if (state.loading || session === null) return;
    if (!(await session.confirmSwap())) return;
    patch({ loading: true, status: "파일 선택 창에서 파일을 고르세요…", level: "" });
    try {
      let result = await invoke("pick_data_file", session.screen);
      if (result && typeof result === "object" && result.needs_sheet) {
        result = await services.sheetPicker.current().choose(session.screen, result);
        if (result === null) {
          patch({ status: "시트 선택을 취소했습니다 — 데이터는 그대로입니다.", level: "" });
          return;
        }
      }
      if (result === null) { patch({ status: "", level: "" }); return; }
      if (typeof result === "string" && result.startsWith("ERROR:")) {
        patch({ status: `⚠ 파일을 읽을 수 없습니다: ${result.slice(6).trim()}`, level: "danger" });
        return;
      }
      const nextSession = {
        ...session,
        mounted: result.label,
        /* 파일 mount 성공은 여기서 즉시 한 번 알린다. 이후 닫기는 session settle만 하고
           같은 onLoaded를 다시 부르지 않는다. */
        onLoaded: null,
        current: {
          label: result.label, detail: `${result.rows}건`, path: result.path,
          // 파일 찾아보기가 낳는 마운트는 늘 엑셀/CSV 다 — 종류를 비워 두지 않고 명시한다.
          sheet: result.sheet || "", origin: "file", kind: "",
        },
      };
      patch({
        session: nextSession,
        status: `${result.label} — ${result.rows}건을 불러왔습니다. 이대로 쓰려면 [닫기], 자주 쓰는 파일이면 「이 데이터 고정…」으로 남겨 두세요.`,
        level: "ok",
      });
      session.onLoaded?.(result.label);
    } catch (error) {
      patch({ status: `⚠ 파일을 읽을 수 없습니다:\n${String(error)}`, level: "danger" });
    } finally {
      patch({ loading: false });
    }
  }

  function openRegDialog(options: Partial<RegState>): void {
    reg = {
      title: options.title || "데이터 등록",
      okLabel: options.okLabel || "등록",
      mode: options.mode || "excel",
      name: options.name || "",
      path: options.path || "",
      sheet: options.sheet || "",
      db: options.db || "",
      view: options.view || "",
      note: options.note || "",
      targetKey: options.targetKey || "",
      pinMode: !!options.pinMode,
      error: "",
    };
    emitReg();
    const focusId = reg.mode === "pclm" || options.pinMode ? "poolRegName" : "poolRegPath";
    modal.open("poolRegModal", { initialFocus: args.doc.getElementById(focusId) });
  }

  function openPin(): void {
    const current = state.session?.current;
    if (!current?.path) return;
    openRegDialog({
      title: "이 데이터 고정", okLabel: "고정", name: current.label,
      path: current.path, sheet: current.sheet || "", pinMode: true,
    });
  }

  /* 계약 목록 등록 — 물어야 할 두 좌표(기본 DB 자리·고를 수 있는 뷰)는 **스냅샷이 준다**.
     웹이 뷰 목록이나 기본 경로를 리터럴로 들면 링0 허용목록이 늘 때 한쪽만 늙는다.
     블록이 아직 없으면 열지 않고 사유를 말한다(조용한 무반응 금지) — 버튼도 같은
     판정으로 비활성이라 정상 경로에서는 여기 닿지 않는다. */
  function openPclm(): void {
    const block = poolModel.getSnapshot()?.pclm;
    if (!block) { patch({ status: `⚠ ${PCLM_UNAVAILABLE}`, level: "danger" }); return; }
    openRegDialog({
      title: "계약 목록 등록", okLabel: "등록", mode: "pclm",
      db: String(block.default_db || ""), view: "",
    });
  }

  async function submitReg(): Promise<void> {
    if (reg === null) return;
    const pclm = reg.mode === "pclm";
    const action = pclm ? "register_pclm" : reg.targetKey ? "relink" : "register_excel";
    const payload: Obj = pclm
      ? { name: reg.name.trim(), db: reg.db.trim(), view: reg.view, note: reg.note.trim() }
      : {
        name: reg.name.trim(), path: reg.path.trim(), sheet: reg.sheet.trim(), note: reg.note.trim(),
      };
    if (!pclm && reg.targetKey) payload.key = reg.targetKey;
    if (pclm) {
      /* 빈 뷰는 백엔드가 「약속한 뷰가 아닙니다」로 거절하지만, 사용자가 아직 **고르지
         않은 것**과 **틀리게 고른 것**은 다른 사건이라 여기서 그 말로 막는다. db 는
         비어도 된다(백엔드가 「기본 자리」로 해석) — 폼은 그 자리를 미리 보여 준다. */
      if (!payload.name) { patchReg({ error: "이름을 입력하세요." }); return; }
      if (!payload.view) {
        patchReg({ error: "읽을 시트를 고르세요." });
        return;
      }
    } else if (!payload.name || !payload.path) {
      patchReg({ error: "이름과 파일 경로를 입력하세요." });
      return;
    }
    try {
      let result = await dispatch("pool", action, payload);
      if (result.needs_confirm) {
        const accepted = await modal.confirm({
          body: result.confirm_text, confirmLabel: reg.okLabel, cancelLabel: "취소", danger: true,
        });
        if (!accepted) return;
        result = await dispatch("pool", action, { ...payload, confirm: true, basis: result.basis });
      }
      if (result.ok === false) { patchReg({ error: result.error || "등록하지 못했습니다." }); return; }
      modal.close("poolRegModal");
      reg = null;
      emitReg();
    } catch (error) {
      patchReg({ error: String((error as Obj)?.message || error) });
    }
  }

  /* 관리 동사 한 벌은 **고르기 화면과 공유**한다(U6-B #976) — 같은 `pool` 채널, 같은
     확인 왕복, 같은 지문 되싣기. 갈리는 것은 실패가 착지하는 자리와 「사용」의 몸통뿐이라
     그 둘만 주입한다. */
  const { poolAction, resolveDuplicate } = createPoolVerbs({
    dispatch,
    modal,
    onError: (message: string) => { patch({ status: `⚠ ${message}`, level: "danger" }); },
    onUse: (row: Obj) => mountPinned(row.key, row.name),
    openRelink: (row: Obj) => openRegDialog({
      title: "데이터 다시 연결", okLabel: "다시 연결", targetKey: row.key,
      name: row.name, path: row.locate_path, sheet: row.sheet, note: row.note,
    }),
    busyReason: () => (
      state.loading ? "불러오는 중입니다. 끝날 때까지 닫을 수 없습니다." : ""
    ),
  });

  return {
    init(): Promise<unknown> { return args.runtime.loadInitial("pool"); },
    poolModel,
    model: {
      getSnapshot: () => state,
      subscribe(listener: Listener): () => void { listeners.add(listener); return () => { listeners.delete(listener); }; },
    },
    regModel: {
      getSnapshot: () => reg,
      subscribe(listener: Listener): () => void { regListeners.add(listener); return () => { regListeners.delete(listener); }; },
    },
    open(options: DataPickerOpenOptions): Promise<string | null> {
      if (state.session !== null) return Promise.reject(new Error("데이터 선택 창이 이미 열려 있습니다."));
      return new Promise((resolve) => {
        patch({
          session: {
            screen: options.screen,
            current: options.current || {},
            confirmSwap: options.confirmSwap || (() => Promise.resolve(true)),
            onLoaded: options.onLoaded || null,
            mounted: "",
            resolve,
          },
          loading: false, status: "", level: "",
        });
        modal.open("dataPickerModal", {
          initialFocus: args.doc.getElementById("dataPickerClose"),
          beforeClose: () => {
            if (!state.loading) return true;
            patch({ status: "⚠ 불러오는 중입니다. 끝날 때까지 닫을 수 없습니다.", level: "danger" });
            return false;
          },
          onClose: () => finish(state.session?.mounted || null),
        });
        void dispatch("pool", "refresh", {}).catch((error) => {
          patch({ status: `⚠ 고정한 데이터를 읽을 수 없습니다: ${String(error)}`, level: "danger" });
        });
      });
    },
    close(): void {
      if (state.loading) {
        patch({ status: "⚠ 불러오는 중입니다. 끝날 때까지 닫을 수 없습니다.", level: "danger" });
        return;
      }
      finish(state.session?.mounted || null);
    },
    browseFile,
    openPin,
    openPclm,
    poolAction,
    resolveDuplicate,
    openRegDialog,
    patchReg,
    closeReg(): void { modal.close("poolRegModal"); reg = null; emitReg(); },
    browseRegPath: async (): Promise<void> => {
      const path = await invoke("pick_pool_data_file");
      if (path) patchReg({ path: String(path) });
    },
    submitReg,
    client,
    notify,
  };
}

export type DataPickerController = ReturnType<typeof createDataPickerController>;

/** 이 다이얼로그가 몸통에 넘기는 호스트 포트 — 갈리는 것은 라벨·발행·id 접두 셋뿐이다.
 *
 *  좌표는 **불변**이다(`#dataPickerCurrent`·`#dataPickerPinned`·`#dataPickerBrowse`…):
 *  이 화면을 겨눈 게이트가 이미 있고, 몸통을 공유한다는 것이 그 좌표를 바꿀 이유가 되지
 *  않는다. 그래서 접두는 종전 id 를 글자 그대로 재생산한다. */
function dialogHost(controller: DataPickerController, current: Obj): PoolListHost {
  return {
    idPrefix: "dataPicker",
    chooseLabel: "이 데이터 사용",
    onChoose: (row: Obj) => { void controller.poolAction("use", row); },
    current,
    /* 다이얼로그는 「지금 고른 것」을 겨눔 키가 아니라 「현재 데이터」 카드로 말한다 —
       세션이 슬롯 키를 들고 다니지 않으므로 여기서 지어내지 않는다(추측 금지). */
    currentKey: "",
    openPin: controller.openPin,
    browse: () => { void controller.browseFile(); },
    openPclm: controller.openPclm,
    poolAction: (action: string, row: Obj) => { void controller.poolAction(action, row); },
    resolveDuplicate: (keep: string) => { void controller.resolveDuplicate(keep); },
    client: controller.client,
    notify: controller.notify,
  };
}

export function DataPickerDialog(props: { controller: DataPickerController }): ReactNode {
  const { controller } = props;
  /* 세 번째 인자(getServerSnapshot)를 같은 getter 로 넘긴다(`EditorScreen` 선례): 제품
     런타임은 쓰지 않지만, 없으면 이 면이 `react-dom/server` 로 한 번도 렌더되지 못해
     노드 배치 계약을 단위층에서 잴 수 없다. */
  const state = useSyncExternalStore(
    controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot);
  const pool = useSyncExternalStore(
    controller.poolModel.subscribe, controller.poolModel.getSnapshot,
    controller.poolModel.getSnapshot);
  const current = state.session?.current || {};
  return h("div", { className: "modal-card data-picker" },
    h("h3", { id: "dataPickerTitle" }, "데이터 선택"),
    h("p", { id: "dataPickerNote", className: `note ${state.level === "danger" ? "dangerbox" : state.level === "ok" ? "okbox" : ""}`,
      role: "status", "aria-live": "polite", style: { display: state.status ? "" : "none", whiteSpace: "pre-line" } }, state.status),
    h(PoolSections as any, { host: dialogHost(controller, current), pool }),
    h("div", { className: "modal-actions" },
      h("button", { className: "btn", id: "dataPickerClose", onClick: controller.close }, "닫기")));
}

export function PoolRegistrationDialog(props: { controller: DataPickerController }): ReactNode {
  const { controller } = props;
  const state = useSyncExternalStore(
    controller.regModel.subscribe, controller.regModel.getSnapshot,
    controller.regModel.getSnapshot);
  const pool = useSyncExternalStore(
    controller.poolModel.subscribe, controller.poolModel.getSnapshot,
    controller.poolModel.getSnapshot);
  const value = state || {
    title: "데이터 등록", okLabel: "등록", mode: "excel", name: "", path: "", sheet: "",
    db: "", view: "", note: "", targetKey: "", pinMode: false, error: "",
  };
  const pclm = value.mode === "pclm";
  /* 고를 수 있는 시트와 그 설명은 링0 단일 출처가 스냅샷으로 내려준 것만 쓴다(웹에 리터럴 0). */
  const views: Obj[] = (pool?.pclm?.views || []) as Obj[];
  return h("div", { className: "modal-card" },
    h("h3", { id: "poolRegTitle" }, value.title),
    h("label", { className: "ctl" }, h("span", { className: "lbl" }, "이름"),
      h("input", { className: "field", id: "poolRegName", type: "text", value: value.name,
        placeholder: "예: 7월 공고목록", onChange: (event: Obj) => controller.patchReg({ name: event.currentTarget.value }) })),
    pclm ? null : h("label", { className: "ctl" }, h("span", { className: "lbl" }, "파일 경로(.xlsx/.csv)"),
      h("span", { className: "row" }, h("input", { className: "field mono spacer", id: "poolRegPath", type: "text",
        value: value.path, readOnly: value.pinMode, onChange: (event: Obj) => controller.patchReg({ path: event.currentTarget.value }) }),
      h("button", { className: "btn", id: "poolRegBrowse", type: "button", hidden: value.pinMode,
        onClick: () => { void controller.browseRegPath(); } }, "찾아보기…"))),
    pclm ? null : h("label", { className: "ctl" }, h("span", { className: "lbl" }, "시트(선택)"),
      h("input", { className: "field", id: "poolRegSheet", type: "text", value: value.sheet,
        readOnly: value.pinMode, onChange: (event: Obj) => controller.patchReg({ sheet: event.currentTarget.value }) })),
    /* DB 자리는 편집 가능하다 — 기본 자리를 프리필하되 다른 사본을 가리킬 수 있어야 한다.
       비우면 백엔드가 「기본 자리」로 해석해 opts 에 박는다(미기재로 두지 않는다). */
    pclm ? h("label", { className: "ctl" }, h("span", { className: "lbl" }, "DB 자리"),
      h("input", { className: "field mono", id: "poolRegDb", type: "text", value: value.db,
        onChange: (event: Obj) => controller.patchReg({ db: event.currentTarget.value }) })) : null,
    /* 시트는 **사용자가 확정**한다 — 목록 첫 항목을 기본으로 세우면 계약면이 조용히 섞여
       문서 건수가 어긋난다. 그래서 초기 선택은 빈 placeholder 이고, 빈 채 제출은 막는다.
       보이는 것은 제목과 설명이고 `value` 는 실제 뷰 이름이다 — 백엔드 계약이 그 이름이라
       표기만 사람 말로 옮긴다(내부 이름은 표면에 서지 않는다). */
    pclm ? h("label", { className: "ctl" }, h("span", { className: "lbl" }, "읽을 시트"),
      h("select", { className: "field", id: "poolRegView", value: value.view,
        onChange: (event: Obj) => controller.patchReg({ view: event.currentTarget.value }) },
      h("option", { value: "", key: "" }, PCLM_VIEW_PLACEHOLDER),
      ...views.map((view: Obj) => h("option", { value: String(view.name), key: String(view.name) },
        `${view.title} — ${view.desc}`)))) : null,
    h("label", { className: "ctl" }, h("span", { className: "lbl" }, "메모(선택)"),
      h("input", { className: "field", id: "poolRegNote", type: "text", value: value.note,
        onChange: (event: Obj) => controller.patchReg({ note: event.currentTarget.value }) })),
    h("p", { className: "note dangerbox", role: "alert", style: { display: value.error ? "" : "none" } }, value.error),
    h("div", { className: "modal-actions" },
      h("button", { className: "btn", id: "poolRegCancel", onClick: controller.closeReg }, "취소"),
      h("button", { className: "btn primary", id: "poolRegOk", onClick: () => { void controller.submitReg(); } }, value.okLabel)));
}
