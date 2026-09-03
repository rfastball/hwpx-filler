/* R4-02 문서 작업 편집기의 React 표면(legacy `frontend/js/screens/editor.js`).

   **몰입 표면**(`#scr-editor`)이라는 정체는 그대로다: 상단 2탭을 덮고 출구는 back 하나이며,
   patch 처분(저장·버리기·머무르기)이 그 한 출구에서 끝난다. 탭은 계약 §5.1 의 section
   문자열이고 **집합은 Python 이 매체에서 파생**해 내려준다 — 여기서 목록을 발명하지 않는다.

   달라진 것은 소유다. legacy 는 `innerHTML` 재구성 + 공용 보존 헬퍼로 포커스·캐럿을
   되찾고 `pendingFieldEdit` 1슬롯으로 커밋 전 타이핑을 들었다. React 소유에서는 노드가
   살아 있어 되찾을 것이 없고, 커밋 전 값의 주인은 `editor_state.ts` reducer 하나다.

   바뀌지 않는 것(이 슬라이스의 불변식):

   - 판정·문안·수치는 Python 이다. 표면은 그리기와 발신만 한다.
   - 브리지 왕복은 **한 줄에 선다**(`EDIT_CHAIN`). 커밋(이동·저장·이탈)은 그 줄을 먼저 정산한다.
   - 확인 전에는 draft 를 파기하지 않는다. */
import { createElement, Fragment, useEffect, useRef, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import { disposeLintpad, mountLintpad, updateLintpad } from "../editorview/txt_lintpad.ts";
import type { LintpadHandle, LintpadSpan } from "../editorview/txt_lintpad.ts";

import type { BridgeClient } from "../runtime/client.ts";
import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import type { ScreenPorts } from "./ports.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import {
  ContextMenu,
  createContextMenu,
} from "./context_menu.ts";
import type {
  ContextMenuItem,
  ContextMenuPopoverPort,
} from "./context_menu.ts";
import { DetailSheetFrame } from "./detail_sheet.ts";
import { NoticeBox } from "./notice_box.ts";
import { PathActions, invokePathAction } from "./path_actions.ts";
import { PreviewCell } from "./preview_cell.ts";
import {
  PCLM_UNAVAILABLE, POOL_GONE_FROM_LIST, ROW_DETAIL_LABEL, createPoolVerbs,
  dataRowMenuItems, mergeSessionRow, poolHeadSub, poolRefusalText,
} from "./pool_verbs.ts";
import { SETTINGS_MODAL_ID } from "./settings_sheet.ts";
import type { PoolRegistrationPort } from "./pool_verbs.ts";
import { PoolColumn, SESSION_DATA_KEY } from "./pool_column.ts";
import type { PoolColumnHost } from "./pool_column.ts";
import {
  NAME_FIELD, PATTERN_FIELD, editorRevision, editorServerValues, editorSession,
  emptyDraft, hasPendingEdits, ingestSnapshot, issueToken, markField,
  rowField, settle, typeInto, valueOf,
} from "./editor_state.ts";
import type { DraftState, RowAxis } from "./editor_state.ts";

type Obj = Record<string, any>;
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

const INFERRED_LABEL: Record<string, string> = {
  text: "텍스트", date: "날짜", amount: "금액", number: "숫자", phone: "전화번호",
};
/** 매핑 행 상태 → class. Python 이 내는 닫힌 집합 넷과 1:1(발명·누락 금지).
 *  **라벨은 여기 없다** — 배지 문안은 링1 `ROW_STATUS_LABEL` 이 스냅샷에 실어 보낸다
 *  (U6-C #977: 같은 상태를 두 층이 문안화하면 한쪽만 옛말을 계속 한다). */
export const ROW_STATE_CLASS: Record<string, string> = {
  suggested: "r-suggested", edited: "r-edited",
  confirmed: "r-confirmed", needs_source: "r-needs-source",
};
/** 행 상태 → 배지 색 class(제안=액센트 · 확인=완료 · 확인 필요=주의). */
const ROW_BADGE_CLASS: Record<string, string> = {
  suggested: "sugg", edited: "warn", confirmed: "ok", needs_source: "warn",
};
/** 확정 배지가 잠기는 이유 — 눌러도 되는 자리와 안 되는 자리를 말없이 가르지 않는다. */
const NOT_CONFIRMABLE_HINT = "열을 고르거나 고정값·오늘 날짜·비워 둠을 고르세요";

/* 단계 이름은 **각 단계가 묻는 질문**이다(U6 §2.2 · U6-B #976 · U6-D #978). section id 는
   계약이라 그대로이고 바뀐 것은 라벨뿐이다 — 「템플릿」은 이제 절반만 말하고(오른쪽에서
   데이터도 고른다), 「필드 연결·표시」는 그 단계가 하는 일(맞는지 보는 것)보다 넓었으며,
   「파일 이름」은 작업 이름이 그 단계로 오면서 절반만 말하게 됐다.
   **Python `SECTION_LABELS` 와 글자가 같아야 한다** — 되돌림 notice 가 그 표를 쓴다. */
const SECTION_TITLES: Record<string, string> = {
  template: "고르기", binding: "연결 확인", filename: "이름·저장",
};

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
type TxtLintState = {
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

type ViewState = {
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

const isEditing = (snapshot: Obj): boolean => !!snapshot.editing_origin;

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
    } else if (kind === "blank") {
      sendRowChoice("set_blank", { index });
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
    if (row === null) return refuse(`데이터를 찾을 수 없습니다. ${POOL_GONE_FROM_LIST}`);
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

  /** 「서식 폴더 설정」 — **기존 설정 모달을 그대로 연다**(새 표면 0).
   *
   *  이 화면은 몰입 표면이라 셸 토바의 `#settingsOpen` 이 덮여 있다: 문이 없는 것이지 다른
   *  문이 필요한 것이 아니라, 같은 모달을 여기서 한 번 더 연다. 서식 폴더 행의 판정·문안·
   *  브리지(`pick_templates_root`)는 전부 그 모달이 계속 소유한다(U6-A #975). */
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

/* ---- 표현 ---- */

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function stageTitle(snapshot: Obj, section: string): string {
  const title = SECTION_TITLES[section] || section;
  if (isEditing(snapshot)) return title;
  const index = (snapshot.sections || []).indexOf(section);
  return index < 0 ? title : `${index + 1}단계: ${title}`;
}

function gateHint(snapshot: Obj): string {
  /* 1단계의 사유는 **Python 이 낸다**(`pairing.advance_block_reason`) — 좌·우 어느 쪽이
     비었는지에 따라 고칠 자리가 갈리는데, 그 판정을 여기서 다시 하면 게이트와 문안이
     서로 다른 상태를 말하게 된다(U6-B #976). */
  if (snapshot.section === "template") {
    return String((snapshot.pairing || {}).advance_block_reason || "");
  }
  if (snapshot.section === "binding") return "전 행을 확정해야 진행할 수 있습니다";
  return "";
}

/** 머리 부제 — 「{템플릿} ⟷ {데이터}」 한 줄(동결 시안 장면 2·3 머리와 같다).
 *
 *  1단계에서는 연결 카드가 같은 말을 하지만 2·3단계에는 그 카드가 없다. 단계마다 다른
 *  문형을 세우면 같은 사실이 두 어휘를 갖는다 — 한 줄로 통일한다. **짝이 다 서기 전에는
 *  침묵한다**(2026-09-03 재판정): 「템플릿을 아직 고르지 않았습니다 ⟷ gg」 는 1단계 연결
 *  카드가 이미 하는 말의 되풀이였다. */
function pairLine(snapshot: Obj): string {
  const pairing = (snapshot.pairing || {}) as Obj;
  const template = String(pairing.template_name || "");
  const data = String(pairing.data_name || "");
  return template && data ? `${template} ⟷ ${data}` : "";
}

/** 머리 — 이 세션이 **무엇을 편집 중인가**와 그 저장 상태.
 *
 *  작업 이름 입력은 U6-D(#978)에서 3단계 「이름·저장」 폼으로 옮겼다. 라벨 없이 제목 자리에
 *  사는 입력이라 저장 게이트가 「작업 이름을 입력하세요」라고 말해도 사람이 찾지 못하던
 *  자리다(`SaveVerdict.blocked_field` 의 주석이 그 사실을 적고 있었다). 머리에 남은 것은
 *  제목(부제와 같은 짝 한 줄)과 상태 pill 이고, **소유는 여전히 세션**이다 — 이름은 어느
 *  section patch 에도 속하지 않아 탭 이동의 자동 버리기가 건드리지 않는다(판정 L). */
function EditorHead(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot } = props;
  const dirty = !!snapshot.dirty;
  const level = snapshot.is_draft ? "idle" : (dirty ? "warn" : "idle");
  /* 머리는 **상태만** 말한다(#945 F5). 저장 세대 카운터(`revisions`)는 규칙이 갈릴 때 오르는
     내부 어휘라 여기서 읽는 사람에게 아무 행동도 주지 않는다 — 스냅샷 키와 도메인 축은
     그대로 살고, 판본을 실제로 대조하는 자리(실행 결과 증거·작업 목록)가 계속 든다. */
  const stateText = snapshot.is_draft
    ? "아직 저장하지 않은 새 작업"
    : (dirty ? "저장하지 않은 변경" : "저장됨");
  return h("header", { className: "scr-head editor-head" },
    h("div", null,
      h("p", { className: "eyebrow" }, "문서 작업 편집기"),
      /* 제목은 **읽기 전용 정체**다. 초안은 아직 이름이 없을 수 있어(고르기 전) 그때는
         이름 없는 새 작업이라고 말한다 — 빈 제목은 화면이 무엇을 편집 중인지 말하지 않는다. */
      h("h1", { id: "editorTitle" }, String(snapshot.name || "새 작업")),
      pairLine(snapshot) ? h("p", { className: "sub", id: "editorSubtitle" }, pairLine(snapshot)) : null),
    h("div", { className: "status", id: "editorSaveState", "data-level": level }, stateText));
}

/** 진입 문맥 배너 — **증거가 있을 때만** 선다(2026-09-03 재판정). 사유 문장(「…에서
 *  열었습니다」)과 복귀 버튼은 걷혔다: 방금 거기서 온 사람에게 출처는 새 정보가 아니고, 복귀는
 *  왼쪽 위 「← 원래 업무로 돌아가기」 가 같은 곳으로 간다. 남는 것은 진입이 실어 온 **사실**
 *  (실패한 행 · 입력이 필요한 항목 · 고칠 것)뿐이고, 값이 빈 증거는 줄을 세우지 않는다. */
function ContextBanner(props: { snapshot: Obj }): ReactNode {
  const context = props.snapshot.context || {};
  const evidence = (context.evidence || {}) as Obj;
  const rows = Object.keys(evidence).filter((key) => String(evidence[key] ?? "") !== "")
    .map((key) => h("span", { key }, h("b", null, key), " ", String(evidence[key])));
  if (!rows.length) {
    return h("section", { className: "note ctxbanner", id: "editorContext", style: { display: "none" } });
  }
  return h("section", { className: "note ctxbanner", id: "editorContext" },
    h("div", { className: "ctx-ev" }, ...rows));
}

function StepHeader(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const sections = (snapshot.sections || []) as string[];
  const here = sections.indexOf(snapshot.section);
  const children = isEditing(snapshot)
    ? sections.map((section) => h("button", {
      className: `wstep-tab as-tab${(snapshot.dirty_sections || []).includes(section) ? " dirty" : ""}`,
      "data-act": "goto-tab", "data-section": section, key: section,
      "aria-current": section === snapshot.section ? "true" : undefined,
      onClick: () => controller.guarded(() => controller.gotoSection(section)),
    }, SECTION_TITLES[section] || section))
    : sections.map((section, index) => h("div", {
      className: `wstep-tab${index < here ? " done" : ""}`, key: section,
      "aria-current": section === snapshot.section ? "true" : undefined,
    }, h("span", { className: "k" }, String(index + 1)), SECTION_TITLES[section] || section));
  return h("div", { className: "wsteps", id: "editor-steps", "aria-label": "문서 작업 편집 영역" },
    ...children);
}

/** 행 ⋮ 가 열 동사 목록 — **한 술어**다. 메뉴를 여는 쪽·시트의 동사 줄·트리거가 같은 값을
 *  봐야 「버튼은 있는데 눌러도 아무 일도 없다」가 생기지 않는다(같은 상태 두 곳 판정 금지).
 *
 *  목록·라벨은 링1 소유다 — hwpx 는 스냅샷 `actions`(상태 게이트가 낸 동사)를 그대로 그리고,
 *  txt 는 읽을 수 있을 때만 「내용 편집」이 선다.
 *
 *  **「자세히…」는 모든 행에 선다**(U6-E #979). 그래서 동사 0 인 행이 없고, 종전의
 *  「동사 0 → ⋮ 비활성 + 사유」(U6-A 판정)는 「상시 활성」으로 대체됐다 — 그 판정이 막던
 *  결함(무반응 버튼)은 여전히 막힌다: 어느 행에서든 누르면 답할 것이 있다. 오류 행에서는
 *  그 하나만 서고, 시트가 답하는 것이 바로 그 오류 사유다.
 *
 *  이 함수는 목록 행(`item`)과 상세 투영(`detail`) 둘 다 받는다 — 두 자리가 읽는 두 값이
 *  같은 두 축(`actions`·`error`)을 들기 때문이고, 그래서 동사 목록을 두 번 짓지 않는다. */
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
  /* 「읽을 수 있는가」는 두 자리가 **같은 사실을 다른 이름으로** 든다: 상세 투영은 판독
     실패 원문(`error`), 좌 열 행은 그것을 링1 이 문장으로 옮긴 차단 사유(`reason` —
     `TemplateRow.select_block_reason`). 둘 다 없을 때만 읽을 수 있다. 여기서 어느 한쪽만
     보면 열의 오류 행에 「내용 편집」이 서서, 열리지 않을 파일을 편집하라고 권하게 된다. */
  const unreadable = !!item.error || !!item.reason;
  return unreadable ? [detail] : [{ action: "edit", label: "내용 편집" }, detail];
}

