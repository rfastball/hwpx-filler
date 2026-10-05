import type { AuthoringController } from "./authoring_controller.ts";
import type { Obj } from "./authoring_primitives.ts";
import { focusRequest, PALETTE_SELF } from "./authoring_commands.ts";
import type { MenuAction } from "./authoring_commands.ts";
import { PROPOSAL_COPY } from "./authoring_proposal.ts";
import { proposalReadOnly } from "./authoring_proposal_view.ts";

type ActionContext = { controller: AuthoringController; item: Obj | undefined;
  act: (work: () => unknown, kind?: string) => () => void;
  openPalette: () => void; openPanel: (panel: string) => void };

/** 파일·더보기 메뉴와 팔레트가 공유하는 셸 동사. */
export function shellMenuActions({ controller, item, act, openPalette, openPanel }: ActionContext): { moreActions: MenuAction[]; fileActions: MenuAction[] } {
  const moreActions: MenuAction[] = [
    [PALETTE_SELF, () => openPalette(), false, "Ctrl+Shift+P"],
    ["의미 복사", act(async () => { await controller.copy(); controller.update(focusRequest(controller.viewModel.getSnapshot(), "dock")); }), false],
    ["의미 붙여넣기", () => openPanel("paste"), !controller.clipboard()],
    ["이전 위치로", act(controller.back), false],
    // 「데이터로 필드 찾기…」(#1156) — 데이터 한 행으로 필드 자리를 찾는 띠를 켠다. 원문을 고칠 수 없으면 흐리다.
    [PROPOSAL_COPY.menu, act(() => controller.proposal.find()), proposalReadOnly(item)]];
  const fileActions: MenuAction[] = [
    ["문서 열기", act(controller.openFile), false],
    ["새 TXT", act(controller.create), false],
    ["저장", act(() => controller.save(), "save"), !item, "Ctrl+S"],
    ["다른 이름으로 저장", act(() => controller.save(item?.id, true), "save"), !item]];
  return { moreActions, fileActions };
}
