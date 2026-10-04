/* 산출물 관찰 시트 — 만들어진 문서의 실물을 보기 전용으로 보는 면(S7-03 · #825, #1138).

   ## 예고가 아니라 실물이다(#820 D4)

   이 파일이 그리는 것은 **생성 후** 실물, 그것도 디스크에서 다시 읽어 기록 digest 와 대조를
   통과한 bytes 다. 골격 관용구(`.modal-card .sheet-card`·`.sheet-head`/`.sheet-body`)만
   공유하고 클래스는 `artifact-*`, 제목은 '산출물 관찰' 계열로 간다.

   ## 저작면의 렌더러를 보기 전용으로 쓴다(#1138)

   문서는 템플릿 저작면과 같은 rhwp(봉인된 Studio·WASM·폰트)로 쪽 모양 그대로 그린다. 마운트는
   `readOnly` 하나로 편집을 닫는다 — 보존 검사·도구 막대·선택 추적·문맥 메뉴·범위 고르기·장식이
   없고, 내보내기(onChanged)는 받지 않으며, Studio 가 넘기는 셸 키는 Escape(닫기)만 듣는다.
   저작 세션을 열지 않고 템플릿을 만지지 않는다. 어느 파일의 어느 bytes 인지는 Python 이 정한다
   (`job/artifact_content` 는 무페이로드 — 열린 면의 문서를 다시 관찰해 낸다).

   ## 상태를 여기서 판정하지 않는다

   열림·대상·성립 여부·사유는 Python 스냅샷(`artifact_view`)과 원료 응답에서 온다. 이 층은 그
   값을 자리에 놓고, 코드가 뜻하는 바를 문안으로 옮기는 지도 하나만 쓴다.

   ## 못 그린 것을 그린 것처럼 두지 않는다

   원료가 거절되거나(그사이 파일이 바뀌었다 등) 렌더러가 문서를 열지 못하면 빈 면이나 다른
   표현(텍스트 투영)으로 접지 않고 거절 면에 사유를 그대로 말한다. */

