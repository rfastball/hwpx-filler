/* Editor bridge, draft, and asynchronous interaction controller. */
import type { LintpadSpan } from "../editorview/txt_lintpad.ts";
import type { BridgeClient } from "../runtime/client.ts";
import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import type { ScreenPorts } from "./ports.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import { createContextMenu } from "./context_menu.ts";
import type { ContextMenuItem, ContextMenuPopoverPort } from "./context_menu.ts";
import { invokePathAction } from "./path_actions.ts";
import {
  POOL_DATA_GONE, POOL_GONE_FROM_LIST, ROW_DETAIL_LABEL, createPoolVerbs,
  dataRowMenuItems, poolRefusalText,
} from "./pool_verbs.ts";
import { SETTINGS_MODAL_ID } from "./settings_sheet.ts";
import type { PoolRegistrationPort } from "./pool_verbs.ts";
import {
  NAME_FIELD, PATTERN_FIELD, editorRevision, editorServerValues, editorSession,
  emptyDraft, ingestSnapshot, issueToken, markField, rowField, settle, typeInto,
} from "./editor_state.ts";
import type { DraftState, RowAxis } from "./editor_state.ts";
import { SESSION_DATA_KEY } from "./pool_column.ts";
export type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = {
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

/** `tpl/txt_lint` 한 왕복의 결과 — Python 이 낸 값을 **그대로** 든다.
 *
 *  `content` 는 이 판정이 본 본문이다(세대 검사의 근거). 진단 문안은 `message` 를 그대로
 *  쓴다 — `kind` 로 여기서 문장을 다시 지으면 같은 결함이 두 어휘를 갖는다. */
export type TxtLintState = {
  content: string;
  diagnostics: Obj[];
  summary: Obj;
  spans: LintpadSpan[];
};

type TxtEditState = {
  mode: "new" | "edit";
  path: string;
  title: string;
  name: string;
  content: string;
  baselineName: string;
  baselineContent: string;
  error: string;
  allowClose: boolean;
  /** 마지막으로 도착한 판정(아직 없으면 `null`). 낡은 응답은 여기 오지 못한다. */
  lint: TxtLintState | null;
};

type LibMenu = {
  /** 어느 열의 행인가 — 두 열이 같은 ⋯ 를 쓰므로 **동사표가 이 값으로 갈린다**(③a).
   *  키만으로는 가를 수 없다: 좌는 루트 상대경로, 우는 풀 슬롯 키라 우연히 같을 수 있다. */
  side: "tpl" | "dat";
  media: string;
  kind: "row";
  key?: string;
  item?: Obj | null;
  trigger: HTMLElement;
};

export type ViewState = {
  libMenu: LibMenu | null;
  /** 2단계 머리의 ⋯ 메뉴가 열려 있는가 — 항목·위치는 공용 `ContextMenu` 가 소유한다. */
  bindingMenu: boolean;
  /** 「고정값…」을 고른 행 — 그 입력이 **실제로 선 렌더**에서 초점을 받는다(리뷰 8). */
  pendingConstFocus: number | null;
  txtEdit: TxtEditState | null;
  /** 항목 상세 시트가 열려 있는가(U6-E 리뷰 3) — 동사의 결과가 **어느 채널로 갈지**를 가른다.
   *  시트가 스크림으로 화면을 덮는 동안 `#save-msg` 에 쓰면 그 문장은 뒤에 그려진다. */
  detailOpen: boolean;
  /** 시트가 열려 있는 동안의 동사 실패 문안 — 닫히면 걷힌다(다음 열림에 남지 않는다). */
  detailMessage: string | null;
  tokFoldOpen: boolean;
  saveMessage: { text: string; level: string } | null;
  invalidField: string;
  aim: string;
  /** 이 문맥에서 이미 겨눈 목표 — 문맥당 한 번만 조준한다. */
  aimed: string;
};

/** 편집기 **세션**을 건드리지 않는 tpl 동사 — 완료 뒤 editor 재당김을 걸지 않는다.
 *
 *  `txt_lint` 는 저작 중 타이핑마다(디바운스) 도는 **순수 판정**이라, 재당김이 붙으면
 *  글자 하나마다 편집기 스냅샷 전체가 다시 온다. `refresh` 는 U6-B(#976)에서 합류했다:
 *  목록의 정본이 `tpl` 채널이 된 뒤로 재스캔은 그 채널의 push 하나로 끝나고, 편집기
 *  스냅샷을 한 번 더 묻는 것은 같은 진입에서 디스크를 두 번 읽는 일이다. 나머지 tpl
 *  동사는 파일을 변이시켜 이 세션의 스키마·게이트를 흔들 수 있으므로 종전대로다. */
const TPL_READONLY_ACTIONS = new Set(["txt_lint", "refresh"]);

/** 저작 창의 lint 왕복 디바운스(ms) — 하우스 관용구(`library.ts` 검색 상자와 같은 값). */
const TXT_LINT_DEBOUNCE_MS = 180;

/** 저장 뒤 안내 — 저장은 Draft 보존일 뿐이고 작업에 실리는 것은 별개 동사다(D5 · #299).
 *
 *  이 한 줄이 없으면 「저장했으니 반영됐다」는 조용한 오해가 남는다. 문안의 두 동사는
 *  「문서 만들기」의 실제 버튼 이름이다(`job_run.ts` — 여기서 발명하지 않는다). */
const TXT_SAVE_NOTICE = "저장했습니다. 작업에 반영하려면 「변경사항 확인」 다음 「변경사항 적용」을 누르세요.";

/** 템플릿 행 ⋮ 의 동사표 — 메뉴와 상세 시트가 이 하나를 공유한다. */
export function libRowMenuItems(media: string, item: Obj | null): ContextMenuItem[] {
  if (item === null || item === undefined) return [];
  const detail: ContextMenuItem = { action: "detail", label: ROW_DETAIL_LABEL };
  if (media === "hwpx") {
    return [
      ...((item.actions || []) as Obj[]).map((action: Obj) =>
        ({ action: `act:${String(action.key)}`, label: String(action.label) })),
      detail,
    ];
  }
  return !!item.error || !!item.reason
    ? [detail] : [{ action: "edit", label: "내용 편집" }, detail];
}

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
    libMenu: null, bindingMenu: false, pendingConstFocus: null, txtEdit: null,
    detailOpen: false, detailMessage: null,
    tokFoldOpen: false, saveMessage: null,
    invalidField: "", aim: "", aimed: "",
  };
  const libContextMenu = createContextMenu();
  const bindingContextMenu = createContextMenu();
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
      revision: editorRevision(current),
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

  /** dirty draft를 발신열에 올리고 그 줄을 비운다 — 커밋(이동·저장·이탈) 전 관문이다.
   *  버튼 행동이 먼저 온 경우에도 blur 이벤트의 발생 여부에 기대지 않는다. 이미 blur가 올린
   *  field(`pendingToken > 0`)는 다시 보내지 않고 아래 sentinel이 그 발신만 기다린다. */
  async function flushPendingEdits(): Promise<unknown> {
    const commits: Promise<void>[] = [];
    for (const [field, state] of Object.entries(draft.fields)) {
      if (!state.dirty || state.pendingToken > 0 || state.composing) continue;
      if (field === NAME_FIELD) {
        commits.push(commit(field, "set_name", { name: state.draftValue }));
        continue;
      }
      if (field === PATTERN_FIELD) {
        commits.push(commit(field, "set_pattern", { pattern: state.draftValue }));
        continue;
      }
      /* 행 축의 초안은 **고정값 입력 하나**다(U6-C 리뷰 2). 종전에는 데이터 열 select 도
         초안을 가졌는데 그 값은 열 이름이 아니라 **항목 값**(`col:…`/`sp:…`)이라, 지연
         flush 의 일반 갈래가 그것을 `set_source` 에 그대로 실어 존재하지 않는 열
         「col:품명」에 결속시켰다 — R5 센티넬 금지의 정확한 위반이다. 두 select 는 이제
         초안을 두지 않고 고른 그 자리에서 kind 로 갈라 발행한다. */
      const match = /^row:(\d+):(const)$/.exec(field);
      if (match === null) throw new Error(`알 수 없는 편집 draft field입니다: ${field}`);
      const index = Number(match[1]);
      commits.push(commit(field, "set_const", { index, const: state.draftValue }));
    }
    await Promise.all(commits);
    return deps.chain.chained(EDIT_CHAIN, () => Promise.resolve());
  }

  /* ---- draft 커밋: 컨트롤에서 온 값의 발신 자리 ---- */

  function type(field: string, value: string): void {
    draft = typeInto(draft, field, value);
    /* 겨눈 칸을 사용자가 고치는 순간 그 차단 알림은 현 상태를 서술하지 않는다 — 겨눔과
       사유를 같은 전이에서 함께 걷는다(#874). */
    if (view.invalidField !== "" && field === view.invalidField) {
      patchView({ invalidField: "", saveMessage: null });
    }
    emitDraft();
  }

  function focus(field: string, focused: boolean): void {
    draft = markField(draft, field, { focused });
    emitDraft();
  }

  function compose(field: string, composing: boolean): void {
    draft = markField(draft, field, { composing });
    emitDraft();
  }

  /** 값 커밋 — session·token 이 맞는 응답만 draft 를 clean 으로 올린다. */
  async function commit(field: string, action: string, payload: Obj): Promise<void> {
    const session = draft.session;
    const issued = issueToken(draft, field);
    draft = issued.state;
    emitDraft();
    try {
      await sendEdit(action, payload);
      draft = settle(draft, { ok: true, session, token: issued.token, key: field });
    } catch (error) {
      draft = settle(draft, {
        ok: false, session, token: issued.token, key: field,
        error: String((error as Obj)?.message || error),
      });
      deps.notify(String((error as Obj)?.message || error));
    }
    emitDraft();
  }

  /* 발신은 **호출 자리마다 리터럴**이다 — 액션 이름과 페이로드 키를 표로 감추면 정적
     계약(dispatch 배선·페이로드 스키마)이 이 화면을 못 보고 공허하게 통과한다. */
  function commitField(field: string): void {
    const state = draft.fields[field];
    if (state === undefined || !state.dirty) return;
    if (field === NAME_FIELD) void commit(field, "set_name", { name: state.draftValue });
    if (field === PATTERN_FIELD) void commit(field, "set_pattern", { pattern: state.draftValue });
  }

  /** 데이터 열 항목 값 → 발행할 액션(U6-C #977).
   *
   *  **값을 파싱하지 않는다** — Python 이 낸 항목 목록에서 그 값을 찾아 `kind` 를 읽는다.
   *  접두 규칙(`col:`/`sp:`)을 여기서 다시 해석하면 그 규칙을 두 곳이 소유하게 되고,
   *  Python 이 이름 공간을 바꾸는 날 웹만 옛 규칙으로 남는다. 목록에 없는 값은 조용히
   *  무시하지 않고 시끄럽게 던진다(선택지에 없는 것이 선택됐다 = 배선 결함). */
  /** 표 안의 두 select 가 쓰는 **초안 없는** 발신(U6-C 리뷰 2).
   *
   *  select 는 값을 들고 있을 이유가 없다 — 고르는 순간이 곧 커밋이고, 타이핑처럼 지켜야 할
   *  중간 상태가 없다. 초안을 두면 그 값(항목 값)이 지연 flush 의 일반 갈래로 새어 액션
   *  payload 를 오염시킨다. 실패하면 화면을 서버 값으로 되돌린다: 재렌더가 제어 select 의
   *  DOM 값을 스냅샷 값으로 되맞추므로 「고른 것처럼 보이는데 안 고른」 자리가 남지 않는다. */
  function sendRowChoice(action: string, payload: Obj): void {
    void sendEdit(action, payload)
      .catch((error) => { noticeSave(String((error as Obj)?.message || error)); })
      /* 성공이든 실패든 한 번 더 그린다 — 실패는 되돌리기고, 성공은 push 가 오기 전까지
         화면이 옛 값을 들고 있지 않게 하는 정산이다. */
      .finally(() => { patchView({}); });
  }

  /** 데이터 열 항목 값 → 발행할 액션(U6-C #977).
   *
   *  **값을 파싱하지 않는다** — Python 이 낸 항목 목록에서 그 값을 찾아 `kind` 를 읽는다.
   *  접두 규칙(`col:`/`sp:`)을 여기서 다시 해석하면 그 규칙을 두 곳이 소유하게 되고,
   *  Python 이 이름 공간을 바꾸는 날 웹만 옛 규칙으로 남는다. 목록에 없는 값은 조용히
   *  무시하지 않고 시끄럽게 던진다(선택지에 없는 것이 선택됐다 = 배선 결함). */
  function chooseDataColumn(index: number, value: string): void {
    const options = (snapshot().data_column_options || []) as Obj[];
    const row = ((snapshot().rows || []) as Obj[]).find((r) => Number(r.index) === index);
    /* 「데이터에 없음」 항목은 그 행에만 서는 자리라 공용 목록에 없다 — 지금 값 그대로
       되보내는 무동작이므로 발신하지 않는다(같은 열을 다시 고른 것과 같다). */
    if (row && row.source_missing_label && value === String(row.source_value)) return;
    const picked = options.find((option) => String(option.value) === value);
    if (picked === undefined) throw new Error(`알 수 없는 데이터 열 항목입니다: ${value}`);
    const kind = String(picked.kind);
    if (kind === "column") {
      sendRowChoice("set_source", { index, source: String(picked.field) });
    } else if (kind === "none") {
      sendRowChoice("set_source", { index, source: "" });
    } else {
      /* 「고정값…」을 고르면 값을 적을 자리가 새로 생긴다. 그 입력은 **서버가 이 행을
         const 로 인정한 뒤에야** 렌더되므로 지금 DOM 에는 없다 — 마이크로태스크로 겨누면
         언제나 빈손이다. 표지를 남기고 그 입력이 실제로 선 렌더에서 초점을 준다(리뷰 8). */
      if (kind === "const") patchView({ pendingConstFocus: index });
      sendRowChoice("set_display", { index, type: kind, fmt: "" });
    }
  }

  /** 표시형 항목 값 → (유형, 표시형) 한 쌍(U6-C 리뷰 1). 값 문자열은 파싱하지 않는다 —
   *  항목이 `type`·`fmt` 를 따로 들고 오므로 접두 규칙을 웹이 소유하지 않는다. */
  function chooseDisplay(index: number, value: string): void {
    const row = ((snapshot().rows || []) as Obj[]).find((r) => Number(r.index) === index);
    const groups = ((row || {}).display_options || []) as Obj[];
    for (const group of groups) {
      const picked = ((group.options || []) as Obj[])
        .find((option) => String(option.value) === value);
      if (picked !== undefined) {
        sendRowChoice("set_display", {
          index, type: String(picked.type), fmt: String(picked.fmt),
        });
        return;
      }
    }
    throw new Error(`알 수 없는 표시형 항목입니다: ${value}`);
  }

  function commitRowValue(index: number, axis: RowAxis, value: string): void {
    void commit(rowField(index, axis), "set_const", { index, const: value });
  }

  function commitRow(index: number, axis: RowAxis, value: string): void {
    type(rowField(index, axis), value);
    commitRowValue(index, axis, value);
  }

  function commitRowOnBlur(index: number, axis: RowAxis): void {
    const state = draft.fields[rowField(index, axis)];
    if (state === undefined || !state.dirty) return;
    commitRowValue(index, axis, state.draftValue);
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

  /* ---- 라이브러리 관리(F8 — tpl 화면 사망의 승계) ---- */

  /** 좌 열 항목 전수 — 정본은 `tpl` 채널의 **공용 열 존**(`column.rows`) 하나다.
   *
   *  종전에는 매체별 밴드(`hwpx`/`txt` 의 `sections[].items[]`)를 여기서 이어 붙여 한
   *  목록으로 만들었다. 그 접기는 이제 Python 이 하고(좌·우 열이 같은 형을 쓰는 조건),
   *  표면이 그 순서를 두 번 짓지 않는다 — 목록이 갈릴 자리가 사라진다. */
  function libItems(): Obj[] {
    return (((tplModel.getSnapshot() || {}).column || {}).rows || []) as Obj[];
  }

  /** 좌 열 항목 하나 — 매체는 행이 든 표지(`icon`)로 대조한다.
   *
   *  키만으로 찾지 않는 이유는 ⋮ 의 열림 상태가 `(media, key)` 쌍이기 때문이다: 겨눈 행이
   *  바뀌었는데 키가 같으면 지난 행의 메뉴가 그대로 서 있게 된다. */
  function findLibItem(media: string, key: string): Obj | null {
    return libItems().find(
      (row) => String(row.key) === key && String(row.icon || "") === media) || null;
  }

  /** 우 열 항목 하나 — 목록 행(`pool.column.rows`)과 세션 행(`pairing.data_row`)의 합.
   *
   *  세션 행은 풀에 없는 결속(파일로 연 데이터)이라 `pool` 채널에 없다. 그 행을 여기서
   *  찾지 못하면 그 행의 ⋯ 가 조용히 빈 메뉴가 된다 — 두 출처를 같은 자리에서 본다. */
  function findDataItem(key: string): Obj | null {
    if (key === SESSION_DATA_KEY) {
      return ((snapshot().pairing || {}) as Obj).data_row as Obj | null || null;
    }
    const rows = (((poolModel.getSnapshot() || {}).column || {}).rows || []) as Obj[];
    return rows.find((row) => String(row.key) === key) || null;
  }

  function closeLibMenu(): void {
    patchView({ libMenu: null });
    libContextMenu.close();
  }

  /* 겨눔은 **행 하나**다 — 그룹 갈래는 U4 §2-30 에서 그룹 표면과 함께 사라졌다. */
  function openLibMenu(
    side: "tpl" | "dat", media: string, id: string, trigger: HTMLElement,
  ): void {
    const item = side === "tpl" ? findLibItem(media, id) : findDataItem(id);
    const items: ContextMenuItem[] = side === "tpl"
      ? libRowMenuItems(media, item) : dataRowMenuItems(item);
    /* 동작이 0 이면 애초에 트리거가 비활성이라 여기 오지 않는다(어포던스는 `LibRowTail`
       이 같은 술어로 잠근다) — 그래도 방어로 남긴다: 빈 팝오버는 「눌렀는데 아무 일도
       없다」라서 조용한 no-op 이다. */
    if (items.length === 0) return;
    patchView({ libMenu: { side, media, kind: "row", key: id, item, trigger } });
    libContextMenu.open(trigger, items);
  }

  function toggleLibMenu(
    side: "tpl" | "dat", media: string, id: string, trigger: HTMLElement,
  ): void {
    const open = view.libMenu;
    if (open !== null && open.side === side && open.media === media && open.key === id) {
      closeLibMenu(); return;
    }
    openLibMenu(side, media, id, trigger);
  }

  /** 항목 동사의 **단일 분기표**(U6-E 리뷰 9) — 행 ⋯ 와 시트 동사 줄이 같은 것을 본다.
   *
   *  갈리는 것은 **대상과 실패의 착지**뿐이라 둘 다 인자로 받는다: 행 메뉴는 눌린 행을
   *  겨누고 예외를 경보 백스톱으로 보내며, 시트는 열려 있는 항목을 겨누고 사유를 시트 안에
   *  남긴다. 표를 복제하면 한쪽에만 동사가 늘어나는 날이 온다.
   *
   *  **닫힌 집합이다**: 모르는 키를 조용히 떨어뜨리면 메뉴에 항목을 더하고 배선을 잊은 날
   *  「눌렀는데 아무 일도 없다」가 된다. 목록을 짓는 곳(`libRowMenuItems`)과 여기가 같은
   *  집합을 봐야 하고, 어긋남은 던진다. `act:review` 가 없는 것은 계약이다 — 검토 왕복은
   *  「자세히…」 하나가 진다(리뷰 10).
   */
  async function runItemVerb(
    action: string, target: Obj, trigger: HTMLElement,
  ): Promise<void> {
    const path = String(target.path || "");
    if (action === "edit") {
      const result = await dispatch("tpl", "txt_content", { path });
      openTxtEdit("edit", path, String(target.name || ""), String(result.content || ""), trigger);
    } else if (action === "detail") await openDetail(path, trigger);
    else if (action === "act:compile") await compileTemplate(path);
    else throw new Error(`알 수 없는 항목 동사입니다: ${action}`);
  }

  async function handleLibMenu(action: string): Promise<void> {
    const menu = view.libMenu;
    if (menu === null) return;
    const item = (menu.item || {}) as Obj;
    const trigger = menu.trigger;
    const side = menu.side;
    closeLibMenu();
    try {
      /* 우 열 분기표는 **공용 몸통 하나**다(공용 ⑤ 리뷰) — 이 화면이 데이터 동사를
         발명하지 않는다. 좌 열(`runItemVerb`)은 tpl 채널이라 여기 남는다. */
      if (side === "dat") await poolVerbs.runVerb(action, item, trigger);
      else await runItemVerb(action, item, trigger);
    } catch (error) {
      deps.notify(String((error as Obj)?.message || error));
    }
  }

  /** 「자세히…」 — 검토 왕복이 시트의 재료를 채우고 **그 뒤에** 시트를 연다(U6-E #979).
   *
   *  순서가 계약이다: 먼저 열면 지난 항목의 상세가 한 프레임 서 있다가 갈리고, 검토가
   *  거절되면 빈 시트만 남는다. 실패는 왕복이 던지므로 호출자의 백스톱까지 올라간다.
   *
   *  열림·닫힘을 뷰 상태로 드는 이유는 **동사 결과의 채널**이 그 사실로 갈리기 때문이다
   *  (리뷰 3): 시트가 화면을 덮는 동안 `#save-msg` 에 쓴 문장은 스크림 뒤에 그려진다. */
  async function openDetail(path: string, trigger: HTMLElement): Promise<void> {
    await dispatch("tpl", "review", { path });
    patchView({ detailOpen: true, detailMessage: null });
    deps.modal.open("tplDetailModal", {
      returnFocus: trigger,
      beforeClose: () => {
        patchView({ detailOpen: false, detailMessage: null });
        return true;
      },
    });
  }

  /** 동사 실패의 착지 — 시트가 열려 있으면 **시트 안**, 아니면 인라인 채널(#323).
   *
   *  같은 문장을 두 자리에 쓰지 않는다: 읽는 사람이 지금 보고 있는 면에 남긴다. */
  function noticeVerb(message: string): void {
    if (view.detailOpen) patchView({ detailMessage: message });
    else noticeSave(message);
  }

  /** 누름틀·구간 변환 — 2단계(스캔 dry-run → 확인 왕복 → 제자리 적용).
   *
   *  문안·수치·차단 판정은 Python 이 낸다. 여기서 재조립하지 않는다: 차단(`blocked`)은
   *  결과 줄로 이미 재진술됐으므로 확인을 띄우지 않고 조용히 끝난다. */
  async function compileTemplate(path: string): Promise<void> {
    const result = await dispatch("tpl", "compile", { path });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n지금 변환할까요?`,
      confirmLabel: "제자리 변환", cancelLabel: "취소", danger: true,
    })) {
      await dispatch("tpl", "compile", { path, confirm: true });
    }
  }

  /* 동봉 예제 세트의 설치(#891)·제거(#892) 진입점은 여기 있었다. 튜토리얼 진입 표면과 함께
     배포본에서 걷혔고(#941), `tpl` 채널의 `install_examples`·`remove_examples` 액션과 그
     스냅샷 축(`library.examples`)은 동결로 남는다 — 되살릴 때 이 자리에서 다시 소비한다. */

  /* ---- 컴파일된 구간 항목(Slot) 관리 동사 3종(S8-03) ----
     동사가 서는 자리는 U6-E(#979)에서 **항목 상세 시트** 안으로 옮겼다. 겨누는 경로·목록은
     그래서 `tpl` 채널의 `detail` 존이 낸다 — 시트가 그리는 것과 동사가 겨누는 것이 같은
     값이어야 「보이는 항목과 다른 파일을 바꾸는」 자리가 생기지 않는다. */

  /** 시트가 지금 겨눈 상세(없으면 빈 객체) — 동사와 렌더가 같은 값을 읽는 단일 자리. */
  function detailZone(): Obj {
    return ((tplModel.getSnapshot() || {}).detail || {}) as Obj;
  }

  function detailPath(): string {
    return String(detailZone().path || "");
  }

  /** 항목 이름 바꾸기 — 파괴가 아니라 프롬프트 하나다(확인 왕복 없음). */
  async function renameSlot(slotId: string, label: string, trigger: HTMLElement): Promise<void> {
    const value = await deps.modal.prompt({
      /* 빈 문자열도 유효한 답이다(이름 없는 항목으로 되돌리기) — 검증을 걸지 않는다. */
      title: "항목 이름 바꾸기", body: `'${slotId}' 의 새 이름`, value: label,
      returnFocus: trigger,
    });
    if (value === null) return;
    await dispatch("tpl", "slot_rename", { path: detailPath(), slot_id: slotId, label: value });
  }

  /** 항목을 표기로 되돌리기 — 확인 본문(전이 결과 재진술)은 Python 이 싣는다. */
  async function decompileSlot(slotId: string, trigger: HTMLElement): Promise<void> {
    const path = detailPath();
    const result = await dispatch("tpl", "slot_decompile", { path, slot_id: slotId });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n되돌릴까요?`,
      confirmLabel: "표기로 되돌리기", cancelLabel: "취소", returnFocus: trigger, danger: true,
    })) {
      await dispatch("tpl", "slot_decompile", { path, slot_id: slotId, confirm: true });
    }
  }

  /** 이 템플릿의 항목을 전부 표기로 되돌리기 — 대상이 항목이 아니라 파일이라 `slot_id` 가 없다. */
  async function decompileAllSlots(trigger: HTMLElement): Promise<void> {
    const path = detailPath();
    const result = await dispatch("tpl", "slot_decompile_all", { path });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n되돌릴까요?`,
      confirmLabel: "전부 되돌리기", cancelLabel: "취소", returnFocus: trigger, danger: true,
    })) {
      await dispatch("tpl", "slot_decompile_all", { path, confirm: true });
    }
  }

  /** 항목 삭제 — 내용째 사라지는 파괴 확정. */
  async function removeSlot(slotId: string, trigger: HTMLElement): Promise<void> {
    const path = detailPath();
    const result = await dispatch("tpl", "slot_remove", { path, slot_id: slotId });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n지울까요?`,
      confirmLabel: "삭제", cancelLabel: "취소", returnFocus: trigger, danger: true,
    })) {
      await dispatch("tpl", "slot_remove", { path, slot_id: slotId, confirm: true });
    }
  }

  /** 상세 시트 동사 줄의 단일 진입 — 겨누는 것은 **시트가 지금 든 항목**이다(리뷰 9).
   *
   *  분기표는 행 ⋮ 와 공유하고(`runItemVerb`) 여기가 정하는 것은 대상과 실패의 착지뿐이다. */
  async function handleDetailVerb(action: string, trigger: HTMLElement): Promise<void> {
    patchView({ detailMessage: null });   // 새 동사는 지난 사유를 이고 가지 않는다
    try {
      await runItemVerb(action, detailZone(), trigger);
    } catch (error) {
      noticeVerb(String((error as Obj)?.message || error));
    }
  }

  /** Slot 동사의 단일 진입 — 실패는 인라인 채널로(#323 라우팅 규칙).
   *
   *  밴드 동사(`decompile-all`)는 `slotId` 를 쓰지 않는다 — 대상이 파일이다. */
  async function handleSlotVerb(
    verb: string, slotId: string, trigger: HTMLElement,
  ): Promise<void> {
    try {
      if (verb === "decompile-all") await decompileAllSlots(trigger);
      else if (verb === "rename") {
        const rows = ((detailZone().slots || {}).rows || []) as Obj[];
        const row = rows.find((item) => String(item.id) === slotId);
        await renameSlot(slotId, String((row || {}).label || ""), trigger);
      } else if (verb === "decompile") await decompileSlot(slotId, trigger);
      else if (verb === "remove") await removeSlot(slotId, trigger);
      else throw new Error(`알 수 없는 항목 동사입니다: ${verb}`);
    } catch (error) {
      /* 구간 동사는 **시트 안**에 서므로 실패도 그 면에 남는다(리뷰 3) — 시트가 닫혀 있는
         호출(프로브·직접 호출)에서는 종전대로 인라인 채널이 받는다. */
      noticeVerb(String((error as Obj)?.message || error));
    }
  }

  /* ---- TXT 저작 모달 ---- */

  function txtDirty(state: TxtEditState): boolean {
    return state.name !== state.baselineName || state.content !== state.baselineContent;
  }

  function openTxtEdit(
    mode: "new" | "edit", path: string, name: string, content: string, trigger: HTMLElement,
  ): void {
    const state: TxtEditState = {
      mode, path: path || "",
      title: mode === "new" ? "새 TXT 템플릿" : `TXT 템플릿 편집: ${name}`,
      name: "", content: content || "",
      baselineName: "", baselineContent: content || "",
      error: "", allowClose: false, lint: null,
    };
    patchView({ txtEdit: state });
    scheduleTxtLint(state.content);   // 연 순간의 표기 상태부터 말한다(첫 타이핑을 기다리지 않는다)
    deps.modal.open("txtEditModal", {
      /* 초기 포커스는 여기서 넘기지 않는다 — 이 시점엔 창 내용이 아직 커밋 전이라 대상이
         없다. 겨눔은 `TxtEditDialog` 의 커밋 뒤 effect 가 진다. */
      returnFocus: trigger,
      beforeClose: () => {
        const current = view.txtEdit;
        if (current === null || current.allowClose || !txtDirty(current)) {
          cancelTxtLint();          // 도착할 곳이 사라졌다 — 예약과 진행 중 왕복을 함께 걷는다
          patchView({ txtEdit: null });
          return true;
        }
        void confirmDiscardTxtEdit();
        return false;
      },
    });
  }

  function patchTxtEdit(next: Partial<TxtEditState>): void {
    if (view.txtEdit === null) return;
    patchView({ txtEdit: { ...view.txtEdit, ...next } });
  }

  /* ---- 저작 중 본문의 라이브 판정(S10-05 #862) ----
     판정 원천은 링0 스캐너 하나다(`tpl/txt_lint` → `scan_text_structure`). 표면은 좌표와
     문안을 받아 얹기만 하고 `{{…}}` 를 다시 가르지 않는다 — sigil 선행 분류가 두 곳에
     살면 같은 토큰이 표면과 백엔드에서 다른 것이 된다. */

  /** 왕복 세대 — 낡은 응답이 새 입력을 덮지 않게 하는 두 관문 중 하나. */
  let txtLintGeneration = 0;
  let txtLintTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleTxtLint(content: string): void {
    if (txtLintTimer !== null) clearTimeout(txtLintTimer);
    txtLintTimer = setTimeout(() => {
      txtLintTimer = null;
      void runTxtLint(content);
    }, TXT_LINT_DEBOUNCE_MS);
  }

  /** 예약된 판정을 걷는다 — 창이 닫히면 도착할 곳이 없다. */
  function cancelTxtLint(): void {
    if (txtLintTimer !== null) clearTimeout(txtLintTimer);
    txtLintTimer = null;
    txtLintGeneration += 1;
  }

  /** 한 왕복. 실패는 **조용히** 버린다 — 린트는 보조 표시라, 못 물었다고 저작을 막지 않는다.
   *
   *  관문 둘: ① 세대(그 사이 새 요청이 떴는가) ② 본문 대조(응답이 본 문자열이 지금
   *  화면의 것인가). 오프셋을 다른 문서에 얹으면 강조가 조용히 어긋난다. */
  async function runTxtLint(content: string): Promise<void> {
    const generation = ++txtLintGeneration;
    let result: Obj;
    try {
      result = await dispatch("tpl", "txt_lint", { content });
    } catch {
      return;
    }
    if (generation !== txtLintGeneration) return;
    const current = view.txtEdit;
    if (current === null || current.content !== content) return;
    patchTxtEdit({
      lint: {
        content,
        diagnostics: (result.diagnostics || []) as Obj[],
        summary: (result.summary || {}) as Obj,
        spans: (result.spans || []) as LintpadSpan[],
      },
    });
  }

  /** 메모장이 낸 본문 변경 — 상태를 갱신하고 판정을 다시 예약한다. */
  function typeTxtEdit(content: string): void {
    if (view.txtEdit === null || view.txtEdit.content === content) return;
    patchTxtEdit({ content });
    scheduleTxtLint(content);
  }

  async function confirmDiscardTxtEdit(): Promise<void> {
    const current = view.txtEdit;
    if (current === null) return;
    if (!txtDirty(current)) {
      patchTxtEdit({ allowClose: true });
      deps.modal.close("txtEditModal");
      return;
    }
    const accepted = await deps.modal.confirm({
      title: "편집 내용 버리기",
      body: "저장하지 않은 템플릿 내용이 사라집니다.",
      confirmLabel: "편집 내용 버리기", cancelLabel: "계속 편집",
    });
    if (accepted && view.txtEdit !== null) {
      patchTxtEdit({ allowClose: true });
      deps.modal.close("txtEditModal");
    }
  }

  /** 편집 저장 — 드리프트 확인 왕복(#216 이월 2). 문안·지문은 Python 이 낸다.
   *
   *  확인을 받고 되부른 호출이 **또** 막힐 수 있다(그 사이 또 바뀜) — 그때는 새 문안·새
   *  지문으로 다시 묻는다. 취소하면 창을 그대로 둔다(편집 내용을 잃지 않는다). */
  async function saveTxtEdit(state: TxtEditState): Promise<boolean> {
    const { path, content, baselineContent: baseline } = state;
    let confirmed = "";
    for (;;) {
      const payload: Obj = { path, content, baseline };
      if (confirmed) payload.confirm_fingerprint = confirmed;
      const result = await dispatch("tpl", "txt_edit", payload);
      if (!result.needs_confirm) return true;
      const accepted = await deps.modal.confirm({
        body: `${result.text}\n\n덮어쓸까요?`,
        confirmLabel: "덮어쓰기", cancelLabel: "취소", danger: true,
      });
      if (!accepted) return false;
      confirmed = String(result.fingerprint || "");
    }
  }

  async function submitTxtEdit(): Promise<void> {
    const current = view.txtEdit;
    if (current === null) return;
    try {
      if (current.mode === "new") {
        await dispatch("tpl", "txt_new", { name: current.name, content: current.content });
      } else if (!await saveTxtEdit(current)) {
        return;                                  // 덮어쓰기를 거절했다 — 창은 그대로 산다
      }
      closeTxtEditAfterSave();
    } catch (error) {
      patchTxtEdit({ error: String((error as Obj)?.message || error) });
    }
  }

  /** 편집 중인 본문을 **다른 이름의 새 템플릿**으로 낸다(D5 · #299).
   *
   *  새 백엔드 동사를 세우지 않는다 — 「새 TXT 템플릿」이 쓰는 `txt_new` 를 그대로 부른다.
   *  이름 검증·중복 차단은 그쪽 한 자리가 지고 여기서 재조립하지 않는다. 취소는 창을
   *  그대로 둔다(편집 내용을 잃지 않는다). */
  async function saveTxtEditAsNew(trigger: HTMLElement): Promise<void> {
    const current = view.txtEdit;
    if (current === null) return;
    const name = await deps.modal.prompt({
      title: "새 파일로 저장",
      body: "새 TXT 템플릿 이름(확장자 제외)",
      value: "", returnFocus: trigger,
    });
    if (name === null) return;
    try {
      await dispatch("tpl", "txt_new", { name, content: current.content });
      closeTxtEditAfterSave();
    } catch (error) {
      patchTxtEdit({ error: String((error as Obj)?.message || error) });
    }
  }

  /** 저장 성공 뒤 닫기 — 창을 걷고 **저장의 한계**를 인라인으로 재진술한다.
   *
   *  TXT 정본에서 파일 쓰기는 Draft 보존까지다(L19). Candidate 가 태어나는 것은 「문서
   *  만들기」의 「변경사항 확인」이고, 그것을 말하지 않으면 저장이 반영까지 한 것처럼
   *  읽힌다 — 한 동작이 두 사건인 척하지 않게 하는 한 줄이다. */
  function closeTxtEditAfterSave(): void {
    patchTxtEdit({ allowClose: true });
    deps.modal.close("txtEditModal");
    noticeSave(TXT_SAVE_NOTICE, "ok");
  }

  /* ---- 확인 관문 ---- */

  /** 확정·수동 매핑 보호 — 수치는 Python 이 **지금** 판정한다(stale 우회 차단). */
  async function confirmMappingResetIfConfirmed(verbPhrase: string): Promise<boolean> {
    const stakes = await sendEdit("mapping_reset_stakes", {});
    const human = Number(stakes.human || 0);
    if (!human) return true;
    return deps.modal.confirm({
      body: `${verbPhrase} 확정했거나 직접 편집한 매핑 ${human}개가 전부 미확정으로 돌아갑니다` +
        `(값은 이월).\n\n계속할까요?`,
      confirmLabel: "미확정으로 되돌리기", cancelLabel: "취소",
    });
  }

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

  async function doSave(flags: Obj = {}): Promise<boolean> {
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
      clearSaveMessage();   // 막았던 사유가 해소됐다 — 차단 문안을 남겨 두지 않는다(#874)
      /* 겨눔 표지도 같은 전이에서 걷는다: 사유가 사라졌는데 칸만 빨갛게 남으면 화면이
         「저장됐다」와 「이 칸이 잘못됐다」를 동시에 말한다. */
      if (view.invalidField !== "") patchView({ invalidField: "" });
      /* 저장은 제자리(결정 40). 후보·문서 탐색 스냅샷만 갱신해 새/개명 작업이 바로 보이게 한다. */
      void deps.ports.jobRead.current().refreshList();
      return true;
    }
    if (result.needs_overwrite) {
      /* 본 문안을 그대로 되돌려 준다(#149) — 판정은 Python 이 쓰기 잠금 안에서 다시 한다. */
      if (await deps.modal.confirm({
        body: `${result.overwrite_text}\n\n계속할까요?`,
        confirmLabel: "덮어쓰기", cancelLabel: "취소", danger: true,
      })) {
        return doSave({
          ...flags, confirm_overwrite: true, confirmed_overwrite_text: result.overwrite_text,
        });
      }
      return false;
    }
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
   *     `#save-msg` 로 재진술한다 — 저장은 이미 일어났고 사람이 다시 누를 일이 아니다. */
  async function saveAndOpen(): Promise<void> {
    if (!(await doSave({}))) return;
    const name = String(snapshot().name || "");
    let result: Obj;
    try {
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

  /* ---- 본문 행동 ---- */

  /** 템플릿 채택 — **같은 템플릿이면 아무 일도 하지 않고**, 교체면 먼저 묻는다.
   *
   *  둘 다 고르기 화면이 연 자리다(U6-B #976 리뷰 1·2). 종전 표면에서는 현재 항목이 클릭
   *  핸들러 없는 span 이라 재선택이 구조적으로 불가능했고, 교체 확인은 데이터 쪽에만 있었다
   *  — 이제 같은 제스처(클릭·끌어 놓기)가 좌·우에 다 서므로 규칙도 하나여야 한다.
   *  수치는 Python 이 **지금** 판정한다(`mapping_reset_stakes` — 웹 지역 스냅샷 금지),
   *  확인 UI 만 여기서 짓는다. 백엔드도 같은 no-op 을 진다(표면만 막으면 뚫린다). */
  async function useLibraryTemplate(path: string): Promise<boolean> {
    if (path === String(snapshot().template_path || "")) return true;
    if (snapshot().template_path
      && !(await confirmMappingResetIfConfirmed("템플릿을 바꾸면"))) return false;
    await sendEdit("use_library_template", { path });
    return true;
  }

  async function importTemplate(): Promise<void> {
    const result = await invoke("import_template_file", SCREEN);
    if (typeof result === "string" && result.startsWith("ERROR:")) {
      noticeSave(result.slice(6).trim());
      return;
    }
    if (typeof result === "string" && result !== "") await deps.runtime.refresh(SCREEN);
  }

  async function pickData(): Promise<void> {
    if (!(await confirmMappingResetIfConfirmed("데이터를 바꾸면"))) return;
    let result = await invoke("pick_data_file", SCREEN) as any;
    if (result && typeof result === "object" && result.needs_sheet) {
      result = await deps.services.sheetPicker.current().choose(SCREEN, result);
      if (result === null) return;                             // 취소 = 중단(첫 시트 강등 없음)
    }
    if (typeof result === "string" && result.startsWith("ERROR:")) {
      noticeSave(result.slice(6).trim());
      return;
    }
  }

  /** 고정한 데이터 하나를 이 작업의 데이터로 — 파일 피커와 **같은 선행 규율**을 지킨다:
   *  확정 매핑이 걸린 교체는 고르기 **전에** 한 번 묻는다(고른 뒤 되묻는 순서 금지). */
  async function usePoolData(key: string): Promise<boolean> {
    if (!(await confirmMappingResetIfConfirmed("데이터를 바꾸면"))) return false;
    const result = await sendEdit("use_pool_data", { key });
    if (result.ok === false) {
      noticeSave(String(result.error || "등록 데이터를 불러올 수 없습니다."));
      return false;
    }
    return true;
  }

  /* 고를 수 없는 항목의 거절 문안과 「목록에서 사라졌다」는 **데이터 선택 다이얼로그와
     공용**이다(③b — 두 자리가 같은 열을 그리므로 거절의 문형도 한 벌이다). 사유 자체는
     Python 이 행에 실어 보낸 것을 그대로 재진술한다. */
  function refuseSelection(name: string, reason: string): void {
    noticeSave(poolRefusalText(name, reason));
  }

  /** 좌 열 선택 — 클릭도 드롭도 **이 한 자리**를 지난다(같은 액션, 같은 거절).
   *
   *  ``refusals`` 를 받으면 거절을 그 배열에 담고 알림은 **호출자가** 낸다(끌어 놓기는 두
   *  반의 결과를 한 문장으로 말해야 하고, 알림 채널이 1슬롯이라 각자 쓰면 앞 문장이 사라진다).
   *  반환값은 「이 반쪽이 적용됐는가」다. */
  async function chooseTemplate(key: string, refusals?: string[]): Promise<boolean> {
    const item = libItems().find((row) => String(row.key) === key);
    const refuse = (text: string): boolean => {
      if (refusals) refusals.push(text); else noticeSave(text);
      return false;
    };
    if (item === undefined) return refuse(`템플릿을 찾을 수 없습니다. ${POOL_GONE_FROM_LIST}`);
    if (!item.selectable) {
      return refuse(poolRefusalText(String(item.name), String(item.reason || "")));
    }
    return useLibraryTemplate(String(item.path));
  }

  /** 우 열 선택 — 좌 열과 대칭.
   *
   *  세션 행(파일로 연 데이터)은 **무동작**이다(③a): 이미 이 작업의 데이터라 다시 마운트할
   *  것이 없고, 풀에 없으니 「목록에서 사라졌다」도 아니다. 거절 문장을 세우면 지금 쓰고
   *  있는 것을 못 고른다고 말하는 꼴이 된다 — 좌 열의 「이미 고른 항목 재선택 = 무동작」과
   *  같은 자리다. */
  async function chooseData(key: string, refusals?: string[]): Promise<boolean> {
    if (key === SESSION_DATA_KEY) return false;
    /* 재료는 **그리고 있는 그 열**이다(고르기 열 공용 ④) — 다른 존을 곁눈질하면 화면에
       선 사유와 거절이 재진술하는 사유가 서로 다른 출처에서 온다. */
    const row = findDataItem(key);
    const refuse = (text: string): boolean => {
      if (refusals) refusals.push(text); else noticeSave(text);
      return false;
    };
    if (row === null) return refuse(POOL_DATA_GONE);
    if (!row.selectable) {
      return refuse(poolRefusalText(String(row.name), String(row.reason || "")));
    }
    return usePoolData(key);
  }

  /** 끌어 놓기 성사 — **클릭이 발행하는 액션 두 번**이다(새 액션 0).
   *
   *  순서는 템플릿 먼저다: 템플릿이 필드를 정하고 그 위에 데이터가 온다(U4 §2.4). 뒤집으면
   *  데이터 마운트가 모델 재조립을 태운 뒤 템플릿 교체가 그것을 또 무너뜨린다.
   *
   *  우 열의 세션 행(`session`)이 상대가 되면 **데이터 쪽은 그대로 둔다**(③a) — 「지금 쓰는
   *  데이터에 이 템플릿을 붙인다」는 뜻이고, 그 무동작은 `chooseData` 하나가 진다(거절 0). */
  async function dropPair(sourceSide: string, sourceKey: string, targetKey: string): Promise<void> {
    const [templateKey, dataKey] = sourceSide === "tpl"
      ? [sourceKey, targetKey] : [targetKey, sourceKey];
    /* 거절은 **모아서 한 번** 말한다(리뷰 5): 알림 채널이 1슬롯이라 두 반쪽이 각자 쓰면
       먼저 쓴 문장이 조용히 사라지고, 사람은 무엇이 반만 바뀌었는지 알 수 없다. */
    const refusals: string[] = [];
    const gotTemplate = await chooseTemplate(templateKey, refusals);
    const gotData = await chooseData(dataKey, refusals);
    if (refusals.length === 0) return;
    const applied = [gotTemplate ? "템플릿" : "", gotData ? "데이터" : ""].filter(Boolean);
    noticeSave(applied.length
      ? `${applied.join("·")}만 바뀌었습니다. ${refusals.join(" ")}`
      : refusals.join(" "));
  }

  /* 동사 한 벌은 데이터 선택 다이얼로그와 **같은 몸통**이다(U6-B · 공용 ⑤ 리뷰) — 같은
     `pool` 채널·같은 확인 왕복·같은 분기표·같은 검토 왕복·같은 통지 동사. 갈리는 것은
     「사용」의 발행과 실패가 착지하는 자리, 그리고 네 포트뿐이다. */
  const poolVerbs = createPoolVerbs({
    /* 관리 동사도 **편집 체인**에 선다(리뷰 6): 이 화면의 다른 발신과 순서를 나눠 갖지
       않으면 보관·삭제가 마운트·저장 왕복 사이로 끼어든다. 연타 차단은 공용 몸통의
       in-flight 가드가 지고(다이얼로그와 같은 자리), 체인은 그 위의 직렬화다. */
    dispatch: (screen: string, action: string, payload: Obj = {}) =>
      deps.chain.chained(EDIT_CHAIN, () => dispatch(screen, action, payload)),
    modal: deps.modal,
    onError: noticeSave,
    onUse: (row: Obj) => usePoolData(String(row.key)),
    /* 프리필 재료는 **검토 왕복이 낸 상세 투영**이다(고르기 열 공용 ④) — 키 이름도
       그 투영 그대로(`path`·`sheet`·`note`)다. */
    openRelink: (row: Obj) => deps.poolRegistration.openRegDialog({
      title: "데이터 다시 연결", okLabel: "다시 연결", targetKey: row.key,
      name: row.name, path: row.path, sheet: row.sheet, note: row.note,
    }),
    poolSnapshot: () => poolModel.getSnapshot() as Obj | null,
    reveal: (path: string) => invokePathAction({
      client: deps.client, path, action: "reveal", notify: deps.notify,
    }),
    /* 시트의 주인은 데이터 선택 컨트롤러다 — 이 화면은 문만 연다(두 번째 구현 금지). */
    openDetail: (key: string, trigger: HTMLElement | null) =>
      deps.poolRegistration.openDetail(key, trigger),
  });
  const { poolAction, resolveDuplicate } = poolVerbs;

  /** 저장 폴더 변경은 기존 설정 모달을 연다. */
  function openSettings(): void {
    deps.modal.open(SETTINGS_MODAL_ID, {});
  }

  /** 「계약 목록(.db) 등록…」 — 등록 폼의 주인은 데이터 선택 컨트롤러다(포트 위임). */
  function openPclm(): void { deps.poolRegistration.openPclm(); }

  /** 「이 데이터 고정…」 — 파일로 연 데이터를 풀에 남긴다(`#poolRegModal` pin 모드). */
  function openPin(): void {
    const state = snapshot();
    if (!state.data_path) return;
    deps.poolRegistration.openRegDialog({
      title: "이 데이터 고정", okLabel: "고정", name: state.data_name,
      path: state.data_path, sheet: state.data_sheet || "", pinMode: true,
    });
  }

  async function resuggestAll(): Promise<void> {
    /* 수치는 **이 관문의 것**을 읽는다 — 관문마다 자기 수치를 읽는다. */
    const stakes = await sendEdit("mapping_reset_stakes", {});
    const manual = Number(stakes.resuggest_manual || 0);
    const kept = Number(stakes.confirmed || 0);
    if (manual && !(await deps.modal.confirm({
      body: `직접 편집한 매핑 ${manual}개가 자동 제안으로 돌아갑니다.` +
        `\n직접 입력한 상수·유형·표시형도 함께 지워집니다.` +
        (kept ? `\n확정한 ${kept}개는 그대로 둡니다.` : "") +
        `\n\n계속할까요?`,
      confirmLabel: "다시 받기", cancelLabel: "취소",
    }))) return;
    const result = await sendEdit("resuggest_all", {});
    /* 아무것도 안 바뀐 경우를 조용히 넘기지 않는다 — 무동작으로 보이면 그게 조용한 소실이다. */
    if (!result.resuggested) {
      noticeSave(`자동 제안을 다시 받을 행이 없습니다. 확정한 ${result.kept_confirmed}개는 그대로 둡니다.`);
    }
  }

  /** 「제안 n건 모두 확인」 — 자동 제안 행만 승격한다(U6-C #977).
   *
   *  확인 왕복이 없는 이유: 이 동사는 **잃을 것을 만들지 않는다**(미확정 → 확정 한 방향
   *  이고, 되돌리는 동사가 ⋯ 메뉴에 그대로 있다). 종전 「모두 확정」이 이름 재진술 모달을
   *  세운 것은 채울 것이 없는 행까지 한 번에 비움 확정으로 밀어 넣었기 때문이고, 그 승격은
   *  이제 행별 「비워 둠」 선언이 진다. 승격한 수치는 배지·pill 이 그 자리에서 말한다. */
  async function confirmSuggested(): Promise<void> {
    await sendEdit("confirm_suggested", {});
  }

  /* ---- 2단계 머리의 드문 동사(⋯) ---- */

  function bindingMenuItems(snap: Obj): ContextMenuItem[] {
    const items: ContextMenuItem[] = [
      { action: "resuggest-all", label: "자동 제안 다시 받기" },
      { action: "unconfirm-all", label: "모두 해제", danger: true },
    ];
    const undo = Number(snap.unconfirm_undo_count || 0);
    if (undo) {
      items.push({
        action: "restore-confirmed", label: `직전 확인 ${undo}개 복원`,
        separatorBefore: true,
      });
    }
    return items;
  }

  function closeBindingMenu(): void {
    patchView({ bindingMenu: false });
    bindingContextMenu.close();
  }

  function toggleBindingMenu(trigger: HTMLElement): void {
    if (view.bindingMenu) { closeBindingMenu(); return; }
    patchView({ bindingMenu: true });
    bindingContextMenu.open(trigger, bindingMenuItems(snapshot()));
  }

  async function handleBindingMenu(action: string): Promise<void> {
    closeBindingMenu();
    if (action === "resuggest-all") { await resuggestAll(); return; }
    if (action === "unconfirm-all") { await sendEdit("unconfirm_all", {}); return; }
    if (action === "restore-confirmed") { await sendEdit("restore_confirmed", {}); return; }
    throw new Error(`알 수 없는 연결 확인 메뉴 동작: ${action}`);
  }

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
    setTokFold(open: boolean): void { patchView({ tokFoldOpen: open }); },
    toggleLibMenu, closeLibMenu, handleLibMenu, handleSlotVerb,
    /** 항목 상세 시트(U6-E #979) — 여는 자리 둘(행 ⋮ · 게이트 존)이 같은 한 문을 지난다. */
    openDetail,
    closeDetail: (): void => { deps.modal.close("tplDetailModal"); },
    handleDetailVerb,
    isLibMenuOpen: (): boolean => view.libMenu !== null,
    libContextMenu,
    findLibItem,
    openTxtEdit, patchTxtEdit, confirmDiscardTxtEdit, submitTxtEdit,
    typeTxtEdit, saveTxtEditAsNew,
    /** 외부 FS 재스캔(tpl 채널) — push 가 재당김을 태워 목록·결과 줄이 되그려진다. */
    refreshLibrary: (): Promise<Obj> => dispatch("tpl", "refresh", {}),
    /** 우 열의 같은 문(pool 채널) — 두 열이 대칭이라 「새로 읽기」도 양쪽에 선다(③a). */
    refreshPool: (): Promise<Obj> => dispatch("pool", "refresh", {}),
    useLibraryTemplate, importTemplate, pickData,
    usePoolData, chooseTemplate, chooseData, dropPair, refuseSelection,
    poolAction, resolveDuplicate, poolNoticeAction: poolVerbs.noticeAction, findDataItem,
    openPin, openPclm, openSettings,
    tplModel, poolModel,
    confirmSuggested, chooseDataColumn, chooseDisplay, takePendingConstFocus,
    discardPatch, cancelNewDraft,
    toggleBindingMenu, closeBindingMenu, handleBindingMenu, bindingContextMenu,
    isBindingMenuOpen: (): boolean => view.bindingMenu,
    gotoSection, neighbour, doSave, saveAndOpen, returnScreen, flushPendingEdits, sendEdit,
    guarded,
    doc: deps.doc,
    client: deps.client,
    popover: deps.popover,
    notify: deps.notify,
  };
}

export type EditorController = ReturnType<typeof createEditorController>;