/** 좌 열 — 「템플릿」 풀. 정본은 `tpl` 채널 스냅샷의 **공용 열 존**(`column`)이고 선택
 *  표지만 편집기 스냅샷이 준다(`pairing.template_key`).
 *
 *  hwpx·txt 를 **한 목록으로** 그리고 매체는 pill 로 가른다(동결 시안 장면 1): 루트가
 *  하나가 된 뒤(U6-A) 두 밴드는 같은 폴더의 두 확장자일 뿐이라, 구획으로 가르면 「어디에
 *  무엇이 있나」를 사람이 두 번 훑게 된다. 그 목록을 **한 목록으로 접는 일도 이제 Python
 *  이 한다** — 이 자리는 호스트만 세운다(고르기 열 공용 ②).
 *
 *  갈리는 것은 바닥 동사 줄 하나다: 「파일 가져오기…」·「폴더에서 보기」·「서식 폴더 설정」·
 *  「새 TXT 템플릿…」은 서식 폴더에만 있는 동사라 우 열과 공유할 것이 없다. */
function TemplatePool(props: {
  tpl: Obj | null; snapshot: Obj; controller: EditorController;
}): ReactNode {
  const { tpl, snapshot, controller } = props;
  const root = (tpl || {}).templates_root || {};
  const pairing = (snapshot.pairing || {}) as Obj;
  const host: PoolColumnHost = {
    side: "tpl",
    rootId: "editorTplPool",
    listId: "editorTplList",
    title: "템플릿",
    headSub: "서식 폴더",
    headSubTitle: String(root.directory || ""),
    /* 선택 표지의 정본은 **편집기 스냅샷의 키**다(고르기 열 공용 ①) — 종전에는 경로
       문자열을 좌 열이 직접 대조했고, 그러면 같은 사실을 Python 과 표면이 각자 잰다. */
    selectedKey: String(pairing.template_key || ""),
    choose: (key: string) => controller.guarded(() => controller.chooseTemplate(key)),
    drop: (sourceSide: string, sourceKey: string, targetKey: string) =>
      controller.guarded(() => controller.dropPair(sourceSide, sourceKey, targetKey)),
    /* ⋮ 가 겨누는 매체는 행이 든 표지 그대로다(`icon` = `hwpx`/`txt`) — 표면이 밴드로
       매체를 유도하지 않는다. */
    onMore: (row: Obj, trigger: HTMLElement) =>
      controller.toggleLibMenu("tpl", String(row.icon || ""), String(row.key), trigger),
    reload: () => controller.guarded(() => controller.refreshLibrary()),
    acts: createElement(Fragment, null,
      h("button", {
        className: "btn sm", "data-act": "import-template", key: "import",
        onClick: () => controller.guarded(() => controller.importTemplate()),
      }, "파일 가져오기…"),
      /* 「폴더에서 보기」 — 삭제 동사의 승계처다(U6 §2.3: 앱은 사용자 서식 폴더에 쓰지
         않는다). 열기·경로 복사는 여기서 세우지 않는다: 이 줄이 답하는 것은 「그 폴더를
         어떻게 여나」 하나이고, 나머지는 설정 모달의 서식 폴더 행이 이미 든다. */
      h(PathActions as any, {
        client: controller.client, path: String(root.directory || ""),
        only: ["reveal"], notify: controller.notify, key: "reveal",
      }),
      h("button", {
        className: "btn sm", "data-act": "open-settings", key: "settings",
        onClick: () => controller.openSettings(),
      }, "서식 폴더 설정"),
      h("button", {
        className: "btn sm", "data-act": "lib-new-txt", key: "new-txt",
        onClick: (event: Obj) => controller.openTxtEdit("new", "", "", "", event.currentTarget),
      }, "새 TXT 템플릿…")),
    emptyFallback: "서식 폴더를 아직 읽지 못했습니다.",
  };
  return h(PoolColumn as any, { host, column: ((tpl || {}).column || null) as Obj | null });
}

/** 중앙 — 연결 카드. **수치도 그 출처(`basis`)도 Python 이 낸다**(U6-B #976).
 *
 *  `basis="model"` 이면 이미 세운 매핑 모델의 실제 수치라 라벨이 「확인」이고,
 *  `"preview"` 면 아직 모델이 없어 순수 함수로 미리 세어 본 값이라 「자동 연결」이다.
 *  두 어휘를 하나로 뭉치면 카드가 「이미 확인했다」와 「확인하면 이렇게 될 것이다」를
 *  같은 말로 하게 된다. */
