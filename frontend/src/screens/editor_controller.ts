/* Editor bridge, draft, and asynchronous interaction controller. */
import type { BridgeClient } from "../runtime/client.ts";
import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import type { ScreenPorts } from "./ports.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import type { ContextMenuPopoverPort } from "./context_menu.ts";
import { saveSheetOrder } from "./pool_verbs.ts";
import { SETTINGS_MODAL_ID } from "./settings_sheet.ts";
import type { PoolRegistrationPort } from "./pool_verbs.ts";
import {
  NAME_FIELD, PATTERN_FIELD, editorServerValues, editorSession, emptyDraft, ingestSnapshot,
} from "./editor_state.ts";
import type { DraftState } from "./editor_state.ts";
import type { SlicePort } from "./slice_popover.ts";
import { createBindingMenu, createSlotMenus, findDataItem, findLibItem } from "./editor_controller_slots.ts";
import type { LibMenu } from "./editor_controller_slots.ts";
import { createSelectionController } from "./editor_controller_selection.ts";
import { createDraftOps } from "./editor_controller_draft.ts";
export type Obj = Record<string, any>;
type Listener = () => void;

export type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
  prompt(spec: Obj): Promise<string | null>;
  open(id: string, spec?: Obj): void;
  close(id: string): void;
};

/** 발신 직렬화 — legacy `Intent` 를 그대로 주입받는다(기제를 두 벌 만들지 않는다). */
type ChainPort = {
  chained<T>(key: string, send: () => Promise<T>): Promise<T>;
  settle(key: string): Promise<unknown>;
};

export type EditorControllerDeps = {
  doc: Document;
  runtime: ScreenRuntime;
  client: BridgeClient;
  ports: ScreenPorts;
  services: ServiceHandoffPorts;
  modal: ModalPort;
  popover: ContextMenuPopoverPort;
  chain: ChainPort;
  navigation: { go(screen: string, options?: Obj): void; refresh(screen: string): Promise<unknown> };
  /** `#poolRegModal` 진입 — 등록 폼의 수명은 데이터 선택 컨트롤러가 계속 소유한다(U6-B). */
  poolRegistration: PoolRegistrationPort;
  notify(message: string): void;
};

const SCREEN = "editor";
const EDIT_CHAIN = "editor:mutate";

/* (진입 사유 문장 `ENTRY_LEAD` 과 배너의 복귀 버튼 `RETURN_LABEL` 은 2026-09-03 재판정으로
   걷혔다 — 「어디서 열었나」는 방금 거기서 온 사람에게 새 정보가 아니고, 복귀는 왼쪽 위
   「← 원래 업무로 돌아가기」 하나가 이미 같은 곳으로 간다. 두 번째 버튼은 동작 하나를 더할 뿐이다.)
   복귀처 — 진입 문맥이 말한 표면(계약 §8). 없으면 「문서 만들기」다. */
const RETURN_SCREEN: Record<string, string> = {
  data: "job", result: "job", documents: "job", library: "library",
};

export type ViewState = {
  libMenu: LibMenu | null;
  /** 2단계 머리의 ⋯ 메뉴가 열려 있는가 — 항목·위치는 공용 `ContextMenu` 가 소유한다. */
  bindingMenu: boolean;
  /** 「고정값…」을 고른 행 — 그 입력이 **실제로 선 렌더**에서 초점을 받는다(리뷰 8). */
  pendingConstFocus: number | null;
  /** 항목 상세 시트가 열려 있는가(U6-E 리뷰 3) — 동사의 결과가 **어느 채널로 갈지**를 가른다.
   *  시트가 스크림으로 화면을 덮는 동안 `#save-msg` 에 쓰면 그 문장은 뒤에 그려진다. */
  detailOpen: boolean;
  /** 시트가 열려 있는 동안의 동사 실패 문안 — 닫히면 걷힌다(다음 열림에 남지 않는다). */
  detailMessage: string | null;
  /** 「가공」 인라인 편집기가 열려 있는 행 index — 한 번에 하나만 연다(`pendingConstFocus`
   *  와 같은 1슬롯 표지). UI-local 상태라 서버 왕복이 없다. */
  sliceOpenIndex: number | null;
  tokFoldOpen: boolean;
  saveMessage: { text: string; level: string } | null;
  invalidField: string;
  aim: string;
  /** 이 문맥에서 이미 겨눈 목표 — 문맥당 한 번만 조준한다. */
  aimed: string;
};

/** 편집기 **세션**을 건드리지 않는 tpl 동사 — 완료 뒤 editor 재당김을 걸지 않는다.
 *
 *  `refresh` 는 U6-B(#976)에서 합류했다: 목록의 정본이 `tpl` 채널이 된 뒤로 재스캔은 그
 *  채널의 push 하나로 끝나고, 편집기 스냅샷을 한 번 더 묻는 것은 같은 진입에서 디스크를
 *  두 번 읽는 일이다. 나머지 tpl 동사는 파일을 변이시켜 이 세션의 스키마·게이트를 흔들
 *  수 있으므로 종전대로다. */
const TPL_READONLY_ACTIONS = new Set(["refresh"]);

