/* 라이브러리 좌·우 열 ⋮ 메뉴와 항목 상세 시트·Slot(컴파일된 구간) 동사. 공유 상태(뷰·스냅샷·
 * 발신)는 deps로 받는다. */
import { createContextMenu } from "./context_menu.ts";
import type { ContextMenuItem } from "./context_menu.ts";
import { dataRowMenuItems, ROW_DETAIL_LABEL } from "./pool_verbs.ts";
import { SESSION_DATA_KEY } from "./pool_column.ts";
import type { ModalPort, Obj } from "./editor_controller.ts";

/** 템플릿 행 ⋮ 의 동사표 — 메뉴와 상세 시트가 이 하나를 공유한다. */
export function libRowMenuItems(media: string, item: Obj | null): ContextMenuItem[] {
  if (item === null || item === undefined) return [];
  const detail: ContextMenuItem = { action: "detail", label: ROW_DETAIL_LABEL };
  if (media === "hwpx") {
    return [
      { action: "edit", label: "템플릿 편집" },
      ...((item.actions || []) as Obj[]).map((action: Obj) =>
        ({ action: `act:${String(action.key)}`, label: String(action.label) })),
      detail,
    ];
  }
  return !!item.error || !!item.reason
    ? [detail] : [{ action: "edit", label: "내용 편집" }, detail];
}

export type LibMenu = {
  /** 어느 열의 행인가 — 두 열이 같은 ⋯ 를 쓰므로 **동사표가 이 값으로 갈린다**(③a).
   *  키만으로는 가를 수 없다: 좌는 루트 상대경로, 우는 풀 슬롯 키라 우연히 같을 수 있다. */
  side: "tpl" | "dat";
  media: string;
  kind: "row";
  key?: string;
  item?: Obj | null;
  trigger: HTMLElement;
};

/** 좌 열 항목 전수 — 정본은 `tpl` 채널의 **공용 열 존**(`column.rows`) 하나다.
 *
 *  종전에는 매체별 밴드(`hwpx`/`txt` 의 `sections[].items[]`)를 여기서 이어 붙여 한
 *  목록으로 만들었다. 그 접기는 이제 Python 이 하고(좌·우 열이 같은 형을 쓰는 조건),
 *  표면이 그 순서를 두 번 짓지 않는다 — 목록이 갈릴 자리가 사라진다. */
export function libItems(tplModel: { getSnapshot(): Obj | null }): Obj[] {
  return (((tplModel.getSnapshot() || {}).column || {}).rows || []) as Obj[];
}

/** 좌 열 항목 하나 — 매체는 행이 든 표지(`icon`)로 대조한다.
 *
 *  키만으로 찾지 않는 이유는 ⋮ 의 열림 상태가 `(media, key)` 쌍이기 때문이다: 겨눈 행이
 *  바뀌었는데 키가 같으면 지난 행의 메뉴가 그대로 서 있게 된다. */
export function findLibItem(
  tplModel: { getSnapshot(): Obj | null }, media: string, key: string,
): Obj | null {
  return libItems(tplModel).find(
    (row) => String(row.key) === key && String(row.icon || "") === media) || null;
}

/** 우 열 항목 하나 — 목록 행(`pool.column.rows`)과 세션 행(`pairing.data_row`)의 합.
 *
 *  세션 행은 풀에 없는 결속(파일로 연 데이터)이라 `pool` 채널에 없다. 그 행을 여기서
 *  찾지 못하면 그 행의 ⋯ 가 조용히 빈 메뉴가 된다 — 두 출처를 같은 자리에서 본다. */
export function findDataItem(
  poolModel: { getSnapshot(): Obj | null }, snapshot: () => Obj, key: string,
): Obj | null {
  if (key === SESSION_DATA_KEY) {
    return ((snapshot().pairing || {}) as Obj).data_row as Obj | null || null;
  }
  const rows = (((poolModel.getSnapshot() || {}).column || {}).rows || []) as Obj[];
  return rows.find((row) => String(row.key) === key) || null;
}