function LinkCard(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const pairing = (snapshot.pairing || {}) as Obj;
  const ready = !!pairing.ready;
  const blockReason = String(pairing.advance_block_reason || "");
  const can = !!(snapshot.reachable || {}).template;
  const autoLabel = pairing.basis === "model" ? "확인" : "자동 연결";
  return h("div", { className: "linkzone" },
    h("div", { className: `wire${ready ? " live" : ""}`, id: "editorWire" },
      h("b", null), h("i", null), h("b", null)),
    h("div", {
      className: "linkcard", id: "editorLinkCard", role: "status", "aria-live": "polite",
    },
    ready
      ? createElement(Fragment, null,
        h("span", { className: "pairname" },
          `${pairing.template_name} ⟷ ${pairing.data_name}`),
        h("span", { className: "size" },
          `필드 ${pairing.field_count}개 · 열 ${pairing.column_count}개`),
        h("span", null, `${autoLabel} `),
        h("span", { className: "n" }, String(pairing.auto_count)),
        h("span", null, " · "),
        Number(pairing.confirm_count)
          ? h("span", { className: "warnline" }, "확인 필요 ",
            h("span", { className: "n" }, String(pairing.confirm_count)))
          : createElement(Fragment, null, "확인 필요 ",
            h("span", { className: "n" }, "0")))
      : h("span", { className: "empty" }, "왼쪽과 오른쪽에서 하나씩 고르세요.")),
    h("button", {
      className: "btn primary cta", id: "editorLinkCta", "data-act": "goto-binding",
      disabled: !can, title: can ? "" : blockReason,
      onClick: () => controller.guarded(() => controller.gotoSection("binding")),
    }, "연결 확인으로"),
    !can && blockReason
      ? h("p", { className: "note quiet", id: "editorLinkBlock", style: { textAlign: "center" } },
        blockReason)
      : null,
    h("p", { className: "note quiet", style: { textAlign: "center", marginTop: 0 } },
      "끌어다 놓아도 같은 결과입니다."));
}

/** 우 열 — 「데이터」 풀. 좌 열과 **같은 컴포넌트의 다른 인스턴스**다(고르기 열 공용 ③a).
 *
 *  종전에는 이 자리가 「데이터 선택」 다이얼로그의 세 구획(`PoolSections`)을 그렸다. 같은
 *  컴포넌트를 나눠 쓰는 것 자체는 옳았지만 **나눌 상대가 틀렸다**: 우 열의 이웃은 다이얼로그가
 *  아니라 **좌 열**이고, 그래서 「고를 수 있는가」의 시각적 얼굴·⋯ 메뉴·새로 읽기가 한쪽에만
 *  있었다. 이제 두 열이 같은 것을 그린다 — 갈리는 것은 바닥 동사 줄 하나다.
 *
 *  「현재 데이터」 카드는 **행 하나로 접혔다**: 파일로 연 데이터는 Python 이 같은 행 계약으로
 *  내려주고(`pairing.data_row` · 키 `session`) 그것이 목록 맨 위에 선다. 풀에 등록된 결속은
 *  그 행이 없다(`data_row === null`) — 풀 행이 이미 그것을 들고 있어 두 번 세우지 않는다. */
function DataPool(props: {
  pool: Obj | null; snapshot: Obj; controller: EditorController;
}): ReactNode {
  const { pool, snapshot, controller } = props;
  const column = ((pool || {}).column || null) as Obj | null;
  const pairing = (snapshot.pairing || {}) as Obj;
  const sessionRow = (pairing.data_row || null) as Obj | null;
  /* 이어붙이기는 **공용 순수 함수 하나**다(공용 ⑤ 리뷰) — 데이터 선택 다이얼로그와 같은
     목록이라 같은 순서·같은 최소 열을 써야 한다. */
  const merged = mergeSessionRow(column, sessionRow);
  const host: PoolColumnHost = {
    side: "dat",
    rootId: "editorDataPool",
    listId: "editorDataList",
    title: "데이터",
    headSub: poolHeadSub(column),
    /* 고름 표지의 정본은 편집기 스냅샷이다: 풀 결속이면 그 슬롯 키, 파일 결속이면 세션
       행이다. 두 축이 배타라 한 줄로 접힌다(둘 다 서는 상태는 Python 이 만들지 않는다). */
    selectedKey: String(pairing.data_key || (sessionRow ? SESSION_DATA_KEY : "")),
    choose: (key: string) => controller.guarded(() => controller.chooseData(key)),
    drop: (sourceSide: string, sourceKey: string, targetKey: string) =>
      controller.guarded(() => controller.dropPair(sourceSide, sourceKey, targetKey)),
    onMore: (row: Obj, trigger: HTMLElement) =>
      controller.toggleLibMenu("dat", String(row.icon || ""), String(row.key), trigger),
    reload: () => controller.guarded(() => controller.refreshPool()),
    onNoticeAction: (key: string, payload: Obj) => controller.poolNoticeAction(key, payload),
    acts: createElement(Fragment, null,
      h("button", {
        className: "btn sm", id: "editorPoolBrowse", "data-busy-lock": true, key: "browse",
        onClick: () => controller.guarded(() => controller.pickData()),
      }, "파일 찾아보기…"),
      /* 계약 목록은 파일 피커가 아니라 **DB 자리 + 시트**로 겨눈다(#937). 스냅샷이 그
         둘을 아직 안 실었으면 숨기지 않고 비활성 + 사유 병기 — 죽은 버튼을 조용히 두면
         「눌러도 아무 일 없음」이 결함으로 읽힌다. */
      h("button", {
        className: "btn sm", id: "editorPoolPclm", "data-busy-lock": true, key: "pclm",
        disabled: !(pool || {}).pclm, title: (pool || {}).pclm ? "" : PCLM_UNAVAILABLE,
        onClick: () => controller.openPclm(),
      }, "계약 목록(.db) 등록…"),
      /* 「이 데이터 고정…」은 **고정할 것이 있을 때만** 선다 — 풀에서 고른 데이터는 이미
         고정돼 있고, 아무것도 안 골랐으면 겨눌 것이 없다. 그 사실을 드는 값이 곧 세션 행이다. */
      sessionRow ? h("button", {
        className: "btn sm", id: "editorPoolPin", "data-busy-lock": true, key: "pin",
        onClick: () => controller.openPin(),
      }, "이 데이터 고정…") : null),
    emptyFallback: "고정한 데이터를 아직 읽지 못했습니다.",
  };
  return h(PoolColumn as any, { host, column: merged });
}

/** 항목 상세 시트의 **구간 항목 표** — 행 동사 3종 + 밴드 동사 1종(S8-03 · U4-E3 #939).
 *
 *  좌표(`data-act="slot-*"` · `data-slot=<id>`)와 왕복은 U6-E(#979)에서 **그대로** 시트 안으로
 *  옮겼다 — 바뀐 것은 이 표가 서는 자리 하나다. 그 이동이 메운 구멍은 도달성이다: U6-B 뒤
 *  COMPILED 행의 동사가 0 이 되면서, 완전 변환된 템플릿에서만 존재하는 이 동사들에 닿을 길이
 *  없었다.
 *
 *  진단이 있으면 목록 대신 사유가 서고 동사는 하나도 서지 않는다(못 믿는 구조 위에서 변이를
 *  권하지 않는다 — 진단 우선 규율). */
function SlotTable(props: {
  slots: Obj; diagnostics: string[]; controller: EditorController;
}): ReactNode {
  const { slots, diagnostics, controller } = props;
  const rows = (slots.rows || []) as Obj[];
  const verb = (row: Obj, act: string, label: string, danger?: boolean): ReactNode =>
    h("button", {
      className: `btn sm${danger ? " danger" : ""}`, key: act,
      "data-act": `slot-${act}`, "data-slot": String(row.id),
      onClick: (event: Obj) => controller.guarded(
        () => controller.handleSlotVerb(act, String(row.id), event.currentTarget)),
    }, label);
  const bandVerb = diagnostics.length || !rows.length ? null : h("button", {
    className: "btn sm danger", "data-act": "slot-decompile-all",
    style: { marginLeft: "auto" },
    onClick: (event: Obj) => controller.guarded(
      () => controller.handleSlotVerb("decompile-all", "", event.currentTarget)),
  }, "전부 표기로 되돌리기");
  return h("div", { className: "grp", id: "tplDetailSlots" },
    h("div", { className: "row", style: { marginBottom: "var(--sp-4)" } },
      h("span", { className: "cap" }, "구간 항목"),
      h("span", { className: "muted capnote" }, String(slots.summary || "")),
      bandVerb),
    ...(diagnostics.length ? [] : rows.map((row) => h("div", {
      className: "slotrow", key: String(row.id), "data-slot": String(row.id),
    },
    h("span", { className: "fname" }, String(row.label || row.id)),
    h("span", { className: "tbadge", title: (row.options || []).join(" · ") },
      `선택 ${row.option_count}`),
    verb(row, "rename", "이름 바꾸기"),
    verb(row, "decompile", "표기로 되돌리기"),
    verb(row, "remove", "삭제", true)))));
}

/** 항목 상세 시트의 **필드 표** — 나열식 금지(#16 판정)의 좌표 `.schema-fields` 를 잇는다.
 *
 *  값의 주인은 `tpl` 채널이다(`detail.fields` — 이름과 링0 추정 유형). 편집기가 자기 세션
 *  스키마로 그리던 종전 표와 겨누는 대상이 다르다: 이 표가 말하는 것은 **풀 항목(파일)** 이고,
 *  그래서 세션이 아직 그 템플릿을 고르지 않았어도 답할 수 있다. */
function DetailFields(props: { detail: Obj }): ReactNode {
  const fields = (props.detail.fields || []) as Obj[];
  return createElement(Fragment, null,
    h("p", { className: "fields-head", id: "tplDetailFieldSummary" },
      String(props.detail.field_summary || "")),
    fields.length
      ? h("div", { className: "tblwrap" },
        h("table", { className: "schema-fields" },
          h("thead", null, h("tr", null,
            h("th", null, "필드"), h("th", null, "추정 타입"))),
          h("tbody", null, ...fields.map((field: Obj, index: number) =>
            h("tr", { key: index },
              h("td", null, h("span", { className: "fname" }, String(field.name))),
              h("td", null, h("span", { className: "tbadge" },
                INFERRED_LABEL[String(field.type_hint)] || String(field.type_hint || ""))))))))
      : null);
}

