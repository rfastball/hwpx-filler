/* R4-02 TXT 검토·복사 작업대의 React 표면(legacy `frontend/js/screens/workbench.js`).

   정체는 그대로다 — 「문서 만들기」에서 TXT 작업을 실행하면 오는 **몰입 화면**이고, 진입
   시점의 고정 사본을 받아 레코드 하나씩 검토·복사한다. 판정은 전부 Python(workbench 스냅샷)
   이다: 작업점·복사 이력·미저장 변경·린트 술어를 웹이 다시 계산하지 않는다.

   지키는 순서 계약 셋:

   - 이 화면의 상태는 하나라 **체인도 하나**다(`WB_CHAIN`). 축별로 가르면 「값을 고치고 곧바로
     유형을 고쳤다」가 서로를 추월한다.
   - 커밋(복사·저장·이탈)은 그 체인을 **먼저 정산**한다 — 그것들이 읽는 것이 바로 이 발신들이
     쓴 상태다.
   - 복사는 사전확인이 본 **그 카드**의 토큰을 실어 보낸다. 그사이 작업점이 옮겨졌으면 백엔드가
     stale 로 돌려주고, 확인하지 않은 카드가 클립보드로 나가지 않는다. */
import { createElement, useEffect, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import { SegmentView } from "./segment_view.ts";
import {
  TARGET_FONT_FIELD, checked, mapField, workbenchRevision, workbenchServerValues, workbenchSession,
} from "./workbench_state.ts";
import {
  emptyDraft, ingestSnapshot, issueToken, markField, settle, typeInto, valueOf,
} from "./editor_state.ts";
import type { DraftState } from "./editor_state.ts";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
  choose(spec: Obj): Promise<string | null>;
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
  navigation: { go(screen: string, options?: Obj): void };
  notify(message: string): void;
};

const SCREEN = "workbench";
const WB_CHAIN = "workbench:session";