/** 템플릿 행 ⋮ 의 동사표 — `editor_controller_slots.ts` 로 옮겼다(라이브러리 메뉴 책임
 *  분리). `editor.ts` 가 이 이름으로 그대로 가져오므로 여기서 재-export 한다. */
export { libRowMenuItems } from "./editor_controller_slots.ts";

export function createEditorController(deps: EditorControllerDeps) {
  const model = deps.runtime.model<Obj | null>(SCREEN);
  /* 고르기 단계의 두 열은 **자기 채널의 정본을 직접 읽는다**(U6-B #976): 좌 열은 `tpl`,
     우 열은 `pool`. 종전에는 편집기 스냅샷이 템플릿 목록을 한 번 더 성형해 실어 왔고
     (구 `library` 존), 그래서 같은 목록을 두 컨트롤러가 그렸다. 채널이 하나가 되면
     tpl 의 변환·검토가 목록을 바꾸는 순간 이 화면도 같은 push 로 따라간다. */
  const tplModel = deps.runtime.model<Obj | null>("tpl");
  const poolModel = deps.runtime.model<Obj | null>("pool");

  let draft: DraftState = emptyDraft();
  let view: ViewState = {
    libMenu: null, bindingMenu: false, pendingConstFocus: null,
    detailOpen: false, detailMessage: null, sliceOpenIndex: null,
    tokFoldOpen: false, saveMessage: null,
    invalidField: "", aim: "", aimed: "",
  };
  const draftListeners = new Set<Listener>();
  const viewListeners = new Set<Listener>();

  function emitDraft(): void { for (const listener of [...draftListeners]) listener(); }
  function emitView(): void { for (const listener of [...viewListeners]) listener(); }

  function patchView(next: Partial<ViewState>): void {
    view = { ...view, ...next };
    emitView();
  }

  function snapshot(): Obj {
    return model.getSnapshot() || {};
  }

  /* 스냅샷 흡수 — 전송 값만 갈아 끼우고 사용자가 들고 있는 값은 건드리지 않는다. */
  function absorb(): void {
    const current = model.getSnapshot();
    if (current === null) return;
    /* 편집기 세션이 다시 서면(새 작업 시작·다른 작업 load) 앞 세션의 알림은 지금 상태를
       더는 서술하지 않는다. 컨트롤러는 부팅 1회 싱글턴이라 여기서 걷지 않으면 화면을
       나갔다 들어와도 남는다(#874). draft 를 통째로 새로 세우는 그 전이와 같은 자리다. */
    if (editorSession(current) !== draft.session) clearSaveMessage();
    draft = ingestSnapshot(draft, {
      session: editorSession(current),
      values: editorServerValues(current),
    });
    emitDraft();
  }
  const dispatch = async (screen: string, action: string, payload: Obj = {}): Promise<Obj> => {
    const call = deps.client.dispatch as unknown as (
      channel: string, name: string, body: Obj,
    ) => ReturnType<BridgeClient["dispatch"]>;
    const value = (expectHostValue(await call(screen, action, payload), `${screen}/${action}`) ?? {}) as Obj;
    /* tpl 동사는 모두 snapshot push를 내지만 editor 목록의 정본은 editor snapshot이다.
       교차 채널 구독으로 push를 다시 initial로 번역하지 않고, 원인 동사의 완료와 같은 줄에서
       editor를 한 번 재당긴다. 호출이 실패하면 재당김도 실행하지 않는다. */
    if (screen === "tpl" && !TPL_READONLY_ACTIONS.has(action)) await deps.runtime.refresh(SCREEN);
    return value;
  };

  model.subscribe(absorb);
  absorb();

  const invoke = async (
    method: Parameters<BridgeClient["invoke"]>[0], ...args: unknown[]
  ): Promise<unknown> => expectHostValue(await deps.client.invoke(method, ...args), method);

  /** 고르기 단계에 **들어설 때** 두 풀을 다시 읽는다(U6-B #976 · 리뷰 4).
   *
   *  「읽는 시점은 화면 진입 시 diff + 수동 새로 읽기」(U6 §2.3 · 폴더=라이브러리 관례).
   *  렌더마다 재스캔하면 타이핑 한 번에 디스크를 훑고, 아예 안 하면 탐색기에서 넣은 파일이
   *  영영 안 보인다.
   *
   *  **결속 대상은 사건이지 스냅샷이 아니다.** 종전에는 마지막으로 본
   *  `(editorSession(), section)` 을 기억해 전이를 유도했는데, 초안의 세션 표지는 **언제나
   *  `"draft"`** 라 「초안 → 취소 → 새 초안」이 같은 값으로 읽혔다 — 두 번째 새 작업부터
   *  재스캔이 조용히 빠진다(선언은 살고 결과가 죽는 자리). 지금 부르는 자리는 둘이고 둘 다
   *  실제 진입이다: 셸이 편집기 화면에 들어설 때마다 부르는 `rerender`(`shell/nav.ts`)와,
   *  같은 세션 안에서 1단계로 돌아오는 `gotoSection("template")`. 각 호출이 채널당 한 발이라
   *  탭 왕복 한 번에 한 번이다. */
  function rescanPools(): void {
    void dispatch("tpl", "refresh", {}).catch((error) => {
      noticeSave(`서식 폴더를 다시 읽지 못했습니다: ${String((error as Obj)?.message || error)}`);
    });
    void dispatch("pool", "refresh", {}).catch((error) => {
      noticeSave(`고정한 데이터를 다시 읽지 못했습니다: ${String((error as Obj)?.message || error)}`);
    });
  }

  /** 편집 변이 — 전부 한 체인에 선다(순서에 기대는 질의도 포함). */
  function sendEdit(action: string, payload: Obj = {}): Promise<Obj> {
    return deps.chain.chained(EDIT_CHAIN, () => dispatch(SCREEN, action, payload));
  }

  /* draft(이름·패턴·행 값) 발신·커밋과 데이터 열/표시형 select 발행(U6-C #977)은
     `editor_controller_draft.ts` 가 진다(저장/더티 처리). `draft` 그 자체는 흡수(`absorb`)
     도 쓰는 공유 가변 상태라 여기(main)가 계속 소유하고, get/set 만 넘긴다. */
  const draftOps = createDraftOps({
    getDraft: () => draft,
    setDraft: (next: DraftState) => { draft = next; },
    emitDraft,
    sendEdit,
    settleChain: () => deps.chain.chained(EDIT_CHAIN, () => Promise.resolve()),
    notify: deps.notify,
    noticeSave,
    getView: () => view,
    patchView,
    snapshot,
  });
  const {
    type, focus, compose, commitField, commitRow, commitRowOnBlur,
    chooseDataColumn, chooseDisplay, flushPendingEdits,
  } = draftOps;

  /* ---- 「가공」 팝오버 — 칩 하나와 칩에 붙어 서는 편집 칸(`slice_popover.ts`) ----

     칸의 뜻(문장·방식 목록·후보·미리보기)은 전부 Python 이 낸다. 여기는 행 index 로 정체를
     감싼 문(`SlicePort`)만 짓는다: 명세 커밋(`set_slice`)과 무변이 질의 둘(`preview_slice`·
     `propose_slice`). 질의도 편집 체인에 선다 — 방금 보낸 커밋 뒤의 상태를 읽어야 한다. */

  /** 가공 명세 커밋 — 거절은 저장 알림 자리에 그대로 세운다(`sendRowChoice` 와 같은 채널). */
  async function commitSlice(index: number, slice: Obj | null): Promise<boolean> {
    try {
      await sendEdit("set_slice", { index, slice });
      return true;
    } catch (error) {
      noticeSave(String((error as Obj)?.message || error));
      return false;
    }
  }

  /** 무변이 질의의 거절도 같은 자리에 세운다 — 조용히 삼키지 않고, 부른 칸에는 거절로 돌려준다. */
  async function sliceQuery(send: () => Promise<Obj>): Promise<Obj> {
    try {
      return await send();
    } catch (error) {
      noticeSave(String((error as Obj)?.message || error));
      throw error;
    }
  }

  /** 「가공」 팝오버 토글 — 한 번에 한 행만 연다(1슬롯 표지, 서버 왕복 없음). */
  function toggleSliceEditor(index: number): void {
    patchView({ sliceOpenIndex: view.sliceOpenIndex === index ? null : index });
  }

  function isSliceEditorOpen(index: number): boolean {
    return view.sliceOpenIndex === index;
  }

  /** 행 하나의 「가공」 칸이 쓰는 문 — 정체는 행 index 다. */
  function slicePort(index: number): SlicePort {
    return {
      doc: deps.doc,
      open: view.sliceOpenIndex === index,
      toggle: () => toggleSliceEditor(index),
      close: () => { if (view.sliceOpenIndex === index) patchView({ sliceOpenIndex: null }); },
      commit: (slice) => commitSlice(index, slice),
      preview: (sample) => sliceQuery(() => sendEdit("preview_slice", { index, sample })),
      propose: (sample, start, end) =>
        sliceQuery(() => sendEdit("propose_slice", { index, sample, start, end })),
    };
  }

  /** 대기 중인 「고정값」 초점을 이 행이 가져간다 — 가져가면 표지를 걷는다(1회성).
   *
   *  판정을 렌더가 아니라 여기서 하는 이유: 표지가 남아 있으면 이후 모든 재렌더가 그 입력을
   *  다시 겨눠 사람이 옮긴 커서를 계속 빼앗는다. */
  function takePendingConstFocus(index: number): boolean {
    if (view.pendingConstFocus !== index) return false;
    patchView({ pendingConstFocus: null });
    return true;
  }

  /* ---- 조준(deep-link) ---- */

  /** **옮겨 보고 결과를 읽는다** — 요소가 있다는 것과 초점이 섰다는 것은 다르다.
   *
   *  어떤 요소가 초점을 받을 수 있는지의 규칙(비활성·분리·숨김·inert·전이 중)을 여기서
   *  재현하려 들면 그 목록이 곧 다음 결함이 된다. 실제로 옮겨 보고 안 옮겨졌으면 실패로
   *  보고해 요청을 남긴다 — 다음 렌더가 다시 시도한다. 존재만 보고 성사했다고 답하면 조준은
   *  「했다」고 말하면서 초점은 아무 데도 안 서고, 그 거짓 성공이 재시도까지 막는다(실측).
   *
   *  `modal.js` 의 초점 복원이 이미 같은 규율을 쓴다: 판정을 흉내내지 않고 결과를 읽는다. */
  function aimAtTarget(target: string): boolean {
    if (target === "filename/filenamePattern") {
      const input = deps.doc.querySelector<HTMLElement>(
        '#editor-body input[data-act="pattern"]');
      input?.focus();
      return input !== null && deps.doc.activeElement === input;
    }
    const field = target.slice("binding/".length);
    const row = deps.doc.querySelector<HTMLElement>(
      `#editor-body table.map tr[data-field="${CSS.escape(field)}"]`);
    if (row === null) return false;  // 없는 행에 가짜 초점을 세우지 않는다
    row.scrollIntoView({ block: "center" });
    const select = row.querySelector<HTMLElement>('select[data-act="row-source"]');
    select?.focus();
    return select !== null && deps.doc.activeElement === select;
  }

  /** 보낸 표면이 진입 성사 뒤 부르는 조준 seam — **설 때까지** 살아 있는다.
   *
   *  진입이 성사된 그 순간에는 매핑 표가 아직 DOM 에 없다(렌더는 다음 틱이다). 거기서 한 번
   *  겨누고 요청을 버리면 초점은 **영영** 안 선다 — 행은 나중에 생기는데 아무도 다시 겨누지
   *  않기 때문이다. 실측으로 SX-05 actual shell 이 정확히 그 자리에서 죽었다: 행은 있고 초점만
   *  없었다. 그래서 성사하지 못한 요청은 남겨 다음 렌더가 다시 시도한다. */
  function aimAt(target: string): void {
    if ((snapshot().context || {}).target === target && aimAtTarget(target)) {
      patchView({ aim: "", aimed: target });
      return;
    }
    patchView({ aim: target });
  }

  /** 렌더 뒤 소비 — **진입 문맥이 지목한 자리**를 그 문맥당 한 번 겨눈다.
   *
   *  보낸 화면의 호출을 기다리지 않는다. 그 경로는 port 표면에 없는 메서드를 `typeof` 로
   *  확인하고 조용히 지나가는 형상이었고(있지도 않은 것을 물어보고 없으면 넘어간다), 그래서
   *  deep-link 초점은 **한 번도 선 적이 없었다**. 진입 문맥은 이미 목표를 담아 여기 도착하므로
   *  물어볼 곳은 바깥이 아니라 여기다.
   *
   *  성사할 때까지 남는다 — 진입 성사 시점에는 매핑 표가 아직 DOM 에 없다. 그리고 문맥당 한
   *  번만이라, 사용자가 그 뒤 초점을 옮겨도 매 렌더 다시 빼앗지 않는다. */
  /** 초점을 **아무도 안 잡고 있는가**.
   *
   *  `body`·`null` 은 초점을 잃은 것이고, 화면 루트는 「트리거로 못 돌아갈 때」의 대안 착지라
   *  사용자가 고른 자리가 아니다. 셋 다 「비어 있음」으로 읽는다 — 사용자가 실제로 옮겨 둔
   *  초점(입력칸·버튼)은 여기 해당하지 않으므로 빼앗지 않는다. */
  function focusIsUnclaimed(): boolean {
    const active = deps.doc.activeElement;
    if (active === null || active === deps.doc.body) return true;
    return active === deps.doc.querySelector(".scr.on");
  }

  function consumeAim(): void {
    const target = String((snapshot().context || {}).target || "");
    if (target === "") {
      // 진입 문맥이 없으면(편집기를 떠났다) 기억을 비운다 — 같은 자리로 **다시** 들어오면
      // 그때도 겨눠야 한다. 안 비우면 두 번째 진입부터 조용히 안 선다.
      if (view.aimed !== "" || view.aim !== "") patchView({ aim: "", aimed: "" });
      return;
    }
    // 이미 겨눴어도 **초점을 잃었으면** 다시 세운다. 리렌더가 그 노드를 갈아 끼우면 초점이
    // 조용히 `body` 로 떨어지고, 그 틈을 면 닫힘의 대안 착지가 화면 루트로 채운다 — 그러면
    // 사용자가 지목한 자리는 영영 비어 있다. 사용자가 스스로 옮긴 초점은 여기 안 걸린다.
    if (target === view.aimed && !focusIsUnclaimed()) return;
    if (aimAtTarget(target)) patchView({ aim: "", aimed: target });
  }

  /* 라이브러리 좌·우 열 ⋮ 메뉴·항목 상세 시트·Slot(컴파일된 구간) 동사(F8·S8-03·U6-E #979)는
     `editor_controller_slots.ts` 가, 템플릿·데이터 채택·등록 데이터(pool) 관리 동사·매핑
     재판정 관문은 `editor_controller_selection.ts` 가 각각 진다. 공유 상태(뷰·스냅샷·발신·
     알림)는 deps 로 넘긴다. */
  const selectionCtl = createSelectionController({
    modal: deps.modal,
    client: deps.client,
    services: deps.services,
    poolRegistration: deps.poolRegistration,
    tplModel, poolModel,
    snapshot,
    notify: deps.notify,
    noticeSave,
    sendEdit,
    /* 관리 동사도 **편집 체인**에 선다(리뷰 6): 이 화면의 다른 발신과 순서를 나눠 갖지
       않으면 보관·삭제가 마운트·저장 왕복 사이로 끼어든다. */
    dispatchChained: (screen: string, action: string, payload: Obj = {}) =>
      deps.chain.chained(EDIT_CHAIN, () => dispatch(screen, action, payload)),
    invoke,
    refreshScreen: () => deps.runtime.refresh(SCREEN),
  });

  const slotMenus = createSlotMenus({
    modal: deps.modal,
    notify: deps.notify,
    tplModel, poolModel,
    snapshot,
    dispatch,
    openAuthoringAt: (path: string) => deps.ports.authoring.current().open(path),
    /* 우 열 분기표는 데이터 선택 컨트롤러와 공유한다(공용 ⑤ 리뷰) — 이 화면이 데이터 동사를
       발명하지 않는다. */
    runPoolVerb: (action: string, item: Obj, trigger: HTMLElement) =>
      selectionCtl.poolVerbs.runVerb(action, item, trigger),
    getView: () => view,
    patchView,
    noticeSave,
  });

  /* ---- 저장·이동·이탈 ---- */

  /** 편집기의 **인라인 알림 채널**(#323) — 세 탭 어디서든 같은 자리(`#save-msg`)로 간다.
   *
   *  종전에는 파일 이름 탭에서만 인라인이고 나머지 두 탭에서는 `window.alert` 로 샜다.
   *  구조화된 거절·안내는 화면이 붙들고 있어야 사용자가 값을 고치면서 읽는데, 모달 경보는
   *  읽자마자 사라지고 그 사이 화면은 아무 말도 하지 않는다. `deps.notify` 는 이제 던져진
   *  예외의 catch 백스톱 전용이다(잡을 자리가 화면에 없는 실패). */
  function noticeSave(message: string, level?: string): void {
    patchView({ saveMessage: { text: message, level: level || "" } });
  }

  /** 세우는 자리의 짝 — 사유가 해소된 알림을 걷는다(#874).
   *
   *  이 채널에는 지우는 전이가 없었다: 한 번 선 「⚠ …」이 이름을 채워도, 저장이 성사돼도,
   *  화면을 다시 들어와도 남아 지금이 아닌 과거를 계속 서술했다. 성공 문구를 새로 짓지는
   *  않는다 — 사유가 사라졌으면 말할 것도 사라진 것이다. */
  function clearSaveMessage(): void {
    if (view.saveMessage !== null) patchView({ saveMessage: null });
  }

  /** 차단당한 칸으로 커서를 옮긴다 — 어느 칸인지는 Python 이 말한다.
   *
   *  **겨눔은 단계를 옮기지 않는다.** 이름·패턴은 둘 다 3단계 「이름·저장」 폼에 살지만
   *  (U6-D #978), 거절당한 저장이 사람을 그 단계로 데려가면 지나온 단계의 patch 가 탭 이동의
   *  자동 버리기에 걸린다 — 연결 확인에서 방금 선언한 「비워 둠」이 저장 거절 하나로 사라지는
   *  자리다. 거절은 아무것도 파괴하지 않는다. 그래서 다른 단계에 있으면 문구만 남기고, 어느
   *  단계인지는 링1 차단 문안이 말한다(`'이름·저장' 단계에서 …`). */
  function aimAtBlockedField(field: string): void {
    /* 데이터 미연결(#932 U4-C S2-3)의 「칸」은 입력이 아니라 **고르기 단계 우 열**이다
       (U6-B #976 — 2단계 머리의 관문이 걷혔다). 그 단계에 있지 않으면 겨눌 노드가 없으므로
       문구만 남긴다: 1단계로 되돌리는 것은 사람이 지금 보고 있는 표를 걷어내는 큰 이동이라
       거절 하나로 자동 수행할 일이 아니다. */
    if (field === "data") {
      if (snapshot().section !== "template") return;
      const browse = deps.doc.querySelector<HTMLElement>("#editorPoolBrowse");
      browse?.focus();
      return;
    }
    if (field !== NAME_FIELD && field !== PATTERN_FIELD) return;
    /* 표지는 **그 칸이 보이는 단계에서만** 선다. 안 보이는 칸에 `aria-invalid` 를 남기면
       다음에 그 단계로 갔을 때 고치지도 않은 칸이 빨갛게 서 있다(끈적한 표지). */
    if (snapshot().section !== "filename") return;
    patchView({ invalidField: field });
    const element = field === NAME_FIELD
      ? deps.doc.getElementById("editorName")
      : deps.doc.querySelector<HTMLElement>('#editor-body input[data-act="pattern"]');
    if (element === null) return;
    element.focus();
    if (typeof (element as HTMLInputElement).select === "function") {
      (element as HTMLInputElement).select();
    }
  }

  /** 저장 성공의 정산 — 사유가 해소된 표지·알림을 걷고, 저장은 제자리이므로(결정 40)
   *  후보·문서 탐색 스냅샷만 호출자 선택에 따라 갱신한다. */
  function settleSaveSuccess(options: { listRefresh?: "background" | "caller" }): void {
    clearSaveMessage();   // 막았던 사유가 해소됐다 — 차단 문안을 남겨 두지 않는다(#874)
    /* 겨눔 표지도 같은 전이에서 걷는다: 사유가 사라졌는데 칸만 빨갛게 남으면 화면이
       「저장됐다」와 「이 칸이 잘못됐다」를 동시에 말한다. */
    if (view.invalidField !== "") patchView({ invalidField: "" });
    /* 저장은 제자리(결정 40). 후보·문서 탐색 스냅샷만 갱신해 새/개명 작업이 바로 보이게 한다. */
    if (options.listRefresh !== "caller") void deps.ports.jobRead.current().refreshList();
  }

  /** 덮어쓰기 확인 — 동의하면 그 표지를 실어 저장을 재시도한다(#149). 판정은 Python 이
   *  쓰기 잠금 안에서 다시 한다. */
  async function confirmOverwriteThenRetry(
    result: Obj, flags: Obj, options: { listRefresh?: "background" | "caller" },
  ): Promise<boolean> {
    if (!(await deps.modal.confirm({
      body: `${result.overwrite_text}\n\n계속할까요?`,
      confirmLabel: "덮어쓰기", cancelLabel: "취소", danger: true,
    }))) return false;
    return doSave({
      ...flags, confirm_overwrite: true, confirmed_overwrite_text: result.overwrite_text,
    }, options);
  }

  /** 저장 한 번. ``listRefresh: "background"`` 가 기본이다 — 일반 [작업 저장]은 제자리
   *  저장이라(결정 40) 「문서 만들기」 목록만 뒤에서 다시 받게 하고 기다리지 않는다.
   *  ``"caller"`` 는 그 갱신을 호출자가 직접 순서 안에서 보내겠다는 뜻이다(`saveAndOpen`). */
  async function doSave(
    flags: Obj = {}, options: { listRefresh?: "background" | "caller" } = {},
  ): Promise<boolean> {
    await flushPendingEdits();
    let result: Obj;
    try {
      result = await sendEdit("save", flags);
    } catch (error) {
      deps.notify("저장 처리 중 오류가 발생했습니다. 작업이 저장됐는지 「문서 작업」에서 확인하세요.\n" + String(error));
      return false;
    }
    if (result === null || typeof result !== "object") {
      noticeSave("저장 결과를 확인할 수 없습니다. 작업이 저장됐는지 「문서 작업」에서 확인하세요.");
      return false;
    }
    if (result.ok) {
      settleSaveSuccess(options);
      return true;
    }
    if (result.needs_overwrite) return confirmOverwriteThenRetry(result, flags, options);
    noticeSave(String(result.block_reason || "저장할 수 없습니다."));
    aimAtBlockedField(String(result.blocked_field || ""));
    return false;
  }

  /** 「저장하고 문서 만들기로」 — 저장 성공 뒤 이 작업이 **선 상태로** 문서 만들기에 착석한다.
   *
   *  세 가지가 계약이다.
   *
   *  ① **`leaveTo` 를 타지 않는다.** 그 출구는 나가기 전에 `discard_patch`/`new_session` 을
   *     먼저 쏜다 — 방금 저장한 세션에 그것을 보내면 저장 착지 상태를 진입 시점으로
   *     되돌리게 된다. 저장 직후 세션은 clean 이라 버릴 것도 없다(가드 없는 이동이 안전한
   *     것도 그래서다).
   *  ② **3분기 판정은 Python `prefer_work` 가 진다**(§19.8) — 라이브러리 「문서 만들기에서
   *     사용」과 **같은 순서**로 보낸다. 여기서 `select_job` 을 직접 쏘면 준비·호환 판정이
   *     표면에 한 벌 더 생긴다.
   *  ③ **이동만 실패해도 저장 성공을 숨기지 않는다.** 착지가 안 되면 머무르며 그 사실을
   *     `#save-msg` 로 재진술한다 — 저장은 이미 일어났고 사람이 다시 누를 일이 아니다.
   *  ④ **목록 갱신을 끝낸 뒤 착석을 보낸다.** 저장 뒤 목록 갱신(`job/refresh`)을 기다리지 않고
   *     `prefer_work` 를 이어 쏘면 두 요청이 별도 스레드에서 겹친다 — 한쪽이 스냅샷을 짓는
   *     사이 다른 쪽이 앞 작업을 해제해 빈 이름으로 작업 파일을 찾던 결함이 그 자리다(백엔드는
   *     상태 잠금으로 직렬화하지만, 순서가 정해진 두 요청을 표면이 경주시킬 이유도 없다). */
  async function saveAndOpen(): Promise<void> {
    if (!(await doSave({}, { listRefresh: "caller" }))) return;
    const name = String(snapshot().name || "");
    let result: Obj;
    try {
      await deps.ports.jobRead.current().refreshList();
      result = await dispatch("job", "prefer_work", { name });
      await deps.navigation.refresh("job");
    } catch (error) {
      noticeSave("저장했습니다. '문서 만들기' 로 이동하지 못했습니다: "
        + String((error as Obj)?.message || error));
      return;
    }
    deps.navigation.go("job", { force: true, refreshed: true });
    deps.ports.editorEntry.current().restoreEntryFocus();
    if (result && result.reason === "incompatible") {
      await deps.ports.jobRead.current().openBrowseNeedsAction(name);
    }
  }

  /** 탭 이동 — 정산하고 한 발 보낸다. 막는 patch 의 처분은 Python 이 진다(계약 §5.2).
   *
   *  종전에는 여기서 3택(저장하고 이동·버리고 이동·머무르기)을 받고 처분 표지를 실어 같은
   *  액션을 다시 보냈다. 지금은 컨트롤러가 막는 자리를 자동으로 되돌리고 그 사실을 통지로
   *  재진술하므로, 웹이 할 일은 정산과 발신 하나뿐이다. */
  async function gotoSection(target: string): Promise<void> {
    if (!target) return;
    await flushPendingEdits();
    await sendEdit("goto_section", { section: target });
    /* 단계를 옮기면 겨눔 표지는 뜻을 잃는다 — 안 보이는 칸의 `aria-invalid` 는 다음에 그
       단계로 돌아왔을 때 고치지도 않은 칸을 나무란다. */
    if (view.invalidField !== "") patchView({ invalidField: "" });
    /* 같은 세션 안의 1단계 **재진입** — 화면 진입과 같은 사건이라 같은 재스캔을 지난다
       (리뷰 4). 이동이 거절되면 여기 닿지 않는다(`sendEdit` 가 던진다). */
    if (target === "template") rescanPools();
  }

  function neighbour(delta: number): string {
    const sections = (snapshot().sections || []) as string[];
    const here = sections.indexOf(snapshot().section);
    return sections[Math.min(sections.length - 1, Math.max(0, here + delta))];
  }

  function returnScreen(): string {
    const context = snapshot().context || {};
    return RETURN_SCREEN[(context.return_context || {}).surface] || "job";
  }

  /** 착지 절차 — 목적 화면을 노출하기 **전에** 그 화면이 디스크를 다시 읽게 한다. */
  async function landOn(target: string): Promise<boolean> {
    try {
      await deps.navigation.refresh(target);
    } catch (error) {
      deps.notify("돌아갈 화면을 다시 읽지 못해 편집기에 머무릅니다: "
        + String((error as Obj)?.message || error));
      return false;
    }
    deps.navigation.go(target, { force: true, refreshed: true });
    deps.ports.editorEntry.current().restoreEntryFocus();
    return true;
  }

  /** 편집기를 나가는 **단일 출구** — 묻지 않고 버리고 나간다.
   *
   *  이탈은 두 갈래다: 저장본 편집은 `discard_patch {}` 로 진입 시점 상태(데이터 결속 포함)로
   *  되돌리고, 초안은 `new_session {}` 으로 세션째 끊는다. 버릴 것이 있는지는 **여기서 다시
   *  세지 않는다** — 클린 세션의 이탈을 무동작으로 만드는 no-op 게이트가 컨트롤러 안에 있고,
   *  웹이 dirty 를 재판정하면 같은 상태를 두 곳이 답하게 된다. */
  async function leaveTo(target: string): Promise<void> {
    await flushPendingEdits();
    const state = snapshot();
    if (state.is_draft) {
      await sendEdit("new_session", {});
    } else {
      await sendEdit("discard_patch", {});
    }
    await landOn(target);
    // 복귀 **상태** 복원(구 `restoreReturnState`)은 미리보기 드로어 재개 하나뿐이었고
    // #957 에서 함께 사망했다 — 착지 화면은 자기 스냅샷으로 선다.
  }

  /* ---- 2단계 머리의 드문 동사(⋯) ---- */

  const bindingMenu = createBindingMenu({
    snapshot, sendEdit, resuggestAll: () => selectionCtl.resuggestAll(),
    getView: () => view, patchView,
  });
  const {
    bindingContextMenu, closeBindingMenu, toggleBindingMenu, handleBindingMenu, isBindingMenuOpen,
  } = bindingMenu;

  /** 변경 버리기 — 발신 **전에** 대기 중 편집을 정산한다(정산하지 않으면 방금 친 글자가
   *  되돌리기 뒤에 도착해 버린 상태를 다시 더럽힌다). 되돌렸다는 재진술은 컨트롤러 통지다. */
  async function discardPatch(): Promise<void> {
    await flushPendingEdits();
    await sendEdit("discard_patch", {});
  }

  async function cancelNewDraft(): Promise<void> {
    await sendEdit("discard_session", {});
    /* 폐기를 마쳤으니 이탈 경로를 다시 태우지 않는다 — 착지는 이탈과 **같은 절차**다. */
    await landOn(returnScreen());
  }

  /** 화면 행동의 loud 가드 — 디스패처 한 자리에서 rejection 을 재진술한다. */
  function guarded(run: () => Promise<unknown> | void): void {
    try {
      const result = run();
      if (result instanceof Promise) {
        result.catch((error) => deps.notify(String((error as Obj)?.message || error)));
      }
    } catch (error) {
      deps.notify(String((error as Obj)?.message || error));
    }
  }

  return {
    init(): Promise<unknown> {
      /* 첫 initial 이 실패한 뒤의 명시적 재-init 은 다시 당긴다. loadInitial이 실패에서
         기억을 지우므로 별도 init/wired 호환 가드는 필요 없다. */
      return deps.runtime.loadInitial(SCREEN);
    },
    /** 현 스냅샷 재당김 — **셸이 편집기 화면에 들어설 때마다** 부른다(`shell/nav.ts`).
     *
     *  그 자리가 곧 「고르기 단계 진입」이라 두 풀 재스캔이 여기 붙는다(리뷰 4): 신규
     *  초안·저장본 편집·취소 뒤 재진입이 전부 이 문을 지난다. */
    rerender(): Promise<unknown> {
      rescanPools();
      return deps.runtime.refresh(SCREEN);
    },
    leaveTo,
    aimAt,
    consumeAim,
    model,
    draftModel: {
      getSnapshot: (): DraftState => draft,
      subscribe(listener: Listener): () => void {
        draftListeners.add(listener);
        return () => { draftListeners.delete(listener); };
      },
    },
    viewModel: {
      getSnapshot: (): ViewState => view,
      subscribe(listener: Listener): () => void {
        viewListeners.add(listener);
        return () => { viewListeners.delete(listener); };
      },
    },
    /** 인라인 알림의 닫기 동사(U4 §2.12 · #945) — `NoticeBox` 의 `onClose` 가 이것이다.
     *  JS 전용 상태라 백엔드 왕복이 없다. */
    clearSaveMessage,
    type, focus, compose, commitField, commitRow, commitRowOnBlur,
    toggleSliceEditor, isSliceEditorOpen, slicePort,
    setTokFold(open: boolean): void { patchView({ tokFoldOpen: open }); },
    toggleLibMenu: slotMenus.toggleLibMenu,
    closeLibMenu: slotMenus.closeLibMenu,
    handleLibMenu: slotMenus.handleLibMenu,
    handleSlotVerb: slotMenus.handleSlotVerb,
    /** 항목 상세 시트(U6-E #979) — 여는 자리 둘(행 ⋮ · 게이트 존)이 같은 한 문을 지난다. */
    openDetail: slotMenus.openDetail,
    closeDetail: (): void => { deps.modal.close("tplDetailModal"); },
    handleDetailVerb: slotMenus.handleDetailVerb,
    isLibMenuOpen: slotMenus.isLibMenuOpen,
    libContextMenu: slotMenus.libContextMenu,
    findLibItem: (media: string, key: string): Obj | null => findLibItem(tplModel, media, key),
    openAuthoring: () => deps.ports.authoring.current().open(),
    /** 외부 FS 재스캔(tpl 채널) — push 가 재당김을 태워 목록·결과 줄이 되그려진다. */
    refreshLibrary: (): Promise<Obj> => dispatch("tpl", "refresh", {}),
    /** 우 열의 같은 문(pool 채널) — 두 열이 대칭이라 「새로 읽기」도 양쪽에 선다(③a). */
    refreshPool: (): Promise<Obj> => dispatch("pool", "refresh", {}),
    reorderSheets: (key: string, sheets: string[]) => saveSheetOrder(key, sheets, dispatch,
      () => deps.runtime.refresh(SCREEN), deps.notify),
    useLibraryTemplate: selectionCtl.useLibraryTemplate,
    importTemplate: selectionCtl.importTemplate,
    pickData: selectionCtl.pickData,
    usePoolData: selectionCtl.usePoolData,
    chooseTemplate: selectionCtl.chooseTemplate,
    chooseData: selectionCtl.chooseData,
    dropPair: selectionCtl.dropPair,
    refuseSelection: selectionCtl.refuseSelection,
    poolAction: selectionCtl.poolVerbs.poolAction,
    resolveDuplicate: selectionCtl.poolVerbs.resolveDuplicate,
    poolNoticeAction: selectionCtl.poolVerbs.noticeAction,
    findDataItem: (key: string): Obj | null => findDataItem(poolModel, snapshot, key),
    openPin: selectionCtl.openPin,
    openSettings: (): void => selectionCtl.openSettings(SETTINGS_MODAL_ID),
    tplModel, poolModel,
    confirmSuggested: selectionCtl.confirmSuggested,
    chooseDataColumn, chooseDisplay, takePendingConstFocus,
    discardPatch, cancelNewDraft,
    toggleBindingMenu, closeBindingMenu, handleBindingMenu, bindingContextMenu,
    isBindingMenuOpen,
    gotoSection, neighbour, doSave, saveAndOpen, returnScreen, flushPendingEdits, sendEdit,
    guarded,
    doc: deps.doc,
    client: deps.client,
    popover: deps.popover,
    notify: deps.notify,
  };
}

export type EditorController = ReturnType<typeof createEditorController>;