/** 「자세히…」가 여는 **항목 상세 시트**(U6-E #979 · `#tplDetailModal`).
 *
 *  편집기 고르기 존 아래에 흩어져 있던 관리 표면(선택 chip + 경로 동사 · 작성 출처 · 스키마
 *  표 · 구간 항목 밴드 · 구간 요약)이 여기 하나로 모였다. 모을 때의 규율 둘:
 *
 *  - **재료는 `tpl` 채널 존 하나**다(`detail`). 시트가 두 스냅샷을 합성하면 그 사이에 갈린
 *    사실이 한 장에 함께 선다(상태 배지는 옛것, 항목 목록은 새것).
 *  - **겨누는 것은 세션이 아니라 파일**이다. 그래서 편집 중인 템플릿이든 아니든 같은 시트가
 *    서고, 마침 같은 파일이면 변이 통지 seam(`mutation_sinks` → `reconcile_template_mutation`)
 *    이 편집 세션을 스스로 다시 세운다 — 시트는 닫지 않는다(편집기 notice 가 말한다).
 *
 *  골격(머리·경로 문·오류 상자·성과 두 줄·동사 줄)은 이 파일이 그리지 않는다: 등록 데이터
 *  쪽 시트(`pool_detail.ts`)와 **같은 형**이라 `DetailSheetFrame` 하나가 진다(고르기 열
 *  공용 ④). 여기 남는 것은 이 매체만 아는 몸통(필드 표·구간 항목)과 좌표 접두어다. */
export function TplDetailSheet(props: { controller: EditorController }): ReactNode {
  const { controller } = props;
  /* 세 번째 인자(getServerSnapshot)는 `EditorScreen` 과 같은 이유로 선다 — 없으면 이 창이
     `react-dom/server` 로 한 번도 렌더되지 못해 노드 배치를 단위층에서 잴 수 없다. */
  const tpl = useSyncExternalStore(
    controller.tplModel.subscribe, controller.tplModel.getSnapshot,
    controller.tplModel.getSnapshot);
  /* 동사의 성과와 실패가 **이 면 안**에 선다(U6-E 리뷰 3): 시트는 스크림으로 화면을
     덮으므로 좌 열 바닥 결과 줄도 `#save-msg` 도 그 뒤에 그려진다. 값의 정본은 고르기 열
     존(`tpl.column.result`, Python)이고, 여기서 다시 짓는 문안은 없다. */
  const view = useSyncExternalStore(
    controller.viewModel.subscribe, controller.viewModel.getSnapshot,
    controller.viewModel.getSnapshot);
  const result = ((((tpl || {}) as Obj).column || {}) as Obj).result || {};
  const detail = (((tpl || {}) as Obj).detail || null) as Obj | null;
  const shared = {
    idPrefix: "tplDetail",
    client: controller.client,
    notify: controller.notify,
    message: view.detailMessage ? String(view.detailMessage) : "",
    result,
    onClose: (): void => { controller.closeDetail(); },
  };
  if (detail === null) {
    return h(DetailSheetFrame as any, Object.assign({}, shared, {
      title: "항목 상세",
      empty: "볼 항목이 없습니다. 목록에서 항목의 ⋮ → 「자세히…」를 누르세요.",
    }));
  }
  const media = String(detail.media || "hwpx");
  const diagnostics = (detail.diagnostics || []) as string[];
  const slots = (detail.slots || null) as Obj | null;
  /* 동사 줄은 행 ⋮ 와 **같은 함수**가 짓는다(같은 상태 두 곳 판정 금지) — 지금 서 있는
     「자세히…」 자신만 걷는다. */
  const verbs = libRowMenuItems(media, detail)
    .filter((entry) => entry.action !== "detail");
  return h(DetailSheetFrame as any, Object.assign({}, shared, {
    title: String(detail.name || ""),
    /* 배지의 저자는 **링1 하나**다(공용 ⑤ 리뷰) — TXT 는 말할 상태 축이 없어 그 자리에
       매체 표지가 서지만, 그 판정도 문안도 `compile_badge` 가 낸다. 종전에는 여기서
       `media === "txt"` 를 다시 판정해 문자열을 지었다(같은 상태 두 곳 판정). */
    pill: {
      label: String(detail.badge_label || ""),
      level: String(detail.badge_level || "muted"),
    },
    path: String(detail.path || ""),
    /* 판독 실패·구간 진단은 숨기지 않는다 — 오류 행에서 「자세히…」가 서는 이유가 이것이다. */
    error: String(detail.error || ""),
    diagnostics,
    body: createElement(Fragment, null,
      h(DetailFields as any, { detail }),
      slots ? h(SlotTable as any, { slots, diagnostics, controller }) : null),
    verbs,
    onVerb: (action: string, trigger: HTMLElement): void => {
      controller.guarded(() => controller.handleDetailVerb(action, trigger));
    },
  }));
}

/** 1단계 게이트 존 — **세션 판정**이라 고르기 단계에 남되 한 줄이다(U6-E #979).
 *
 *  이 존이 답하는 것은 「지금 고른 템플릿으로 진행할 수 있는가」 하나다. 「그 템플릿에 무엇이
 *  들어 있는가」(스키마 표·구간 요약·작성 출처)는 그 답 뒤에 묻는 별개의 질문이고, 그 자리는
 *  「자세히…」가 여는 시트다 — 그래서 여기 남는 수치는 `field_count` 하나다.
 *
 *  RAW 차단·판독 실패 사유는 Python 문안 그대로이고, 「비우고 진행 확인」의 조건도 종전과
 *  같다(`gate` 가 서고 아직 확인 전). */
function TemplateGate(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  if (!snapshot.template_path) return null;
  const detail = (snapshot.session_detail || {}) as Obj;
  const available = !!detail.available;
  const reason = String(detail.reason || "");
  const gate = snapshot.gate;
  const drift = String(snapshot.schema_drift || "");
  /* 머리는 **상태와 무관하게** 선다(U6-E 리뷰 8): 「파일을 고치세요」라고 말하는 바로 그
     상태(RAW·판독 실패)에서 이름과 「폴더에서 보기」가 사라지면, 고치러 갈 길이 그 문장
     옆에 없다. 아래 몸통만 상태로 갈린다. */
  const head = h("div", { className: "row" },
    h("span", { className: "cap" }, "선택한 템플릿"),
    h("span", { className: "muted capnote" }, String(snapshot.template_name || "")),
    snapshot.field_count
      ? h("span", { className: "muted capnote" }, `필드 ${snapshot.field_count}개`)
      : null,
    h("span", { className: "spacer" }),
    h(PathActions as any, {
      client: controller.client, path: String(snapshot.template_path || ""),
      only: ["reveal"], notify: controller.notify,
    }),
    /* 시트는 `tpl` 이 아는 항목만 연다 — 가부·사유는 Python 판정이고 여기는 잠금과 병기만
       한다(리뷰 5). 조용히 열리지 않는 문을 두지 않는다. */
    h("button", {
      className: "btn sm", "data-act": "session-detail",
      disabled: !available, title: available ? undefined : reason,
      onClick: (event: Obj) => controller.guarded(
        () => controller.openDetail(String(snapshot.template_path || ""), event.currentTarget)),
    }, ROW_DETAIL_LABEL));
  let body: ReactNode = null;
  if (snapshot.raw_block) {
    body = h("p", { className: "note dangerbox", style: { whiteSpace: "pre-line" } },
      String(snapshot.raw_block));
  } else if (snapshot.gate_error) {
    body = h("p", { className: "note dangerbox" },
      "템플릿 상태를 확인할 수 없습니다. 진행할 수 없습니다.");
  }
  return h("div", { className: "grp", id: "editorTplGate" },
    head,
    !available && reason
      ? h("p", { className: "muted capnote", id: "editorTplDetailBlock" }, reason)
      : null,
    body,
    /* 작성 출처 드리프트(#53-C 승계 · 리뷰 6) — **세션 판정**이라 이 자리다. 판정도 문안도
       Python 이 낸다(웹이 필드 목록을 다시 대조하지 않는다). */
    drift
      ? h("p", { className: "note warnbox", id: "editorSchemaDrift" }, drift)
      : null,
    gate
      ? h("div", { className: "note warnbox", style: { whiteSpace: "pre-line" } }, gate.message)
      : null,
    gate && !gate.acked
      ? h("button", {
        className: "btn", "data-act": "ack-gate",
        onClick: () => controller.guarded(() => controller.sendEdit("ack_gate", {})),
      }, `비우고 진행 확인 (${gate.unmet.length}개 토큰)`)
      : null);
}

/** 1단계 「고르기」 — 좌 템플릿 풀 · 중앙 연결 카드 · 우 데이터 풀(U6 §2.2 · #976).
 *
 *  **이 단계가 묻는 질문은 하나**다: 「어느 템플릿을 어느 데이터에?」. U6-E(#979)가 그 아래에
 *  남아 있던 것들을 걷었다 — 선택 chip + 경로 동사 · 작성 출처 · 스키마 표 · 구간 항목 밴드 ·
 *  구간 요약은 전부 항목 상세 시트로 갔고, 결과 줄은 관리 동사가 나가는 좌 열 바닥으로 갔다.
 *  존 아래에 남은 것은 세션 판정 한 줄(`TemplateGate`)뿐이다.
 *
 *  구 `DataGateway`(2단계 머리의 데이터 관문)와 축약 목록 `PoolPickList` 는 U6-B 에서 사슬째
 *  퇴역했다: 데이터를 고르는 자리가 우 열 하나가 됐고, 그 열은 「데이터 선택」 다이얼로그와
 *  같은 컴포넌트라 같은 상태를 두 표면이 다르게 그릴 길이 없다. */
