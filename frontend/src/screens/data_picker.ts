/* R4-01 데이터 선택·pool registration React 표면. session/loading/status와 settle-once는
   controller가 소유하고, 두 modal의 content DOM과 모든 이벤트는 React가 소유한다. */
import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import type { BridgeClient } from "../runtime/client.ts";
import { createContextMenu } from "./context_menu.ts";
import type { ContextMenuPopoverPort } from "./context_menu.ts";
import { invokePathAction } from "./path_actions.ts";
import { createRegistrationForm } from "./data_picker_registration.ts";
import { pickDataFile } from "./data_file_pick.ts";
import { SESSION_DATA_KEY } from "./pool_column.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import {
  POOL_DATA_GONE, createPoolVerbs, dataRowMenuItems,
  pclmSheetEditOptions, poolRefusalText,
} from "./pool_verbs.ts";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
  open(id: string, spec?: Obj): void;
  close(id: string): void;
};

/** 「지금 쓰는 데이터」의 재진술 — **Python 값 두 개**다(고르기 열 공용 ③b).
 *
 *  종전에는 여는 쪽이 라벨·부제·경로·시트·종류를 조립한 `current` 카드 값을 넘겼고, 이 면이
 *  그것으로 카드를 그렸다 — 같은 사실을 Python(`data_target`·`record_count`)과 웹이 각자
 *  성형하던 자리다. 지금 넘어오는 것은 스냅샷이 낸 행 하나와 그 마운트의 풀 슬롯 키뿐이고,
 *  문안은 한 글자도 여기서 짓지 않는다.
 *
 *  **함수로 받는다**: 이 면 안에서 「파일 찾아보기…」가 성사하면 그 순간 마운트가 바뀌고
 *  작업 스냅샷이 다시 온다. 여는 순간의 값을 얼려 두면 목록 맨 위 행이 **이제는 쓰지 않는
 *  데이터**를 「사용 중」이라 말한다(조용히 틀리는 자리). */
export type PickerSessionRead = () => {
  /** 공용 열 행(키 `session`) — 마운트가 없으면 `null`. */
  data_row: Obj | null;
  /** 그 마운트가 풀 슬롯에서 왔으면 그 키, 아니면 `""`. */
  data_pool_key: string;
  /** 「이 데이터 등록…」 프리필의 시트 자리(`data_target.sheet`). */
  sheet: string;
};

export type DataPickerOpenOptions = {
  screen: string;
  session?: PickerSessionRead;
  confirmSwap?: () => Promise<boolean>;
  onLoaded?: (label: string) => void;
  trigger?: HTMLElement;
};

/** 여는 쪽이 세션 값을 주지 않았을 때 — **비어 있음을 명시**한다(추측 금지). */
const NO_SESSION_DATA: PickerSessionRead = () => (
  { data_row: null, data_pool_key: "", sheet: "" }
);

type Session = {
  screen: string;
  read: PickerSessionRead;
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
  /** 등록 데이터 상세 시트가 지금 화면을 덮고 있는가 — **동사 결과의 채널**이 이 사실로
   *  갈린다(tpl 시트 리뷰 3 과 같은 근거): 시트가 스크림을 세우는 동안 이 면의 상태줄에
   *  쓴 문장은 그 뒤에 그려진다. */
  detailOpen: boolean;
  /** 그 시트 안에 서는 실패 재진술(`#poolDetailMsg`). */
  detailMessage: string;
};

