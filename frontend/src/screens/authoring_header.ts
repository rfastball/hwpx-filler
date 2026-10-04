import { createElement as h } from "react";
import type { ReactNode } from "react";
import type { AuthoringController } from "./authoring_controller.ts";
import { button, quiet, iconButton } from "./authoring_primitives.ts";
import type { Obj } from "./authoring_primitives.ts";
import { roveFocus, tabName } from "./authoring_a11y.ts";

export type HeaderContext = { controller: AuthoringController; tabs: Obj[]; snapshot: Obj;
  act: (work: () => unknown, kind?: string) => () => void;
  menuToggle: (kind: "more" | "file") => (event: any) => void;
  menuButton: (kind: "more" | "file") => Obj;
  closeTab: (id: string) => void; item: Obj | undefined };

export function renderAuthoringHeader({ controller, tabs, snapshot, act, menuToggle, menuButton, closeTab, item }: HeaderContext): ReactNode {
  return     h("header", { className: "authoring-head" },
      iconButton("chevron-left", "돌아가기", act(() => controller.leaveTo(controller.returnScreen()))),
      h("h1", null, "템플릿 저작"),
      quiet("파일", menuToggle("file"), menuButton("file")),
    // 열린 문서 탭(APG tabs, 수동 활성화): ←→·Home·End 로 옮기고 Enter·Space 로 연다. Delete 는 닫기(닫기 보호 그대로).
    // 닫기 단추는 탭 안의 마우스용 표지다 — tab 의 자식은 표시용이라 Tab 순서에 두지 않는다(tabIndex -1).
    tabs.length > 0 && h("div", { className: "authoring-tabs", role: "tablist", "aria-label": "열린 문서", onKeyDown: (event: any) => {
      if (roveFocus(event, event.currentTarget, '[role="tab"]', "horizontal")) return;
      const tab = (event.target as HTMLElement).closest?.('[role="tab"]');
      const id = tab?.getAttribute("data-tab");
      if (!id || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); act(() => controller.activate(id))(); }
      else if (event.key === "Delete") { event.preventDefault(); closeTab(id); }
    } }, ...tabs.map((tab) => {
      const selected = tab.id === snapshot.active_id;
      const dirty = !!(tab.dirty || controller.pending(tab.id));
      return h("div", { key: tab.id, className: "authoring-tab", role: "tab", "data-tab": tab.id, tabIndex: selected ? 0 : -1, "aria-selected": selected,
        "aria-controls": "authoring-canvas", "aria-label": tabName(tab.name, dirty), "aria-keyshortcuts": "Delete", onClick: act(() => controller.activate(tab.id)) },
        // 미저장 표지는 글자가 아니라 점 원소다 — 뜻은 탭 이름(tabName)이 싣는다.
        h("span", { className: "authoring-tab-name" }, tab.name), dirty ? h("span", { className: "authoring-dirty", "aria-hidden": true }) : null,
        iconButton("close", `${tab.name} 닫기`, (event: any) => { event.stopPropagation(); closeTab(tab.id); }, { tabIndex: -1 }));
    })),
      // 머리 띠의 주 행동은 저장이다 — 저장할 변경이 있거나 새 템플릿이라 저장이 필요할 때만 채움으로 선다.
      button("저장", act(() => controller.save(), "save"), { "data-guide": "save-template", disabled: !item,
        className: item && (item.dirty || item.save_as_required || controller.pending(item.id)) ? "btn primary" : "btn quiet" }));
}