function PairingStage(props: {
  snapshot: Obj; tpl: Obj | null; pool: Obj | null; controller: EditorController;
}): ReactNode {
  const { snapshot, tpl, pool, controller } = props;
  return h("div", null,
    h("div", { className: "wtitle" }, stageTitle(snapshot, "template")),
    h("p", { className: "wsub" }, "템플릿과 데이터를 하나씩 고르세요."),
    h("div", { className: "pairzone", id: "editorPairZone" },
      h(TemplatePool as any, { tpl, snapshot, controller }),
      h(LinkCard as any, { snapshot, controller }),
      h(DataPool as any, { pool, snapshot, controller })),
    h(TemplateGate as any, { snapshot, controller }));
}


/** 데이터 열 칸 — select(실 열 + 특수 항목) · 고정값 인라인 입력 · 상태 배지 버튼.
 *
 *  이 칸 하나가 종전 세 열(데이터 열 · 타입/고정값 · 확정 체크)을 흡수한다(U6 §2.2 · 동결
 *  시안 장면 2). 흡수의 조건은 **판정이 늘지 않는 것**이었다: 항목의 `kind` 도, 배지의
 *  문안·가부도, 「데이터에 없음」 표기도 전부 Python 이 낸 값이고 여기서는 그리기만 한다. */
function DataColumnCell(props: {
  row: Obj; snapshot: Obj; draft: DraftState; controller: EditorController;
}): ReactNode {
  const { row, snapshot, draft, controller } = props;
  const index = Number(row.index);
  const options = (snapshot.data_column_options || []) as Obj[];
  /* select 값의 정본은 **스냅샷**이다(리뷰 2) — 초안을 두지 않으므로 여기서 읽을 draft
     가 없고, 실패한 선택은 다음 렌더가 이 값으로 되돌린다. */
  const value = String(row.source_value || "");
  const missingLabel = String(row.source_missing_label || "");
  const nodes: ReactNode[] = options.map((option) => h("option", {
    value: String(option.value), key: String(option.value),
    title: String(option.label), "data-kind": String(option.kind),
  }, String(option.label)));
  /* 현재 데이터에 없는 결속은 목록에 없다 — 「(비움)」으로 오표시하지 않고 명시 항목으로
     드러낸다(문안은 Python). 이 항목을 다시 고르는 것은 무동작이다. */
  if (missingLabel) {
    nodes.push(h("option", {
      value: String(row.source_value), key: "missing", title: missingLabel,
      "data-kind": "column",
    }, missingLabel));
  }
  const confirmable = !!row.confirmable;
  const constRef = useRef<HTMLInputElement | null>(null);
  /* 「고정값…」을 고른 뒤 값을 적을 자리로 커서를 옮긴다(리뷰 8). 그 입력은 **서버가 이
     행을 const 로 인정한 뒤에야** 렌더되므로 고른 순간에는 DOM 에 없다 — 초점은 그 입력이
     실제로 선 이 렌더에서 선다. 표지는 가져가는 쪽이 걷어 재렌더마다 커서를 빼앗지 않는다. */
  useEffect(() => {
    if (constRef.current === null) return;
    if (controller.takePendingConstFocus(index)) constRef.current.focus();
  });
  return h("div", { className: "srccell" },
    h("select", {
      className: `sel${row.row_state === "needs_source" ? " empty" : ""}`,
      "data-act": "row-source", "data-index": index, value,
      onChange: (event: Obj) => controller.guarded(
        () => controller.chooseDataColumn(index, String(event.currentTarget.value))),
    }, ...nodes),
    row.source_kind === "const" ? h("input", {
      className: "sel", "data-act": "row-const", "data-index": index, placeholder: "고정값",
      ref: constRef,
      value: valueOf(draft, rowField(index, "const")),
      onChange: (event: Obj) => controller.type(rowField(index, "const"), String(event.currentTarget.value)),
      onFocus: () => controller.focus(rowField(index, "const"), true),
      onBlur: () => {
        controller.focus(rowField(index, "const"), false);
        controller.commitRowOnBlur(index, "const");
      },
      onCompositionStart: () => controller.compose(rowField(index, "const"), true),
      onCompositionEnd: () => controller.compose(rowField(index, "const"), false),
    }) : null,
    h("button", {
      className: `badge ${ROW_BADGE_CLASS[String(row.row_state)]}`,
      type: "button", "data-act": "row-confirm", "data-index": index,
      disabled: !confirmable,
      title: confirmable ? "" : NOT_CONFIRMABLE_HINT,
      "aria-pressed": !!row.confirmed,
      onClick: () => controller.guarded(() => controller.sendEdit(
        "set_confirmed", { index, confirmed: !row.confirmed })),
    }, String(row.state_label)),
    /* ↻ 의 노출 술어는 **Python 이 낸다**(`revertable` — 리뷰 9). `_do_revert_source` 가
       확정 행을 거절하는 것과 같은 술어라야 「눌렀는데 거절당하는」 버튼이 남지 않는다. */
    row.revertable ? h("button", {
      className: "btn icon", "data-act": "revert-source", "data-index": index,
      title: "자동 제안으로 되돌리기", "aria-label": "이 행 자동 제안 다시 받기",
      onClick: () => controller.guarded(() => controller.sendEdit("revert_source", { index })),
    }, "↻") : null);
}

function MapRow(props: {
  row: Obj; snapshot: Obj; draft: DraftState; controller: EditorController;
}): ReactNode {
  const { row, snapshot, draft, controller } = props;
  const index = Number(row.index);
  const displayGroups = (row.display_options || []) as Obj[];
  /* 행 상태 class 는 **닫힌 집합**이다(Python `screen_editor.py` 가 넷 중 하나를 낸다).
     보간으로 지으면 이름이 코드에 안 남아 CSS 고아 검사가 이 자리를 통째로 건너뛴다 —
     넷을 리터럴로 적어 그 검사에 들게 하고, 계약 밖 값은 조용히 무-class 로 접지 않는다. */
  const rowClass = ROW_STATE_CLASS[String(row.row_state)];
  if (rowClass === undefined) throw new Error(`알 수 없는 행 상태: ${row.row_state}`);
  return h("tr", { className: rowClass, "data-field": row.template_field, key: index },
    h("td", null,
      h("span", { className: "fname", title: row.context || row.template_field }, row.template_field),
      h("span", { className: "tbadge" },
        `[추정: ${INFERRED_LABEL[row.inferred_type] || row.inferred_type || ""}]`)),
    h("td", null, h(DataColumnCell as any, { row, snapshot, draft, controller })),
    /* 표시형 select 가 **유형 축까지 든다**(리뷰 1). `infer_type` 은 이름 키워드
       휴리스틱이라 「계약일」이 text 로 추정되면 날짜 서식을 영영 못 고르는 자리가 생겼다 —
       옵션을 유형별 그룹으로 묶어 한 번의 선택이 (유형, 표시형) 한 쌍을 원자적으로 세운다.
       그룹·라벨·값은 전부 Python 이 낸다. */
    h("td", null, h("select", {
      className: "sel", "data-act": "row-fmt", "data-index": index,
      value: String(row.display_value || ""), disabled: !displayGroups.length,
      onChange: (event: Obj) => controller.guarded(
        () => controller.chooseDisplay(index, String(event.currentTarget.value))),
    }, ...(displayGroups.length
      ? displayGroups.map((group) => h("optgroup", {
        label: String(group.label), key: String(group.label),
      }, ...((group.options || []) as Obj[]).map((option) =>
        h("option", { value: String(option.value), key: String(option.value) },
          String(option.label)))))
      : [h("option", { value: "", key: "" }, "—")]))),
    h("td", null, h(PreviewCell as any, { row })));
}

/** 표 머리 — pill 3개 · 일괄 승격 · 드문 동사 ⋯. 수치도 문안도 Python 이 낸다. */
function BindingHead(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const head = (snapshot.binding_head || {}) as Obj;
  const suggested = Number(head.suggested || 0);
  return h("div", { className: "bindbar" },
    h("span", { className: "pill acc", "data-pill": "suggested" }, `자동 제안 ${suggested}`),
    h("span", { className: "pill warn", "data-pill": "needs-confirm" },
      `확인 필요 ${Number(head.needs_confirm || 0)}`),
    h("span", { className: "pill muted", "data-pill": "const" },
      `고정값 ${Number(head.const || 0)}`),
    h("span", { className: "spacer" }),
    h("button", {
      className: "btn sm", "data-act": "confirm-suggested", type: "button",
      disabled: !suggested,
      onClick: () => controller.guarded(() => controller.confirmSuggested()),
    }, String(suggested ? head.promote_label : head.promoted_label)),
    h("button", {
      className: "btn sm icon binding-more", "data-act": "binding-more", type: "button",
      "aria-label": "연결 확인 그 밖의 동작", "aria-haspopup": "menu",
      "aria-expanded": controller.isBindingMenuOpen(),
      onClick: (event: Obj) => controller.guarded(
        () => controller.toggleBindingMenu(event.currentTarget as HTMLElement)),
    }, "⋯"));
}

