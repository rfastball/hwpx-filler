import { createElement as h } from "react";
import type { ReactNode } from "react";
import type { AuthoringController } from "./authoring_controller.ts";
import type { AuthoringLayout } from "./authoring_layout.ts";
import { PanelSplitter } from "./authoring_layout.ts";
import { Outline, crumbs } from "./authoring_outline.ts";
import { DocumentEditor } from "./authoring_editor.ts";
import type { ShellInput } from "./authoring_editor.ts";
import { SemanticForm } from "./authoring_properties.ts";
import { selectionNoteView } from "./authoring_commands.ts";
import { icon } from "./icons.ts";
import type { Obj } from "./authoring_primitives.ts";

export type BodyContext = { tabs: Obj[]; item: Obj | undefined; view: Obj; snapshot: Obj; outlineOpen: boolean;
  setOutlineOpen: (open: boolean) => void; controller: AuthoringController; counts: Map<string, number>;
  chooseFromOutline: (entry: Obj, element: HTMLElement) => void;
  outlineMenu: (entry: Obj, element: HTMLElement, anchor: { x: number; y: number; top?: number }) => void;
  contextMenu: (event: any) => void; layout?: AuthoringLayout | null; zoom: Obj;
  select: (entry: Obj) => () => void;
  shellInput: ShellInput; returnFocus: (slot: "properties" | "dock" | "error") => void };

export function renderAuthoringBody({ tabs, item, view, snapshot, outlineOpen, setOutlineOpen, controller, counts,
  chooseFromOutline, outlineMenu, contextMenu, layout, zoom, select, shellInput, returnFocus }: BodyContext): ReactNode {
  return     tabs.length > 0 && h("div", { className: `authoring-body${view.panel === "properties" ? " with-properties" : ""}${outlineOpen ? " outline-open" : ""}` },
      // 좁은 폭의 구조 레일(UX-08): 몸통 높이 띠의 그림 단추 — 이름은 기존 문장 그대로 aria-label·title 이다.
      item && h("button", { type: "button", className: "authoring-rail-toggle", "aria-expanded": outlineOpen, "aria-label": outlineOpen ? "구조 패널 숨기기" : "구조 패널 보기",
        title: outlineOpen ? "구조 패널 숨기기" : "구조 패널 보기", onClick: () => setOutlineOpen(!outlineOpen) }, icon(outlineOpen ? "chevron-left" : "chevron-right")),
      // 몸통의 자식은 한 배열이다 — 문서 탭마다 다시 서는 구조·속성 패널의 열쇠는 종류를 앞에 붙여 서로 겹치지 않게 한다
      // (같은 열쇠의 형제는 React 가 옛 원소를 지우지 못해 탭을 옮길 때마다 구조 열이 쌓였다, #1077).
      item && h(Outline, { key: `outline:${item.id}`, controller, item, view, counts, onSelect: chooseFromOutline, onMenu: outlineMenu, onContext: contextMenu }),
      item && h(PanelSplitter, { panel: "outline", label: "구조 패널 너비", layout }),
      // 가운데 열: 현재 위치의 의미(한 줄 경로) 바로 아래에 문서 편집면이 선다. 줄은 항상 자리를 지켜 캐럿 이동에 편집면이 밀리지 않는다.
      h("div", { className: "authoring-center" },
        item && h("div", { className: "authoring-selection", role: "navigation", "aria-label": "현재 위치의 의미" },
          // 뿌리 조각은 열린 문서 이름(글, 단추 아님) — 일치가 없어도 줄이 비어 보이지 않는다.
          h("span", { className: "authoring-crumb root", title: item.name }, item.name),
          // 조각은 테두리 알약이 아니라 글 링크다(UX-09) — 사이는 › 그림, 마지막(가장 안쪽) 조각은 굵게.
          ...crumbs(view.matches).flatMap((match: Obj, index: number, all: Obj[]) => [h("span", { key: `sep-${index}`, className: "authoring-crumb-sep" }, icon("chevron-right")),
            h("button", { key: index, type: "button", className: "authoring-crumb", onClick: select(match), "aria-current": index === all.length - 1 ? "location" : undefined },
              `${({ field: "필드", slot: "항목", option: "선택" } as Obj)[match.kind]} · ${match.name || match.label || match.option_id || match.slot_id}${match.approximate ? " · 문단 내 후보" : ""}`)]),
          // 위치 줄 메모(IDE-01): 줄 오른쪽 끝의 제자리 사유 한 줄(controller.note) — 다음 캐럿 이동·Escape 에서 걷힌다.
          selectionNoteView(view.selectionNote)),
        // 편집면은 화면 안의 이름 붙은 구획이다 — 앱 셸의 main 안에 main 을 겹치지 않는다(UX-04). 문서 탭이 이것을 가리킨다.
        h("section", { className: "authoring-canvas", id: "authoring-canvas", "aria-label": "원문 편집", style: { zoom: zoom.cssZoom }, onContextMenu: shellInput.current.menu = contextMenu }, ...tabs.map((tab) => h(DocumentEditor, { key: `${tab.id}:${controller.editorGeneration(tab.id)}`, item: tab, active: tab.id === snapshot.active_id, controller, shell: shellInput })))),
      item && view.panel === "properties" && h(PanelSplitter, { panel: "properties", label: "속성 패널 너비", layout }),
      item && view.panel === "properties" && h(SemanticForm, { key: `properties:${item.id}`, controller, selected: view.selected, selection: view.selection, preview: view.preview, onClose: () => returnFocus("properties") }),
      // 좁은 폭의 속성 시트 뒤 가림막 — 누르면 「닫기」와 같은 일을 한다(초점도 같은 자리로, 넓은 폭에서는 CSS 가 숨긴다).
      item && view.panel === "properties" && h("div", { className: "authoring-scrim", "aria-hidden": true,
        onClick: () => { controller.update({ panel: "", preview: null, refusal: null }); returnFocus("properties"); } }));
}