import { Fragment, createElement, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { mountRhwp } from "../editorview/rhwp_editor.ts";
import type { RhwpHandle, RhwpMountSpec } from "../editorview/rhwp_editor.ts";
import { keepFocusOutside } from "./authoring_trial.ts";
import type { JobRunController } from "./job_run.ts";
import { ARTIFACT_REFUSAL_TITLE, useRun, useRunSnapshot } from "./job_run.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 렌더러 마운트 자리 — 제품은 늘 mountRhwp 다. Node 시험은 WASM iframe 을 띄울 수 없어 여기만 바꿔 낀다. */
export const artifactRenderer = { mount: mountRhwp };

/** 렌더러가 문서를 열지 못한 실패의 표지(DOM `data-status` 용 — 사용자 문안이 아니다). */
export const ARTIFACT_RENDER_FAILED = "ARTIFACT_RENDER_FAILED";

export type ArtifactShown =
  | { state: "loading" }
  | { state: "rendered" }
  | { state: "failed"; status: string; detail: string };

const noop = () => {};

/** 보기 전용 마운트 인자. 편집으로 이어지는 훅(보존 검사·선택·문맥 메뉴·범위 고르기)을 하나도 싣지 않는다.
 *  폭 맞춤은 마운트마다 명시한다(IDE-06 — Studio 가 맞춤 방식을 설정에 남긴다). */
export function artifactViewerSpec(host: HTMLElement, content: string, filename: string,
  callbacks: { onClose: () => void; onError: (error: unknown) => void }): RhwpMountSpec {
  return {
    host, content, fileName: filename, title: filename, readOnly: true, zoom: "fit", trackSelection: "never",
    onChanged: noop, onSelectionChanged: noop, onError: callbacks.onError,
    // iframe 안의 Escape 는 셸까지 올라오지 못한다 — Studio 가 넘긴 것만 닫기로 잇는다. 저장 등 그 밖의 키는 버린다.
    onShortcut: (shortcut) => { if (shortcut === "Escape") callbacks.onClose(); },
  };
}

/** 실패 하나를 거절 면의 값으로 — 오류 문장은 그대로 사유가 된다. */
export function renderFailure(error: unknown): ArtifactShown {
  const detail = String((error as { message?: unknown } | null)?.message ?? error);
  return { state: "failed", status: ARTIFACT_RENDER_FAILED, detail };
}

/** 원료를 받아 보기 전용으로 띄운다. 원료 거절·요청 실패·마운트 실패는 모두 거절 면 값으로 돌아온다. */
export async function showArtifact(args: {
  fetch: () => Promise<Obj>;
  mount: (spec: RhwpMountSpec) => Promise<RhwpHandle>;
  host: HTMLElement;
  filename: string;
  onClose: () => void;
  onError: (error: unknown) => void;
}): Promise<{ shown: ArtifactShown; handle: RhwpHandle | null }> {
  try {
    const reply = await args.fetch();
    if (reply.ok !== true) {
      return { shown: { state: "failed", status: String(reply.status || ""), detail: String(reply.detail || "") }, handle: null };
    }
    const handle = await args.mount(artifactViewerSpec(args.host, String(reply.content || ""), args.filename,
      { onClose: args.onClose, onError: args.onError }));
    return { shown: { state: "rendered" }, handle };
  } catch (error) {
    return { shown: renderFailure(error), handle: null };
  }
}

function Refused(props: { status: string; detail: string }): ReactNode {
  return h("section", {
    className: "picker-sec artifact-refused", id: "artifactRefused", "data-status": props.status,
  },
    h("p", { className: "note dangerbox", id: "artifactRefusedTitle" },
      ARTIFACT_REFUSAL_TITLE[props.status] || "문서를 확인하지 못했습니다"),
    h("p", { className: "capnote", id: "artifactRefusedDetail" }, props.detail));
}

/** 관찰이 선 문서 하나의 보기 — 열린 면(ordinal)마다 새로 원료를 받아 마운트하고 닫히면 해제한다. */
function ArtifactDocument(props: { controller: JobRunController; ordinal: number; filename: string }): ReactNode {
  const host = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState<ArtifactShown>({ state: "loading" });
  useEffect(() => {
    let disposed = false;
    let release: (() => void) | undefined;
    const before = document.activeElement;
    void showArtifact({
      fetch: async () => expectHostValue(
        await props.controller.client.dispatch("job", "artifact_content", {}), "job/artifact_content") as Obj,
      mount: (spec) => artifactRenderer.mount(spec),
      host: host.current!, filename: props.filename,
      onClose: props.controller.closeArtifact,
      onError: (error) => { if (!disposed) setShown(renderFailure(error)); },
    }).then(({ shown: next, handle }) => {
      if (disposed) { handle?.dispose(); return; }
      if (handle) release = () => handle.dispose();
      // Studio 는 문서를 싣는 동안 제 iframe 에 초점을 준다 — 시트가 준 초점(닫기)으로 돌린다.
      keepFocusOutside(host.current, before);
      setShown(next);
    });
    return () => { disposed = true; release?.(); };
  }, [props.controller, props.ordinal]);
  const failed = shown.state === "failed" ? shown : null;
  return createElement(Fragment, null,
    failed ? createElement(Refused as any, { status: failed.status, detail: failed.detail }) : null,
    h("div", {
      ref: host, className: "artifact-doc", id: "artifactDoc", "data-state": shown.state,
      "aria-busy": shown.state === "loading" ? "true" : undefined, hidden: !!failed,
    }));
}

export function JobArtifactSheet(props: { controller: JobRunController }): ReactNode {
  const snapshot = useRunSnapshot(props.controller);
  const run = useRun(props.controller);
  const view = (snapshot?.artifact_view || {}) as Obj;
  const status = String(view.status || "");
  const filename = String(view.filename || "");
  const ordinal = Number(view.ordinal);
  const observed = view.open === true && status === "observed";
  const saved = run.artifactSave;

  return h("div", { className: "modal-card sheet-card artifact-sheet" },
    h("div", { className: "sheet-head" },
      h("h3", { id: "artifactTitle" },
        filename ? `산출물 관찰: ${filename}` : "산출물 관찰"),
      h("button", {
        className: "btn", id: "artifactClose", type: "button",
        onClick: props.controller.closeArtifact,
      }, "닫기")),
    h("div", { className: "sheet-body artifact-sheet-body" },
      observed
        ? createElement(ArtifactDocument as any, {
            key: `${ordinal}:${filename}`, controller: props.controller, ordinal, filename,
          })
        : createElement(Refused as any, { status, detail: String(view.detail || "") })),
    h("div", { className: "modal-actions" },
      h("span", {
        className: "capnote", id: "artifactSaveNote", role: "status",
        "aria-live": "polite",
      }, saved),
      h("button", {
        className: "btn primary", id: "artifactSaveAs", type: "button",
        // 저장의 원료는 관찰한 bytes 다. 관찰이 서지 않은 상태에서 버튼을 열어 두면
        // 저장할 수 있을 것 같은 미끼가 되고, 실제로 눌리면 백엔드가 거절한다.
        disabled: !observed,
        onClick: () => { void props.controller.saveArtifactAs(); },
      }, "다른 이름으로 저장")));
}