function MappingStage(props: {
  snapshot: Obj; draft: DraftState; view: ViewState; controller: EditorController;
}): ReactNode {
  const { snapshot, draft, controller } = props;
  const rows = (snapshot.rows || []) as Obj[];
  const head = (snapshot.binding_head || {}) as Obj;
  return h("div", null,
    h("div", { className: "wtitle" }, stageTitle(snapshot, "binding")),
    /* 부제는 걷혔다 — 제목·표 머리·배지가 이미 「필드마다 데이터 열을 정한다」를 보여준다
       (`docs/COPY_STYLE_GUIDE.md` §1·§2: 상시 부제 기본 0). */
    /* 처방은 **저장 게이트와 같은 말**이어야 한다(#945 F8). U4-C 이후 데이터 연결은 저장의
       하드 게이트라(`gui/job_editor_state.validate_save`), 종전의 "고정값을 넣거나 비움으로
       확정하세요"는 그대로 따라도 저장이 막히는 거짓 처방이었다. 같은 상태를 두 어휘로
       판정하지 않는다 — 여기서 말하는 것은 그 게이트의 사실과 고칠 자리(1단계)다. */
    snapshot.schema_only ? h("p", { className: "note warnbox" },
      "데이터를 연결하지 않아 지금은 저장할 수 없습니다. '고르기' 단계에서 데이터를 고르세요.") : null,
    h(BindingHead as any, { snapshot, controller }),
    h("div", { className: "tblwrap" }, h("table", { className: "map" },
      h("thead", null, h("tr", null,
        h("th", null, "템플릿 필드"),
        h("th", null, "데이터 열"),
        h("th", null, "표시형"),
        h("th", null, "미리보기",
          h("span", { className: "stepper" }, ...(snapshot.preview_count
            ? [
              h("button", {
                className: "btn sm", "data-act": "prev-rec", type: "button",
                "aria-label": "이전 행", key: "prev",
                onClick: () => controller.guarded(() => controller.sendEdit("step_preview", { delta: -1 })),
              }, "◀"),
              h("span", { className: "mono", key: "at" },
                `행 ${snapshot.preview_index} / ${snapshot.preview_count}`),
              h("button", {
                className: "btn sm", "data-act": "next-rec", type: "button",
                "aria-label": "다음 행", key: "next",
                onClick: () => controller.guarded(() => controller.sendEdit("step_preview", { delta: 1 })),
              }, "▶"),
            ]
            : [h("span", { className: "muted", key: "none" }, "행 0 / 0 · 데이터 없음")]))))),
      h("tbody", null, ...rows.map((row) =>
        h(MapRow as any, { key: row.index, row, snapshot, draft, controller }))),
      /* 바닥은 **수치 하나**다(§8 낭독 패턴 3): 「미리보기는 실제 행입니다」는 시스템 원칙
         낭독이라 걷혔고, 안 쓰는 열이 0 이면 말할 것이 없어 줄 자체가 서지 않는다. */
      Number(head.unused_columns || 0) > 0
        ? h("tfoot", null, h("tr", null, h("td", { colSpan: 4 },
          `사용하지 않는 데이터 열 ${Number(head.unused_columns)}개`)))
        : null)),
    h(DataPreview as any, { snapshot }));
}

function DataPreview(props: { snapshot: Obj }): ReactNode {
  const { snapshot } = props;
  if (!snapshot.record_count) return null;
  const columns = (snapshot.source_fields || []) as string[];
  const sample = (snapshot.sample_rows || []) as any[][];
  return h("div", null,
    h("p", { className: "fields-head" },
      `${snapshot.record_count}행 불러옴 · 전체 ${columns.length}열.`),
    h("div", { className: "tblwrap" }, h("table", { className: "data-preview" },
      h("thead", null, h("tr", null, ...columns.map((name) =>
        h("th", { title: name, key: name }, name)))),
      h("tbody", null, ...sample.map((row, rowIndex) =>
        h("tr", { key: rowIndex }, ...columns.map((name, columnIndex) => {
          const value = row[columnIndex];
          return h("td", { key: name }, (value === "" || value === null || value === undefined)
            ? h("span", { className: "pv emptyval" }, "(빈 값)")
            : h("span", { className: "pv" }, value));
        })))))),
    snapshot.record_count > sample.length ? h("p", { className: "fields-head muted" },
      `샘플 ${sample.length}행 표시(외 ${snapshot.record_count - sample.length}행)`) : null);
}

function fnPreviewText(row: Obj, snapshot: Obj): ReactNode {
  if (row.preview_error) return h("span", { className: "pv emptyval" }, "(미리보기 오류)");
  if (row.preview_empty) {
    return h("span", { className: "pv emptyval" },
      snapshot.record_count ? "(빈 값)" : "(샘플 데이터 없음)");
  }
  let display = String(row.preview).replace(/[\r\n]+/g, " ");
  if (display.length > 40) display = `${display.slice(0, 39)}…`;
  return h("span", { className: "pv" }, display);
}

/** 3단계 「이름·저장」 — 「뭐라고 부르고 뭐라고 저장하나?」(U6 §2.2 · 동결 시안 장면 3).
 *
 *  행 셋이고 그 셋이 이 단계가 묻는 전부다: **작업 이름**(두 매체 공통) · **문서 파일
 *  이름**(hwpx 만 — TXT 는 파일을 만들지 않는다) · **저장 폴더**(읽기 전용 재진술).
 *
 *  이름은 여기 그려지지만 **`filename` section patch 에 속하지 않는다**(§10.13 판정 L):
 *  탭 이동의 자동 버리기와 `discard_patch {section}` 은 패턴만 되돌리고 이름은 그대로 둔다.
 *  같은 화면에 그린다고 같은 거래에 드는 것이 아니다.
 *
 *  저장 폴더는 **여기서 바꾸지 않는다** — 전역 설정이라 고르는 자리가 하나여야 한다(#968).
 *  값·출처·하향 사유는 Python 이 작업 화면과 같은 함수로 낸다(웹 재조립 0). */
function NameSaveStage(props: {
  snapshot: Obj; draft: DraftState; view: ViewState; controller: EditorController;
}): ReactNode {
  const { snapshot, draft, view, controller } = props;
  /* 문서 파일 이름 행은 **매체 파생**이다(§3.2) — TXT 작업은 파일을 만들지 않는다.
     단계 자체는 두 매체가 함께 갖는다(U6-D): 이름은 매체와 무관한 저장 게이트 술어다. */
  const hasPattern = snapshot.template_media !== "txt";
  /* 저장 폴더 행은 **Python 이 존을 낼 때만** 선다(U6-D #978 리뷰 4). TXT 는 파일을 만들지
     않아 폴더가 축이 아니고(`UI_CONTRACT` 「폴더가 축이 아니다」), 그때 존은 `null` 이다 —
     웹이 매체로 다시 판정하면 같은 사실을 두 곳이 답한다. */
  const folder = (snapshot.output_folder || null) as Obj | null;
  const rows = ((snapshot.rows || []) as Obj[]).filter((row) => row.has_content);
  const tokens: ReactNode[] = [];
  rows.forEach((row, index) => {
    if (index > 0) tokens.push(h("span", { key: `sep-${index}` }, "  ·  "));
    tokens.push(h("code", { key: `tok-${index}` }, `{{${row.template_field}}}`));
    tokens.push(h("span", { key: `arrow-${index}` }, " → "));
    tokens.push(h("span", { key: `pv-${index}` }, fnPreviewText(row, snapshot)));
  });
  return h("div", null,
    h("div", { className: "wtitle" }, stageTitle(snapshot, "filename")),
    h("p", { className: "wsub" },
      "이 작업을 뭐라고 부를지, 만든 문서를 어떤 이름으로 저장할지 정합니다."),
    h("div", { className: "row" },
      h("span", { className: "lbl lbl-fixed" }, "작업 이름"),
      h("input", {
        className: "field", id: "editorName", type: "text", "data-act": "name",
        placeholder: "작업 이름을 입력하세요", "aria-label": "작업 이름",
        value: valueOf(draft, NAME_FIELD),
        "aria-invalid": view.invalidField === NAME_FIELD ? "true" : undefined,
        onChange: (event: Obj) => controller.type(NAME_FIELD, String(event.currentTarget.value)),
        onFocus: () => controller.focus(NAME_FIELD, true),
        onBlur: () => { controller.focus(NAME_FIELD, false); controller.commitField(NAME_FIELD); },
        onCompositionStart: () => controller.compose(NAME_FIELD, true),
        onCompositionEnd: () => controller.compose(NAME_FIELD, false),
      })),
    /* 힌트는 **Python 표지 하나**가 세운다(`job_name_is_derived`). 웹이 「이름이 도출값과
       같은가」로 되유추하면 사람이 우연히 같은 이름을 지은 순간 힌트가 되살아난다. */
    snapshot.name_hint
      ? h("p", { className: "hint", id: "editorNameHint", style: { marginTop: 0 } },
        String(snapshot.name_hint))
      : null,
    hasPattern ? h("div", { className: "row" },
      h("span", { className: "lbl lbl-fixed" }, "문서 파일 이름"),
      h("input", {
        className: "field mono", "data-act": "pattern", value: valueOf(draft, PATTERN_FIELD),
        "aria-label": "문서 파일 이름",
        "aria-invalid": view.invalidField === PATTERN_FIELD ? "true" : undefined,
        onChange: (event: Obj) => controller.type(PATTERN_FIELD, String(event.currentTarget.value)),
        onFocus: () => controller.focus(PATTERN_FIELD, true),
        onBlur: () => { controller.focus(PATTERN_FIELD, false); controller.commitField(PATTERN_FIELD); },
        onCompositionStart: () => controller.compose(PATTERN_FIELD, true),
        onCompositionEnd: () => controller.compose(PATTERN_FIELD, false),
      })) : null,
    /* 예시는 **연번째로** Python 이 만든다(`pattern_preview`) — 여기서 「· 002 · 003」을
       조립하면 seq 토큰이 없는 패턴에서도 연번이 있는 것처럼 그려진다. */
    (hasPattern && snapshot.pattern_preview)
      ? h("p", { className: "hint mono", id: "editorPatternPreview", style: { marginTop: 0 } },
        `예: ${snapshot.pattern_preview}${snapshot.record_count ? " (표본 1행 기준)" : ""}`)
      : null,
    hasPattern ? h("details", {
      className: "hidden-hdrs tok-fold", open: view.tokFoldOpen,
      onToggle: (event: Obj) => controller.setTokFold(!!event.currentTarget.open),
    },
    h("summary", null, "파일명에 넣을 수 있는 값 (펼쳐 보기)"),
    h("p", { className: "hint", style: { marginTop: "var(--sp-4)" } },
      ...(tokens.length ? tokens
        : [h("span", { className: "muted", key: "none" },
          "매핑을 완료하면 파일명에 쓸 수 있는 필드가 여기 표시됩니다.")])),
    h("p", { className: "hint" },
      "날짜: ", h("code", null, "{{date}}"), " → 생성 날짜(YYYYMMDD) · ",
      h("code", null, "{{date:YYYY-MM-DD}}"), " → 하이픈 포함 날짜", h("br", null),
      "순번: ", h("code", null, "{{seq}}"), " → 1부터 증가 · ",
      h("code", null, "{{seq:001}}"), " → 001부터 세 자리로 증가")) : null,
    folder ? h("div", { className: "row", id: "editorOutFolderRow" },
      h("span", { className: "lbl lbl-fixed" }, "저장 폴더"),
      h("input", {
        className: "field ro mono", id: "editorOutDir", type: "text", readOnly: true,
        "aria-label": "저장 폴더", tabIndex: -1,
        value: String(folder.directory || "아직 정해지지 않았습니다"),
      }),
      folder.source_label
        ? h("span", { className: "muted capnote", id: "editorOutDirSource" },
          String(folder.source_label))
        : null,
      h("button", {
        className: "btn linklike", type: "button", "data-act": "open-settings",
        id: "editorOpenFolderSettings",
        onClick: () => controller.openSettings(),
      }, "설정에서 바꾸기")) : null,
    /* 설정한 폴더가 사라져 기본값으로 내려간 사유 — 조용한 하향 금지(문안은 링0 소유). */
    (folder && folder.notice)
      ? h("p", { className: "hint", id: "editorOutDirNotice", style: { marginTop: 0 } },
        String(folder.notice))
      : null);
}

