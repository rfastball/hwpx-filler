/* R4-02 TXT 검토·복사 작업대의 React 표면(legacy `frontend/js/screens/workbench.js`).

   정체는 그대로다 — 「문서 만들기」에서 TXT 작업을 실행하면 오는 **몰입 화면**이고, 진입
   시점의 고정 사본을 받아 레코드 하나씩 검토·복사한다. 판정은 전부 Python(workbench 스냅샷)
   이다: 작업점·복사 이력·린트 술어를 웹이 다시 계산하지 않는다.

   **복사할 본문이 화면의 중심이다**(#1148). 이 화면은 필드 연결 표를 들지 않는다 — 연결은
   읽기만 하고, 고치는 일은 머리의 두 문(「연결 편집」→ 편집기 연결 표, 「템플릿 편집」→ 저작
   작업대)이 화면 밖으로 나가서 한다. 빈 값은 본문 안의 〈빈 값〉 표식과 복사 전 확인이 계속
   드러낸다.

   **본문은 그 행 복사본의 임시 편집기다**(#1148 PR B). CodeMirror 편집면(`txt_lintpad.ts` — vendor 를
   아는 유일한 파일)을 빌려 쓰고, 친 글자는 행별로 Python 세션에 맡긴다. 〈빈 값〉·〈비워 둠〉 표지와
   값 칠의 자리·채움 여부는 Python 이 낸 표식(`card.marks`)을 그대로 그린다 — 여기서 다시 가르지
   않는다. 복사는 편집기에 보이는 글자 그대로다(대조·쓰기 판정은 Python 의 복사 거래).

   지키는 순서 계약 셋:

   - 이 화면의 상태는 하나라 **체인도 하나**다(`WB_CHAIN`). 축별로 가르면 「글꼴을 고르고
     곧바로 다음 행으로 갔다」가 서로를 추월한다.
   - 커밋(복사·이탈)은 그 체인을 **먼저 정산**한다 — 그것들이 읽는 것이 바로 이 발신들이
     쓴 상태다.
   - 복사는 사전확인이 본 **그 카드**의 토큰을 실어 보낸다. 그사이 작업점이 옮겨졌으면 백엔드가
     stale 로 돌려주고, 확인하지 않은 카드가 클립보드로 나가지 않는다. */
import { Fragment, createElement, useEffect, useRef, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import { disposeLintpad, mountLintpad, updateLintpad } from "../editorview/txt_lintpad.ts";
import type { LintpadHandle } from "../editorview/txt_lintpad.ts";
import type { LintpadMark } from "../editorview/txt_card_marks.ts";
import type { BridgeClient } from "../runtime/client.ts";
import type { ScreenPorts } from "./ports.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import { TARGET_FONT_FIELD, workbenchServerValues, workbenchSession } from "./workbench_state.ts";
import {
  emptyDraft, ingestSnapshot, issueToken, settle, typeInto, valueOf,
} from "./editor_state.ts";
import type { DraftState } from "./editor_state.ts";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
};
type ChainPort = {
  chained<T>(key: string, send: () => Promise<T>): Promise<T>;
  settle(key: string): Promise<unknown>;
};

export type WorkbenchControllerDeps = {
  doc: Document;
  runtime: ScreenRuntime;
  client: BridgeClient;
  modal: ModalPort;
  chain: ChainPort;
  /** 항행과 **관측** — 화면 밖 문이 열리지 않았는지를 `currentScreen` 으로 되읽는다. */
  navigation: { go(screen: string, options?: Obj): void; currentScreen(): string | null };
  /** 나가는 문 둘 — 편집기 진입 seam 과 저작 작업대 진입(둘 다 late-bound 포트). */
  ports: Pick<ScreenPorts, "editorEntry" | "authoring">;
  notify(message: string): void;
};

const SCREEN = "workbench";
const WB_CHAIN = "workbench:session";
/** 화면 밖 문으로 나간 뒤의 복귀처 — 작업대 세션은 나갈 때 닫히므로 돌아갈 세션이 없고,
    다시 들어오는 길은 「문서 만들기」 하나다(편집기 `return_context.surface: "data"` 와 같은 곳). */
const RETURN_SCREEN = "job";

