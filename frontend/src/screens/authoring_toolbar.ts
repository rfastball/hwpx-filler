import { createElement as h } from "react";
import type { ReactNode } from "react";
import { AUTHORING_COPY } from "./authoring_controller.ts";
import type { AuthoringController } from "./authoring_controller.ts";
import { MODES } from "./authoring_shell_state.ts";
import { roveFocus } from "./authoring_a11y.ts";
import { button, quiet, iconButton } from "./authoring_primitives.ts";
import type { Obj } from "./authoring_primitives.ts";

export type ToolbarContext = { controller: AuthoringController; item: Obj | undefined; view: Obj;
  act: (work: () => unknown, kind?: string) => () => void;
  toolbarKey: string; setToolbarKey: (key: string) => void;
  undoDisabled: boolean; redoDisabled: boolean; readOnly: boolean; creates: Obj[];
  rove: (key: string) => Obj;
  pick: (commandType: string) => void;
  menuToggle: (kind: "more" | "file") => (event: any) => void;
  menuButton: (kind: "more" | "file") => Obj;
  trialShown: boolean; openDock: (key: string) => void };

export function renderAuthoringToolbar({ controller, item, view, act, toolbarKey, setToolbarKey,
  undoDisabled, redoDisabled, readOnly, creates, rove, pick, menuToggle, menuButton, trialShown, openDock }: ToolbarContext): ReactNode {
  return     item && h("div", { className: "authoring-toolbar", role: "toolbar", "aria-label": "문서 명령",
      onKeyDown: (event: any) => { roveFocus(event, event.currentTarget, "[data-rove]:not([disabled])", "horizontal"); },
      onFocus: (event: any) => { const key = event.target?.getAttribute?.("data-rove"); if (key && key !== toolbarKey) setToolbarKey(key); } },
      // 실행 취소·다시 실행은 그림 단추다 — 되돌릴 명령의 이름은 툴팁·이름과 live region 이 싣는다(새 문구 없음).
      h("div", { className: "authoring-toolbar-group" },
        iconButton("undo", `문서 실행 취소${view.lastCommandLabel ? `: ${view.lastCommandLabel}` : ""}`, act(() => controller.command("undo")), { disabled: undoDisabled, ...rove("undo") }),
        iconButton("redo", "문서 다시 실행", act(() => controller.command("redo")), { disabled: redoDisabled, ...rove("redo") })),
      h("div", { className: "authoring-toolbar-group" }, h("div", { className: "authoring-mode", role: "group", "aria-label": "표시" },
        ...MODES.map(([value, label]) => h("button", { key: value, type: "button", value, "aria-pressed": view.mode === value, ...rove(`mode-${value}`), onClick: () => controller.setMode(value) }, label)))),
      h("div", { className: "authoring-toolbar-group" },
        ...creates.map(({ commandType, label, available, disabled, dimmed }) =>
          quiet(label, disabled ? () => {} : dimmed ? () => controller.note(String(available.reason || "")) : () => pick(commandType),
            { key: commandType, disabled, "aria-disabled": disabled || dimmed || undefined, title: available.reason || undefined, ...rove(commandType) })),
        // 범위 고르기(두 번 누름): 시작 자리를 누르고, 스크롤해 끝 자리를 누르면 그 사이가 선택된다 — 표로 끝나는 범위도 고른다.
        // TXT·HWPX 모두. 켠 동안 눌린 단추(aria-pressed)이고 Escape·다시 누름으로 접는다.
        !readOnly && h("button", { key: "range-pick", type: "button", className: "btn quiet", "aria-pressed": !!view.rangePick,
          ...rove("range-pick"), onClick: () => controller.toggleRangePick() }, AUTHORING_COPY.rangePick)),
      // 명령 팔레트(Ctrl+Shift+P)·복사·붙여넣기·이전 위치로는 「더보기」 메뉴 안에 선다.
      h("div", { className: "authoring-toolbar-group" },
        iconButton("more", "더보기", menuToggle("more"), { ...menuButton("more"), ...rove("more") })),
      // 막대의 실행 단추는 결과 시험 하나다 — 테두리 단추로 남는 유일한 명령이다.
      h("div", { className: "authoring-toolbar-group authoring-toolbar-end" },
        button("결과 시험", () => { if (trialShown) controller.update({ trial: false, dock: "" }); else openDock("trial"); }, { "aria-pressed": trialShown, ...rove("trial") })));
}
