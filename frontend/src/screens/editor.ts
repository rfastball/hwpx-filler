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
import { createElement, Fragment, useEffect, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

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
import { PathActions } from "./path_actions.ts";
import type { GroupMoveDialogController } from "./group_move_dialog.ts";
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
  choose(spec: Obj): Promise<string | null>;
  open(id: string, spec?: Obj): void;
  close(id: string): void;
};

type UndoPort = { show(message: string, action: () => unknown): void };
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
  undo: UndoPort;
  popover: ContextMenuPopoverPort;
  groupMove: GroupMoveDialogController;
  chain: ChainPort;
  navigation: { go(screen: string, options?: Obj): void; refresh(screen: string): Promise<unknown> };
  notify(message: string): void;
};

const SCREEN = "editor";
const EDIT_CHAIN = "editor:mutate";

/* 표시형·타입 라벨은 표현 계층이라 여기 산다(Qt mapping_table 의 웹 짝). */
const TYPE_LABEL: Record<string, string> = {
  text: "텍스트", date: "날짜", amount: "금액", const: "고정값",
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
  preview_result: "미리보기에서 열었습니다.",
  run_failure: "생성 실패 결과에서 열었습니다.",
  output_result: "생성 결과에서 열었습니다.",
  document_browser_repair: "실행을 막는 문제를 고치러 열었습니다.",
  document_browser_new_work: "고른 데이터로 새 작업을 시작합니다.",
};
const RETURN_LABEL: Record<string, string> = {
  data: "문서 만들기로 돌아가기", preview: "미리보기로 돌아가기",
  result: "결과로 돌아가기", library: "「문서 작업」으로 돌아가기",
  documents: "문서 탐색으로 돌아가기",
};
/* 복귀처 — 진입 문맥이 말한 표면(계약 §8). 없으면 「문서 만들기」다. */
const RETURN_SCREEN: Record<string, string> = {
  data: "job", preview: "job", result: "job", documents: "job", library: "library",
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
};

type LibMenu = {
  media: string;
  kind: "row" | "group";
  key?: string;
  group?: string;
  item?: Obj | null;
  trigger: HTMLElement;
};

type ViewState = {
  libMenu: LibMenu | null;
  folderImportInFlight: boolean;
  txtEdit: TxtEditState | null;
  foldOpen: boolean;
  tokFoldOpen: boolean;
  saveMessage: { text: string; level: string } | null;
  invalidField: string;
  aim: string;
  /** 이 문맥에서 이미 겨눈 목표 — 문맥당 한 번만 조준한다. */
  aimed: string;
};

const isEditing = (snapshot: Obj): boolean => !!snapshot.editing_origin;