const REVIEW_TEXT: Record<string, [string, string]> = {
  todo: ["복사 전", "idle"],
  copied: ["복사 완료", "ok"],
  recheck: ["규칙 변경 뒤 다시 확인 필요", "warn"],
};
const DOT_STATE_LABEL: Record<string, string> = {
  current: "작업 중", copied: "복사 완료", uncopied: "대기",
};
/** 친 글자를 Python 에 맡기기까지의 쉼 — 타건마다 왕복하지 않되, 이동·복사·이탈은 먼저 정산한다. */
const EDIT_DELAY_MS = 250;
/** 표식 종류 → 칠(제품 CSS `.wc-render .seg-*`). 종류의 판정은 Python 이 낸다. */
const MARK_CLASS: Record<string, string> = {
  fill: "seg-fill", blank: "seg-blank", declared: "seg-declared", missing: "seg-missing",
};
/** 길이 0 표식의 표지 문구 — 빈 값(데이터가 빈 칸)과 비워 둠(일부러 비운 선언)을 가른다. */
const HOLE_LABEL: Record<string, string> = { blank: "〈빈 값〉", declared: "〈비워 둠〉" };

/** Python 표식 → 편집면 표식. 빈 자리에 글자를 치면 그 범위는 값 칠로 바뀐다. */
export function cardMarks(marks: readonly Obj[] | null | undefined): LintpadMark[] {
  return (marks || []).map((mark) => {
    const kind = String(mark.kind);
    const hole = HOLE_LABEL[kind];
    return {
      start: Number(mark.start), end: Number(mark.end), className: MARK_CLASS[kind] || "",
      token: String(mark.name || ""),
      ...(hole ? { label: hole, filledClassName: MARK_CLASS.fill } : {}),
    };
  });
}

