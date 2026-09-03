/* 「자세히…」가 여는 **항목 상세 시트의 골격** — 두 시트가 이 컴포넌트의 두 인스턴스다:
 * 좌 열의 템플릿 항목(`#tplDetailModal`)과 우 열의 등록 데이터(`#poolDetailModal`).
 *
 * 골격이 하나인 이유는 고르기 열(`pool_column.ts`)이 하나인 이유와 같다: 두 시트가 답하는
 * 질문의 **형**이 같기 때문이다 — 정체(이름·배지) · 경로와 그 문 · 못 읽은 사유 · 구조 표 ·
 * 동사의 성과와 실패 · 관리 동사 줄. 각자 그리면 오류 상자의 자리, 결과 줄이 스크림 앞인지
 * 뒤인지, 닫기 버튼의 초점 같은 것들이 한쪽에서만 고쳐진다.
 *
 * **판정도 문안도 여기 없다.** 이 파일이 아는 것은 좌표(`idPrefix`)와 배치뿐이고, 값은 전부
 * 각 채널의 상세 존(Python 링1 `TemplateDetail`·`DatasetDetail`)이 낸다.
 *
 * 좌표 계약: `${idPrefix}` + `Title`·`Path`·`Error`·`Msg`·`Result`·`Verbs`·`Close`·`Empty`.
 * 두 접두어(`tplDetail`·`poolDetail`)의 이 여덟 자리를 게이트가 든다.
 */
import { createElement } from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import type { ContextMenuItem } from "./context_menu.ts";
import { PathActions } from "./path_actions.ts";

/** 상세가 없을 때의 한 문장 — 템플릿·데이터 두 시트가 같은 말을 한다(문장 두 벌 금지). */
export const DETAIL_SHEET_EMPTY = "볼 항목이 없습니다. 목록에서 항목의 ⋮ → 「자세히…」를 누르세요.";

type Obj = Record<string, any>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

export type DetailSheetProps = {
  /** DOM 좌표의 접두어 — `"tplDetail"` / `"poolDetail"`. */
  idPrefix: string;
  /** 머리의 이름. 상세가 없을 때(`empty`)는 그 면의 이름이 선다. */
  title: string;
  /** 머리의 배지(없으면 서지 않는다). */
  pill?: { label: string; level: string } | null;
  /** 겨누는 파일의 경로 — 있으면 경로 줄과 그 문(`PathActions`)이 함께 선다. */
  path?: string;
  client: BridgeClient;
  notify: (message: string) => void;
  /** 판독 실패 사유 — 숨기지 않는다(오류 항목에서 「자세히…」가 서는 이유가 이것이다). */
  error?: string;
  /** 구조 진단(경고) — 사유와 다른 축이라 함께 선다. */
  diagnostics?: string[];
  /** 동사 실패의 재진술 — 이 면 **안**에 선다(시트가 화면을 덮으므로 뒤 채널은 안 보인다). */
  message?: string;
  /** 채널 결과 줄(Python 문안 그대로). */
  result?: { text?: string; level?: string } | null;
  /** 몸통 — 시트마다 다른 유일한 덩어리(필드 표·구간 항목 / 정체 줄·열 표). */
  body?: ReactNode;
  /** 관리 동사 줄 — 행 ⋯ 와 **같은 목록**에서 「자세히…」만 걷은 것이다. */
  verbs?: ContextMenuItem[];
  onVerb?(action: string, trigger: HTMLElement): void;
  onClose(): void;
  /** 비어 있을 때의 안내 — 값이 있으면 **빈 면**을 그린다(몸통·동사 줄 없음). */
  empty?: string;
};

/** 성과와 실패 두 줄 — 빈 면에도 선다(동사가 상세를 걷어 갈 수 있다). */
function feedback(props: DetailSheetProps): ReactNode[] {
  const { idPrefix } = props;
  const result = props.result || {};
  const level = String(result.level || "");
  return [
    props.message
      ? h("p", {
        className: "note dangerbox", id: `${idPrefix}Msg`, role: "alert", key: "msg",
      }, String(props.message))
      : null,
    result.text
      ? h("div", {
        key: "result",
        className: `run-result${level && level !== "muted" ? " " + level : ""}`,
        id: `${idPrefix}Result`,
      }, String(result.text))
      : null,
  ];
}

export function DetailSheetFrame(props: DetailSheetProps): ReactNode {
  const { idPrefix } = props;
  const close = h("button", {
    className: "btn", id: `${idPrefix}Close`, type: "button",
    onClick: () => { props.onClose(); },
  }, "닫기");
  if (props.empty) {
    return h("div", { className: "modal-card" },
      h("h3", { id: `${idPrefix}Title` }, props.title),
      h("p", { className: "note", id: `${idPrefix}Empty` }, props.empty),
      ...feedback(props),
      h("div", { className: "modal-actions" }, close));
  }
  const pill = props.pill || null;
  const path = String(props.path || "");
  const diagnostics = props.diagnostics || [];
  const verbs = props.verbs || [];
  return h("div", { className: "modal-card detail-sheet" },
    h("div", { className: "row" },
      h("h3", { id: `${idPrefix}Title` }, props.title),
      pill ? h("span", { className: `pill ${pill.level || "muted"}` }, pill.label) : null,
      h("span", { className: "spacer" }),
      close),
    /* 경로는 상태와 무관하게 선다 — 「파일을 고치세요」라고 말하는 그 자리에서 고치러 갈
       길이 사라지면 안 된다(게이트 존 리뷰 8 과 같은 근거). */
    path
      ? h("p", {
        className: "muted capnote detail-path", id: `${idPrefix}Path`,
      }, path)
      : null,
    path
      ? h(PathActions as any, { client: props.client, path, notify: props.notify })
      : null,
    props.error
      ? h("p", { className: "note dangerbox", id: `${idPrefix}Error` }, String(props.error))
      : null,
    ...diagnostics.map((text, index) =>
      h("p", { className: "note warnbox", key: `diag-${index}` }, text)),
    props.body || null,
    ...feedback(props),
    verbs.length
      ? h("div", { className: "modal-actions", id: `${idPrefix}Verbs` },
        ...verbs.map((entry) => h("button", {
          className: "btn", key: entry.action, "data-act": `detail-${entry.action}`,
          onClick: (event: Obj) => props.onVerb?.(entry.action, event.currentTarget),
        }, entry.label)))
      : null);
}