/** 인라인 알림 노드(#323) — **셸 레벨**이라 세 탭이 공유하고 본문 재렌더에 증발하지 않는다.
 *  종전 거처는 파일 이름 탭 본문이었고, 그래서 나머지 두 탭의 통지가 갈 곳이 없었다.
 *
 *  상자·닫기는 `NoticeBox` 가 소유한다(U4 §2.12 · #945) — 문안 조립(`⚠ ` 표지)은 여기
 *  그대로다. 통지가 없어도 **노드는 남는다**: 세 탭 어디서든 통지가 갈 자리가 있다는
 *  것이 #323 의 계약이라 프로브가 그 존재를 통지 이전에 먼저 잰다. */
function SaveMessage(props: { view: ViewState; controller: EditorController }): ReactNode {
  const { saveMessage } = props.view;
  if (!saveMessage) return h("div", { id: "save-msg", className: "note", style: { display: "none" } });
  return createElement(NoticeBox, {
    id: "save-msg",
    closeId: "saveMsgClose",
    level: saveMessage.level === "ok" ? "ok" : "warn",
    text: `${saveMessage.level === "ok" ? "" : "⚠ "}${saveMessage.text}`,
    onClose: props.controller.clearSaveMessage,
  });
}

function EditorFooter(props: {
  snapshot: Obj; draft: DraftState; controller: EditorController;
}): ReactNode {
  const { snapshot, draft, controller } = props;
  const sections = (snapshot.sections || []) as string[];
  const here = sections.indexOf(snapshot.section);
  if (isEditing(snapshot)) {
    /* 저장·버리기는 **같은 합성 술어**로 상시 표시 + 상태 비활성이다(U2 §2.4·§2.17). */
    const armed = !!snapshot.dirty || hasPendingEdits(draft);
    /* 연결 확정 대기(#911)는 무장 사유를 **더한다**. 판정·라벨은 Python 이 실어 보낸
       것을 그대로 읽는다 — 「저장 안 됨」 같은 인접 사실로 확정 필요를 여기서 추론하지 않는다.
       바꿀 것이 없는데 관리 검토가 확정을 기다리면 dirty 는 영영 거짓이고, 그 상태에서
       두 동사가 모두 잠겨 사슬을 닫을 길이 없었다. 버리기는 그대로 dirty 술어다(확정
       대기는 버릴 것을 만들지 않는다). 라벨이 갈리는 자리는 **무변경 확정 하나**다:
       손댄 것이 있으면 그 저장이 확정도 겸하므로 「변경 저장」이 여전히 참말이다.
       설명 줄은 걷혔다(§8 낭독 패턴 1) — 전제 조건은 라벨이 말하고 사유는 blocker 가 든다. */
    const confirm = (snapshot.binding_confirm || {}) as Obj;
    const confirmPending = !!confirm.pending;
    const confirmOnly = confirmPending && !armed;
    return h("footer", { className: "wfoot", id: "editor-foot" },
      h("button", {
        className: "btn", "data-act": "discard-patch", disabled: !armed,
        onClick: () => controller.guarded(() => controller.discardPatch()),
      }, "변경 버리기"),
      h("span", { className: "spacer" }),
      h("button", {
        className: "btn", "data-act": "save",
        "data-confirm-binding": confirmOnly ? "1" : null,
        disabled: !(armed || confirmPending),
        onClick: () => controller.guarded(() => controller.doSave({})),
      }, confirmOnly ? String(confirm.label || "") : "변경 저장"),
      saveAndOpenButton(armed || confirmPending, controller));
  }
  const last = here >= sections.length - 1;
  const can = !!(snapshot.reachable || {})[snapshot.section];
  return h("footer", { className: "wfoot", id: "editor-foot" },
    h("button", {
      className: "btn", "data-act": "cancel-new",
      onClick: () => controller.guarded(() => controller.cancelNewDraft()),
    }, "취소"),
    here > 0
      ? h("button", {
        className: "btn", "data-act": "back",
        onClick: () => controller.guarded(() => controller.gotoSection(controller.neighbour(-1))),
      }, "◀ 뒤로")
      : h("button", { className: "btn", disabled: true }, "◀ 뒤로"),
    h("span", { className: "spacer" }),
    (!last && !can) ? h("span", { className: "muted capnote" }, gateHint(snapshot)) : null,
    last
      ? h("button", {
        className: "btn", "data-act": "save",
        onClick: () => controller.guarded(() => controller.doSave({})),
      }, "작업 저장")
      : null,
    last
      ? saveAndOpenButton(true, controller)
      : h("button", {
        className: "btn primary", "data-act": "next", disabled: !can,
        onClick: () => controller.guarded(() => controller.gotoSection(controller.neighbour(1))),
      }, "다음 ▶"));
}

/** 「저장하고 문서 만들기로」 — 마지막 단계의 **주 행동**(U6 §2.2 · 동결 시안 장면 3).
 *
 *  저장 자체는 두 동사 모두 같은 `doSave` 를 지난다(게이트·덮어쓰기 확인·차단 조준 공유).
 *  갈리는 것은 **성사 뒤에 어디에 서는가** 하나다: 「작업 저장」은 제자리(결정 40 불변),
 *  이 동사는 문서 만들기에 그 작업이 선 상태로 착석한다. 무장 술어는 옆 동사와 **같은
 *  값**을 받는다 — 두 술어를 두면 한쪽만 눌리는 상태가 실재한다. */
function saveAndOpenButton(armed: boolean, controller: EditorController): ReactNode {
  return h("button", {
    className: "btn primary", "data-act": "save-and-open", disabled: !armed,
    onClick: () => controller.guarded(() => controller.saveAndOpen()),
  }, "저장하고 문서 만들기로");
}