export function createWorkbenchController(deps: WorkbenchControllerDeps) {
  const model = deps.runtime.model<Obj | null>(SCREEN);
  let draft: DraftState = emptyDraft();
  const draftListeners = new Set<Listener>();

  function emitDraft(): void { for (const listener of [...draftListeners]) listener(); }

  function snapshot(): Obj { return model.getSnapshot() || {}; }

  function absorb(): void {
    const current = model.getSnapshot();
    if (current === null) return;
    draft = ingestSnapshot(draft, {
      session: workbenchSession(current),
      values: workbenchServerValues(current),
    });
    emitDraft();
  }
  model.subscribe(absorb);
  absorb();

  /* 화면 이름을 **호출 자리마다** 싣는다 — 헬퍼 안으로 감추면 정적 배선 가드가 이 화면을
     못 보고 공허하게 통과한다(1R P1 의 재발 자리). */
  const dispatch = async (screen: string, action: string, payload: Obj = {}): Promise<Obj> => {
    const call = deps.client.dispatch as unknown as (
      channel: string, name: string, body: Obj,
    ) => ReturnType<BridgeClient["dispatch"]>;
    return (expectHostValue(await call(screen, action, payload), `${screen}/${action}`) ?? {}) as Obj;
  };

  const invoke = async (
    method: Parameters<BridgeClient["invoke"]>[0], ...args: unknown[]
  ): Promise<unknown> => expectHostValue(await deps.client.invoke(method, ...args), method);

  /** 상태 변이는 전부 한 체인에 선다. */
  function sendWb(action: string, payload: Obj = {}): Promise<Obj> {
    return deps.chain.chained(WB_CHAIN, () => dispatch(SCREEN, action, payload));
  }

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

  /* ---- 본문 임시 편집 — 친 글자는 쉼 뒤에 한 번, 한글 조합이 끝난 뒤에 보낸다 ---- */
  let pendingEdit: { index: number; text: string } | null = null;
  let editTimer: ReturnType<typeof setTimeout> | undefined;
  let composing = false;

  /** 미뤄 둔 편집을 지금 체인에 세운다 — 이동·복사·이탈·되돌리기가 먼저 부른다. */
  function flushEdit(): Promise<unknown> {
    clearTimeout(editTimer);
    const edit = pendingEdit;
    pendingEdit = null;
    if (edit === null) return Promise.resolve();
    return sendWb("set_card_text", { index: edit.index, text: edit.text })
      .catch((error) => deps.notify(String((error as Obj)?.message || error)));
  }

  function scheduleEdit(): void {
    clearTimeout(editTimer);
    editTimer = setTimeout(() => { void flushEdit(); }, EDIT_DELAY_MS);
  }

  /** 편집면이 친 결과(전문). 정체는 그 문서가 선 행 `index` 다 — 작업점이 아니다. */
  function editCard(index: number, text: string): void {
    pendingEdit = { index, text };
    if (!composing) scheduleEdit();
  }

  function setComposing(on: boolean): void {
    composing = on;
    if (!on && pendingEdit !== null) scheduleEdit();
  }

  /** 「원래대로」 — 그 행에 미뤄 둔 편집은 버리고 원문으로 되돌린다. */
  async function revertCard(index: number): Promise<void> {
    if (pendingEdit !== null && pendingEdit.index === index) {
      clearTimeout(editTimer);
      pendingEdit = null;
    }
    await flushEdit();
    await sendWb("revert_card", { index });
  }

  /** 상태를 옮기는 동작 앞에 미뤄 둔 편집을 정산한다(체인 순서가 곧 착지 순서다). */
  function afterEdit<T>(send: () => Promise<T>): Promise<T> {
    void flushEdit();
    return send();
  }

  /** 대상 글꼴 — 고른 값을 곧바로 보이고(초안), 응답이 그 값을 확정하거나 되돌린다. */
  async function setTargetFont(font: string): Promise<void> {
    draft = typeInto(draft, TARGET_FONT_FIELD, font);
    const session = draft.session;
    const issued = issueToken(draft, TARGET_FONT_FIELD);
    draft = issued.state;
    emitDraft();
    try {
      await sendWb("set_target_font", { font });
      draft = settle(draft, { ok: true, session, token: issued.token, key: TARGET_FONT_FIELD });
    } catch (error) {
      draft = settle(draft, {
        ok: false, session, token: issued.token, key: TARGET_FONT_FIELD,
        error: String((error as Obj)?.message || error),
      });
      deps.notify(String((error as Obj)?.message || error));
    }
    emitDraft();
  }

  async function copyCard(): Promise<void> {
    /* 방금 친 글자·이동·보기가 아직 날아가는 중일 수 있다 — 착지한 **뒤에** 무엇을 복사할지 묻는다. */
    void flushEdit();
    await deps.chain.settle(WB_CHAIN);
    const pre = await dispatch(SCREEN, "copy_precheck", {});
    const blockers: string[] = [];
    if (pre.missing_fields && pre.missing_fields.length) {
      blockers.push(`채우지 못한 항목: ${pre.missing_fields.join(", ")}`);
    }
    if (pre.empty_fields && pre.empty_fields.length) {
      blockers.push(`값이 빈 항목: ${pre.empty_fields.join(", ")}`);
    }
    if (blockers.length) {
      const accepted = await deps.modal.confirm({
        title: "이대로 복사할까요?",
        body: `${blockers.join("\n")}\n\n확정-비움으로 선언한 항목은 여기 세지 않습니다.`,
        confirmLabel: "그래도 복사",
        cancelLabel: "돌아가기",
      });
      if (!accepted) return;
    }
    const result = await invoke("copy_clipboard", SCREEN, pre.token) as Obj;
    if (result && result.stale) {
      deps.notify("작업점이 그사이 바뀌어 복사하지 않았습니다. 카드를 확인하고 다시 복사하세요.");
    } else if (result && result.error) {
      deps.notify(String(result.error));   // 차단 사유는 조용한 무동작으로 두지 않는다
    }
  }

  /** 이탈 관문 — 나가는 모든 길이 여기서 가드를 지난다. 참이면 나가도 된다.
   *
   *  가드가 「잃을 것 없음」이라고 답하려면 **대기 중인 발신까지** 세고 답해야 한다. */
  async function confirmLeave(): Promise<boolean> {
    void flushEdit();
    await deps.chain.settle(WB_CHAIN);
    const guard = await dispatch(SCREEN, "leave_guard", {});
    if (!guard || !guard.armed) return true;
    return deps.modal.confirm({
      title: "작업대를 나갈까요?",
      body: (guard.lines || []).join("\n"),
      confirmLabel: "나가기",
      cancelLabel: "계속 검토",
    });
  }

  /** 이탈: 셸 이동(뒤로·상단 탭)의 단일 관문. */
  async function leaveTo(target: string): Promise<void> {
    if (!(await confirmLeave())) return;
    await dispatch(SCREEN, "close", {});
    deps.navigation.go(target, { force: true });
  }

  /** 화면 밖 문(편집기·저작 작업대)으로 나간다 — 같은 관문을 지나 세션을 닫은 **뒤에** 연다.
   *
   *  문이 열리지 못하면(여는 쪽이 사유를 이미 알렸다) 빈 작업대에 남기지 않고 「문서
   *  만들기」로 보낸다: 세션은 이미 닫혔고 다시 들어오는 길은 그쪽 하나다. 여는 데 필요한
   *  정체(작업 이름·템플릿 경로)는 닫기 **전에** 읽는다 — 닫기 푸시가 스냅샷을 비운다. */
  async function leaveThrough(open: () => unknown): Promise<void> {
    if (!(await confirmLeave())) return;
    await dispatch(SCREEN, "close", {});
    try {
      await open();
    } finally {
      if (deps.navigation.currentScreen() === SCREEN) {
        deps.navigation.go(RETURN_SCREEN, { force: true });
      }
    }
  }

  /** 「연결 편집」 — 이 작업을 편집기의 연결 단계로 연다(진입 사유 `workbench_result`). */
  function editBinding(): Promise<void> {
    const name = String(snapshot().job_name || "");
    return leaveThrough(() => deps.ports.editorEntry.current().openGuarded(name, {
      entry_reason: "workbench_result",
      return_context: { surface: "data" },
    }));
  }

  /** 「템플릿 편집」 — 이 작업의 템플릿을 저작 작업대로 연다. 경로는 스냅샷이 낸 그것이다. */
  function editTemplate(): Promise<void> {
    const path = String(snapshot().template_path || "");
    return leaveThrough(() => deps.ports.authoring.current().open(path, RETURN_SCREEN));
  }

  return {
    /** initial 당김이 없는 화면 — push 로만 산다(legacy 와 같은 수명). */
    init(): void { absorb(); },
    leaveTo,
    editBinding,
    editTemplate,
    model,
    draftModel: {
      getSnapshot: (): DraftState => draft,
      subscribe(listener: Listener): () => void {
        draftListeners.add(listener);
        return () => { draftListeners.delete(listener); };
      },
    },
    copyCard,
    editCard,
    setComposing,
    revertCard,
    step: (delta: number): Promise<Obj> => afterEdit(() => sendWb("step", { delta })),
    setCurrent: (index: number): Promise<Obj> => afterEdit(() => sendWb("set_current", { index })),
    setView: (view: string): Promise<Obj> => afterEdit(() => sendWb("set_view", { view })),
    setTargetFont,
    toggleAdvance: (value: boolean): Promise<Obj> => sendWb("toggle_advance", { value }),
    setFullwidth: (value: boolean): Promise<Obj> => afterEdit(() => sendWb("set_fullwidth", { value })),
    guarded,
    doc: deps.doc,
    notify: deps.notify,
  };
}

