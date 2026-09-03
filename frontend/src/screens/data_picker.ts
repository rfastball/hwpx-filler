/* R4-01 데이터 선택·pool registration React 표면. session/loading/status와 settle-once는
   controller가 소유하고, 두 modal의 content DOM과 모든 이벤트는 React가 소유한다. */
import { Fragment, createElement, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import type { BridgeClient } from "../runtime/client.ts";
import { ContextMenu, createContextMenu } from "./context_menu.ts";
import type { ContextMenuPopoverPort } from "./context_menu.ts";
import { invokePathAction } from "./path_actions.ts";
import { PoolColumn, SESSION_DATA_KEY } from "./pool_column.ts";
import type { PoolColumnHost } from "./pool_column.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import {
  PCLM_UNAVAILABLE, POOL_GONE_FROM_LIST, createPoolVerbs, dataRowMenuItems, poolRefusalText,
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
  /** 「이 데이터 고정…」 프리필의 시트 자리(`data_target.sheet`). */
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

  /** 「이 데이터 고정…」 — 프리필 재료는 **전부 Python 값**이다(③b): 이름·경로는 세션 행,
   *  시트는 마운트 대상 재진술(`data_target.sheet`)이다. 웹이 라벨을 다시 쪼개거나 경로
   *  모양으로 시트를 되추측하지 않는다. */
  function openPin(): void {
    const seen = state.session?.read() ?? NO_SESSION_DATA();
    const row = seen.data_row;
    if (!row?.path) return;
    openRegDialog({
      title: "이 데이터 고정", okLabel: "고정", name: String(row.name || ""),
      path: String(row.path), sheet: seen.sheet || "", pinMode: true,
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
    onError: refuseVerb,
    onUse: (row: Obj) => mountPinned(row.key, row.name),
    /* 프리필 재료는 **검토 왕복이 낸 상세 투영**이다(고르기 열 공용 ④) — 옛 `pool.rows`
       곁눈질이 사라진 자리다. 키 이름도 그 투영 그대로(`path`·`sheet`·`note`)다. */
    openRelink: (row: Obj) => openRegDialog({
      title: "데이터 다시 연결", okLabel: "다시 연결", targetKey: row.key,
      name: row.name, path: row.path, sheet: row.sheet, note: row.note,
    }),
    busyReason: () => (
      state.loading ? "불러오는 중입니다. 끝날 때까지 닫을 수 없습니다." : ""
    ),
  });

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
    if (row === undefined) { refuse(`데이터를 찾을 수 없습니다. ${POOL_GONE_FROM_LIST}`); return; }
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

  /** 행 동사 — **닫힌 집합**이다(모르는 키는 시끄럽게 거절한다).
   *
   *  프리필 재료를 **검토 왕복이 낸다**(고르기 열 공용 ④): 「다시 연결」은 `path`·`sheet`·
   *  `note` 를 요구하는데 공용 열 행은 그 셋을 들지 않는다. 종전에는 옛 `pool.rows` 를
   *  곁눈질했고, 그것이 같은 목록을 두 존으로 들던 마지막 자리였다. */
  async function runRowVerb(
    action: string, row: Obj, trigger: HTMLElement | null,
  ): Promise<void> {
    if (action === "reveal") {
      await invokePathAction({
        client, path: String(row.path || ""), action: "reveal", notify,
      });
      return;
    }
    const key = String(row.key || "");
    if (action === "detail") { await openDetail(key, trigger); return; }
    if (!action.startsWith("act:")) {
      throw new Error(`알 수 없는 데이터 동사입니다: ${action}`);
    }
    if (action === "act:relink") {
      const detail = await reviewPoolItem(key);
      if (detail === null) return;
      await poolAction("relink", detail);
      return;
    }
    await poolAction(action.slice(4), row);
  }

  async function handleRowMenu(action: string): Promise<void> {
    const row = menuRow;
    const trigger = menuTrigger;
    if (row === null) return;
    closeRowMenu();
    try {
      await runRowVerb(action, row, trigger);
    } catch (error) {
      refuse(String((error as Obj)?.message || error));
    }
  }

  /* ---- 등록 데이터 상세 시트(`#poolDetailModal` — 고르기 열 공용 ④) ----------------
     시트의 주인이 이 컨트롤러인 이유는 등록 폼과 같다: overlay 는 셸 레벨 하나이고 그것을
     여는 문이 둘(고르기 우 열·이 다이얼로그)이라, 두 번째 구현을 세우면 동사의 착지와
     메시지 채널이 갈린다. 고르기 화면은 `PoolRegistrationPort` 로 이 문을 부른다. */

  /** 검토 왕복 → 그 항목의 상세 투영(못 세우면 사유를 남기고 ``null``).
   *
   *  키 대조가 계약이다: 왕복 사이에 다른 push 가 끼면 스냅샷의 상세가 남의 항목일 수 있고,
   *  그 값을 프리필로 쓰면 사람이 겨눈 적 없는 등록을 덮어쓴다. */
  async function reviewPoolItem(key: string): Promise<Obj | null> {
    await dispatch("pool", "review", { key });
    const detail = ((poolModel.getSnapshot() || {}).detail || null) as Obj | null;
    if (detail === null || String(detail.key) !== key) {
      refuseVerb(`데이터를 찾을 수 없습니다. ${POOL_GONE_FROM_LIST}`);
      return null;
    }
    return detail;
  }

  /** 「자세히…」 — 검토 왕복이 시트의 재료를 채우고 **그 뒤에** 시트를 연다(tpl 미러).
   *
   *  순서가 계약이다: 먼저 열면 지난 항목의 상세가 한 프레임 서 있다가 갈리고, 검토가
   *  거절되면 빈 시트만 남는다. */
  async function openDetail(key: string, trigger: HTMLElement | null): Promise<void> {
    const detail = await reviewPoolItem(key);
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
      refuseVerb(`데이터를 찾을 수 없습니다. ${POOL_GONE_FROM_LIST}`);
      return;
    }
    try {
      await runRowVerb(action, detail, trigger);
    } catch (error) {
      refuseVerb(String((error as Obj)?.message || error));
    }
  }

  function closeDetail(): void { modal.close("poolDetailModal"); }

  /** 존 통지가 든 동사 — 지금은 중복 정리 하나다. **모르는 키는 시끄럽게 거절한다**:
   *  조용히 떨어뜨리면 Python 이 통지에 동사를 더한 날 「눌렀는데 아무 일도 없다」가 된다. */
  function noticeAction(key: string, payload: Obj): void {
    if (key === "resolve_duplicate") { void resolveDuplicate(String(payload.keep || "")); return; }
    refuse(`알 수 없는 통지 동사입니다: ${key}`);
  }

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
    choose,
    /** 「새로 읽기」 — 다른 표면(CLI 등록·고르기 화면)의 변경을 되읽는다. 좌 열·우 열과
     *  같은 액션 하나다(이 면만의 재조회 경로를 만들지 않는다). */
    refresh: (): Promise<Obj> => dispatch("pool", "refresh", {}),
    poolAction,
    resolveDuplicate,
    noticeAction,
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

/** 이 다이얼로그가 공용 열에 넘기는 호스트 — 고르기 화면의 두 열과 **한 컴포넌트**다(③b).
 *
 *  종전에는 이 자리가 세 구획(현재 데이터 / 고정한 데이터 / 다른 데이터)을 그리는 별도
 *  컴포넌트(`pool_list.ts`)였다. 같은 등록 목록을 두 문법으로 그리던 자리라, 「고를 수
 *  있는가」의 시각적 얼굴과 행 동사가 화면마다 갈렸다 — 다이얼로그는 행 안 버튼 다섯,
 *  고르기 열은 ⋯ 하나. 이제 그림은 한 벌이고 갈리는 것은 넷이다: 좌표(`dataPicker*`),
 *  바닥 동사 줄, 짝 지을 상대 열이 없다는 것(`drop` 없음), 1차 동사가 발행하는 액션
 *  (`job/load_pool` — 고르기 화면은 `editor/use_pool_data`).
 *
 *  좌표는 살아 있는 것만 **불변**이다: `#dataPickerPinned` 는 목록 그대로이고,
 *  카드 시절의 `#dataPickerCurrent`·`#dataPickerDupes`·`#dataPickerCorrupt` 는 그 카드와
 *  함께 사라졌다(현재 데이터 = 목록 첫 행, 통지 = 목록 안 `[data-notice]`). */
function dialogHost(
  controller: DataPickerController, seen: ReturnType<PickerSessionRead>, column: Obj | null,
): PoolColumnHost {
  const sessionRow = seen.data_row;
  return {
    side: "dat",
    rootId: "dataPickerPool",
    listId: "dataPickerPinned",
    title: "데이터",
    headSub: column === null ? "읽는 중…" : String(column.count_label || ""),
    /* 고름 표지의 정본은 **작업 스냅샷**이다: 풀 겨눔이면 그 슬롯 키, 아니면 세션 행이다.
       세션이 슬롯 키를 지어내지 않는다(추측 금지) — Python 이 이미 아는 사실이다. */
    selectedKey: seen.data_pool_key || (sessionRow ? SESSION_DATA_KEY : ""),
    choose: controller.choose,
    /* `drop` 없음 = 끌기 props 0. 이 면에는 짝 지을 상대 열이 없다. */
    onMore: (row: Obj, trigger: HTMLElement) => { controller.toggleRowMenu(row, trigger); },
    onNoticeAction: controller.noticeAction,
    reload: () => { void controller.refresh(); },
    acts: createElement(Fragment, null,
      h("button", {
        className: "btn sm", id: "dataPickerBrowse", "data-busy-lock": true, key: "browse",
        onClick: () => { void controller.browseFile(); },
      }, "파일 찾아보기…"),
      /* 계약 목록은 파일 피커가 아니라 **DB 자리 + 시트**로 겨눈다(#937). 스냅샷이 그
         둘을 아직 안 실었으면 숨기지 않고 비활성 + 사유 병기 — 죽은 버튼을 조용히 두면
         「눌러도 아무 일 없음」이 결함으로 읽힌다. 라벨의 괄호는 **확장자**다: 저쪽
         프로그램 이름(pclm)은 이 제품의 표면 어휘가 아니라 표면에 세우지 않는다. */
      h("button", {
        className: "btn sm", id: "dataPickerPclm", "data-busy-lock": true, key: "pclm",
        disabled: !controller.poolModel.getSnapshot()?.pclm,
        title: controller.poolModel.getSnapshot()?.pclm ? "" : PCLM_UNAVAILABLE,
        onClick: controller.openPclm,
      }, "계약 목록(.db) 등록…"),
      /* 「이 데이터 고정…」은 **고정할 것이 있고 아직 고정되지 않았을 때만** 선다: 풀에서
         고른 데이터는 이미 등록된 참조라 다시 고정하면 같은 파일의 참조가 둘로 갈린다. */
      sessionRow && !seen.data_pool_key ? h("button", {
        className: "btn sm", id: "dataPickerPin", "data-busy-lock": true, key: "pin",
        onClick: controller.openPin,
      }, "이 데이터 고정…") : null),
    emptyFallback: "고정한 데이터를 읽는 중…",
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
  const seen = state.session ? state.session.read() : NO_SESSION_DATA();
  const column = ((pool || {}).column || null) as Obj | null;
  /* 두 벌의 **순수 이어붙이기**다 — 판정은 없다(고르기 우 열과 같은 규율). 두 행 다 Python
     이 같은 계약으로 냈고, 여기서 정하는 것은 「세션 행이 먼저」라는 순서 하나뿐이다. */
  const merged = column === null
    ? (seen.data_row
      ? { rows: [seen.data_row], notices: [], empty_hint: "", count_label: "", result: {} }
      : null)
    : {
      ...column,
      rows: seen.data_row ? [seen.data_row, ...(column.rows || [])] : (column.rows || []),
    };
  return h("div", { className: "modal-card data-picker" },
    h("h3", { id: "dataPickerTitle" }, "데이터 선택"),
    h("p", { id: "dataPickerNote", className: `note ${state.level === "danger" ? "dangerbox" : state.level === "ok" ? "okbox" : ""}`,
      role: "status", "aria-live": "polite", style: { display: state.status ? "" : "none", whiteSpace: "pre-line" } }, state.status),
    h(PoolColumn as any, { host: dialogHost(controller, seen, column), column: merged }),
    h("div", { className: "modal-actions" },
      h("button", { className: "btn", id: "dataPickerClose", onClick: controller.close }, "닫기")),
    /* 행 ⋯ — 고르기 화면과 같은 컴포넌트를 이 면의 좌표로 세운다. 트리거 selector 가
       갈리는 것이 두 팝오버의 dismissal 을 나눈다(`#scr-editor .job-more` ↔ 이 면). */
    h(ContextMenu as any, {
      id: "dataPickerRowMenu",
      controller: controller.rowContextMenu,
      popover: controller.popover,
      triggerSelector: "#dataPickerModal .job-more",
      onDismiss: controller.closeRowMenu,
      onSelect: (action: string) => { void controller.handleRowMenu(action); },
    }));
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
