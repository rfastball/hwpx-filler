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
import { NoticeBox } from "./notice_box.ts";
import { PathActions } from "./path_actions.ts";
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
  notify(message: string): void;
};

const SCREEN = "editor";
const EDIT_CHAIN = "editor:mutate";

/* 표시형·타입 라벨은 표현 계층이라 여기 산다(Qt mapping_table 의 웹 짝). */
const TYPE_LABEL: Record<string, string> = {
  text: "텍스트", date: "날짜", amount: "금액", const: "고정값", today: "오늘 날짜",
};
const INFERRED_LABEL: Record<string, string> = {
  text: "텍스트", date: "날짜", amount: "금액", number: "숫자", phone: "전화번호",
};
/** 매핑 행 상태 → class. Python 이 내는 닫힌 집합 넷과 1:1(발명·누락 금지). */
const ROW_STATE_CLASS: Record<string, string> = {
  confirmed: "r-confirmed", unconfirmed: "r-unconfirmed",
  schemaonly: "r-schemaonly", unmatched: "r-unmatched",
};

const SECTION_TITLES: Record<string, string> = {
  template: "템플릿", binding: "필드 연결·표시", filename: "파일 이름",
};

const ENTRY_LEAD: Record<string, string> = {
  library: "「문서 작업」에서 열었습니다.",
  run_failure: "생성 실패 결과에서 열었습니다.",
  output_result: "생성 결과에서 열었습니다.",
  document_browser_repair: "실행을 막는 문제를 고치러 열었습니다.",
  document_browser_new_work: "고른 데이터로 새 작업을 시작합니다.",
};
const RETURN_LABEL: Record<string, string> = {
  data: "문서 만들기로 돌아가기",
  result: "결과로 돌아가기", library: "「문서 작업」으로 돌아가기",
  documents: "문서 탐색으로 돌아가기",
};
/* 복귀처 — 진입 문맥이 말한 표면(계약 §8). 없으면 「문서 만들기」다. */
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
  media: string;
  kind: "row";
  key?: string;
  item?: Obj | null;
  trigger: HTMLElement;
};

type ViewState = {
  libMenu: LibMenu | null;
  txtEdit: TxtEditState | null;
  foldOpen: boolean;
  tokFoldOpen: boolean;
  saveMessage: { text: string; level: string } | null;
  /** 열린 등록 데이터 목록 1슬롯 — 판정·문구는 Python 이 낸 그대로 든다(#932 U4-C S2-5).
   *  `null` = 닫힘. 스냅샷에 상주시키지 않는 이유는 목록이 durable 저장소 읽기라서다. */
  poolPick: { items: Obj[]; corrupted: Obj[] } | null;
  invalidField: string;
  aim: string;
  /** 이 문맥에서 이미 겨눈 목표 — 문맥당 한 번만 조준한다. */
  aimed: string;
};

const isEditing = (snapshot: Obj): boolean => !!snapshot.editing_origin;

/** 목록을 바꾸지 않는 tpl 동사 — 완료 뒤 editor 재당김을 걸지 않는다.
 *
 *  `txt_lint` 는 저작 중 타이핑마다(디바운스) 도는 **순수 판정**이라, 재당김이 붙으면
 *  글자 하나마다 편집기 스냅샷 전체가 다시 온다. 나머지 tpl 동사는 전부 변이라 종전대로다. */
const TPL_READONLY_ACTIONS = new Set(["txt_lint"]);

/** 저작 창의 lint 왕복 디바운스(ms) — 하우스 관용구(`library.ts` 검색 상자와 같은 값). */
const TXT_LINT_DEBOUNCE_MS = 180;

/** 저장 뒤 안내 — 저장은 Draft 보존일 뿐이고 작업에 실리는 것은 별개 동사다(D5 · #299).
 *
 *  이 한 줄이 없으면 「저장했으니 반영됐다」는 조용한 오해가 남는다. 문안의 두 동사는
 *  「문서 만들기」의 실제 버튼 이름이다(`job_run.ts` — 여기서 발명하지 않는다). */
const TXT_SAVE_NOTICE = "저장했습니다. 작업에 반영하려면 「변경사항 확인」 다음 「변경사항 적용」을 누르세요.";