export type WorkbenchController = ReturnType<typeof createWorkbenchController>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 본문 편집면 — 그 행 복사본의 임시 편집기. 원문 보기는 읽기 전용이다.
 *
 *  문서를 **갈아 끼우는** 것은 `text_key` 가 바뀔 때뿐이다(행·보기·전각·되돌리기). 편집 왕복의
 *  메아리(같은 키)는 표식만 얹는다 — 문서를 다시 넣으면 캐럿이 튀고 조합 중인 글자가 끊긴다.
 *  표식은 지금 문서가 Python 이 본 그 문서일 때만 받는다(`sourceDoc`); 그사이 더 친 글자가
 *  있으면 편집면이 들고 있는 표식을 변경에 따라 옮겨 둔다. */
function CardEditor(props: { controller: WorkbenchController; card: Obj; readOnly: boolean }): ReactNode {
  const { controller, card, readOnly } = props;
  const host = useRef<HTMLDivElement | null>(null);
  const handle = useRef<LintpadHandle | null>(null);
  const shownKey = useRef("");
  const docIndex = useRef<number>(Number(card.index));
  const applying = useRef(false);
  useEffect(() => {
    if (host.current === null) return undefined;
    shownKey.current = "";
    const mounted = mountLintpad({
      host: host.current, doc: String(card.text || ""), contentId: "wbCardText",
      ariaLabel: "복사할 본문", readOnly,
      onDocChanged: (text) => {
        if (!applying.current && !readOnly) controller.editCard(docIndex.current, text);
      },
      onCompositionChanged: (on) => controller.setComposing(on),
    });
    handle.current = mounted;
    return () => { handle.current = null; disposeLintpad(mounted); };
  // 편집 가능 여부는 마운트 때 정해진다(보기 전환이 다시 세운다).
  }, [controller, readOnly]);
  useEffect(() => {
    const mounted = handle.current;
    if (mounted === null) return;
    const text = String(card.text || "");
    const key = String(card.text_key || "");
    const marks = cardMarks(card.marks);
    if (shownKey.current !== key) {
      shownKey.current = key;
      docIndex.current = Number(card.index);
      applying.current = true;
      try { updateLintpad(mounted, { doc: text, sourceDoc: text, marks }); } finally { applying.current = false; }
    } else {
      updateLintpad(mounted, { sourceDoc: text, marks });
    }
  }, [card.text, card.text_key, card.marks, card.index]);
  return h("div", { className: "wb-editor", ref: host });
}