type SlotMenusView = {
  libMenu: LibMenu | null;
  detailOpen: boolean;
  detailMessage: string | null;
};

export type SlotMenusDeps = {
  modal: ModalPort;
  notify(message: string): void;
  tplModel: { getSnapshot(): Obj | null };
  poolModel: { getSnapshot(): Obj | null };
  snapshot(): Obj;
  /** 편집기 자신의 `dispatch` — `tpl` 채널에 쏘면 editor 재당김까지 같은 자리가 진다. */
  dispatch(screen: string, action: string, payload?: Obj): Promise<Obj>;
  /** 좌 열 「템플릿 편집」 — 저작 작업대를 그 경로로 연다. */
  openAuthoringAt(path: string): Promise<unknown>;
  /** 우 열 분기표는 데이터 선택 컨트롤러와 공유한다(공용 ⑤ 리뷰) — 이 모듈이 데이터 동사를
   *  발명하지 않는다. */
  runPoolVerb(action: string, item: Obj, trigger: HTMLElement): Promise<void>;
  getView(): SlotMenusView;
  patchView(next: Partial<SlotMenusView>): void;
  noticeSave(message: string): void;
};

export function createSlotMenus(deps: SlotMenusDeps) {
  // 발신은 바로 부른다 — 브리지 계약 검사가 리터럴 화면·동작의 payload 를 읽는다.
  const { dispatch } = deps;
  const libContextMenu = createContextMenu();

  function closeLibMenu(): void {
    deps.patchView({ libMenu: null });
    libContextMenu.close();
  }

  /* 겨눔은 **행 하나**다 — 그룹 갈래는 U4 §2-30 에서 그룹 표면과 함께 사라졌다. */
  function openLibMenu(
    side: "tpl" | "dat", media: string, id: string, trigger: HTMLElement,
  ): void {
    const item = side === "tpl"
      ? findLibItem(deps.tplModel, media, id) : findDataItem(deps.poolModel, deps.snapshot, id);
    const items: ContextMenuItem[] = side === "tpl"
      ? libRowMenuItems(media, item) : dataRowMenuItems(item);
    /* 동작이 0 이면 애초에 트리거가 비활성이라 여기 오지 않는다(어포던스는 `LibRowTail`
       이 같은 술어로 잠근다) — 그래도 방어로 남긴다: 빈 팝오버는 「눌렀는데 아무 일도
       없다」라서 조용한 no-op 이다. */
    if (items.length === 0) return;
    deps.patchView({ libMenu: { side, media, kind: "row", key: id, item, trigger } });
    libContextMenu.open(trigger, items);
  }

  function toggleLibMenu(
    side: "tpl" | "dat", media: string, id: string, trigger: HTMLElement,
  ): void {
    const open = deps.getView().libMenu;
    if (open !== null && open.side === side && open.media === media && open.key === id) {
      closeLibMenu(); return;
    }
    openLibMenu(side, media, id, trigger);
  }

  /** 항목 동사의 **단일 분기표**(U6-E 리뷰 9) — 행 ⋮ 와 시트 동사 줄이 같은 것을 본다.
   *
   *  갈리는 것은 **대상과 실패의 착지**뿐이라 둘 다 인자로 받는다: 행 메뉴는 눌린 행을
   *  겨누고 예외를 경보 백스톱으로 보내며, 시트는 열려 있는 항목을 겨누고 사유를 시트 안에
   *  남긴다. 표를 복제하면 한쪽에만 동사가 늘어나는 날이 온다.
   *
   *  **닫힌 집합이다**: 모르는 키를 조용히 떨어뜨리면 메뉴에 항목을 더하고 배선을 잊은 날
   *  「눌렀는데 아무 일도 없다」가 된다. 목록을 짓는 곳(`libRowMenuItems`)과 여기가 같은
   *  집합을 봐야 하고, 어긋남은 던진다. `act:review` 가 없는 것은 계약이다 — 검토 왕복은
   *  「자세히…」 하나가 진다(리뷰 10).
   */
  async function runItemVerb(
    action: string, target: Obj, trigger: HTMLElement,
  ): Promise<void> {
    const path = String(target.path || "");
    if (action === "edit") {
      await deps.openAuthoringAt(path);
    } else if (action === "detail") await openDetail(path, trigger);
    else if (action === "act:compile") await compileTemplate(path);
    else throw new Error(`알 수 없는 항목 동사입니다: ${action}`);
  }

  async function handleLibMenu(action: string): Promise<void> {
    const menu = deps.getView().libMenu;
    if (menu === null) return;
    const item = (menu.item || {}) as Obj;
    const trigger = menu.trigger;
    const side = menu.side;
    closeLibMenu();
    try {
      /* 우 열 분기표는 **공용 몸통 하나**다(공용 ⑤ 리뷰) — 이 화면이 데이터 동사를
         발명하지 않는다. 좌 열(`runItemVerb`)은 tpl 채널이라 여기 남는다. */
      if (side === "dat") await deps.runPoolVerb(action, item, trigger);
      else await runItemVerb(action, item, trigger);
    } catch (error) {
      deps.notify(String((error as Obj)?.message || error));
    }
  }

  /** 「자세히…」 — 검토 왕복이 시트의 재료를 채우고 **그 뒤에** 시트를 연다(U6-E #979).
   *
   *  순서가 계약이다: 먼저 열면 지난 항목의 상세가 한 프레임 서 있다가 갈리고, 검토가
   *  거절되면 빈 시트만 남는다. 실패는 왕복이 던지므로 호출자의 백스톱까지 올라간다.
   *
   *  열림·닫힘을 뷰 상태로 드는 이유는 **동사 결과의 채널**이 그 사실로 갈리기 때문이다
   *  (리뷰 3): 시트가 화면을 덮는 동안 `#save-msg` 에 쓴 문장은 스크림 뒤에 그려진다. */
  async function openDetail(path: string, trigger: HTMLElement): Promise<void> {
    await dispatch("tpl", "review", { path });
    deps.patchView({ detailOpen: true, detailMessage: null });
    deps.modal.open("tplDetailModal", {
      returnFocus: trigger,
      beforeClose: () => {
        deps.patchView({ detailOpen: false, detailMessage: null });
        return true;
      },
    });
  }

  /** 동사 실패의 착지 — 시트가 열려 있으면 **시트 안**, 아니면 인라인 채널(#323).
   *
   *  같은 문장을 두 자리에 쓰지 않는다: 읽는 사람이 지금 보고 있는 면에 남긴다. */
  function noticeVerb(message: string): void {
    if (deps.getView().detailOpen) deps.patchView({ detailMessage: message });
    else deps.noticeSave(message);
  }

  /** 누름틀·구간 변환 — 2단계(스캔 dry-run → 확인 왕복 → 제자리 적용).
   *
   *  문안·수치·차단 판정은 Python 이 낸다. 여기서 재조립하지 않는다: 차단(`blocked`)은
   *  결과 줄로 이미 재진술됐으므로 확인을 띄우지 않고 조용히 끝난다. */
  async function compileTemplate(path: string): Promise<void> {
    const result = await dispatch("tpl", "compile", { path });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n지금 변환할까요?`,
      confirmLabel: "제자리 변환", cancelLabel: "취소", danger: true,
    })) {
      await dispatch("tpl", "compile", { path, confirm: true });
    }
  }

  /* ---- 컴파일된 구간 항목(Slot) 관리 동사 3종(S8-03) ----
     동사가 서는 자리는 U6-E(#979)에서 **항목 상세 시트** 안으로 옮겼다. 겨누는 경로·목록은
     그래서 `tpl` 채널의 `detail` 존이 낸다 — 시트가 그리는 것과 동사가 겨누는 것이 같은
     값이어야 「보이는 항목과 다른 파일을 바꾸는」 자리가 생기지 않는다. */

  /** 시트가 지금 겨눈 상세(없으면 빈 객체) — 동사와 렌더가 같은 값을 읽는 단일 자리. */
  function detailZone(): Obj {
    return ((deps.tplModel.getSnapshot() || {}).detail || {}) as Obj;
  }

  function detailPath(): string {
    return String(detailZone().path || "");
  }

  /** 항목 이름 바꾸기 — 파괴가 아니라 프롬프트 하나다(확인 왕복 없음). */
  async function renameSlot(slotId: string, label: string, trigger: HTMLElement): Promise<void> {
    const value = await deps.modal.prompt({
      /* 빈 문자열도 유효한 답이다(이름 없는 항목으로 되돌리기) — 검증을 걸지 않는다. */
      title: "항목 이름 바꾸기", body: `'${slotId}' 의 새 이름`, value: label,
      returnFocus: trigger,
    });
    if (value === null) return;
    await dispatch("tpl", "slot_rename", { path: detailPath(), slot_id: slotId, label: value });
  }

  /** 항목을 표기로 되돌리기 — 확인 본문(전이 결과 재진술)은 Python 이 싣는다. */
  async function decompileSlot(slotId: string, trigger: HTMLElement): Promise<void> {
    const path = detailPath();
    const result = await dispatch("tpl", "slot_decompile", { path, slot_id: slotId });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n되돌릴까요?`,
      confirmLabel: "표기로 되돌리기", cancelLabel: "취소", returnFocus: trigger, danger: true,
    })) {
      await dispatch("tpl", "slot_decompile", { path, slot_id: slotId, confirm: true });
    }
  }

  /** 이 템플릿의 항목을 전부 표기로 되돌리기 — 대상이 항목이 아니라 파일이라 `slot_id` 가 없다. */
  async function decompileAllSlots(trigger: HTMLElement): Promise<void> {
    const path = detailPath();
    const result = await dispatch("tpl", "slot_decompile_all", { path });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n되돌릴까요?`,
      confirmLabel: "전부 되돌리기", cancelLabel: "취소", returnFocus: trigger, danger: true,
    })) {
      await dispatch("tpl", "slot_decompile_all", { path, confirm: true });
    }
  }

  /** 항목 삭제 — 내용째 사라지는 파괴 확정. */
  async function removeSlot(slotId: string, trigger: HTMLElement): Promise<void> {
    const path = detailPath();
    const result = await dispatch("tpl", "slot_remove", { path, slot_id: slotId });
    if (result.needs_confirm && await deps.modal.confirm({
      body: `${result.confirm_text}\n\n지울까요?`,
      confirmLabel: "삭제", cancelLabel: "취소", returnFocus: trigger, danger: true,
    })) {
      await dispatch("tpl", "slot_remove", { path, slot_id: slotId, confirm: true });
    }
  }

  /** 상세 시트 동사 줄의 단일 진입 — 겨누는 것은 **시트가 지금 든 항목**이다(리뷰 9).
   *
   *  분기표는 행 ⋮ 와 공유하고(`runItemVerb`) 여기가 정하는 것은 대상과 실패의 착지뿐이다. */
  async function handleDetailVerb(action: string, trigger: HTMLElement): Promise<void> {
    deps.patchView({ detailMessage: null });   // 새 동사는 지난 사유를 이고 가지 않는다
    try {
      await runItemVerb(action, detailZone(), trigger);
    } catch (error) {
      noticeVerb(String((error as Obj)?.message || error));
    }
  }

  /** Slot 동사의 **단일 분기표**(조회 테이블이라 verb 가 늘어도 분기표 자체는 한 줄씩만
   *  늘어난다). 밴드 동사(`decompile-all`)는 `slotId` 를 쓰지 않는다 — 대상이 파일이다. */
  const slotVerbHandlers: Record<string, (slotId: string, trigger: HTMLElement) => Promise<void>> = {
    "decompile-all": (_slotId, trigger) => decompileAllSlots(trigger),
    rename: async (slotId, trigger) => {
      const rows = ((detailZone().slots || {}).rows || []) as Obj[];
      const row = rows.find((item) => String(item.id) === slotId);
      await renameSlot(slotId, String((row || {}).label || ""), trigger);
    },
    decompile: (slotId, trigger) => decompileSlot(slotId, trigger),
    remove: (slotId, trigger) => removeSlot(slotId, trigger),
  };

  /** Slot 동사의 단일 진입 — 실패는 인라인 채널로(#323 라우팅 규칙). */
  async function handleSlotVerb(
    verb: string, slotId: string, trigger: HTMLElement,
  ): Promise<void> {
    try {
      const handler = Object.hasOwn(slotVerbHandlers, verb) ? slotVerbHandlers[verb] : undefined;
      if (handler === undefined) throw new Error(`알 수 없는 항목 동사입니다: ${verb}`);
      await handler(slotId, trigger);
    } catch (error) {
      /* 구간 동사는 **시트 안**에 서므로 실패도 그 면에 남는다(리뷰 3) — 시트가 닫혀 있는
         호출(프로브·직접 호출)에서는 종전대로 인라인 채널이 받는다. */
      noticeVerb(String((error as Obj)?.message || error));
    }
  }

  return {
    libContextMenu,
    closeLibMenu, openLibMenu, toggleLibMenu, handleLibMenu,
    openDetail, handleDetailVerb, handleSlotVerb,
    isLibMenuOpen: (): boolean => deps.getView().libMenu !== null,
  };
}

/** 2단계 머리의 드문 동사(⋯) 표 — 행 ⋮ 표(`libRowMenuItems`)처럼 스냅샷만 읽는 순수 함수다. */
function bindingMenuItems(snap: Obj): ContextMenuItem[] {
  const items: ContextMenuItem[] = [
    { action: "resuggest-all", label: "자동 제안 다시 받기" },
    { action: "unconfirm-all", label: "모두 해제", danger: true },
  ];
  const undo = Number(snap.unconfirm_undo_count || 0);
  if (undo) {
    items.push({
      action: "restore-confirmed", label: `직전 확인 ${undo}개 복원`,
      separatorBefore: true,
    });
  }
  return items;
}

type BindingMenuView = { bindingMenu: boolean };

export type BindingMenuDeps = {
  snapshot(): Obj;
  sendEdit(action: string, payload?: Obj): Promise<Obj>;
  resuggestAll(): Promise<void>;
  getView(): BindingMenuView;
  patchView(next: Partial<BindingMenuView>): void;
};

/** 2단계 머리(연결 확인)의 ⋯ 메뉴 — 자동 제안 다시 받기·모두 해제·직전 확인 복원. */
export function createBindingMenu(deps: BindingMenuDeps) {
  const bindingContextMenu = createContextMenu();

  function closeBindingMenu(): void {
    deps.patchView({ bindingMenu: false });
    bindingContextMenu.close();
  }

  function toggleBindingMenu(trigger: HTMLElement): void {
    if (deps.getView().bindingMenu) { closeBindingMenu(); return; }
    deps.patchView({ bindingMenu: true });
    bindingContextMenu.open(trigger, bindingMenuItems(deps.snapshot()));
  }

  async function handleBindingMenu(action: string): Promise<void> {
    closeBindingMenu();
    if (action === "resuggest-all") { await deps.resuggestAll(); return; }
    if (action === "unconfirm-all") { await deps.sendEdit("unconfirm_all", {}); return; }
    if (action === "restore-confirmed") { await deps.sendEdit("restore_confirmed", {}); return; }
    throw new Error(`알 수 없는 연결 확인 메뉴 동작: ${action}`);
  }

  return {
    bindingContextMenu,
    closeBindingMenu, toggleBindingMenu, handleBindingMenu,
    isBindingMenuOpen: (): boolean => deps.getView().bindingMenu,
  };
}