export function EditorScreen(props: { controller: EditorController }): ReactNode {
  const { controller } = props;
  /* 세 store 모두 세 번째 인자(getServerSnapshot)를 같은 getter 로 넘긴다
     (`JobContentSelection` 선례): 제품 런타임은 이 인자를 쓰지 않지만, 없으면 이 셸이
     `react-dom/server` 로 **한 번도** 렌더되지 못해 노드 배치 계약을 단위층에서 잴 수 없다. */
  const snapshot = useSyncExternalStore(
    controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot);
  const draft = useSyncExternalStore(
    controller.draftModel.subscribe, controller.draftModel.getSnapshot,
    controller.draftModel.getSnapshot);
  const view = useSyncExternalStore(
    controller.viewModel.subscribe, controller.viewModel.getSnapshot,
    controller.viewModel.getSnapshot);
  /* 고르기 단계의 두 열은 **자기 채널을 직접 구독**한다(U6-B #976) — 편집기 스냅샷이
     같은 목록을 한 번 더 실어 나르면 tpl·pool 의 변이가 두 경로로 도착한다. */
  const tpl = useSyncExternalStore(
    controller.tplModel.subscribe, controller.tplModel.getSnapshot,
    controller.tplModel.getSnapshot);
  const pool = useSyncExternalStore(
    controller.poolModel.subscribe, controller.poolModel.getSnapshot,
    controller.poolModel.getSnapshot);

  /* 조준은 렌더 **뒤**에 — 커밋 전에는 겨눌 노드가 아직 없다. */
  useEffect(() => { controller.consumeAim(); });

  if (snapshot === null) {
    return h("div", { className: "editor-shell" },
      h("p", { className: "note", role: "status" }, "편집기를 읽는 중…"));
  }
  let body: ReactNode;
  if (snapshot.section === "template") {
    body = h(PairingStage as any, { snapshot, tpl, pool, controller });
  }
  else if (snapshot.section === "binding") body = h(MappingStage as any, { snapshot, draft, view, controller });
  else body = h(NameSaveStage as any, { snapshot, draft, view, controller });
  return h("div", { className: "editor-shell" },
    h("button", {
      className: "btn sm back", id: "editorBack", type: "button",
      onClick: () => controller.guarded(() => controller.leaveTo(controller.returnScreen())),
    }, "← 원래 업무로 돌아가기"),
    h(EditorHead as any, { snapshot, controller }),
    h(ContextBanner as any, { snapshot }),
    h(StepHeader as any, { snapshot, controller }),
    h("div", { className: "wbody", id: "editor-body", "data-preserve-scroll": true },
      /* 세션 통지(#26) — 문제(warn)만 시끄럽게, 정상(ok)은 muted 한 줄.
         닫기는 **사용자 몫**이다(U4 계열1-20): 세우는 트리거는 그대로라 사유가 다시 서면
         통지도 다시 서고, 해소를 자동 감지하려 들면 통지마다 해소 술어를 새로 지어야 한다. */
      snapshot.notice ? createElement(NoticeBox, {
        tag: "p",
        closeId: "editorNoticeClose",     // 좌표는 불변 — 이 id 를 든 게이트가 이미 있다.
        level: snapshot.notice.level === "ok" ? "quiet" : "warn",
        text: String(snapshot.notice.text),
        onClose: () => { void controller.sendEdit("dismiss_notice", {}); },
      }) : null,
      body),
    h(SaveMessage as any, { view, controller }),
    h(EditorFooter as any, { snapshot, draft, controller }),
    h(ContextMenu as any, {
      id: "tplRowMenu",
      controller: controller.libContextMenu,
      popover: controller.popover,
      triggerSelector: "#scr-editor .job-more",
      onDismiss: controller.closeLibMenu,
      onSelect: (action: string) => { void controller.handleLibMenu(action); },
    }),
    /* 2단계 머리의 드문 동사 — 「제안 n건 모두 확인」 옆에 늘어놓지 않는다(§6: 같은
       선택지를 모든 문맥에 나열하지 않는다). 되돌리는 동사는 필요할 때 찾을 수 있으면
       된다. 트리거 selector 가 lib 쪽과 갈리는 것이 두 메뉴의 dismissal 을 나눈다. */
    h(ContextMenu as any, {
      id: "bindingMoreMenu",
      controller: controller.bindingContextMenu,
      popover: controller.popover,
      triggerSelector: "#scr-editor .binding-more",
      onDismiss: controller.closeBindingMenu,
      onSelect: (action: string) => { controller.guarded(() => controller.handleBindingMenu(action)); },
    }));
}

/** 린트메모장 호스트 — vendor 수명주기를 **React 효과 하나**가 진다.
 *
 *  마운트/해제는 이 창이 살아 있는 동안만이다(`state === null` 이면 부모가 아예 렌더하지
 *  않는다). CodeMirror 타입은 `txt_lintpad.ts` 밖으로 나오지 않으므로 여기 있는 것은
 *  불투명 손잡이뿐이다(#588 봉쇄).
 *
 *  본문의 주인은 CodeMirror 문서이고 상태는 그 거울이다 — 매 렌더마다 값을 되밀어 넣지
 *  않는다(`updateLintpad` 가 같은 문자열이면 아무것도 하지 않는다). 그래서 캐럿이 튀지
 *  않으면서도 밖에서 갈아 끼운 본문은 따라 들어온다. */
function TxtLintpad(props: {
  controller: EditorController; content: string; spans: readonly LintpadSpan[] | null;
}): ReactNode {
  const { controller } = props;
  const hostRef = useRef<HTMLDivElement | null>(null);
  const handleRef = useRef<LintpadHandle | null>(null);
  /* 마지막으로 **얹은** 판정. 렌더마다 같은 좌표를 다시 dispatch 하면 타이핑 한 글자에
     트랜잭션이 둘씩 붙는다(강조는 그대로인 채 비용만 는다). */
  const appliedSpans = useRef<readonly LintpadSpan[] | null>(null);
  /* 마운트 시점의 본문만 심는다 — 이후 갱신은 아래 효과가 진다(deps 를 비워 재마운트 금지). */
  const initial = useRef<string>(props.content);
  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return undefined;
    const handle = mountLintpad({
      host,
      doc: initial.current,
      contentId: "txtEditContent",
      ariaLabel: "템플릿 내용",
      onDocChanged: (text: string) => { controller.typeTxtEdit(text); },
    });
    handleRef.current = handle;
    return () => { disposeLintpad(handle); handleRef.current = null; };
  }, []);
  useEffect(() => {
    const handle = handleRef.current;
    if (handle === null) return;
    const fresh = props.spans !== null && props.spans !== appliedSpans.current;
    if (fresh) appliedSpans.current = props.spans;
    updateLintpad(handle, {
      doc: props.content, spans: fresh ? props.spans ?? undefined : undefined,
    });
  });
  return h("div", { className: "lintpad", id: "txtLintpad", ref: hostRef });
}

/** 진단 재진술 — Python 이 낸 `message` 를 **그대로** 줄로 편다(문안 재조립 금지). */
function TxtLintReport(props: { lint: TxtLintState | null }): ReactNode {
  const { lint } = props;
  const diagnostics = lint?.diagnostics || [];
  if (lint === null) {
    return h("p", { id: "txtLintReport", className: "hint" }, "표기를 확인하는 중…");
  }
  if (diagnostics.length === 0) {
    const summary = lint.summary || {};
    return h("p", { id: "txtLintReport", className: "hint" },
      `표기 이상 없음 · 항목 ${Number(summary.slots || 0)} · 선택 ${Number(summary.options || 0)}`
      + ` · 누름틀 ${Number(summary.fields || 0)}`);
  }
  return h("div", { id: "txtLintReport", className: "note warnbox", role: "status" },
    h("p", { style: { margin: 0 } }, `구간 표기 이상 ${diagnostics.length}건`),
    h("ul", { id: "txtLintDiag", className: "muted capnote" },
      diagnostics.map((diagnostic, index) => h("li", { key: index },
        String(diagnostic.message || ""),
        diagnostic.context ? h("span", { className: "muted" }, ` — ${String(diagnostic.context)}`) : null))));
}

export function TxtEditDialog(props: { controller: EditorController }): ReactNode {
  const { controller } = props;
  /* 세 번째 인자(getServerSnapshot)는 `EditorScreen` 과 같은 이유로 선다: 없으면 이 창이
     `react-dom/server` 로 **한 번도** 렌더되지 못해 노드 배치를 단위층에서 잴 수 없다. */
  const view = useSyncExternalStore(
    controller.viewModel.subscribe, controller.viewModel.getSnapshot,
    controller.viewModel.getSnapshot);
  const state = view.txtEdit;
  /* 초기 포커스는 **커밋 뒤** 이 자리가 겨눈다. 모달 executor 의 `initialFocus` 는 열림
     **시점**의 DOM 을 보는데 이 창의 내용은 그 뒤 커밋에서 생기므로, 열림 시점에 넘기면
     대상이 없어 되돌림 트리거로 떨어진다(시트 선택이 같은 이유로 같은 형태를 쓴다). */
  useEffect(() => {
    if (state === null) return;
    /* 초기 포커스의 주인은 **여기 하나**다. 메모장이 마운트에서 스스로 겨누면 새 생성
       창에서 이름 칸과 두 번 다투고, 마지막에 이긴 쪽이 순서에 따라 갈린다. 메모장의
       컨텐츠 DOM 은 종전 id 를 그대로 이어받으므로 겨눔 방식은 바뀌지 않았다. */
    const target = controller.doc.getElementById(
      state.mode === "new" ? "txtEditName" : "txtEditContent");
    target?.focus();
  }, [state === null, state?.mode]);
  return h("div", { className: "modal-card" },
    h("h3", { id: "txtEditTitle" }, state?.title || "새 TXT 템플릿"),
    h("label", {
      className: "ctl", id: "txtNameRow",
      style: { display: state?.mode === "new" ? "" : "none" },
    },
    h("span", { className: "lbl" }, "이름(확장자 제외)"),
    h("input", {
      className: "field", id: "txtEditName", type: "text", placeholder: "예: 회의결과보고",
      value: state?.name || "",
      onChange: (event: Obj) => controller.patchTxtEdit({ name: String(event.currentTarget.value) }),
    })),
    h("p", { className: "modal-sub" },
      "{{필드}} 토큰과 {{#항목 …}} 구간 표기를 포함한 템플릿 내용"),
    state === null ? null : h(TxtLintpad as any, {
      /* 판정이 아직 없으면 `null` 이다 — 빈 배열을 주면 「강조 없음」을 매번 새로 얹는
         것과 구분되지 않는다(렌더마다 같은 좌표를 다시 dispatch 하는 자리). */
      controller, content: state.content, spans: state.lint?.spans ?? null,
    }),
    h(TxtLintReport as any, { lint: state?.lint || null }),
    h("p", {
      id: "txtEditError", className: "note dangerbox", role: "alert",
      style: { display: state?.error ? "block" : "none" },
    }, state?.error || ""),
    h("div", { className: "modal-actions" },
      h("button", {
        className: "btn", id: "txtEditCancel",
        onClick: () => controller.guarded(() => controller.confirmDiscardTxtEdit()),
      }, "취소"),
      state?.mode === "edit"
        ? h("button", {
          className: "btn", id: "txtEditSaveAs",
          onClick: (event: Obj) => controller.guarded(
            () => controller.saveTxtEditAsNew(event.currentTarget)),
        }, "새 파일로 저장…")
        : null,
      h("button", {
        className: "btn primary", id: "txtEditOk",
        onClick: () => controller.guarded(() => controller.submitTxtEdit()),
      }, "저장")));
}