/** 이 행 복사본을 고쳤다 — 표지와 되돌리는 손잡이가 한 벌이다(판정은 Python `edited`). */
function EditedMark(props: { controller: WorkbenchController; card: Obj }): ReactNode {
  const { controller, card } = props;
  if (!card.edited) return null;
  return createElement(Fragment, null,
    h("span", { className: "status", id: "wbEdited", "data-level": "warn" }, "수정됨"),
    h("button", {
      className: "btn sm", id: "wbRevert", type: "button",
      onClick: () => controller.guarded(() => controller.revertCard(Number(card.index))),
    }, "원래대로"));
}

/** 큐 점 색인 — 큐 줄의 가운데 칸. 점 하나가 탭 정지 하나(로빙)이고 화살표·Home/End 로 옮긴다.
 *
 *  1건이면 순회할 곳이 없어 큐 장치가 숨는다(퇴화 승계) — 정보가 없어서지 장식이라서가 아니다. */
function QueueDots(props: { controller: WorkbenchController; card: Obj; degenerate: boolean }): ReactNode {
  const { controller, card, degenerate } = props;
  return h("div", {
    className: "wb-dots", id: "wbDots", role: "group", "aria-label": "큐 진행 표시",
    hidden: degenerate,
    onFocus: (event: Obj) => {
      const target = (event.target as Element).closest(".wc-dot") as HTMLButtonElement | null;
      if (!target) return;
      const previous = event.currentTarget.querySelector('.wc-dot[tabindex="0"]') as HTMLButtonElement | null;
      if (previous && previous !== target) previous.tabIndex = -1;
      target.tabIndex = 0;
    },
    onKeyDown: (event: Obj) => {
      const buttons = Array.from(event.currentTarget.querySelectorAll(".wc-dot")) as HTMLButtonElement[];
      const index = buttons.indexOf(event.target as HTMLButtonElement);
      if (index < 0) return;
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
        : event.key === "ArrowRight" || event.key === "ArrowDown" ? index + 1
          : event.key === "ArrowLeft" || event.key === "ArrowUp" ? index - 1 : -1;
      if (next < 0 || next >= buttons.length) return;
      event.preventDefault();
      buttons[next].focus();
    },
  }, ...(degenerate ? [] : ((card.index_map || []) as Obj[]).map((dot) => {
    const label = DOT_STATE_LABEL[dot.state] || dot.state;
    const why = label + (dot.recheck ? " · 다시 확인 필요" : "");
    return h("button", {
      className: `wc-dot ${dot.state}${dot.recheck ? " gap" : ""}`, type: "button",
      "data-i": dot.index, key: String(dot.index),
      tabIndex: dot.state === "current" ? 0 : -1,
      "aria-current": dot.state === "current" ? "step" : undefined,
      "aria-label": `${dot.row}행 ${why}`, title: `${dot.row}행 · ${why}`,
      onClick: () => controller.guarded(() => controller.setCurrent(Number(dot.index))),
    });
  })));
}