export function createEditorController(deps: EditorControllerDeps) {
  const model = deps.runtime.model<Obj | null>(SCREEN);

  let draft: DraftState = emptyDraft();
  let view: ViewState = {
    libMenu: null, txtEdit: null,
    foldOpen: false, tokFoldOpen: false, saveMessage: null, poolPick: null,
    invalidField: "", aim: "", aimed: "",
  };
  const libContextMenu = createContextMenu();
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
  model.subscribe(absorb);
  absorb();

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

  const invoke = async (
    method: Parameters<BridgeClient["invoke"]>[0], ...args: unknown[]
  ): Promise<unknown> => expectHostValue(await deps.client.invoke(method, ...args), method);

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
      const match = /^row:(\d+):(source|type|fmt|const)$/.exec(field);
      if (match === null) throw new Error(`알 수 없는 편집 draft field입니다: ${field}`);
      const index = Number(match[1]);
      const axis = match[2] as RowAxis;
      commits.push(commit(field, `set_${axis}`, { index, [axis]: state.draftValue }));
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

  function commitRowValue(index: number, axis: RowAxis, value: string): void {
    const field = rowField(index, axis);
    if (axis === "source") void commit(field, "set_source", { index, source: value });
    if (axis === "type") void commit(field, "set_type", { index, type: value });
    if (axis === "fmt") void commit(field, "set_fmt", { index, fmt: value });
    if (axis === "const") void commit(field, "set_const", { index, const: value });
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

  function findLibItem(media: string, key: string): Obj | null {
    const band = (snapshot().library || {})[media] || {};
    for (const section of band.sections || []) {
      for (const item of section.items || []) if (item.key === key) return item;
    }
    return null;
  }

  function closeLibMenu(): void {
    patchView({ libMenu: null });
    libContextMenu.close();
  }

  /* 겨눔은 **행 하나**다 — 그룹 갈래는 U4 §2-30 에서 그룹 표면과 함께 사라졌다. */
  function openLibMenu(media: string, id: string, trigger: HTMLElement): void {
    const item = findLibItem(media, id);
    const items: ContextMenuItem[] = libRowMenuItems(media, item);
    /* 동작이 0 이면 애초에 트리거가 비활성이라 여기 오지 않는다(어포던스는 `LibRowTail`
       이 같은 술어로 잠근다) — 그래도 방어로 남긴다: 빈 팝오버는 「눌렀는데 아무 일도
       없다」라서 조용한 no-op 이다. */
    if (items.length === 0) return;
    patchView({ libMenu: { media, kind: "row", key: id, item, trigger } });
    libContextMenu.open(trigger, items);
  }

  function toggleLibMenu(media: string, id: string, trigger: HTMLElement): void {
    const open = view.libMenu;
    if (open !== null && open.media === media && open.key === id) { closeLibMenu(); return; }
    openLibMenu(media, id, trigger);
  }

  async function handleLibMenu(action: string): Promise<void> {
    const menu = view.libMenu;
    if (menu === null) return;
    closeLibMenu();
    try {
      if (action === "edit") {
        const item = menu.item || {};
        const result = await dispatch("tpl", "txt_content", { path: item.path });
        openTxtEdit("edit", item.path, item.name, String(result.content || ""), menu.trigger);
      } else if (action === "act:compile") await compileTemplate((menu.item || {}).path);
      else if (action === "act:review") await dispatch("tpl", "review", { path: (menu.item || {}).path });
    } catch (error) {
      deps.notify(String((error as Obj)?.message || error));
    }
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

  /* ---- 컴파일된 구간 항목(Slot) 관리 동사 3종(S8-03) ---- */

  /** 항목 이름 바꾸기 — 파괴가 아니라 프롬프트 하나다(확인 왕복 없음). */
  async function renameSlot(slotId: string, label: string, trigger: HTMLElement): Promise<void> {
    const slots = (snapshot().library || {}).slots || {};
    const value = await deps.modal.prompt({
      /* 빈 문자열도 유효한 답이다(이름 없는 항목으로 되돌리기) — 검증을 걸지 않는다. */
      title: "항목 이름 바꾸기", body: `'${slotId}' 의 새 이름`, value: label,
      returnFocus: trigger,
    });
    if (value === null) return;
    await dispatch("tpl", "slot_rename", { path: String(slots.path || ""), slot_id: slotId, label: value });
  }

  /** 항목을 표기로 되돌리기 — 확인 본문(전이 결과 재진술)은 Python 이 싣는다. */
  async function decompileSlot(slotId: string, trigger: HTMLElement): Promise<void> {
    const path = String(((snapshot().library || {}).slots || {}).path || "");
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
    const path = String(((snapshot().library || {}).slots || {}).path || "");
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
    const path = String(((snapshot().library || {}).slots || {}).path || "");
    const result = await dispatch("tpl", "slot_remove", { path, slot_id: slotId });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n지울까요?`,
      confirmLabel: "삭제", cancelLabel: "취소", returnFocus: trigger, danger: true,
    })) {
      await dispatch("tpl", "slot_remove", { path, slot_id: slotId, confirm: true });
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
        const rows = (((snapshot().library || {}).slots || {}).rows || []) as Obj[];
        const row = rows.find((item) => String(item.id) === slotId);
        await renameSlot(slotId, String((row || {}).label || ""), trigger);
      } else if (verb === "decompile") await decompileSlot(slotId, trigger);
      else if (verb === "remove") await removeSlot(slotId, trigger);
      else throw new Error(`알 수 없는 항목 동사입니다: ${verb}`);
    } catch (error) {
      noticeSave(String((error as Obj)?.message || error));
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

  /** 차단당한 칸으로 커서를 옮긴다 — 어느 칸인지는 Python 이 말한다. */
  function aimAtBlockedField(field: string): void {
    /* 데이터 미연결(#932 U4-C S2-3)의 「칸」은 입력이 아니라 관문의 데이터 선택 동사다.
       그 탭에 있지 않으면 겨눌 노드가 없으므로 문구만 남긴다(패턴 칸과 같은 규율). */
    if (field === "data") {
      if (snapshot().section !== "binding") return;
      const gateway = deps.doc.querySelector<HTMLElement>(
        '#editor-body button[data-act="pick-data"]');
      gateway?.focus();
      return;
    }
    if (field !== NAME_FIELD && field !== PATTERN_FIELD) return;
    if (field === PATTERN_FIELD && snapshot().section !== "filename") return;
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

  /** 탭 이동 — 정산하고 한 발 보낸다. 막는 patch 의 처분은 Python 이 진다(계약 §5.2).
   *
   *  종전에는 여기서 3택(저장하고 이동·버리고 이동·머무르기)을 받고 처분 표지를 실어 같은
   *  액션을 다시 보냈다. 지금은 컨트롤러가 막는 자리를 자동으로 되돌리고 그 사실을 통지로
   *  재진술하므로, 웹이 할 일은 정산과 발신 하나뿐이다. */
  async function gotoSection(target: string): Promise<void> {
    if (!target) return;
    await flushPendingEdits();
    await sendEdit("goto_section", { section: target });
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

  async function useLibraryTemplate(path: string): Promise<void> {
    await sendEdit("use_library_template", { path });
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
    if (result !== null) closePoolData();          // 파일로 갈아탔으면 열린 목록은 지난 상태다
  }

  /* 등록 데이터에서 고르기(#932 U4-C S2-5) — 파일 피커와 **같은 선행 규율**을 지킨다:
     확정 매핑이 걸린 교체는 열기 전에 한 번 묻는다(고른 뒤 되묻는 순서 금지). */
  async function openPoolData(): Promise<void> {
    if (!(await confirmMappingResetIfConfirmed("데이터를 바꾸면"))) return;
    const result = await sendEdit("pool_options", {});
    if (result.ok === false) {
      noticeSave(String(result.error || "등록 데이터 목록을 읽을 수 없습니다."));
      return;
    }
    patchView({
      poolPick: {
        items: (result.items || []) as Obj[],
        corrupted: (result.corrupted || []) as Obj[],
      },
    });
  }

  async function usePoolData(key: string): Promise<void> {
    const result = await sendEdit("use_pool_data", { key });
    if (result.ok === false) {
      noticeSave(String(result.error || "등록 데이터를 불러올 수 없습니다."));
      return;                                       // 목록은 열어 둔다 — 다른 항목을 고를 수 있다
    }
    patchView({ poolPick: null });
  }

  function closePoolData(): void { patchView({ poolPick: null }); }

  async function useNone(): Promise<void> {
    /* 확정 존재는 확인 **전에** 선차단한다(파괴를 승인시킨 뒤 거부하는 순서 금지). */
    const stakes = await sendEdit("mapping_reset_stakes", {});
    if (stakes.confirmed) {
      noticeSave(`확정한 매핑 ${stakes.confirmed}개가 있어 전체 미사용을 할 수 없습니다. 확정을 먼저 해제하거나 칩을 하나씩 끄세요.`);
      return;
    }
    const manual = Number(stakes.use_none_manual || 0);
    if (manual && !(await deps.modal.confirm({
      body: `전체 미사용하면 직접 소스를 고른 매핑 ${manual}개의 수동 지정이 해제됩니다` +
        `(자동 제안으로만 복원).\n\n계속할까요?`,
      confirmLabel: "전체 미사용", cancelLabel: "취소",
    }))) return;
    await sendEdit("use_none", {});
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

  /** 모두 확정 — 내용 행 즉시 확정 + 비움 승격 이름게이트. */
  async function confirmAll(): Promise<void> {
    const result = await sendEdit("confirm_all", {});
    const blanks = (result.blanks || []) as string[];
    if (!blanks.length) return;
    const accepted = await deps.modal.confirm({
      body: `아래 ${blanks.length}개 필드는 채우지 않고 '비움'으로 확정합니다:\n\n${blanks.join(", ")}\n\n계속할까요?`,
      confirmLabel: "비움으로 확정", cancelLabel: "취소",
    });
    if (accepted) await sendEdit("confirm_blanks", { fields: blanks });
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
    /** 현 스냅샷 재당김 — 편집 모드 복귀 때 공유 그룹 접힘을 반영한다(#138 F12). */
    rerender(): Promise<unknown> { return deps.runtime.refresh(SCREEN); },
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
    setFold(open: boolean): void { patchView({ foldOpen: open }); },
    setTokFold(open: boolean): void { patchView({ tokFoldOpen: open }); },
    toggleLibMenu, closeLibMenu, handleLibMenu, handleSlotVerb,
    isLibMenuOpen: (): boolean => view.libMenu !== null,
    libContextMenu,
    findLibItem,
    openTxtEdit, patchTxtEdit, confirmDiscardTxtEdit, submitTxtEdit,
    typeTxtEdit, saveTxtEditAsNew,
    /** 외부 FS 재스캔(tpl 채널) — push 가 재당김을 태워 목록·결과 줄이 되그려진다. */
    refreshLibrary: (): Promise<Obj> => dispatch("tpl", "refresh", {}),
    useLibraryTemplate, importTemplate, pickData,
    openPoolData, usePoolData, closePoolData,
    useNone, resuggestAll, confirmAll, discardPatch, cancelNewDraft,
    gotoSection, neighbour, doSave, returnScreen, flushPendingEdits, sendEdit,
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
  if (snapshot.section === "template") return "템플릿을 선택하고 미해결 토큰을 확인해야 진행할 수 있습니다";
  if (snapshot.section === "binding") return "전 행을 확정해야 진행할 수 있습니다";
  return "";
}

function EditorHead(props: { snapshot: Obj; draft: DraftState; view: ViewState; controller: EditorController }): ReactNode {
  const { snapshot, draft, view, controller } = props;
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
      h("h1", { id: "editorTitle" },
        h("input", {
          className: "field title-input", id: "editorName", type: "text", "data-act": "name",
          placeholder: "작업 이름을 입력하세요", "aria-label": "작업 이름",
          value: valueOf(draft, NAME_FIELD),
          "aria-invalid": view.invalidField === NAME_FIELD ? "true" : undefined,
          onChange: (event: Obj) => controller.type(NAME_FIELD, String(event.currentTarget.value)),
          onFocus: () => controller.focus(NAME_FIELD, true),
          onBlur: () => { controller.focus(NAME_FIELD, false); controller.commitField(NAME_FIELD); },
          onCompositionStart: () => controller.compose(NAME_FIELD, true),
          onCompositionEnd: () => controller.compose(NAME_FIELD, false),
        })),
      h("p", { className: "sub", id: "editorSubtitle" },
        snapshot.template_name ? `템플릿 ${snapshot.template_name}` : "템플릿을 아직 고르지 않았습니다.")),
    h("div", { className: "status", id: "editorSaveState", "data-level": level }, stateText));
}

function ContextBanner(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const context = snapshot.context || {};
  const lead = ENTRY_LEAD[context.entry_reason];
  if (!lead) {
    return h("section", { className: "note ctxbanner", id: "editorContext", style: { display: "none" } });
  }
  const evidence = context.evidence || {};
  const surface = (context.return_context || {}).surface;
  const label = RETURN_LABEL[surface];
  const rows = Object.keys(evidence).map((key) =>
    h("span", { key }, h("b", null, key), " ", String(evidence[key])));
  return h("section", { className: "note ctxbanner", id: "editorContext" },
    h("div", { className: "row" }, h("b", null, lead), h("span", { className: "spacer" }),
      label ? h("button", {
        className: "btn sm", "data-act": "context-return",
        onClick: () => controller.guarded(() => controller.leaveTo(controller.returnScreen())),
      }, label) : null),
    rows.length ? h("div", { className: "ctx-ev" }, ...rows) : null);
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

/** 행 ⋮ 가 열 동사 목록 — **한 술어**다. 메뉴를 여는 쪽과 트리거를 잠그는 쪽이 같은 값을
 *  봐야 「버튼은 있는데 눌러도 아무 일도 없다」가 생기지 않는다(같은 상태 두 곳 판정 금지).
 *
 *  목록·라벨은 링1 소유다 — hwpx 는 스냅샷 `actions`(상태 게이트가 낸 수선 동사)를 그대로
 *  그리고, txt 는 읽을 수 있을 때만 「내용 편집」이 선다. 삭제는 U6-A(#975)에서 퇴역했으므로
 *  COMPILED·FILLED hwpx 행과 판독 실패 txt 행은 동사가 **0** 이다. */
export function libRowMenuItems(media: string, item: Obj | null): ContextMenuItem[] {
  if (item === null || item === undefined) return [];
  if (media === "hwpx") {
    return ((item.actions || []) as Obj[]).map((action: Obj) =>
      ({ action: `act:${String(action.key)}`, label: String(action.label) }));
  }
  return item.error ? [] : [{ action: "edit", label: "내용 편집" }];
}

/** 동작 0 인 행의 ⋮ 에 붙는 사유 — 조용히 죽은 버튼을 두지 않는다. */
export const LIB_ROW_NO_ACTION_REASON = "이 항목에 지금 할 수 있는 작업이 없습니다.";

function LibRowTail(props: { media: string; item: Obj; controller: EditorController }): ReactNode {
  const { media, item, controller } = props;
  /* 동작이 하나도 없으면 **비활성 + 사유**다(U6-A 리뷰): 종전에는 버튼이 멀쩡히 서 있고
     클릭이 조용히 삼켜졌다 — 이 저장소가 금지하는 무반응이다. 버튼을 아예 지우지 않는
     이유는 행마다 꼬리 폭이 달라져 목록이 들쭉날쭉해지기 때문이고, 비활성은 「지금은
     없다」를 말하면서 자리를 지킨다. */
  const disabled = libRowMenuItems(media, item).length === 0;
  /* legacy 는 두 버튼을 감싸지 않고 이어 붙였다 — 요소 트리에서 감싸면 `.libselrow` 의
     flex 자식 수가 바뀌어 배치가 달라진다. Fragment 는 DOM 노드를 만들지 않는다. */
  return createElement(Fragment, null,
    h("button", {
      className: "job-more", "data-act": "lib-more", "data-media": media, "data-key": item.key,
      "aria-haspopup": "true", "aria-label": "항목 관리",
      disabled,
      title: disabled ? LIB_ROW_NO_ACTION_REASON : undefined,
      onClick: (event: Obj) => controller.toggleLibMenu(media, item.key, event.currentTarget),
    }, "⋮"));
}

function HwpxLibRow(props: { item: Obj; controller: EditorController }): ReactNode {
  const { item, controller } = props;
  /* 오류 행은 선택 버튼 대신 사유를 보여준다 — 죽은 버튼이 생 예외로 끝나는 반쪽 노출 금지. */
  const pick = item.is_error
    ? h("span", { className: "muted capnote", title: item.detail || "" }, "사용 불가")
    : (item.current
      ? h("span", { className: "muted capnote" }, "선택됨")
      : h("button", {
        className: "btn sm", "data-act": "use-library", "data-path": item.path,
        onClick: () => controller.guarded(() => controller.useLibraryTemplate(item.path)),
      }, "이 템플릿으로"));
  /* 행과 경고 줄은 **형제**다(legacy 의 문자열 이어붙이기) — 감싸면 경고가 행 안으로 들어간다. */
  return createElement(Fragment, { key: item.key },
    h("div", { className: `libselrow${item.current ? " cur" : ""}` },
      h("span", { className: "fname" }, item.name),
      item.badge_label ? h("span", { className: "tbadge", title: item.detail || "" }, item.badge_label) : null,
      pick,
      h(LibRowTail as any, { media: "hwpx", item, controller })),
    ...(item.fill_warns || []).map((warn: string, index: number) =>
      h("div", { className: "hint warn", key: index }, warn)));
}

function TxtLibRow(props: { item: Obj; controller: EditorController }): ReactNode {
  const { item, controller } = props;
  const badge = item.error
    ? h("span", { className: "tbadge", title: item.error }, "읽기 오류")
    : h("span", { className: "tbadge" }, `필드 ${item.field_count}`);
  const pick = item.error
    ? h("span", { className: "muted capnote", title: item.error }, "사용 불가")
    : (item.current
      ? h("span", { className: "muted capnote" }, "선택됨")
      : h("button", {
        className: "btn sm", "data-act": "use-library", "data-path": item.path,
        onClick: () => controller.guarded(() => controller.useLibraryTemplate(item.path)),
      }, "이 템플릿으로"));
  return h("div", { className: `libselrow${item.current ? " cur" : ""}`, key: item.key },
    h("span", { className: "fname" }, item.name), badge, pick,
    h(LibRowTail as any, { media: "txt", item, controller }));
}

function LibraryBand(props: {
  band: Obj; media: string; emptyText: string; controller: EditorController;
}): ReactNode {
  const { band, media, emptyText, controller } = props;
  const sections = (band && band.sections) || [];
  const total = sections.reduce(
    (sum: number, section: Obj) => sum + (section.items ? section.items.length : 0), 0);
  const Row = media === "hwpx" ? HwpxLibRow : TxtLibRow;
  if (!total) {
    return h("div", { className: "muted", style: { padding: "var(--sp-8)" } }, emptyText);
  }
  /* 그룹 구획은 없다(U4 §2-30) — 백엔드가 언제나 평면 1구획으로 답한다(`grouped_view=False`).
     구획 구조는 스냅샷 계약이라 그대로 훑되 헤더는 그리지 않는다. */
  return h("div", { className: "tpl-grp-rows flat" },
    ...sections.flatMap((section: Obj) => (section.items || []).map((item: Obj) =>
      h(Row as any, { key: item.key, item, controller }))));
}

function BandCap(props: { label: string; band: Obj }): ReactNode {
  const { label, band } = props;
  return h("div", { className: "row", style: { marginBottom: "var(--sp-4)" } },
    h("span", { className: "cap" }, label),
    band.count ? h("span", { className: "muted capnote" }, `${band.count}개`) : null,
    band.dir ? h("span", {
      className: "muted capnote mono", title: band.dir,
      style: {
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "22em",
      },
    }, band.dir) : null);
}

/** 검토가 낸 구간 항목(Slot) 목록 + 행 동사 3종(S8-03 #834) + 밴드 동사 1종(U4-E3 #939).
 *
 *  목록·요약·진단은 Python 투영 그대로 그린다(판정 재조립 금지). 진단이 있으면 목록 대신
 *  사유가 서고 동사 버튼은 아예 없다 — 못 믿는 구조 위에서 변이를 권하지 않는다.
 *
 *  밴드 동사 「전부 표기로 되돌리기」의 노출 술어는 **행 동사와 글자 그대로 같다**(진단 0 ·
 *  행 1건 이상). 개수 문턱(2건 이상)을 새로 두지 않는 이유는 둘이다: 그러면 「진단 0」 하나로
 *  서 있던 노출 규칙이 두 개로 갈리고, 두 항목을 하나씩 풀다 1건이 남는 순간 버튼이 손 밑에서
 *  사라진다. 1건일 때 효과가 행 동사와 같아도 **대상 축이 다르다** — 확인 본문이 항목이 아니라
 *  파일 전체를 말한다. */
function SlotBand(props: { slots: Obj; controller: EditorController }): ReactNode {
  const { slots, controller } = props;
  const rows = (slots.rows || []) as Obj[];
  const diagnostics = (slots.diagnostics || []) as string[];
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
  return h("div", { className: "grp", id: "tplSlots" },
    h("div", { className: "row", style: { marginBottom: "var(--sp-4)" } },
      h("span", { className: "cap" }, "구간 항목"),
      h("span", { className: "muted capnote" }, String(slots.name || "")),
      h("span", { className: "muted capnote" }, String(slots.summary || "")),
      bandVerb),
    ...diagnostics.map((text, index) =>
      h("div", { className: "hint danger", key: `diag-${index}` }, text)),
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

/** 이 세션이 연 템플릿의 구간(항목·선택) 축 요약 — **읽기 전용**(U4-E2 #939).
 *
 *  `SlotBand`(tpl 검토)와 값의 모양은 같지만 동사가 없다: 편집기는 저장 전 초안 세션이라
 *  템플릿 파일을 변이시키지 않는다. 요약 문자열·행·진단은 Python 투영 그대로 그린다 —
 *  여기서 개수를 다시 세지 않는다. 진단이 있으면 목록 대신 사유가 선다(진단 우선).
 *  존 자체의 유무는 판정이 아니다: 스냅샷이 `null` 이면 서지 않는다. */
function TemplateSlotSummary(props: { slots: Obj }): ReactNode {
  const { slots } = props;
  const rows = (slots.rows || []) as Obj[];
  const diagnostics = (slots.diagnostics || []) as string[];
  return h("div", { className: "grp", id: "editorSlotSummary" },
    h("div", { className: "row", style: { marginBottom: "var(--sp-4)" } },
      h("span", { className: "cap" }, "구간 항목"),
      h("span", { className: "muted capnote" }, String(slots.summary || ""))),
    ...diagnostics.map((text, index) =>
      h("div", { className: "hint danger", key: `diag-${index}` }, text)),
    ...(diagnostics.length ? [] : rows.map((row) => h("div", {
      className: "slotrow", key: String(row.id), "data-slot": String(row.id),
    },
    h("span", { className: "fname" }, String(row.label || row.id)),
    h("span", { className: "tbadge", title: (row.options || []).join(" · ") },
      `선택 ${row.option_count}`)))));
}

function LibraryPicker(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const library = snapshot.library || {};
  const hwpx = library.hwpx || {};
  const txt = library.txt || {};
  const result = library.result || {};
  const slots = library.slots || null;
  return createElement(Fragment, null,
    /* 가져오기는 hwpx·txt 겸용(확장자가 매체 라우팅)이라 밴드 밖 공용 줄에 둔다. */
    h("div", { className: "row", style: { marginBottom: "var(--sp-4)" } },
      h("button", {
        className: "btn sm", "data-act": "import-template",
        onClick: () => controller.guarded(() => controller.importTemplate()),
      }, "가져오기…"),
      h("button", {
        className: "btn sm", "data-act": "lib-new-txt",
        onClick: (event: Obj) => controller.openTxtEdit("new", "", "", "", event.currentTarget),
      }, "새 TXT 템플릿…"),
      h("span", { className: "spacer" }),
      h("button", {
        className: "btn sm", "data-act": "lib-refresh", title: "라이브러리 폴더를 다시 읽습니다",
        onClick: () => controller.guarded(() => controller.refreshLibrary()),
      }, "새로고침")),
    h("div", { className: "grp" },
      h(BandCap as any, { label: "HWPX 서식", band: hwpx }),
      h("p", { className: "note quiet", style: { marginTop: 0 } },
        "누름틀에 채운 .hwpx 문서 파일을 만드는 작업입니다."),
      h(LibraryBand as any, {
        band: hwpx, media: "hwpx", controller,
        /* 빈 사유는 **Python 이 낸다**(U6-A #975 — 링1 `empty_hint`): 미지정·폴더 없음·빈
           폴더는 서로 다른 사유이고, 여기서 한 문장으로 접으면 사라진 폴더가 「비었다」로
           읽힌다. 스냅샷이 아직 없을 때만 이 자리 문안이 선다. */
        emptyText: String(hwpx.empty_hint || "라이브러리에 템플릿이 없습니다. '가져오기…'로 추가하세요."),
      })),
    h("div", { className: "grp" },
      h(BandCap as any, { label: "TXT 기안", band: txt }),
      h("p", { className: "note quiet", style: { marginTop: 0 } },
        "채운 본문을 검토하고 복사해 쓰는 작업입니다. 파일은 만들지 않습니다."),
      h(LibraryBand as any, {
        band: txt, media: "txt", controller,
        emptyText: String(txt.empty_hint || "TXT 기안 템플릿이 없습니다. '새 TXT 템플릿…'으로 만들거나 '가져오기…'로 추가하세요."),
      })),
    slots ? h(SlotBand as any, { slots, controller }) : null,
    result.text ? h("div", {
      className: `run-result${result.level && result.level !== "muted" ? " " + result.level : ""}`,
    }, result.text) : null);
}

function SchemaTable(props: { snapshot: Obj }): ReactNode {
  const { snapshot } = props;
  return h("div", null,
    h("p", { className: "fields-head" }, snapshot.schema_summary),
    h("div", { className: "tblwrap" },
      h("table", { className: "schema-fields" },
        h("thead", null, h("tr", null,
          h("th", null, "필드"), h("th", null, "추정 타입"), h("th", null, "위치"), h("th", null, "문맥"))),
        h("tbody", null, ...(snapshot.fields || []).map((field: Obj, index: number) =>
          h("tr", { key: index },
            h("td", null, h("span", { className: "fname" }, field.name)),
            h("td", null, h("span", { className: "tbadge" },
              INFERRED_LABEL[field.inferred_type] || field.inferred_type || "")),
            h("td", { className: "muted" }, field.in_table ? "표 안" : "본문"),
            h("td", { className: "fctx" }, field.context
              ? h("span", { title: field.context }, field.context)
              : h("span", { className: "pv emptyval" }, "—"))))))));
}

function Provenance(props: { snapshot: Obj }): ReactNode {
  const { snapshot } = props;
  const provenance = snapshot.provenance;
  if (!provenance) return null;
  const when = provenance.updated_at
    ? (provenance.authored_at && provenance.authored_at !== provenance.updated_at
      ? `작성 ${provenance.authored_at} · 갱신 ${provenance.updated_at}`
      : `작성 ${provenance.updated_at}`)
    : "";
  const line = (label: string, value: unknown): ReactNode => value
    ? h("div", { className: "hint", style: { marginTop: 0 }, key: label },
      h("b", null, label), " ", String(value))
    : null;
  const fields = (snapshot.fields || []) as Obj[];
  const drift = provenance.template_fields && fields.length
    && provenance.template_fields !== fields.map((field) => field.name).join(" · ");
  return h("div", { className: "grp" },
    h("span", { className: "cap" }, "작성 출처"),
    line("템플릿", provenance.template),
    line("데이터", provenance.dataset),
    line("템플릿 필드", provenance.template_fields),
    line("데이터 열", provenance.source_keys),
    when ? h("div", { className: "hint muted", style: { marginTop: 0 } }, when) : null,
    drift ? h("div", { className: "hint danger", style: { marginTop: "var(--sp-4)" } },
      "⚠ 작성 당시와 템플릿 필드 구성이 다릅니다. 매핑 재검토가 필요할 수 있습니다.") : null);
}

function TemplateStage(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  let gate: ReactNode = null;
  if (snapshot.raw_block) {
    gate = h("p", { className: "note dangerbox", style: { whiteSpace: "pre-line" } }, snapshot.raw_block);
  } else if (snapshot.gate_error) {
    gate = h("p", { className: "note dangerbox" }, "템플릿 상태를 확인할 수 없습니다. 진행할 수 없습니다.");
  } else if (snapshot.field_count) {
    gate = h("div", null,
      h(SchemaTable as any, { snapshot }),
      snapshot.gate ? h("div", { className: "note warnbox", style: { whiteSpace: "pre-line" } },
        snapshot.gate.message) : null,
      snapshot.gate && !snapshot.gate.acked ? h("button", {
        className: "btn", "data-act": "ack-gate",
        onClick: () => controller.guarded(() => controller.sendEdit("ack_gate", {})),
      }, `비우고 진행 확인 (${snapshot.gate.unmet.length}개 토큰)`) : null);
  }
  return h("div", null,
    h("div", { className: "wtitle" }, stageTitle(snapshot, "template")),
    h("p", { className: "wsub" }, "만들 작업의 템플릿을 고르세요."),
    h(LibraryPicker as any, { snapshot, controller }),
    snapshot.template_name ? h("div", { className: "row" },
      h("span", { className: "lbl" }, "선택한 템플릿"),
      h("span", { className: "filechip" }, h("b", null, snapshot.template_name)),
      h(PathActions as any, {
        client: controller.client, path: snapshot.template_path, notify: controller.notify,
      })) : null,
    snapshot.template_name ? h(Provenance as any, { snapshot }) : null,
    gate,
    snapshot.template_slots
      ? h(TemplateSlotSummary as any, { slots: snapshot.template_slots }) : null);
}

function DataGateway(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const has = !!snapshot.data_path;
  return h("div", { className: "row gateway" },
    h("span", { className: "lbl" }, "이 작업의 데이터"),
    has
      ? h("span", { className: "filechip" }, h("b", null, snapshot.data_name),
        snapshot.data_sheet ? h("span", { className: "sheet" }, ` 시트: ${snapshot.data_sheet}`) : null)
      : null,
    h("button", {
      className: has ? "btn" : "btn primary", "data-act": "pick-data",
      onClick: () => controller.guarded(() => controller.pickData()),
    }, has ? "바꾸기…" : "파일 선택…"),
    snapshot.pool_enabled ? h("button", {
      className: "btn", "data-act": "pick-pool-data",
      onClick: () => controller.guarded(() => controller.openPoolData()),
    }, "등록 데이터에서 고르기…") : null,
    has ? h(PathActions as any, {
      client: controller.client, path: snapshot.data_path, notify: controller.notify,
    }) : null);
}

/** 고정해 둔 데이터 목록(#932 U4-C S2-5) — 쓸 수 없는 항목도 **숨기지 않고** 비활성 + 사유.
 *
 *  판정도 사유 문구도 Python 이 낸 값을 그대로 든다(`usable`·`reason`). 여기서 `kind` 나
 *  상태로 문장을 다시 지으면 같은 상태가 두 어휘를 갖는다. */
function PoolPickList(props: { view: ViewState; controller: EditorController }): ReactNode {
  const { view, controller } = props;
  if (view.poolPick === null) return null;
  const items = view.poolPick.items;
  const corrupted = view.poolPick.corrupted;
  return h("div", { className: "grp", id: "editorPoolPick" },
    h("div", { className: "row", style: { marginBottom: "var(--sp-4)" } },
      h("span", { className: "cap" }, "고정한 데이터"),
      h("span", { className: "spacer" }),
      h("button", {
        className: "btn sm", "data-act": "pool-pick-close",
        onClick: () => controller.guarded(() => Promise.resolve(controller.closePoolData())),
      }, "닫기")),
    items.length
      ? h("div", { className: "tpllist" }, ...items.map((item: Obj) => h("div", {
        className: "tplcard", "data-pool-row": String(item.key), key: String(item.key),
      },
      h("div", { className: "tplcard-top" },
        h("span", { className: "tplcard-name", title: String(item.reference || "") },
          String(item.name))),
      h("div", { className: "tplcard-meta muted" }, String(item.reference || "")),
      item.usable ? null : h("div", { className: "tplcard-meta muted" },
        h("span", { className: "pk-note" }, String(item.reason))),
      h("div", { className: "tplcard-acts" },
        h("button", {
          className: "btn sm primary", "data-act": "use-pool-data",
          "data-key": String(item.key),
          disabled: !item.usable, title: item.usable ? "" : String(item.reason),
          onClick: () => controller.guarded(() => controller.usePoolData(String(item.key))),
        }, "이 데이터 연결")))))
      : h("p", { className: "muted capnote" },
        "고정한 데이터가 없습니다. '파일 선택…'으로 고른 뒤 '문서 만들기'에서 고정하세요."),
    ...corrupted.map((entry: Obj) => h("div", {
      className: "note dangerbox", key: String(entry.file),
    }, `손상된 등록 데이터: ${entry.file} (${entry.error})`)));
}

function HeaderSelect(props: { snapshot: Obj; view: ViewState; controller: EditorController }): ReactNode {
  const { snapshot, view, controller } = props;
  const all = (snapshot.source_fields || []) as string[];
  if (!all.length || !snapshot.record_count) return null;
  const active = new Set((snapshot.active_source_fields || []) as string[]);
  const ignored = (snapshot.ignored_source_fields || []) as string[];
  const activeChips = all.filter((field) => active.has(field));
  return h("div", { className: "grp" },
    h("div", { className: "row", style: { marginBottom: "var(--sp-4)" } },
      h("span", { className: "cap" }, "사용할 데이터 열"),
      h("span", { className: "muted", style: { marginLeft: "var(--sp-8)" } },
        `${all.length}개 중 ${snapshot.active_count}개 사용`),
      h("span", { className: "spacer" }),
      snapshot.ignored_count ? h("button", {
        className: "btn sm", "data-act": "use-all-headers",
        onClick: () => controller.guarded(() => controller.sendEdit("use_all_headers", {})),
      }, "전체 사용") : null,
      h("button", {
        className: "btn sm", "data-act": "use-none",
        onClick: () => controller.guarded(() => controller.useNone()),
      }, "전체 미사용")),
    h("div", { className: "hchips" },
      ...(activeChips.length
        ? activeChips.map((field) => h("button", {
          className: "hchip on", "data-act": "toggle-header", "data-field": field, key: field,
          title: "클릭 = 미사용으로",
          onClick: () => controller.guarded(() => controller.sendEdit("toggle_source_active", { field })),
        }, field))
        : [h("span", { className: "muted", key: "none" },
          "사용 중인 데이터 열이 없습니다. 아래 미사용 목록에서 골라 켜세요.")])),
    ignored.length ? h("details", {
      className: "hidden-hdrs ign-fold",
      open: !!(snapshot.ignored_expanded || view.foldOpen),
      onToggle: (event: Obj) => controller.setFold(!!event.currentTarget.open),
    },
    h("summary", null, `미사용 ${ignored.length}개 (펼쳐 다시 사용)`),
    h("div", { className: "hchips" },
      ...ignored.map((field) => h("button", {
        className: "hchip ign", "data-act": "toggle-header", "data-field": field, key: field,
        title: "클릭 = 다시 사용",
        onClick: () => controller.guarded(() => controller.sendEdit("toggle_source_active", { field })),
      }, field))),
    h("p", { className: "hint", style: { marginTop: "var(--sp-4)" } },
      "미사용 데이터 열은 자동 매핑 제안·소스 후보에서 빠집니다.")) : null);
}

function OwnerTag(props: { row: Obj; snapshot: Obj }): ReactNode {
  const { row, snapshot } = props;
  if (row.confirmed) return h("span", { className: "tag conf" }, "확정");
  if (row.touched) return h("span", { className: "tag man" }, "수동");
  if (row.source) return h("span", { className: "tag sugg" }, "제안");
  return h("span", { className: "tag none" }, snapshot.record_count ? "후보 없음" : "—");
}

function MapRow(props: {
  row: Obj; snapshot: Obj; draft: DraftState; controller: EditorController;
}): ReactNode {
  const { row, snapshot, draft, controller } = props;
  const index = Number(row.index);
  const candidates = (snapshot.active_source_fields || snapshot.source_fields || []) as string[];
  const sourceValue = valueOf(draft, rowField(index, "source"));
  const known = candidates.includes(sourceValue);
  const sourceOptions: ReactNode[] = [h("option", { value: "", key: "" }, "(비움)")];
  for (const field of candidates) {
    sourceOptions.push(h("option", { value: field, title: field, key: field }, field));
  }
  /* 현재 데이터에 없는 소스를 (비움)으로 오표시하지 않고 명시 옵션으로 드러낸다. */
  if (sourceValue && !known) {
    sourceOptions.push(h("option", {
      value: sourceValue, title: "현재 데이터에 없는 소스", key: `missing:${sourceValue}`,
    }, `${sourceValue} (데이터에 없음)`));
  }
  const typeValue = valueOf(draft, rowField(index, "type"));
  const formats = ((snapshot.fmt_options || {})[typeValue] || []) as Obj[];
  const preview = row.preview_error
    ? h("span", { className: "pv emptyval" }, "(미리보기 오류)")
    : (row.preview_empty
      ? h("span", { className: "pv emptyval" }, "(이 행에서 빈 값)")
      : h("span", { className: "pv" }, row.preview));
  /* 행 상태 class 는 **닫힌 집합**이다(Python `screen_editor.py` 가 넷 중 하나를 낸다).
     보간으로 지으면 이름이 코드에 안 남아 CSS 고아 검사가 이 자리를 통째로 건너뛴다 —
     넷을 리터럴로 적어 그 검사에 들게 하고, 계약 밖 값은 조용히 무-class 로 접지 않는다. */
  const rowClass = ROW_STATE_CLASS[String(row.row_state)];
  if (rowClass === undefined) throw new Error(`알 수 없는 행 상태: ${row.row_state}`);
  return h("tr", { className: rowClass, "data-field": row.template_field, key: index },
    h("td", null, h("input", {
      type: "checkbox", className: "cbx", "data-act": "row-confirm", "data-index": index,
      checked: !!row.confirmed,
      onChange: (event: Obj) => controller.guarded(() => controller.sendEdit(
        "set_confirmed", { index, confirmed: !!event.currentTarget.checked })),
    })),
    h("td", null,
      h("span", { className: "fname", title: row.context || row.template_field }, row.template_field),
      h("span", { className: "tbadge" },
        `[추정: ${INFERRED_LABEL[row.inferred_type] || row.inferred_type || ""}]`)),
    h("td", null, h("div", { className: "srcwrap" },
      h("select", {
        className: "sel", "data-act": "row-source", "data-index": index, value: sourceValue,
        onChange: (event: Obj) => controller.commitRow(index, "source", String(event.currentTarget.value)),
      }, ...sourceOptions),
      /* 수동·미확정 행만 자동 제안 복귀(↻) — 확정 행은 제외(확정 해제가 의식적 1단계). */
      row.touched && !row.confirmed && snapshot.record_count ? h("button", {
        className: "btn icon", "data-act": "revert-source", "data-index": index,
        title: "자동 제안으로 되돌리기", "aria-label": "이 행 자동 제안 다시 받기",
        onClick: () => controller.guarded(() => controller.sendEdit("revert_source", { index })),
      }, "↻") : null)),
    h("td", null,
      h("select", {
        className: "sel", "data-act": "row-type", "data-index": index, value: typeValue,
        onChange: (event: Obj) => controller.commitRow(index, "type", String(event.currentTarget.value)),
      }, ...((snapshot.type_options || []) as string[]).map((type) =>
        h("option", { value: type, key: type }, TYPE_LABEL[type] || type))),
      " ",
      typeValue === "const" ? h("input", {
        className: "sel", "data-act": "row-const", "data-index": index, placeholder: "고정값",
        value: valueOf(draft, rowField(index, "const")),
        onChange: (event: Obj) => controller.type(rowField(index, "const"), String(event.currentTarget.value)),
        onFocus: () => controller.focus(rowField(index, "const"), true),
        onBlur: () => {
          controller.focus(rowField(index, "const"), false);
          controller.commitRowOnBlur(index, "const");
        },
        onCompositionStart: () => controller.compose(rowField(index, "const"), true),
        onCompositionEnd: () => controller.compose(rowField(index, "const"), false),
      }) : null),
    h("td", null, h("select", {
      className: "sel", "data-act": "row-fmt", "data-index": index,
      value: valueOf(draft, rowField(index, "fmt")), disabled: !formats.length,
      onChange: (event: Obj) => controller.commitRow(index, "fmt", String(event.currentTarget.value)),
    }, ...(formats.length
      ? formats.map((format) => h("option", { value: format.code, key: format.code }, format.label))
      : [h("option", { value: "", key: "" }, "—")]))),
    h("td", null, preview),
    h("td", null, h(OwnerTag as any, { row, snapshot })));
}

function MappingStage(props: {
  snapshot: Obj; draft: DraftState; view: ViewState; controller: EditorController;
}): ReactNode {
  const { snapshot, draft, view, controller } = props;
  const rows = (snapshot.rows || []) as Obj[];
  const counts = snapshot.counts;
  const emptyNote = snapshot.preview_empties && snapshot.preview_empties.length
    ? ` (${snapshot.preview_empties.join(", ")})` : "";
  return h("div", null,
    h("div", { className: "wtitle" }, stageTitle(snapshot, "binding")),
    h("p", { className: "wsub" }, "필드마다 데이터 열을 지정하고 전 행을 확정하세요."),
    h(DataGateway as any, { snapshot, controller }),
    h(PoolPickList as any, { view, controller }),
    h(HeaderSelect as any, { snapshot, view, controller }),
    /* 처방은 **저장 게이트와 같은 말**이어야 한다(#945 F8). U4-C 이후 데이터 연결은 저장의
       하드 게이트라(`gui/job_editor_state.validate_save`), 종전의 "고정값을 넣거나 비움으로
       확정하세요"는 그대로 따라도 저장이 막히는 거짓 처방이었다. 같은 상태를 두 어휘로
       판정하지 않는다 — 여기서 말하는 것은 그 게이트의 사실과 고칠 자리(바로 위 관문)다. */
    snapshot.schema_only ? h("p", { className: "note warnbox" },
      "데이터를 연결하지 않아 지금은 저장할 수 없습니다. 위 '이 작업의 데이터'에서 데이터를 고르세요.") : null,
    h("div", { className: "tblwrap" }, h("table", { className: "map" },
      h("thead", null, h("tr", null,
        h("th", null, "확정"), h("th", null, "템플릿 필드 · 추정"), h("th", null, "데이터 열"),
        h("th", null, "타입 / 고정값"), h("th", null, "표시형"), h("th", null, "미리보기"),
        h("th", null, "상태"))),
      h("tbody", null, ...rows.map((row) =>
        h(MapRow as any, { key: row.index, row, snapshot, draft, controller }))))),
    h("div", { className: "stepper" },
      snapshot.preview_count
        /* `.stepper` 는 flex 다 — 셋을 감싸면 세 항목이 하나가 돼 간격이 무너진다. */
        ? createElement(Fragment, null,
          h("button", {
            className: "btn sm", "data-act": "prev-rec",
            onClick: () => controller.guarded(() => controller.sendEdit("step_preview", { delta: -1 })),
          }, "◀ 이전 행"),
          h("span", { className: "mono" }, `행 ${snapshot.preview_index}/${snapshot.preview_count}`),
          h("button", {
            className: "btn sm", "data-act": "next-rec",
            onClick: () => controller.guarded(() => controller.sendEdit("step_preview", { delta: 1 })),
          }, "다음 행 ▶"))
        : h("span", { className: "muted" }, "행 0/0 · 데이터 없음(템플릿 필드만)"),
      h("span", { className: "spacer" }),
      counts ? h("span", { className: "muted" },
        `채움 ${counts.filled} · 빈 값 ${counts.empty} · 미매핑 ${counts.unmapped}${emptyNote}`) : null),
    h("div", { className: "gate" },
      h("span", { className: `gatecount ${snapshot.is_complete ? "ok" : "pend"}` },
        `확정 ${rows.filter((row) => row.confirmed).length}/${rows.length}`),
      h("span", { className: "spacer" }),
      h("button", {
        className: "btn", "data-act": "confirm-all",
        onClick: () => controller.guarded(() => controller.confirmAll()),
      }, "모두 확정"),
      h("button", {
        className: "btn", "data-act": "unconfirm-all",
        onClick: () => controller.guarded(() => controller.sendEdit("unconfirm_all", {})),
      }, "모두 해제"),
      h("button", {
        className: "btn", "data-act": "resuggest-all",
        onClick: () => controller.guarded(() => controller.resuggestAll()),
      }, "자동 제안 다시 받기"),
      snapshot.unconfirm_undo_count ? h("button", {
        className: "btn", "data-act": "restore-confirmed",
        onClick: () => controller.guarded(() => controller.sendEdit("restore_confirmed", {})),
      }, `직전 확정 ${snapshot.unconfirm_undo_count}개 복원`) : null),
    h(DataPreview as any, { snapshot }));
}

function DataPreview(props: { snapshot: Obj }): ReactNode {
  const { snapshot } = props;
  if (!snapshot.record_count) return null;
  const all = (snapshot.source_fields || []) as string[];
  const active = new Set((snapshot.active_source_fields || all) as string[]);
  const columns = all.map((name, index) => ({ name, index })).filter((column) => active.has(column.name));
  const sample = (snapshot.sample_rows || []) as any[][];
  const hidden = all.length - columns.length;
  const columnNote = hidden
    ? ` · 열 ${columns.length}/${all.length} (미사용 ${hidden}열 제외)`
    : ` · 전체 ${all.length}열`;
  return h("div", null,
    h("p", { className: "fields-head" }, `${snapshot.record_count}행 불러옴${columnNote}.`),
    h("div", { className: "tblwrap" }, h("table", { className: "data-preview" },
      h("thead", null, h("tr", null, ...columns.map((column) =>
        h("th", { title: column.name, key: column.name }, column.name)))),
      h("tbody", null, ...sample.map((row, rowIndex) =>
        h("tr", { key: rowIndex }, ...columns.map((column) => {
          const value = row[column.index];
          return h("td", { key: column.name }, (value === "" || value === null || value === undefined)
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

function FilenameStage(props: {
  snapshot: Obj; draft: DraftState; view: ViewState; controller: EditorController;
}): ReactNode {
  const { snapshot, draft, view, controller } = props;
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
      "이 작업이 만드는 파일의 이름 규칙입니다. HWPX 작업의 영구 규칙이고, 이번 생성에서만 쓸 값은 여기 두지 않습니다."),
    h("div", { className: "row" },
      h("span", { className: "lbl lbl-fixed" }, "파일명 패턴"),
      h("input", {
        className: "field mono", "data-act": "pattern", value: valueOf(draft, PATTERN_FIELD),
        "aria-invalid": view.invalidField === PATTERN_FIELD ? "true" : undefined,
        onChange: (event: Obj) => controller.type(PATTERN_FIELD, String(event.currentTarget.value)),
        onFocus: () => controller.focus(PATTERN_FIELD, true),
        onBlur: () => { controller.focus(PATTERN_FIELD, false); controller.commitField(PATTERN_FIELD); },
        onCompositionStart: () => controller.compose(PATTERN_FIELD, true),
        onCompositionEnd: () => controller.compose(PATTERN_FIELD, false),
      })),
    snapshot.pattern_preview ? h("p", { className: "hint mono", style: { marginTop: 0 } },
      `예: ${snapshot.pattern_preview}${snapshot.record_count ? " (표본 1행 기준)" : ""}`) : null,
    h("details", {
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
      h("code", null, "{{seq:001}}"), " → 001부터 세 자리로 증가")));
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
    /* 연결 확정 대기(#911)는 무장 사유를 **더한다**. 판정·라벨·설명은 Python 이 실어 보낸
       것을 그대로 읽는다 — 「저장 안 됨」 같은 인접 사실로 확정 필요를 여기서 추론하지 않는다.
       바꿀 것이 없는데 관리 검토가 확정을 기다리면 dirty 는 영영 거짓이고, 그 상태에서
       두 동사가 모두 잠겨 사슬을 닫을 길이 없었다. 버리기는 그대로 dirty 술어다(확정
       대기는 버릴 것을 만들지 않는다). 라벨이 갈리는 자리는 **무변경 확정 하나**다:
       손댄 것이 있으면 그 저장이 확정도 겸하므로 「변경 저장」이 여전히 참말이다. */
    const confirm = (snapshot.binding_confirm || {}) as Obj;
    const confirmPending = !!confirm.pending;
    const confirmOnly = confirmPending && !armed;
    return h("footer", { className: "wfoot", id: "editor-foot" },
      h("button", {
        className: "btn", "data-act": "discard-patch", disabled: !armed,
        onClick: () => controller.guarded(() => controller.discardPatch()),
      }, "변경 버리기"),
      h("span", { className: "spacer" }),
      confirmPending
        ? h("span", { className: "muted capnote", "data-role": "binding-confirm-hint" },
          String(confirm.hint || ""))
        : null,
      h("button", {
        className: "btn primary", "data-act": "save",
        "data-confirm-binding": confirmOnly ? "1" : null,
        disabled: !(armed || confirmPending),
        onClick: () => controller.guarded(() => controller.doSave({})),
      }, confirmOnly ? String(confirm.label || "") : "변경 저장"));
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
        className: "btn primary", "data-act": "save",
        onClick: () => controller.guarded(() => controller.doSave({})),
      }, "작업 저장")
      : h("button", {
        className: "btn primary", "data-act": "next", disabled: !can,
        onClick: () => controller.guarded(() => controller.gotoSection(controller.neighbour(1))),
      }, "다음 ▶"));
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

  /* 조준은 렌더 **뒤**에 — 커밋 전에는 겨눌 노드가 아직 없다. */
  useEffect(() => { controller.consumeAim(); });

  if (snapshot === null) {
    return h("div", { className: "editor-shell" },
      h("p", { className: "note", role: "status" }, "편집기를 읽는 중…"));
  }
  let body: ReactNode;
  if (snapshot.section === "template") body = h(TemplateStage as any, { snapshot, controller });
  else if (snapshot.section === "binding") body = h(MappingStage as any, { snapshot, draft, view, controller });
  else body = h(FilenameStage as any, { snapshot, draft, view, controller });
  return h("div", { className: "editor-shell" },
    h("button", {
      className: "btn sm back", id: "editorBack", type: "button",
      onClick: () => controller.guarded(() => controller.leaveTo(controller.returnScreen())),
    }, "← 원래 업무로 돌아가기"),
    h(EditorHead as any, { snapshot, draft, view, controller }),
    h(ContextBanner as any, { snapshot, controller }),
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