export function createEditorController(deps: EditorControllerDeps) {
  const model = deps.runtime.model<Obj | null>(SCREEN);

  let draft: DraftState = emptyDraft();
  let view: ViewState = {
    libMenu: null, folderImportInFlight: false, txtEdit: null,
    foldOpen: false, tokFoldOpen: false, saveMessage: null, invalidField: "", aim: "",
    aimed: "",
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
    if (screen === "tpl") await deps.runtime.refresh(SCREEN);
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
    if (view.invalidField !== "" && field === view.invalidField) patchView({ invalidField: "" });
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

  function openLibMenu(media: string, kind: "row" | "group", id: string, trigger: HTMLElement): void {
    let items: ContextMenuItem[];
    if (kind === "group") {
      items = [
        { action: "grp-rename", label: "그룹 이름 변경" },
        { action: "grp-disband", label: "그룹 해산" },
      ];
      patchView({ libMenu: { media, kind, group: id, trigger } });
    } else {
      const item = findLibItem(media, id);
      /* 수선 동사의 목록·라벨은 링1 소유 — 스냅샷 actions 를 그대로 그린다(발명 금지). */
      const repairs = media === "hwpx"
        ? ((item && item.actions) || []).map((action: Obj) =>
          ({ action: `act:${String(action.key)}`, label: String(action.label) }))
        : (item && !item.error ? [{ action: "edit", label: "내용 편집" }] : []);
      items = [...repairs];
      if (item && item.group) {
        items.push({ action: "move", label: "그룹으로 이동…", separatorBefore: repairs.length > 0 });
      }
      items.push({
        action: "delete",
        label: "삭제",
        danger: true,
        separatorBefore: repairs.length > 0 && !(item && item.group),
      });
      patchView({ libMenu: { media, kind, key: id, item, trigger } });
    }
    libContextMenu.open(trigger, items);
  }

  function toggleLibMenu(media: string, kind: "row" | "group", id: string, trigger: HTMLElement): void {
    const open = view.libMenu;
    const same = open !== null && open.kind === kind && open.media === media &&
      (kind === "group" ? open.group === id : open.key === id);
    if (same) { closeLibMenu(); return; }
    openLibMenu(media, kind, id, trigger);
  }

  async function handleLibMenu(action: string): Promise<void> {
    const menu = view.libMenu;
    if (menu === null) return;
    closeLibMenu();
    try {
      if (action === "move") openLibMoveDialog(menu.media, menu.item || null, menu.trigger);
      else if (action === "delete") await deleteLibTemplate(menu.media, menu.item || null);
      else if (action === "grp-rename") await renameLibGroup(menu.media, menu.group || "", menu.trigger);
      else if (action === "grp-disband") await disbandLibGroup(menu.media, menu.group || "", menu.trigger);
      else if (action === "edit") {
        const item = menu.item || {};
        const result = await dispatch("tpl", "txt_content", { path: item.path });
        openTxtEdit("edit", item.path, item.name, String(result.content || ""), menu.trigger);
      } else if (action === "act:compile") await compileTemplate((menu.item || {}).path);
      else if (action === "act:review") await dispatch("tpl", "review", { path: (menu.item || {}).path });
    } catch (error) {
      deps.notify(String((error as Obj)?.message || error));
    }
  }

  /** 누름틀 변환 — CLI 2단계 미러(스캔 dry-run → 확인 왕복 → 제자리 적용). */
  async function compileTemplate(path: string): Promise<void> {
    const result = await dispatch("tpl", "compile", { path });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n지금 변환할까요?`,
      confirmLabel: "제자리 변환", cancelLabel: "취소", danger: true,
    })) {
      await dispatch("tpl", "compile", { path, confirm: true });
    }
  }

  function openLibMoveDialog(media: string, item: Obj | null, trigger: HTMLElement): void {
    if (item === null) return;
    const band = (snapshot().library || {})[media] || {};
    deps.groupMove.open({
      nameText: String(item.name || ""),
      groups: band.group_names || [],
      current: String(item.group || ""),
      returnFocus: trigger,
      onConfirm: (group) => dispatch("tpl", "set_group", { media, key: item.key, group })
        .catch((error) => deps.notify(String((error as Obj)?.message || error))),
    });
  }

  async function renameLibGroup(media: string, old: string, trigger: HTMLElement): Promise<void> {
    const value = await deps.modal.prompt({
      title: "그룹 이름 변경", body: `'${old}' 의 새 이름`, value: old, returnFocus: trigger,
    });
    if (value === null) return;
    const result = await dispatch("tpl", "rename_group", { media, group: old, new: value });
    if (result.needs_confirm) {
      if (await deps.modal.confirm({
        body: `'${result.new}' 그룹이 이미 있습니다. '${old}' 의 ${result.count}개를 '${result.new}'(${result.target}개)에 합칠까요?`,
        confirmLabel: "합치기", cancelLabel: "취소", returnFocus: trigger,
      })) {
        await dispatch("tpl", "rename_group", { media, group: old, new: value, confirm: true });
      }
    } else if (result.error) {
      deps.notify(String(result.error));
    }
  }

  async function disbandLibGroup(media: string, name: string, trigger: HTMLElement): Promise<void> {
    const result = await dispatch("tpl", "disband_group", { media, group: name });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `'${name}' 그룹을 해산하면 ${result.count}개가 '그룹 없음'으로 이동합니다. 해산할까요?`,
      returnFocus: trigger, confirmLabel: "해산", cancelLabel: "취소",
    })) {
      await dispatch("tpl", "disband_group", { media, group: name, confirm: true });
    }
  }

  async function deleteLibTemplate(media: string, item: Obj | null): Promise<void> {
    if (item === null) return;
    const result = await dispatch("tpl", "delete", { media, path: item.path });
    /* 「휴지통」이라 말하지 않는다(U2 §2.12) — 보존은 실재하나 도달 표면이 아직 없다. */
    if (result.undo) {
      deps.undo.show(`템플릿 '${item.name}' 을(를) 삭제했습니다.`, async () => {
        const restored = await dispatch("tpl", "undo_delete", {});
        if (restored.ok === false) throw new Error(String(restored.error));
      });
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
      error: "", allowClose: false,
    };
    patchView({ txtEdit: state });
    deps.modal.open("txtEditModal", {
      /* 초기 포커스는 여기서 넘기지 않는다 — 이 시점엔 창 내용이 아직 커밋 전이라 대상이
         없다. 겨눔은 `TxtEditDialog` 의 커밋 뒤 effect 가 진다. */
      returnFocus: trigger,
      beforeClose: () => {
        const current = view.txtEdit;
        if (current === null || current.allowClose || !txtDirty(current)) {
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

  async function submitTxtEdit(): Promise<void> {
    const current = view.txtEdit;
    if (current === null) return;
    try {
      if (current.mode === "new") {
        await dispatch("tpl", "txt_new", { name: current.name, content: current.content });
      } else {
        await dispatch("tpl", "txt_edit", { path: current.path, content: current.content });
      }
      patchTxtEdit({ allowClose: true });
      deps.modal.close("txtEditModal");
    } catch (error) {
      patchTxtEdit({ error: String((error as Obj)?.message || error) });
    }
  }

  /* ---- 확인 관문 ---- */

  /** 새 템플릿 진입 = 새 작업 세션 확인. 폐기 판정은 entry port 단일 출처. */
  async function confirmNewSessionIfUnsaved(): Promise<boolean> {
    const editing = snapshot().editing_origin;
    if (editing) {
      const busy = await invoke("editor_has_unsaved_work");
      if (!busy) return true;
      return deps.modal.confirm({
        body: `'${editing}' 편집을 닫고 새 작업 초안을 시작합니다.` +
          "\n저장하지 않은 변경은 사라집니다." +
          "\n\n계속할까요?",
        confirmLabel: "새 작업 시작", cancelLabel: "취소",
      });
    }
    return Boolean(await deps.ports.editorEntry.current().confirmDiscard(
      "새 템플릿으로 시작하면 저장하지 않은 작업 세션이 사라집니다.\n" +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?"));
  }

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

  function noticeSave(message: string, level?: string): void {
    if (snapshot().section === "filename") {
      patchView({ saveMessage: { text: message, level: level || "" } });
      return;
    }
    deps.notify(message);
  }

  /** 차단당한 칸으로 커서를 옮긴다 — 어느 칸인지는 Python 이 말한다. */
  function aimAtBlockedField(field: string): void {
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

  /** 탭 이동 — 처분 미확정 patch 는 Python 이 되돌리고 여기서 3택을 받는다(계약 §5.2). */
  async function gotoSection(target: string): Promise<void> {
    if (!target) return;
    await flushPendingEdits();
    const result = await sendEdit("goto_section", { section: target });
    if (!result.needs_section_guard) return;
    const choice = await deps.modal.choose({
      title: `「${result.section_label}」 에서 바꾼 내용이 있습니다`,
      body: "다른 탭으로 가기 전에 이 변경을 어떻게 할지 정하세요.\n" +
        "한 번에 한 곳만 고칩니다 — 저장하면 새 판본이 되고, 버리면 열었을 때 상태로 돌아갑니다.",
      choices: [
        { value: "save", label: "저장하고 이동" },
        { value: "discard", label: "버리고 이동" },
        { value: "stay", label: "머무르기" },
      ],
    });
    if (choice === "save") {
      if (!(await doSave({}))) return;         // 저장이 막혔으면 이동하지 않는다(문맥 보존)
    } else if (choice === "discard") {
      await sendEdit("discard_patch", { section: result.section });
    } else {
      return;                                  // 머무르기(Escape 포함)
    }
    await sendEdit("goto_section", { section: target, disposition: choice });
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

  /** 복귀 **상태**까지 되돌린다 — 면을 여는 절차는 그 화면이 소유한 seam 을 그대로 쓴다. */
  async function restoreReturnState(): Promise<void> {
    const context = snapshot().context || {};
    const ret = context.return_context || {};
    if (ret.surface === "preview" && ret.reopen_drawer) {
      await deps.ports.jobRun.current().openPreview({
        at: Number(ret.preview_index || 0),
        focusTarget: String(context.target || ""),
      });
    }
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

  /** 편집기를 나가는 **단일 출구** — 확인 전에는 draft 를 파기하지 않는다. */
  async function leaveTo(target: string): Promise<void> {
    await flushPendingEdits();
    const state = snapshot();
    /* 정산 뒤에도 스냅샷이 아니라 컨트롤러에게 묻는다 — 잃을 것이 있는지는 Python 이 지금 답한다. */
    let dirty = !!state.dirty;
    if (!dirty && !state.is_draft) {
      try {
        dirty = Boolean(await invoke("editor_has_unsaved_work"));
      } catch {
        dirty = true;    // 모르면 묻는다(확인-또는-경보의 안전 방향)
      }
    }
    if (dirty && !state.is_draft) {
      const choice = await deps.modal.choose({
        title: "저장하지 않은 변경이 있습니다",
        body: "편집기를 나가기 전에 이 변경을 어떻게 할지 정하세요."
          + "\n저장하면 새 판본이 되고, 버리면 열었을 때 상태로 돌아갑니다.",
        choices: [
          { value: "save", label: "저장하고 나가기" },
          { value: "discard", label: "버리고 나가기" },
          { value: "stay", label: "머무르기" },
        ],
      });
      if (choice === "save") {
        if (!(await doSave({}))) return;       // 저장이 막혔으면 나가지 않는다(문맥 보존)
      } else if (choice === "discard") {
        await sendEdit("discard_patch", {});
      } else {
        return;
      }
    } else if (state.is_draft) {
      const accepted = await deps.ports.editorEntry.current().confirmDiscard(
        "편집기를 나가면 저장하지 않은 새 작업이 사라집니다."
        + "\n사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?");
      if (!accepted) return;
      await sendEdit("new_session", {});       // 확인을 마쳤으면 실제로 폐기한다
    }
    if (!(await landOn(target))) return;
    if (target === returnScreen()) await restoreReturnState();
  }

  /* ---- 본문 행동 ---- */

  async function useLibraryTemplate(path: string): Promise<void> {
    if (!(await confirmNewSessionIfUnsaved())) return;
    await sendEdit("use_library_template", { path });
  }

  async function importTemplate(): Promise<void> {
    if (!(await confirmNewSessionIfUnsaved())) return;
    const result = await invoke("import_template_file", SCREEN);
    if (typeof result === "string" && result.startsWith("ERROR:")) {
      noticeSave(result.slice(6).trim());
      return;
    }
    if (typeof result === "string" && result !== "") await deps.runtime.refresh(SCREEN);
  }

  /** 폴더 일괄 가져오기 — 어포던스 잠금은 클릭을 삼키는 문이고, 정본 거절은 Python 이다. */
  async function importFolder(trigger: HTMLElement): Promise<void> {
    if (view.folderImportInFlight) return;
    patchView({ folderImportInFlight: true });
    try {
      const scanned = await invoke("import_templates_folder", null, false, null) as Obj;
      if (!scanned) return;                                    // 피커 취소
      if (scanned.error) { noticeSave(String(scanned.error)); return; }
      if (!scanned.needs_confirm) return;
      if (!(await deps.modal.confirm({
        body: `${scanned.confirm_text}\n\n지금 가져올까요?`,
        confirmLabel: "가져오기", cancelLabel: "취소", returnFocus: trigger,
      }))) return;
      /* 확정 실행은 **재진술된 후보 목록**을 그대로 나른다 — 재스캔이면 확인 안 된 파일이 따라 든다. */
      const done = await invoke(
        "import_templates_folder", scanned.folder, true, scanned.files) as Obj;
      if (done && done.error) noticeSave(String(done.error));
      else if (done) await deps.runtime.refresh(SCREEN);
    } finally {
      patchView({ folderImportInFlight: false });              // 어느 출구든 해제
    }
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
    }
  }

  async function skipData(): Promise<void> {
    if (!(await confirmMappingResetIfConfirmed("데이터 없이 진행하면"))) return;
    await sendEdit("skip_data", {});
  }

  async function useNone(): Promise<void> {
    /* 확정 존재는 확인 **전에** 선차단한다(파괴를 승인시킨 뒤 거부하는 순서 금지). */
    const stakes = await sendEdit("mapping_reset_stakes", {});
    if (stakes.confirmed) {
      deps.notify(`확정한 매핑 ${stakes.confirmed}개가 있어 전체 미사용을 할 수 없습니다. 확정을 먼저 해제하거나 칩을 하나씩 끄세요.`);
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
      deps.notify(`자동 제안을 다시 받을 행이 없습니다. 확정한 ${result.kept_confirmed}개는 그대로 둡니다.`);
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

  /** 변경 버리기 — 확인을 열기 **전에** 대기 중 편집을 정산한다. */
  async function discardPatch(trigger: HTMLElement): Promise<void> {
    await flushPendingEdits();
    if (!(await deps.modal.confirm({
      body: "이 편집에서 바꾼 내용을 버리고 저장된 상태로 되돌립니다.\n\n계속할까요?",
      returnFocus: trigger, confirmLabel: "변경 버리기", cancelLabel: "취소",
    }))) return;
    await sendEdit("discard_patch", {});
  }

  async function cancelNewDraft(trigger: HTMLElement): Promise<void> {
    const accepted = await deps.ports.editorEntry.current().confirmDiscard(
      "새 작업 만들기를 취소하면 입력한 이름 · 데이터 · 매핑이 사라집니다.\n\n계속할까요?", trigger);
    if (!accepted) return;
    await sendEdit("discard_session", {});
    /* 확인·폐기를 마쳤으니 이탈 가드를 다시 태우지 않는다 — 착지는 이탈과 **같은 절차**다. */
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
    type, focus, compose, commitField, commitRow, commitRowOnBlur,
    setFold(open: boolean): void { patchView({ foldOpen: open }); },
    setTokFold(open: boolean): void { patchView({ tokFoldOpen: open }); },
    toggleLibMenu, closeLibMenu, handleLibMenu,
    isLibMenuOpen: (): boolean => view.libMenu !== null,
    libContextMenu,
    openLibMoveDialog, findLibItem,
    openTxtEdit, patchTxtEdit, confirmDiscardTxtEdit, submitTxtEdit,
    /** 외부 FS 재스캔(tpl 채널) — push 가 재당김을 태워 목록·결과 줄이 되그려진다. */
    refreshLibrary: (): Promise<Obj> => dispatch("tpl", "refresh", {}),
    useLibraryTemplate, importTemplate, importFolder, pickData, skipData,
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
  const revisions = snapshot.revisions || {};
  const dirty = !!snapshot.dirty;
  const level = snapshot.is_draft ? "idle" : (dirty ? "warn" : "idle");
  const stateText = snapshot.is_draft
    ? "아직 저장하지 않은 새 작업"
    : (dirty ? "저장하지 않은 변경 · " : "저장됨 · ")
      + `템플릿 r${revisions.template || "?"} · 연결 r${revisions.binding || "?"}`;
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

function LibRowTail(props: { media: string; item: Obj; controller: EditorController }): ReactNode {
  const { media, item, controller } = props;
  /* legacy 는 두 버튼을 감싸지 않고 이어 붙였다 — 요소 트리에서 감싸면 `.libselrow` 의
     flex 자식 수가 바뀌어 배치가 달라진다. Fragment 는 DOM 노드를 만들지 않는다. */
  return createElement(Fragment, null,
    item.group ? null : h("button", {
      className: "tpl-assign", "data-act": "lib-assign", "data-media": media, "data-key": item.key,
      onClick: (event: Obj) => controller.openLibMoveDialog(
        media, controller.findLibItem(media, item.key), event.currentTarget),
    }, "＋ 그룹 지정"),
    h("button", {
      className: "job-more", "data-act": "lib-more", "data-media": media, "data-key": item.key,
      "aria-haspopup": "true", "aria-label": "항목 관리",
      onClick: (event: Obj) => controller.toggleLibMenu(media, "row", item.key, event.currentTarget),
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
  if (band.flat) {
    /* 퇴화 불변식(그룹 0개) — 헤더 없는 평면 나열. */
    return h("div", { className: "tpl-grp-rows flat" },
      ...sections.flatMap((section: Obj) => (section.items || []).map((item: Obj) =>
        h(Row as any, { key: item.key, item, controller }))));
  }
  /* 그룹 구획도 형제 나열이다(legacy `sections.map(...).join("")`). */
  return createElement(Fragment, null,
    ...sections.flatMap((section: Obj, index: number) => {
      const label = section.group || "그룹 없음";
      const head = h("div", { className: "job-grp", key: `head-${index}` },
        h("button", {
          className: "job-grp-head", id: `libgrp-${media}-${index}`,
          "data-act": "toggle-lib-group", "data-group": section.group, "data-media": media,
          "aria-expanded": section.collapsed ? "false" : "true",
          onClick: () => controller.guarded(() => controller.sendEdit(
            "toggle_library_group", { group: section.group, media })),
        },
        h("span", { className: "grp-name" }, label),
        h("span", { className: "grp-count" }, String(section.count)),
        h("span", { className: "grp-caret" }, section.collapsed ? "▸" : "▾")),
        /* 명명 그룹만 ⋮(이름 변경·해산). 「그룹 없음」은 관리 대상이 아니다. */
        section.group ? h("button", {
          className: "job-more grp-more", "data-act": "lib-grp-more", "data-media": media,
          "data-group": section.group, "aria-haspopup": "true", "aria-label": "그룹 관리",
          onClick: (event: Obj) => controller.toggleLibMenu(
            media, "group", section.group, event.currentTarget),
        }, "⋮") : null);
      if (section.collapsed) return [head];
      return [head, h("div", { className: "tpl-grp-rows", key: `rows-${index}` },
        ...(section.items || []).map((item: Obj) => h(Row as any, { key: item.key, item, controller })))];
    }));
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

function LibraryPicker(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const library = snapshot.library || {};
  const hwpx = library.hwpx || {};
  const txt = library.txt || {};
  const result = library.result || {};
  return createElement(Fragment, null,
    /* 가져오기는 hwpx·txt 겸용(확장자가 매체 라우팅)이라 밴드 밖 공용 줄에 둔다. */
    h("div", { className: "row", style: { marginBottom: "var(--sp-4)" } },
      h("button", {
        className: "btn sm", "data-act": "import-template",
        onClick: () => controller.guarded(() => controller.importTemplate()),
      }, "가져오기…"),
      h("button", {
        className: "btn sm", "data-act": "import-folder",
        onClick: (event: Obj) => controller.guarded(() => controller.importFolder(event.currentTarget)),
      }, "폴더에서 가져오기…"),
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
        emptyText: "라이브러리에 템플릿이 없습니다. '가져오기…'로 하나씩, '폴더에서 가져오기…'로 한꺼번에 추가하세요.",
      })),
    h("div", { className: "grp" },
      h(BandCap as any, { label: "TXT 기안", band: txt }),
      h("p", { className: "note quiet", style: { marginTop: 0 } },
        "채운 본문을 검토하고 복사해 쓰는 작업입니다. 파일은 만들지 않습니다."),
      h(LibraryBand as any, {
        band: txt, media: "txt", controller,
        emptyText: "TXT 기안 템플릿이 없습니다. '새 TXT 템플릿…'으로 만들거나 '가져오기…' 또는 '폴더에서 가져오기…'로 추가하세요.",
      })),
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
    gate);
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
    h("button", {
      className: "btn linklike", "data-act": "skip-data",
      onClick: () => controller.guarded(() => controller.skipData()),
    }, "데이터 없이 진행"),
    has ? h(PathActions as any, {
      client: controller.client, path: snapshot.data_path, notify: controller.notify,
    }) : null);
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
    h(HeaderSelect as any, { snapshot, view, controller }),
    snapshot.schema_only ? h("p", { className: "note warnbox" },
      "데이터 없이 매핑 중입니다. 고정값을 넣거나 비움으로 확정하세요.") : null,
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
      h("code", null, "{{seq:001}}"), " → 001부터 세 자리로 증가")),
    h("div", {
      id: "save-msg", className: `note ${view.saveMessage?.level === "ok" ? "okbox" : "warnbox"}`,
      style: { display: view.saveMessage ? "block" : "none" },
    }, view.saveMessage
      ? `${view.saveMessage.level === "ok" ? "" : "⚠ "}${view.saveMessage.text}` : ""));
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
    return h("footer", { className: "wfoot", id: "editor-foot" },
      h("button", {
        className: "btn", "data-act": "discard-patch", disabled: !armed,
        onClick: (event: Obj) => controller.guarded(() => controller.discardPatch(event.currentTarget)),
      }, "변경 버리기"),
      h("span", { className: "spacer" }),
      h("button", {
        className: "btn primary", "data-act": "save", disabled: !armed,
        onClick: () => controller.guarded(() => controller.doSave({})),
      }, "변경 저장"));
  }
  const last = here >= sections.length - 1;
  const can = !!(snapshot.reachable || {})[snapshot.section];
  return h("footer", { className: "wfoot", id: "editor-foot" },
    h("button", {
      className: "btn", "data-act": "cancel-new",
      onClick: (event: Obj) => controller.guarded(() => controller.cancelNewDraft(event.currentTarget)),
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
  const snapshot = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot);
  const draft = useSyncExternalStore(controller.draftModel.subscribe, controller.draftModel.getSnapshot);
  const view = useSyncExternalStore(controller.viewModel.subscribe, controller.viewModel.getSnapshot);

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
      /* 세션 통지(#26) — 문제(warn)만 시끄럽게, 정상(ok)은 muted 한 줄. */
      snapshot.notice ? h("p", {
        className: `note ${snapshot.notice.level === "ok" ? "quiet" : "warnbox"}`,
        style: { whiteSpace: "pre-line" },
      }, snapshot.notice.text) : null,
      body),
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

export function TxtEditDialog(props: { controller: EditorController }): ReactNode {
  const { controller } = props;
  const view = useSyncExternalStore(controller.viewModel.subscribe, controller.viewModel.getSnapshot);
  const state = view.txtEdit;
  /* 초기 포커스는 **커밋 뒤** 이 자리가 겨눈다. 모달 executor 의 `initialFocus` 는 열림
     **시점**의 DOM 을 보는데 이 창의 내용은 그 뒤 커밋에서 생기므로, 열림 시점에 넘기면
     대상이 없어 되돌림 트리거로 떨어진다(시트 선택이 같은 이유로 같은 형태를 쓴다). */
  useEffect(() => {
    if (state === null) return;
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
    h("p", { className: "modal-sub" }, "{{필드}} 토큰을 포함한 템플릿 내용"),
    h("textarea", {
      id: "txtEditContent", rows: 10, placeholder: "제목: {{공고명}} ...",
      value: state?.content || "",
      onChange: (event: Obj) => controller.patchTxtEdit({ content: String(event.currentTarget.value) }),
    }),
    h("p", {
      id: "txtEditError", className: "note dangerbox", role: "alert",
      style: { display: state?.error ? "block" : "none" },
    }, state?.error || ""),
    h("div", { className: "modal-actions" },
      h("button", {
        className: "btn", id: "txtEditCancel",
        onClick: () => controller.guarded(() => controller.confirmDiscardTxtEdit()),
      }, "취소"),
      h("button", {
        className: "btn primary", id: "txtEditOk",
        onClick: () => controller.guarded(() => controller.submitTxtEdit()),
      }, "저장")));
}
