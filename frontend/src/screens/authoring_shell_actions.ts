import type { AuthoringController } from "./authoring_controller.ts";
import type { Obj } from "./authoring_primitives.ts";
import { focusRequest, PALETTE_SELF } from "./authoring_commands.ts";
import type { MenuAction } from "./authoring_commands.ts";

type ActionContext = { controller: AuthoringController; item: Obj | undefined;
  act: (work: () => unknown, kind?: string) => () => void;
  openPalette: () => void; openPanel: (panel: string) => void };

/** 파일·더보기 메뉴와 팔레트가 공유하는 셸 동사. */
export function shellMenuActions({ controller, item, act, openPalette, openPanel }: ActionContext): { moreActions: MenuAction[]; fileActions: MenuAction[] } {
  const moreActions: MenuAction[] = [
    [PALETTE_SELF, () => openPalette(), false, "Ctrl+Shift+P"],
    ["의미 복사", act(async () => { await controller.copy(); controller.update(focusRequest(controller.viewModel.getSnapshot(), "dock")); }), false],
    ["의미 붙여넣기", () => openPanel("paste"), !controller.clipboard()],
    ["이전 위치로", act(controller.back), false]];
  const fileActions: MenuAction[] = [
    ["문서 열기", act(controller.openFile), false],
    ["새 TXT", act(controller.create), false],
    ["저장", act(() => controller.save(), "save"), !item, "Ctrl+S"],
    ["다른 이름으로 저장", act(() => controller.save(item?.id, true), "save"), !item]];
  return { moreActions, fileActions };
}