export function createDataPickerController(args: {
  doc: Document;
  runtime: ScreenRuntime;
  client: BridgeClient;
  services: ServiceHandoffPorts;
  modal: ModalPort;
  /** 행 ⋯ 팝오버의 배치·전역 dismissal — 공용 `Popover` 하나가 소유한다(좌표 재발명 0). */
  popover: ContextMenuPopoverPort;
  notify(message: string): void;
}) {
  const { client, services, modal, notify } = args;
  const poolModel = args.runtime.model<Obj | null>("pool");
  let state: PickerState = {
    session: null, loading: false, status: "", level: "",
    detailOpen: false, detailMessage: "",
  };
  const listeners = new Set<Listener>();

  function emit(): void { for (const listener of [...listeners]) listener(); }
  function patch(next: Partial<PickerState>): void { state = { ...state, ...next }; emit(); }

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
      /* 응답 해석은 편집기 입구와 한 벌이다 — 계약 목록 파일(.db·.pclm)은 Python 이 등록
         갈래로 돌려주고 그때 여기서 DB 자리를 채운 등록 폼이 열린다(지금 데이터는 그대로). */
      const picked = await pickDataFile(invoke, session.screen, {
        sheetPicker: services.sheetPicker.current(), openContractList: openPclm,
      });
      if (picked.kind === "sheet_cancelled") {
        patch({ status: "시트 선택을 취소했습니다 — 데이터는 그대로입니다.", level: "" });
        return;
      }
      if (picked.kind === "error") {
        patch({ status: `⚠ 파일을 읽을 수 없습니다: ${picked.message}`, level: "danger" });
        return;
      }
      if (picked.kind === "none") { patch({ status: "", level: "" }); return; }
      const result = picked.value;
      /* 「지금 쓰는 데이터」는 여기서 다시 짓지 않는다(③b): 마운트는 이미 Python 에서
         성사했고 그 재진술은 작업 스냅샷의 `data_row` 가 든다 — 세션은 그 값을 **읽는
         함수**만 들고 있으므로 다음 렌더가 저절로 새 행을 그린다. */
      const nextSession = {
        ...session,
        mounted: result.label,
        /* 파일 mount 성공은 여기서 즉시 한 번 알린다. 이후 닫기는 session settle만 하고
           같은 onLoaded를 다시 부르지 않는다. */
        onLoaded: null,
      };
      patch({
        session: nextSession,
        status: `${result.label} — ${result.rows}건을 불러왔습니다. 이대로 쓰려면 [닫기], 자주 쓰는 파일이면 「이 데이터 등록…」으로 남겨 두세요.`,
        level: "ok",
      });
      session.onLoaded?.(result.label);
    } catch (error) {
      patch({ status: `⚠ 파일을 읽을 수 없습니다:\n${String(error)}`, level: "danger" });
    } finally {
      patch({ loading: false });
    }
  }

  /* 등록 폼(`#poolRegModal`) 상태는 `data_picker_registration.ts` 로 분리했다(복잡도
     예산 — module_statements 상한). 이 폼은 「지금 마운트된 데이터」(`state`)와 독립적인
     가변 상태라 깨끗이 나뉜다 — 여는 쪽이 프리필 값을 다 채워 넘긴다. */
  const registrationForm = createRegistrationForm({
    doc: args.doc,
    modal,
    dispatch,
    pickPoolDataFile: () => invoke("pick_pool_data_file"),
    notify,
    refreshScreen: (screen) => args.runtime.refresh(screen),
  });
  const { openRegDialog, patchReg } = registrationForm;

  /** 「이 데이터 등록…」 — 프리필 재료는 **전부 Python 값**이다(③b): 이름·경로는 세션 행,
   *  시트는 마운트 대상 재진술(`data_target.sheet`)이다. 웹이 라벨을 다시 쪼개거나 경로
   *  모양으로 시트를 되추측하지 않는다. */
  function openPin(): void {
    const seen = state.session?.read() ?? NO_SESSION_DATA();
    const row = seen.data_row;
    if (!row?.path) return;
    openRegDialog({
      title: "이 데이터 등록", okLabel: "등록", name: String(row.name || ""),
      path: String(row.path), sheet: seen.sheet || "", pinMode: true,
    });
  }

  /* 계약 목록 등록 — 파일 고르기가 돌려준 DB 자리(`.db`·`.pclm`)를 채워 연다. 그 DB 의
     시트는 백엔드가 그 자리에서 나열한다(`inspect_sheets`) — 웹은 경로도 시트 목록도
     리터럴로 들지 않는다. */
  function openPclm(db: string): void {
    openRegDialog({ title: "계약 목록 등록", okLabel: "등록", mode: "pclm", db, view: "" });
  }

  /* 동사 한 벌은 **고르기 화면과 공유**한다(U6-B #976 · 공용 ⑤ 리뷰) — 같은 `pool` 채널,
     같은 확인 왕복, 같은 지문 되싣기, 같은 분기표·검토 왕복·통지 동사. 갈리는 것은 실패가
     착지하는 자리와 네 포트뿐이라 그것만 주입한다. */
  const poolVerbs = createPoolVerbs({
    dispatch,
    modal,
    onError: refuseVerb,
    onUse: (row: Obj) => mountPinned(row.key, row.name),
    /* 프리필 재료는 **검토 왕복이 낸 상세 투영**이다(고르기 열 공용 ④) — 키 이름도
       그 투영 그대로(`path`·`sheet`·`note`)다. */
    openRelink: (row: Obj) => openRegDialog({
      title: "데이터 다시 연결", okLabel: "다시 연결", targetKey: row.key,
      name: row.name, path: row.path, sheet: row.sheet, sheets: row.sheets, note: row.note,
    }),
    openPclmSheets: (row: Obj) => {
      const owner = state.session?.screen;
      openRegDialog({ ...pclmSheetEditOptions(row),
        refreshScreen: owner === "job" || owner === "editor" ? owner : "" });
    },
    poolSnapshot: () => poolModel.getSnapshot() as Obj | null,
    reveal: (path: string) => invokePathAction({
      client, path, action: "reveal", notify,
    }),
    /* 시트의 주인이 이 컨트롤러다 — 고르기 화면은 `PoolRegistrationPort` 로 같은 문을 부른다. */
    openDetail: (key: string, trigger: HTMLElement | null) => openDetail(key, trigger),
    busyReason: () => (
      state.loading ? "불러오는 중입니다. 끝날 때까지 닫을 수 없습니다." : ""
    ),
  });
  const { poolAction, resolveDuplicate } = poolVerbs;

  function refuse(message: string): void {
    patch({ status: `⚠ ${message}`, level: "danger" });
  }

  /** 동사 실패의 착지 — 시트가 열려 있으면 **시트 안**, 아니면 이 면의 상태줄(tpl 미러).
   *
   *  같은 문장을 두 자리에 쓰지 않는다: 읽는 사람이 지금 보고 있는 면에 남긴다. */
  function refuseVerb(message: string): void {
    if (state.detailOpen) patch({ detailMessage: message });
    else refuse(message);
  }

  /** 열 행 하나를 고름 — **클릭 하나가 1차 동사**다(③b: 종전의 행 안 「이 데이터 사용」 버튼).
   *
   *  세션 행은 무동작이다(이미 이 화면이 쓰고 있는 데이터다 — 거절도 발신도 없다). 못 고르는
   *  행은 조용히 삼키지 않고 이름과 **Python 사유**로 재진술한다(문형은 고르기 화면과 공용). */
  function choose(key: string): void {
    if (key === SESSION_DATA_KEY) return;
    const row = columnRows().find((entry) => String(entry.key) === key);
    if (row === undefined) { refuse(POOL_DATA_GONE); return; }
    if (!row.selectable) {
      refuse(poolRefusalText(String(row.name), String(row.reason || "")));
      return;
    }
    void poolAction("use", row);
  }

  function columnRows(): Obj[] {
    return (((poolModel.getSnapshot() || {}).column || {}).rows || []) as Obj[];
  }

  /* 행 ⋯ — 고르기 화면과 **같은 공용 팝오버 컴포넌트**를 이 면의 좌표로 한 벌 더 세운다.
     열림 정체가 화면마다 갈리므로(같은 슬롯 키가 두 면에 동시에 서 있을 수 있다) 컨트롤러도
     각자 든다. 항목 목록은 링1 동사 + 「폴더에서 보기」이고 이 파일이 동사를 발명하지 않는다. */
  const rowContextMenu = createContextMenu();
  let menuRow: Obj | null = null;
  /** 시트를 닫을 때 초점이 돌아갈 자리 — 메뉴를 연 그 ⋯ 다(초점이 문서 처음으로 튀지 않게). */
  let menuTrigger: HTMLElement | null = null;

  function closeRowMenu(): void {
    menuRow = null;
    menuTrigger = null;
    rowContextMenu.close();
  }

  function toggleRowMenu(row: Obj, trigger: HTMLElement): void {
    if (menuRow !== null && String(menuRow.key) === String(row.key)) { closeRowMenu(); return; }
    /* 목록은 **공용 함수 하나**가 짓는다(고르기 열 공용 ④) — 고르기 우 열과 같은 행을
       그리므로 그 ⋯ 도 같은 목록이어야 한다. 이 파일이 동사를 발명하지 않는다. */
    const items = dataRowMenuItems(row);
    /* 빈 팝오버는 「눌렀는데 아무 일도 없다」라서 조용한 no-op 이다 — 열지 않는다. */
    if (items.length === 0) return;
    menuRow = row;
    menuTrigger = trigger;
    rowContextMenu.open(trigger, items);
  }

  async function handleRowMenu(action: string): Promise<void> {
    const row = menuRow;
    const trigger = menuTrigger;
    if (row === null) return;
    closeRowMenu();
    try {
      /* 분기표는 **공용 몸통 하나**다(공용 ⑤ 리뷰) — 이 면이 동사를 발명하지 않는다.
         갈리는 것은 던진 것을 받는 자리뿐이고, 그 자리가 여기다. */
      await poolVerbs.runVerb(action, row, trigger);
    } catch (error) {
      refuse(String((error as Obj)?.message || error));
    }
  }

  /* ---- 등록 데이터 상세 시트(`#poolDetailModal` — 고르기 열 공용 ④) ----------------
     시트의 주인이 이 컨트롤러인 이유는 등록 폼과 같다: overlay 는 셸 레벨 하나이고 그것을
     여는 문이 둘(고르기 우 열·이 다이얼로그)이라, 두 번째 구현을 세우면 동사의 착지와
     메시지 채널이 갈린다. 고르기 화면은 `PoolRegistrationPort` 로 이 문을 부른다. */

  /** 「자세히…」 — 검토 왕복이 시트의 재료를 채우고 **그 뒤에** 시트를 연다(tpl 미러).
   *
   *  순서가 계약이다: 먼저 열면 지난 항목의 상세가 한 프레임 서 있다가 갈리고, 검토가
   *  거절되면 빈 시트만 남는다. 검토 왕복 자체(키 대조 포함)는 공용 몸통이 진다. */
  async function openDetail(key: string, trigger: HTMLElement | null): Promise<void> {
    const detail = await poolVerbs.review(key);
    if (detail === null) return;
    patch({ detailOpen: true, detailMessage: "" });
    modal.open("poolDetailModal", {
      initialFocus: args.doc.getElementById("poolDetailClose"),
      returnFocus: trigger || undefined,
      beforeClose: () => {
        patch({ detailOpen: false, detailMessage: "" });
        return true;
      },
    });
  }

  /** 시트의 동사 줄 — 행 ⋯ 와 **같은 분기표**를 지난다(같은 상태 두 곳 판정 금지).
   *
   *  겨누는 것은 지금 시트가 그리는 상세다: 그 사이 항목이 사라졌으면 상세도 걷혔으므로
   *  시트가 빈 면이 되고, 여기서는 사유를 남긴다(조용한 무동작 금지). */
  async function handleDetailVerb(
    action: string, trigger: HTMLElement | null,
  ): Promise<void> {
    const detail = ((poolModel.getSnapshot() || {}).detail || null) as Obj | null;
    if (detail === null) {
      refuseVerb(POOL_DATA_GONE);
      return;
    }
    try {
      await poolVerbs.runVerb(action, detail, trigger);
    } catch (error) {
      refuseVerb(String((error as Obj)?.message || error));
    }
  }

  function closeDetail(): void { modal.close("poolDetailModal"); }

  return {
    init(): Promise<unknown> { return args.runtime.loadInitial("pool"); },
    poolModel,
    model: {
      getSnapshot: () => state,
      subscribe(listener: Listener): () => void { listeners.add(listener); return () => { listeners.delete(listener); }; },
    },
    regModel: registrationForm.regModel,
    open(options: DataPickerOpenOptions): Promise<string | null> {
      if (state.session !== null) return Promise.reject(new Error("데이터 선택 창이 이미 열려 있습니다."));
      return new Promise((resolve) => {
        patch({
          session: {
            screen: options.screen,
            read: options.session || NO_SESSION_DATA,
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
          patch({ status: `⚠ 등록한 데이터를 읽을 수 없습니다: ${String(error)}`, level: "danger" });
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
    choose,
    /** 「새로 읽기」 — 다른 표면(CLI 등록·고르기 화면)의 변경을 되읽는다. 좌 열·우 열과
     *  같은 액션 하나다(이 면만의 재조회 경로를 만들지 않는다). */
    refresh: (): Promise<Obj> => dispatch("pool", "refresh", {}),
    poolAction,
    resolveDuplicate,
    noticeAction: poolVerbs.noticeAction,
    rowContextMenu,
    toggleRowMenu,
    closeRowMenu,
    handleRowMenu,
    /* 등록 데이터 상세 시트 — 고르기 화면도 `PoolRegistrationPort` 로 이 셋을 부른다. */
    openDetail,
    closeDetail,
    handleDetailVerb,
    popover: args.popover,
    openRegDialog,
    patchReg,
    inspectRegSheets: registrationForm.inspectRegSheets,
    selectRegSheets: registrationForm.selectRegSheets,
    closeReg: registrationForm.closeReg,
    browseRegPath: registrationForm.browseRegPath,
    submitReg: registrationForm.submitReg,
    client,
    notify,
  };
}

export type DataPickerController = ReturnType<typeof createDataPickerController>;

/** 이 다이얼로그의 렌더(`dialogHost`·`DataPickerDialog`)는 `data_picker_dialog.ts` 로
 *  옮겼다(복잡도 예산 — module_statements 상한). 컨트롤러(상태·발신)는 여기 그대로 둔다 —
 *  `product_screens.ts` 가 이 이름으로 그대로 가져오므로 재-export 한다. */
export { DataPickerDialog } from "./data_picker_dialog.ts";
export { PoolRegistrationDialog } from "./registration_dialog.ts";
