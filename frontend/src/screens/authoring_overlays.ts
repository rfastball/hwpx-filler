import { createElement as h } from "react";
import type { ReactNode } from "react";
import type { AuthoringController } from "./authoring_controller.ts";
import { roveFocus, focusable } from "./authoring_a11y.ts";
import { CommandPalette, ariaKeys } from "./command_palette.ts";
import type { CommandEntry, PaletteAction } from "./command_palette.ts";
import { CommandMenu, MENU_REASON_ID } from "./authoring_commands.ts";
import type { MenuAction } from "./authoring_commands.ts";
import { quiet } from "./authoring_primitives.ts";
import type { Obj } from "./authoring_primitives.ts";

type OverlayContext = { controller: AuthoringController; item: Obj | undefined; view: Obj;
  menuRef: React.RefObject<HTMLDivElement | null>; menuReason: string | null; fileActions: MenuAction[]; moreActions: MenuAction[];
  commandTable: CommandEntry[]; readOnly: boolean; menuEditor: boolean; pick: (commandType: string) => void;
  openPalette: (opener?: unknown) => void; barShown: boolean; barRef: React.RefObject<HTMLDivElement | null>;
  barItems: { key: string; label: string; command: string }[]; setBarAnchor: (anchor: null) => void;
  paletteTable: CommandEntry[]; paletteActions: PaletteAction[]; closePalette: (restore: boolean) => void };

export function renderAuthoringOverlays({ controller, item, view, menuRef, menuReason, fileActions, moreActions,
  commandTable, readOnly, menuEditor, pick, openPalette, barShown, barRef, barItems, setBarAnchor,
  paletteTable, paletteActions, closePalette }: OverlayContext): ReactNode[] {
  return [
    // 문맥 메뉴·더보기(§6.1·APG menu): ↑↓·Home·End 로 옮기고 Tab 은 메뉴를 닫는다. 문맥 메뉴는 되는 명령과 대안만 싣는다
    // (IDE-02) — 불가 사유는 명령 팔레트가 읽힌다. 되는 것이 없으면 공유 사유 머리 줄 + 「명령」 한 줄이다. 단 하나의 예외:
    // 편집면에서 연 메뉴의 「필드로 만들기」는 불가여도 사유와 함께 선다(결정 C).
    // 「더보기」·「파일」의 불가 항목은 초점을 받는다(자리를 기억하는 메뉴다).
    view.contextMenu && (item || view.contextMenu.kind === "file") && h("div", { className: "authoring-context-menu", ref: menuRef, style: { left: view.contextMenu.x, top: view.contextMenu.y },
      onKeyDown: (event: any) => {
        if (roveFocus(event, event.currentTarget, '[role="menuitem"]', "vertical")) return;
        if (event.key === "Tab") { const trigger = view.contextMenu?.trigger; controller.update({ contextMenu: null }); if (focusable(trigger)) trigger.focus(); }
      } },
      !view.contextMenu.kind && menuReason && h("p", { id: MENU_REASON_ID, className: "authoring-reason" }, menuReason),
      h("div", { className: "authoring-menu", id: "authoring-menu", role: "menu", "aria-label": view.contextMenu.kind === "more" ? "더보기" : view.contextMenu.kind === "file" ? "파일" : "문맥 명령" },
        view.contextMenu.kind
          ? (view.contextMenu.kind === "file" ? fileActions : moreActions).map(([label, run, disabled, keys]) => h("button", { key: label, type: "button",
            className: `authoring-menu-item${keys ? " with-key" : ""}`, role: "menuitem", tabIndex: -1, "aria-disabled": disabled || undefined, "aria-keyshortcuts": ariaKeys(keys),
            onClick: () => { if (disabled) return; const trigger = view.contextMenu?.trigger; if (focusable(trigger)) trigger.focus(); controller.update({ contextMenu: null }); run(); } },
            label, keys ? h("kbd", { className: "authoring-key", "aria-hidden": true }, keys) : null))
          : h(CommandMenu, { entries: commandTable, readOnly, editor: menuEditor, reason: menuReason, onPick: pick, onPalette: () => { const trigger = view.contextMenu?.trigger; controller.update({ contextMenu: null }); openPalette(trigger); } }))),
    // 선택 옆 막대(IDE-08 P-05): 이름 없는 group 이다 — 「문서 명령」 도구 막대와 이름이 겹치지 않는다. 단추는 기존 명령 이름이고
    // Tab 순서 밖(tabIndex -1)이며, 누름이 초점을 먼저 가져가지 않는다(mousedown 기본 동작 없음). 누르면 도구 막대·문맥 메뉴와
    // 같은 pick 경로다 — 만들기 폼이 제안 이름과 함께 서고 Enter 한 번이면 선다(IDE-03).
    barShown && h("div", { className: "authoring-selection-bar", role: "group", ref: barRef, onMouseDown: (event: any) => event.preventDefault() },
      ...barItems.map((entry) => quiet(entry.label, () => { setBarAnchor(null); pick(entry.command); },
        { key: entry.key, tabIndex: -1 }))),
    // 명령 팔레트(IDE-02): 비모달 오버레이 — 여는 차례 번호가 열쇠라 다시 열면 입력이 비고 초점이 입력칸으로 간다.
    item && view.palette ? h(CommandPalette, { key: view.palette, entries: paletteTable, actions: paletteActions, onPick: pick, onClose: closePalette }) : null,
  ];
}