const OWN_LABEL: Record<string, string> = { auto: "데이터 열에서", man: "직접 입력한 값" };
const REVIEW_TEXT: Record<string, [string, string]> = {
  todo: ["복사 전", "idle"],
  copied: ["복사 완료", "ok"],
  recheck: ["규칙 변경 뒤 다시 확인 필요", "warn"],
};
const DOT_STATE_LABEL: Record<string, string> = {
  current: "작업 중", copied: "복사 완료", uncopied: "대기",
};

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
      revision: workbenchRevision(current),
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

  function type(field: string, value: string): void {
    draft = typeInto(draft, field, value);
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

  async function commit(field: string, action: string, payload: Obj): Promise<Obj | null> {
    const session = draft.session;
    const issued = issueToken(draft, field);
    draft = issued.state;
    emitDraft();
    try {
      const result = await sendWb(action, payload);
      draft = settle(draft, { ok: true, session, token: issued.token, key: field });
      emitDraft();
      return result;
    } catch (error) {
      draft = settle(draft, {
        ok: false, session, token: issued.token, key: field,
        error: String((error as Obj)?.message || error),
      });
      emitDraft();
      deps.notify(String((error as Obj)?.message || error));
      return null;
    }
  }

  /** 결속 — 직접 입력한 값을 지울 수 있어 확인 왕복을 가진다(무확인 파괴 금지). */
  async function bindColumn(name: string, column: string): Promise<void> {
    const field = mapField(name, "source");
    type(field, column);
    const result = await commit(field, "set_source", { name, col: column });
    if (result === null || !result.confirm) return;
    const accepted = await deps.modal.confirm({
      title: "직접 입력한 값을 덮어쓸까요?", body: result.confirm,
      confirmLabel: "열 값으로 바꾸기", cancelLabel: "취소", danger: true,
    });
    if (!accepted) {
      /* 드롭다운을 스냅샷 상태로 되돌린다 — 확인을 거절하면 아무 일도 없었던 것과 같다. */
      type(field, draft.fields[field]?.serverValue ?? "");
      return;
    }
    await commit(field, "set_source", { name, col: column, confirm: true });
  }

  /** 값 입력은 blur 에서만 발신한다 — 타이핑 중 재구성이 없도록. */
  function commitValue(name: string): void {
    const field = mapField(name, "value");
    const state = draft.fields[field];
    if (state === undefined || !state.dirty) return;
    void commit(field, "set_map_value", { name, text: state.draftValue });
  }

  async function saveRules(): Promise<void> {
    /* 저장이 세는 dirty 집합도 대기 중 편집을 포함해야 한다. */
    await deps.chain.settle(WB_CHAIN);
    let result = await dispatch(SCREEN, "save_rules", {});
    /* 확인 문안을 **되돌려 보낸다** — 열린 사이 대상이 바뀌었으면 새 문안으로 다시 묻는다. */
    while (result && result.needs_confirm) {
      const confirmedText = result.confirm_text;
      const accepted = await deps.modal.confirm({
        title: "기본 규칙으로 저장할까요?",
        body: confirmedText,
        confirmLabel: "기본 규칙으로 저장",
        cancelLabel: "취소",
      });
      if (!accepted) return;
      result = await dispatch(SCREEN, "save_rules", { confirm: true, confirmed_text: confirmedText });
    }
    if (result && result.ok === false && result.error) deps.notify(String(result.error));
  }

  async function copyCard(): Promise<void> {
    /* 방금 친 값이 아직 날아가는 중일 수 있다 — 착지한 **뒤에** 무엇을 복사할지 묻는다. */
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

  /** 결과 → 규칙 겨눔 — 겨눔은 **포커스 그 자체**다(표면이 상태로 들지 않는다). */
  function aimAt(name: string): void {
    const row = name
      ? deps.doc.getElementById(`wbMap-row-${encodeURIComponent(name)}`)
      : null;
    if (row === null) return;                  // 소유 행 없는 토큰 — 겨눌 곳이 없다
    try { row.focus({ preventScroll: true }); } catch { row.focus(); }
    row.scrollIntoView({ block: "nearest" });
  }

  /** 이탈: 단일 관문 — 나가는 모든 이동이 여기를 지난다. */
  async function leaveTo(target: string): Promise<void> {
    /* 가드가 「잃을 것 없음」이라고 답하려면 **대기 중인 편집까지** 세고 답해야 한다. */
    await deps.chain.settle(WB_CHAIN);
    const guard = await dispatch(SCREEN, "leave_guard", {});
    if (guard && guard.armed) {
      const state = snapshot();
      const hasChanges = !!(state.dirty && state.dirty.count);
      if (hasChanges) {
        const choice = await deps.modal.choose({
          title: "작업대를 나갈까요?",
          body: (guard.lines || []).join("\n"),
          choices: [
            { value: "save", label: "저장하고 나가기" },
            { value: "discard", label: "버리고 나가기" },
            { value: "stay", label: "계속 검토" },
          ],
        });
        if (choice === "stay" || !choice) return;
        if (choice === "save") {
          await saveRules();
          /* 저장이 확인 창에서 취소됐으면 여전히 dirty 다 — 그때는 나가지 않는다. */
          const after = await dispatch(SCREEN, "leave_guard", {});
          const now = snapshot();
          if (after && after.armed && now.dirty && now.dirty.count) return;
        }
      } else {
        const accepted = await deps.modal.confirm({
          title: "작업대를 나갈까요?",
          body: (guard.lines || []).join("\n"),
          confirmLabel: "나가기",
          cancelLabel: "계속 검토",
        });
        if (!accepted) return;
      }
    }
    await dispatch(SCREEN, "close", {});
    deps.navigation.go(target, { force: true });
  }

  return {
    /** initial 당김이 없는 화면 — push 로만 산다(legacy 와 같은 수명). */
    init(): void { absorb(); },
    leaveTo,
    aimAt,
    model,
    draftModel: {
      getSnapshot: (): DraftState => draft,
      subscribe(listener: Listener): () => void {
        draftListeners.add(listener);
        return () => { draftListeners.delete(listener); };
      },
    },
    type, focus, compose, commit, commitValue, bindColumn, saveRules, copyCard,
    step: (delta: number): Promise<Obj> => sendWb("step", { delta }),
    setCurrent: (index: number): Promise<Obj> => sendWb("set_current", { index }),
    setView: (view: string): Promise<Obj> => sendWb("set_view", { view }),
    setTargetFont(font: string): void {
      type(TARGET_FONT_FIELD, font);
      void commit(TARGET_FONT_FIELD, "set_target_font", { font });
    },
    toggleAdvance: (value: boolean): Promise<Obj> => sendWb("toggle_advance", { value }),
    setFullwidth: (value: boolean): Promise<Obj> => sendWb("set_fullwidth", { value }),
    setConfirmed(name: string, value: boolean): void {
      const field = mapField(name, "confirmed");
      type(field, value ? "1" : "");
      void commit(field, "set_confirmed", { name, value });
    },
    setMapType(name: string, type_: string): void {
      const field = mapField(name, "type");
      type(field, type_);
      void commit(field, "set_map_type", { name, type: type_ });
    },
    setMapFmt(name: string, code: string): void {
      const field = mapField(name, "fmt");
      type(field, code);
      void commit(field, "set_map_fmt", { name, code });
    },
    revertMap: (name: string): Promise<Obj> => sendWb("revert_map", { name }),
    guarded,
    doc: deps.doc,
    notify: deps.notify,
  };
}

export type WorkbenchController = ReturnType<typeof createWorkbenchController>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function MapRow(props: {
  row: Obj; snapshot: Obj; draft: DraftState; controller: WorkbenchController;
}): ReactNode {
  const { row, snapshot, draft, controller } = props;
  const name = String(row.name);
  const key = encodeURIComponent(name);
  const sourceValue = valueOf(draft, mapField(name, "source"));
  const columns = ((snapshot.source_fields || []) as string[]).slice();
  if (sourceValue && columns.indexOf(sourceValue) < 0) columns.unshift(sourceValue);
  const declared = !!row.blank_declared;
  const isAuto = row.own === "auto";
  const typeValue = valueOf(draft, mapField(name, "type"));
  const formats = ((snapshot.fmt_options || {})[typeValue] || []) as Obj[];
  return h("tr", {
    "data-name": name, id: `wbMap-row-${key}`, tabIndex: -1,
    className: declared ? "row-blank-declared" : undefined,
  },
  h("td", { className: "maptok", title: `{{${name}}}` }, name),
  h("td", null, h("div", { className: "mapsrc" },
    row.own ? h("span", { className: `own ${row.own}`, title: OWN_LABEL[row.own] || "" }) : null,
    h("select", {
      className: "field sm mapsrc-sel", id: `wbMap-src-${key}`, "data-name": name,
      "aria-label": `${name} 데이터 열`, value: sourceValue,
      onChange: (event: Obj) => controller.guarded(
        () => controller.bindColumn(name, String(event.currentTarget.value))),
    },
    h("option", { value: "", key: "" }, "(직접 입력)"),
    ...columns.map((column) => h("option", { value: column, key: column }, column))),
    row.suggest && !isAuto ? h("button", {
      className: "btn sm mapsug", id: `wbMap-sug-${key}`, "data-name": name,
      title: "이름이 비슷한 열입니다",
      onClick: () => controller.guarded(() => controller.bindColumn(name, String(row.suggest))),
    }, `'${row.suggest}' 적용`) : null,
    row.can_revert ? h("button", {
      className: "btn sm maprev", id: `wbMap-rev-${key}`, "data-name": name,
      onClick: () => controller.guarded(() => controller.revertMap(name)),
    }, "자동으로 되돌리기") : null)),
  h("td", { className: "maptype-cell" }, isAuto
    ? h("select", {
      className: "field sm maptype", id: `wbMap-type-${key}`, "data-name": name,
      "aria-label": `${name} 유형`, value: typeValue,
      onChange: (event: Obj) => controller.setMapType(name, String(event.currentTarget.value)),
    }, ...((snapshot.type_options || []) as Obj[]).map((option) =>
      h("option", { value: option.code, key: option.code }, option.label)))
    : h("span", { className: "muted" }, "—")),
  h("td", { className: "mapfmt-cell" }, (isAuto && formats.length)
    ? h("select", {
      className: "field sm mapfmt", id: `wbMap-fmt-${key}`, "data-name": name,
      "aria-label": `${name} 표시형`, value: valueOf(draft, mapField(name, "fmt")),
      onChange: (event: Obj) => controller.setMapFmt(name, String(event.currentTarget.value)),
    }, ...formats.map((option) => h("option", { value: option.code, key: option.code }, option.label)))
    : h("span", { className: "muted" }, "—")),
  /* 확정-비움은 「아직 안 씀」이 아니라 「비워둠(선언)」이다 — 판정은 서버. */
  h("td", { className: "mapval-cell" }, declared
    ? h("span", {
      className: "mapval-declared muted",
      title: "비우기로 확정한 값입니다. 복사 전 확인에서 제외됩니다.",
    }, "비움 확정")
    : h("textarea", {
      className: `mapval-in${valueOf(draft, mapField(name, "value")).trim() === "" ? " empty" : ""}`,
      rows: 1, id: `wbMap-val-${key}`, "data-name": name, placeholder: "직접 입력",
      "aria-label": `${name} 값`, value: valueOf(draft, mapField(name, "value")),
      onChange: (event: Obj) => controller.type(mapField(name, "value"), String(event.currentTarget.value)),
      onFocus: () => controller.focus(mapField(name, "value"), true),
      onBlur: () => { controller.focus(mapField(name, "value"), false); controller.commitValue(name); },
      onCompositionStart: () => controller.compose(mapField(name, "value"), true),
      onCompositionEnd: () => controller.compose(mapField(name, "value"), false),
    })),
  h("td", { className: "mapck-cell" }, h("input", {
    className: "ck mapck", type: "checkbox", id: `wbMap-ck-${key}`, "data-name": name,
    "aria-label": `${name} 확정`, checked: checked(draft, mapField(name, "confirmed")),
    onChange: (event: Obj) => controller.setConfirmed(name, !!event.currentTarget.checked),
  })));
}

export function WorkbenchScreen(props: { controller: WorkbenchController }): ReactNode {
  const { controller } = props;
  const snapshot = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot);
  const draft = useSyncExternalStore(controller.draftModel.subscribe, controller.draftModel.getSnapshot);
  /* 카드 조각 클릭 → 소유 행 겨눔. 조각엔 id 가 없다(같은 토큰이 여러 번 나올 수 있어
     신원은 `data-token` 이다) — 그래서 위임으로 받는다. */
  useEffect(() => {
    const card = controller.doc.getElementById("wbCard");
    if (card === null) return;
    const onClick = (event: Event): void => {
      const segment = (event.target as Element | null)?.closest<HTMLElement>("[data-token]");
      if (segment != null) controller.aimAt(segment.dataset.token || "");
    };
    card.addEventListener("click", onClick);
    return () => card.removeEventListener("click", onClick);
  }, [controller]);

  if (snapshot === null || !snapshot.open) {
    /* 세션 없음 — 화면은 라우팅 가드가 막는다. 골격은 그대로 두고 값만 비운다. */
    return h("div", { className: "wb-shell" },
      h("button", {
        className: "btn sm back", id: "wbBack", type: "button",
        onClick: () => controller.guarded(() => controller.leaveTo("job")),
      }, "← 문서 만들기로 돌아가기"));
  }
  const card = (snapshot.card || {}) as Obj;
  const total = Number(snapshot.total || 0);
  const position = card.position === null || card.position === undefined ? 0 : card.position + 1;
  const review = REVIEW_TEXT[card.review_state] || REVIEW_TEXT.todo;
  const degenerate = !!card.queue_degenerate;
  const dirty = snapshot.dirty || { count: 0 };
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
  return h("div", { className: "wb-shell" },
    h("button", {
      className: "btn sm back", id: "wbBack", type: "button",
      onClick: () => controller.guarded(() => controller.leaveTo("job")),
    }, "← 문서 만들기로 돌아가기"),
    h("header", { className: "scr-head wb-head" },
      h("div", null,
        h("p", { className: "eyebrow", id: "wbMode" }, snapshot.mode_label || ""),
        h("h1", { id: "wbTitle" }, snapshot.job_name || "검토·복사"),
        h("p", { className: "sub" }, "선택 당시 표시순서로 고정된 항목만 검토합니다.")),
      h("div", { className: "wb-stats" },
        h("span", null, "작업점 ", h("strong", { id: "wbPosition" }, `${position} / ${total}`)),
        h("span", null, "복사 완료 ", h("strong", { id: "wbCopied" }, `${snapshot.copied_count || 0} / ${total}`)),
        h("span", { className: "status", id: "wbRevision", "data-level": "idle" },
          `템플릿 r${revision.template || 0} · 연결 r${revision.binding || 0}`))),
    h("div", {
      className: `note ${notice && notice.text ? (notice.level || "muted") : ""}`, id: "wbNotice",
      role: "status", style: { display: notice && notice.text ? "" : "none" },
    }, notice && notice.text ? notice.text : ""),
    h("div", { className: "wb-body" },
      h("section", { className: "wb-left" },
        h("div", { className: "zone-head" },
          h("div", null,
            h("h2", { className: "zone-cap" }, "필드 연결·표시"),
            h("p", { className: "muted", id: "wbDirtyNote" }, dirty.count
              ? `저장하지 않은 변경 ${dirty.count}건`
              : (dirty.pending ? "확정하지 않은 편집이 있습니다" : "저장하지 않은 변경 없음"))),
          h("button", {
            className: "btn", id: "wbSaveRules", type: "button",
            disabled: !snapshot.can_save, title: snapshot.save_block || "",
            onClick: () => controller.guarded(() => controller.saveRules()),
          }, "기본 규칙으로 저장…")),
        h("div", { id: "wbMapPanel", "data-preserve-scroll": true },
          h("table", { className: "dmap" },
            h("thead", null, h("tr", null,
              h("th", null, "항목"), h("th", null, "데이터 열"), h("th", null, "유형"),
              h("th", null, "표시형"), h("th", null, "값"), h("th", null, "확정"))),
            h("tbody", null, ...((snapshot.rows || []) as Obj[]).map((row) =>
              h(MapRow as any, { key: String(row.name), row, snapshot, draft, controller })))))),
      h("section", { className: "wb-right" },
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
            onChange: (event: Obj) => controller.setTargetFont(String(event.currentTarget.value)),
          },
          h("option", { value: "gulimche" }, "굴림체"),
          h("option", { value: "dotumche" }, "돋움체"),
          h("option", { value: "malgun" }, "맑은고딕")),
          h("span", { className: "status", id: "wbReview", "data-level": review[1] }, review[0])),
        /* 1건이면 순회할 곳이 없어 큐 장치가 숨는다(퇴화 승계) — 정보가 없어서지 장식이라서가 아니다. */
        h("div", {
          className: "wb-dots", id: "wbDots", role: "list", "aria-label": "큐 진행 표시",
          hidden: degenerate,
        }, ...(degenerate ? [] : ((card.index_map || []) as Obj[]).map((dot) => {
          const label = DOT_STATE_LABEL[dot.state] || dot.state;
          const why = label + (dot.recheck ? " · 다시 확인 필요" : "");
          return h("button", {
            className: `wc-dot ${dot.state}${dot.recheck ? " gap" : ""}`, role: "listitem",
            "data-i": dot.index, key: String(dot.index),
            "aria-label": `${dot.row}행 ${why}`, title: `${dot.row}행 · ${why}`,
            onClick: () => controller.guarded(() => controller.setCurrent(Number(dot.index))),
          });
        }))),
        h("article", {
          className: `wb-preview wc-render f-${snapshot.target_font || "gulimche"}`,
          id: "wbCard", "data-preserve-scroll": true,
        }, h(SegmentView as any, { segments: card.segments || [] })),
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
              }, "전각으로 바꾸기"))))),
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