export function WorkbenchScreen(props: { controller: WorkbenchController }): ReactNode {
  const { controller } = props;
  const snapshot = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot);
  const draft = useSyncExternalStore(controller.draftModel.subscribe, controller.draftModel.getSnapshot);
  const cardOpen = snapshot !== null && !!snapshot.open;
  const currentIndex = snapshot?.card?.index;
  useEffect(() => {
    if (!cardOpen) return;
    const dots = controller.doc.getElementById("wbDots");
    const current = dots?.querySelector<HTMLElement>('[aria-current="step"]');
    if (!dots || !current) return;
    dots.querySelectorAll<HTMLButtonElement>(".wc-dot").forEach((button) => {
      button.tabIndex = button === current ? 0 : -1;
    });
    const box = dots.getBoundingClientRect();
    const item = current.getBoundingClientRect();
    if (item.top < box.top) dots.scrollTop -= box.top - item.top;
    else if (item.bottom > box.bottom) dots.scrollTop += item.bottom - box.bottom;
  }, [controller, cardOpen, currentIndex]);

  if (snapshot === null || !snapshot.open) {
    /* 세션 없음 — 화면은 라우팅 가드가 막는다. 골격은 그대로 두고 값만 비운다. */
    return h("div", { className: "wb-shell" },
      h("button", {
        className: "btn sm quiet back", id: "wbBack", type: "button",
        onClick: () => controller.guarded(() => controller.leaveTo("job")),
      }, "← 문서 만들기로 돌아가기"));
  }
  const card = (snapshot.card || {}) as Obj;
  const total = Number(snapshot.total || 0);
  const position = card.position === null || card.position === undefined ? 0 : card.position + 1;
  const review = REVIEW_TEXT[card.review_state] || REVIEW_TEXT.todo;
  const degenerate = !!card.queue_degenerate;
  const lint = (card.lint || {}) as Obj;
  const lastCopy = card.last_copy as Obj | undefined;
  const revision = snapshot.revision || {};
  const notice = snapshot.notice;
  const noteText = lastCopy
    ? `${lastCopy.row}행을 복사했습니다.`
      + (lastCopy.empty_fields && lastCopy.empty_fields.length
        ? ` (빈 값: ${lastCopy.empty_fields.join(", ")})` : "")
      + (lastCopy.stamp_error ? ` — 최근 사용 기록은 실패했습니다: ${lastCopy.stamp_error}` : "")
    : (card.source_row ? `원본 ${card.source_row}행` : "");
  /* 한 읽기 열(.wb-shell)에 머리 → 큐 줄 → 본문 판(도구 막대 + 카드) → 린트 → 발이 선다 —
     DOM 순서가 곧 보이는 순서(초점 순서)다. 판정·문구는 그대로이고 자리만 정한다. */
  return h("div", { className: "wb-shell" },
    h("header", { className: "scr-head wb-head" },
      h("button", {
        className: "btn sm quiet back", id: "wbBack", type: "button",
        onClick: () => controller.guarded(() => controller.leaveTo("job")),
      }, "← 문서 만들기로 돌아가기"),
      h("div", { className: "wb-title" },
        h("p", { className: "eyebrow", id: "wbMode" }, snapshot.mode_label || ""),
        h("h1", { id: "wbTitle" }, snapshot.job_name || "검토·복사"),
        h("p", { className: "sub" }, "선택 당시 표시순서로 고정된 항목만 검토합니다.")),
      /* 화면 밖으로 나가는 문 둘 — 이 화면은 연결을 읽기만 한다(#1148). 템플릿 문은 스냅샷이
         여는 파일을 낼 때만 선다(경로를 웹이 짓지 않는다). 판본은 두 문이 여는 것의 판이라
         문 곁에 선다 — 진행 수치는 본문 위 큐 줄이 따로 든다. */
      h("div", { className: "wb-links" },
        h("span", { className: "status", id: "wbRevision", "data-level": "idle" },
          `템플릿 r${revision.template || 0} · 연결 r${revision.binding || 0}`),
        h("button", {
          className: "btn sm quiet", id: "wbEditBinding", type: "button",
          onClick: () => controller.guarded(() => controller.editBinding()),
        }, "연결 편집"),
        snapshot.template_path ? h("button", {
          className: "btn sm quiet", id: "wbEditTemplate", type: "button",
          onClick: () => controller.guarded(() => controller.editTemplate()),
        }, "템플릿 편집") : null)),
    h("div", {
      className: `note ${notice && notice.text ? (notice.level || "muted") : ""}`, id: "wbNotice",
      role: "status", style: { display: notice && notice.text ? "" : "none" },
    }, notice && notice.text ? notice.text : ""),
    h("section", { className: "wb-body" },
      /* 큐 줄 — 작업점 · 점 색인 · 복사 완료가 한 줄에 모여 본문 바로 위에 선다. */
      h("div", { className: "wb-queue" },
        h("span", { className: "wb-count" }, "작업점 ", h("strong", { id: "wbPosition" }, `${position} / ${total}`)),
        h(QueueDots as any, { controller, card, degenerate }),
        h("span", { className: "wb-count wb-count-end" },
          "복사 완료 ", h("strong", { id: "wbCopied" }, `${snapshot.copied_count || 0} / ${total}`))),
      /* 도구 막대는 카드의 머리 띠로 붙는다 — 그래도 카드의 **형제**다(카드 글자 되읽기에 섞이지
         않게, 카드가 본체의 남는 높이를 직접 받게). */
      h("div", { className: "wb-toolbar", role: "group", "aria-label": "본문 보기" },
        ...[["filled", "채운 모습"], ["raw", "원문"]].map(([view, label]) => h("button", {
          className: "btn sm", type: "button", "data-wb-view": view, key: view,
          "aria-pressed": snapshot.view === view ? "true" : "false",
          onClick: () => controller.guarded(() => controller.setView(view)),
        }, label)),
        h("label", { className: "lbl", htmlFor: "wbTargetFont" }, "대상 글꼴"),
        h("select", {
          className: "field sm", id: "wbTargetFont",
          title: "붙여넣는 곳(기안작성기)의 표준 글꼴입니다(전역 설정으로 저장).",
          value: valueOf(draft, TARGET_FONT_FIELD),
          onChange: (event: Obj) => controller.guarded(
            () => controller.setTargetFont(String(event.currentTarget.value))),
        },
        h("option", { value: "gulimche" }, "굴림체"),
        h("option", { value: "dotumche" }, "돋움체"),
        h("option", { value: "malgun" }, "맑은고딕")),
        h("span", { className: "status", id: "wbReview", "data-level": review[1] }, review[0]),
        h(EditedMark as any, { controller, card })),
      h("article", {
        className: `wb-preview wc-render f-${snapshot.target_font || "gulimche"}`,
        id: "wbCard", "data-preserve-scroll": true,
      }, h(CardEditor as any, {
        key: String(snapshot.view), controller, card, readOnly: snapshot.view !== "filled",
      })),
      /* 린트는 **표지 + 행동**이 한 벌이다 — 경고만 두면 문제를 통보받고 손잡이는 없다. */
      h("p", { className: "muted", id: "wbLint", style: { display: lint.active ? "" : "none" } },
        lint.applied
          ? h("span", null, "연속 공백을 전각으로 바꿔 복사합니다. ",
            h("button", {
              className: "btn sm", type: "button", id: "wbLintAction", "data-fullwidth": "off",
              onClick: () => controller.guarded(() => controller.setFullwidth(false)),
            }, "되돌리기"))
          : h("span", null, "이 글꼴에서는 연속 공백이 밀릴 수 있습니다. ",
            h("button", {
              className: "btn sm", type: "button", id: "wbLintAction", "data-fullwidth": "on",
              onClick: () => controller.guarded(() => controller.setFullwidth(true)),
            }, "전각으로 바꾸기")))),
    h("footer", { className: "wb-foot" },
      h("label", { className: "wb-adv", style: { display: degenerate ? "none" : "" } },
        h("input", {
          type: "checkbox", id: "wbAdvance", checked: !!card.advance_after,
          onChange: (event: Obj) => controller.guarded(
            () => controller.toggleAdvance(!!event.currentTarget.checked)),
        }), " 복사 후 다음 항목으로 이동"),
      h("span", { className: "muted", id: "wbNote" }, noteText),
      h("div", { className: "wb-foot-nav" },
        h("button", {
          className: "btn", id: "wbPrev", type: "button",
          style: { display: degenerate ? "none" : "" },
          disabled: degenerate || !card.can_prev,
          onClick: () => controller.guarded(() => controller.step(-1)),
        }, "이전"),
        h("button", {
          className: "btn", id: "wbNext", type: "button",
          style: { display: degenerate ? "none" : "" },
          disabled: degenerate || !card.can_next,
          onClick: () => controller.guarded(() => controller.step(1)),
        }, "다음"),
        /* 복사 차단은 **Python 이 낸 사유**로 닫는다 — 「보이는 것 = 복사되는 것」. */
        h("button", {
          className: "btn primary", id: "wbCopy", type: "button",
          disabled: !card.has_current || !!card.copy_block, title: card.copy_block || "",
          onClick: () => controller.guarded(() => controller.copyCard()),
        }, "복사"))));
}
