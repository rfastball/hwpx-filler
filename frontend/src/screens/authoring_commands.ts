import { createElement as h } from "react";
import type { ReactNode } from "react";
import type { AuthoringController } from "./authoring_controller.ts";
import { COMMANDS } from "./authoring_controller.ts";
import { clampMenu, focusable, menuTrigger } from "./authoring_a11y.ts";
import { EDITOR_PINNED, menuLines } from "./command_palette.ts";
import type { CommandEntry } from "./command_palette.ts";
import { KIND_LABEL, SEVERITY_LABEL, commandAvailability } from "./authoring_outline_model.ts";
import type { Obj } from "./authoring_primitives.ts";

export const CREATE_TYPES = ["create_field", "create_slot", "create_option"];

type MenuEvent = { clientX: number; clientY: number; anchorTop?: number; target?: unknown; preventDefault?(): void };
/** 문맥 메뉴를 좌표(셸 기준)에 연다(§6.1). trigger 는 닫힐 때 초점을 돌려줄 자리 — 사건 대상의 가장 가까운 초점 가능
 *  조상이다(글자 span 이 아니다). anchor 는 창 좌표로, 그린 뒤 창 안에 들도록 위치를 다시 잰다(UX-04).
 *  kind="more" 는 도구 막대 「더보기」, kind="file" 은 머리 띠 「파일」의 작은 메뉴다 — 같은 상태·Escape·바깥 클릭 경로를 쓴다. */
export function openContextMenu(controller: Pick<AuthoringController, "update">, event: MenuEvent, root?: { getBoundingClientRect(): { left: number; top: number } } | null, kind?: "more" | "file"): void {
  event.preventDefault?.();
  const rect = root?.getBoundingClientRect();
  controller.update({ contextMenu: { x: event.clientX - (rect?.left || 0), y: event.clientY - (rect?.top || 0), anchor: { x: event.clientX, y: event.clientY, ...(event.anchorTop != null ? { top: event.anchorTop } : {}) },
    trigger: menuTrigger(event.target), ...(kind ? { kind } : {}),
    // 편집면(글 자리)에서 연 메뉴인가 — 「필드로 만들기」가 늘 서는 자리다(결정 C). 구조 목록 줄의 메뉴는 아니다.
    ...(!kind && (event.target as { closest?(selector: string): unknown } | null | undefined)?.closest?.(".authoring-canvas") ? { editor: true } : {}) }, palette: 0 });
}
/** 초점 요청(UX-04) — 초점은 사용자가 패널을 연 순간(속성·독 탭)·F2 에서만 옮긴다. 명령 select 의 값 변경,
 *  경보가 스스로 연 독, 선택 판정의 도착은 초점을 끌어가지 않는다. focusPanel 은 요청의 차례 번호다. */
export function focusRequest(view: Obj, target: "properties" | "dock"): Obj {
  return { focusTarget: target, focusPanel: (view.focusPanel || 0) + 1 };
}

/** 독 탭의 수 배지(IDE-01) — 「문제」는 Python 의 problems 수, 「결과 시험」은 손대지 않은 시험 입력(trial_missing)의
 *  필드+선택 수다. 표면은 어느 탭에 둘지만 고르고 세는 대상은 Python 이 정한다. 그 밖의 탭은 0(배지 없음). */
export function dockBadge(item: Obj | undefined, key: string, view: Obj = {}): number {
  if (key === "problems") return item?.problems?.length || 0;
  // 결과 시험 배지(IDE-04): 시험을 시도한 뒤에만 선다 — 상태 막대의 시험 표지와 같은 규칙(시험 전이 아니거나 시험 값·선택이
  // 하나라도 있다). 갓 연 문서의 「4」는 문제 4개로 읽힌다. 공백 수 자체(trial_missing)는 그대로 Python 투영이다.
  if (key === "trial") {
    const attempted = trialAttempted(item, view);
    return attempted ? (item?.trial_missing?.fields?.length || 0) + (item?.trial_missing?.slots?.length || 0) : 0;
  }
  return 0;
}

function trialAttempted(item: Obj | undefined, view: Obj): boolean {
  return item?.trial_state !== "untried" || Object.keys(view.values || {}).length > 0 || Object.keys(view.selectedOptions || {}).length > 0;
}

/** F2 의 이름 변경 명령 셋 — 선택 종류와 같은 것이 먼저, 종류가 없으면 필드 → 선택 → 항목(안쪽부터)이다. */
const RENAME_BY_KIND: Obj = { field: "rename_field", option: "rename_option", slot: "rename_slot" };
const RENAME_ORDER = ["rename_field", "rename_option", "rename_slot"];
/** F2(IDE-01): Python 이 **enabled** 로 판정한 이름 변경 명령만 연다. 판정 전(pending)이면 아무것도 하지 않고, 셋 다
 *  불가이면 패널을 열지 않고 선택 종류에 맞는 명령(종류가 없으면 필드 이름 변경)의 Python 사유를 돌려준다. */
export function renameChoice(commands: Obj[] | undefined, kind: string | undefined): { open: string } | { reason: string | null } | null {
  const preferred = RENAME_BY_KIND[kind || ""] || "rename_field";
  const order = [preferred, ...RENAME_ORDER.filter((type) => type !== preferred)];
  const entries = order.map((type) => commandAvailability(commands, type));
  if (entries.some((entry) => entry.pending)) return null;
  const enabled = entries.find((entry) => entry.enabled);
  if (enabled) return { open: enabled.type };
  return { reason: entries[0].reason ? String(entries[0].reason) : null };
}
/** 셸 F2 와 편집면(rhwp)이 넘겨준 F2 가 같은 길을 쓴다. 열 수 있으면 속성 패널을 그 명령으로 열고 이름 칸으로 가며,
 *  불가이면 위치 줄 메모(controller.note)에 Python 사유 한 줄을 세운다 — 메모 칸의 첫 호출자다. */
export function renameShortcut(controller: Pick<AuthoringController, "update" | "note" | "viewModel">): void {
  const view = controller.viewModel.getSnapshot();
  const choice = renameChoice(view.commands, view.selected?.kind);
  if (!choice) return;
  if ("open" in choice) { controller.update({ panel: "properties", commandType: choice.open, formEntry: "", selectionNote: null, ...focusRequest(view, "properties") }); return; }
  if (choice.reason) controller.note(choice.reason);
}
/** 위치 줄 메모(IDE-01) — 브레드크럼 줄 오른쪽 끝의 제자리 사유 칸 하나. 넘치면 말줄임이고 전문은 title 에 있다.
 *  오류·경고는 색만이 아니라 앞의 글자 칩(오류/경고)으로도 가른다(data-severity). 읽기는 live region 이 세울 때 한 번 한다
 *  (이 칸은 live region 이 아니다). 문장은 호출자가 넘긴 Python 문장 그대로다. */
export function selectionNoteView(note: { message: string; severity?: "error" | "warning" | "info" } | null | undefined): ReactNode {
  if (!note?.message) return null;
  const chip = note.severity === "error" || note.severity === "warning"
    ? h("span", { className: "authoring-badge", "data-severity": note.severity }, SEVERITY_LABEL[note.severity]) : null;
  return h("span", { className: "authoring-selection-note", title: note.message, "data-severity": note.severity },
    chip, chip ? " " : null, note.message);
}

/** 하단 독(§3.1 UI01~UI10)이 한 탭으로 보이는 패널 — `view.panel` 값이 곧 탭 열쇠다. 속성은 옆 패널이라 빠진다. */
export const DOCK_PANELS = ["problems", "search", "raw", "impact", "paste", "external", "comparison"];
/** 독의 탭 목록과 지금 보일 탭 하나. 기본 탭(문제·검색·원문 표기·결과 시험)은 문서가 열려 있으면 늘 서고,
 *  문맥 탭은 그 상태가 있을 때만 선다. 「변경 영향·작업 적용」은 Python 이 연결 작업이 있다고(또는 확인할 수 없다고) 투영한
 *  문서에만 서는 문맥 탭이다(NG-09 · `has_linked_jobs`) — 표면은 그 값을 읽을 뿐 연결을 추측하지 않는다. 보일 탭: 열린 패널 → 사용자가 고른 탭 → 경보·비교·시험 순의 대체.
 *  `dockClosed` 는 사용자가 닫은 뒤 경보가 스스로 다시 펼치지 않게 한다(새로 선 경보는 화면이 다시 연다). */
export function dockTabs(item: Obj | undefined, view: Obj): { tabs: [string, string][]; active: string } {
  const tabs = dockTabList(item, view);
  return { tabs, active: activeDock(tabs, view) };
}

function dockTabList(item: Obj | undefined, view: Obj): [string, string][] {
  const tabs: [string, string][] = item ? [["problems", "문제"], ["search", "검색"], ["raw", "원문 표기"], ...(item.has_linked_jobs ? [["impact", "변경 영향·작업 적용"] as [string, string]] : []), ["trial", "결과 시험"]] : [];
  const saveFailed = !!item && (view.panel === "external" || !!view.saveFailed);
  addContextTabs(tabs, item, view, saveFailed);
  return tabs;
}

function addContextTabs(tabs: [string, string][], item: Obj | undefined, view: Obj, saveFailed: boolean): void {
  if (item && view.panel === "paste") tabs.push(["paste", "의미 붙여넣기"]);
  if (saveFailed) tabs.push(["external", "저장 실패"]);
  if (item?.external_changed && !saveFailed) tabs.push(["external_changed", "외부 파일 변경"]);
  if (item && view.panel === "comparison" && view.comparison) tabs.push(["comparison", "외부 파일 내용"]);
}

function activeDock(tabs: [string, string][], view: Obj): string {
  const has = (key: string) => !!key && tabs.some(([tab]) => tab === key);
  const open = (key: string) => has(key) && (key !== "trial" || !!view.trial) && (!DOCK_PANELS.includes(key) || view.panel === key);
  const fallback = view.dockClosed ? ["trial"] : ["external_changed", "trial"];
  return DOCK_PANELS.includes(view.panel) && has(view.panel) ? view.panel : open(view.dock) ? view.dock : fallback.find(open) || "";
}
/** 같은 불가 사유를 명령마다 되풀이하지 않는다(§3.1): 불가 명령이 둘 이상이고 사유가 모두 같으면 그 한 문장, 아니면 null.
 *  사유는 Python 의 판정 문장 그대로다(P07) — 표면은 모을 뿐 새로 짓지 않는다. 문맥 메뉴에 되는 명령이 하나도 없어
 *  「명령」 한 줄만 설 때 그 위 머리 줄이다(IDE-02) — 처음 쓰는 사람이 팔레트를 열지 않고도 왜 아무것도 안 되는지 본다. */
export function sharedReason(commands: Obj[] | undefined, types: string[] = COMMANDS.map(([type]) => type)): string | null {
  // 판정이 없는 명령(pending)은 사유가 없는 세 번째 상태라 모으지 않는다.
  const reasons = types.map((type) => commandAvailability(commands, type)).filter((entry) => !entry.enabled && !entry.pending).map((entry) => String(entry.reason || ""));
  return reasons.length > 1 && reasons.every((reason) => reason && reason === reasons[0]) ? reasons[0] : null;
}
/** Escape 한 단계(§10): 문맥 메뉴가 열려 있으면 그것만 닫고 초점을 연 자리로 돌린다("menu"); 아니면 패널을 닫는다("panel"). */
export function escapeShell(controller: Pick<AuthoringController, "update" | "viewModel">): "menu" | "panel" {
  const view = controller.viewModel.getSnapshot();
  if (view.contextMenu) { const trigger = view.contextMenu.trigger; controller.update({ contextMenu: null, selectionNote: null }); if (focusable(trigger)) trigger.focus(); return "menu"; }
  controller.update({ panel: "", preview: null, refusal: null, selectionNote: null });
  return "panel";
}
/** 클립보드 복사 — 권한·API 부재 시 textarea 경로로 대신한다. */
export async function copyText(text: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return; }
  const area = document.createElement("textarea");
  area.value = text; area.setAttribute("readonly", ""); area.style.position = "fixed"; area.style.opacity = "0";
  document.body.appendChild(area); area.select();
  try { document.execCommand("copy"); } finally { area.remove(); }
}

/** 명령 판정 표(F40·P07) — 도구 막대·속성 select·문맥 메뉴·팔레트가 같은 Python 판정을 읽는다. 읽기 전용이면 어떤 명령도
 *  되지 않는다(사유 문장은 짓지 않는다 — 호환성 안내가 이미 선다). 대안도 읽기 전용에서는 싣지 않는다.
 *  `table` 은 이름 표다 — 기본은 선택 명령, 문서 명령(#1078)은 탭 투영 `document_commands` 와 `DOCUMENT_COMMANDS` 로 같은 모양을 짓는다. */
export function commandEntries(commands: Obj[] | undefined, readOnly: boolean, table: [string, string][] = COMMANDS): CommandEntry[] {
  return table.map(([type, label]) => {
    const available = commandAvailability(commands, type);
    return { type, label, enabled: !readOnly && !!available.enabled, pending: !!available.pending, reason: available.enabled ? null : available.reason || null,
      alternative: readOnly || available.enabled ? null : available.alternative || null };
  });
}
/** 선택 옆 막대(IDE-08 P-05)에 실을 것 — 만들기 셋 가운데 되는 것과, 되지 않는 것의 대안만이다(문맥 메뉴와 같은 Python 판정,
 *  같은 이름). 판정 전·읽기 전용이면 싣지 않는다 — 막대가 서지 않는다. 같은 명령으로 가는 대안은 한 번만 싣는다. */
export function selectionBarItems(entries: CommandEntry[], readOnly: boolean): { key: string; label: string; command: string; alternative: boolean }[] {
  const creates = entries.filter((entry) => CREATE_TYPES.includes(entry.type));
  if (readOnly || creates.some((entry) => entry.pending)) return [];
  const items = creates.flatMap((entry) => entry.enabled ? [{ key: entry.type, label: entry.label, command: entry.type, alternative: false }]
    : entry.alternative ? [{ key: `${entry.type}-alternative`, label: entry.alternative.label, command: entry.alternative.command_type, alternative: true }] : []);
  return items.filter((entry, index) => items.findIndex((other) => other.command === entry.command) === index);
}
/** 선택 끝 줄과 막대 사이(px). */
export const SELECTION_BAR_GAP = 8;
/** 선택 옆 막대의 창 좌표 — 선택 끝 줄 아래 8px 에 서고, 아래가 모자라면 그 줄 위로 뒤집으며 창 안에 든다(clampMenu 규칙). */
export function selectionBarPlace(rect: { left: number; top: number; bottom: number }, size: { width: number; height: number },
  viewport: { width: number; height: number }): { left: number; top: number } {
  return clampMenu({ x: rect.left, y: rect.bottom + SELECTION_BAR_GAP, top: rect.top - SELECTION_BAR_GAP }, size, viewport);
}
/** 작은 메뉴(「더보기」·「파일」)의 한 항목: 이름 · 실행 · 불가 · 단축키 표기(있을 때만). */
export type MenuAction = [string, () => void, boolean, string?];
/** 「더보기」의 첫 항목이자 빈 문맥 메뉴의 한 줄 — 명령 팔레트를 연다. 팔레트 자신에는 서지 않는다(자기를 여는 줄이 된다). */
export const PALETTE_SELF = "명령";
/** 빈 문맥 메뉴의 공유 사유 머리 줄 — 메뉴의 자식이 아니라 메뉴 위의 줄이고 「명령」 줄이 설명으로 가리킨다. */
export const MENU_REASON_ID = "authoring-command-reason-menu";

/** 문맥 메뉴(IDE-02 · P-04)는 자동 표면이다 — 되는 명령과 불가 명령의 대안만 싣고, 불가 항목·사유 줄은 싣지 않는다.
 *  이것은 UX-04·UX-10 R5(「불가 항목도 초점을 받아 사유를 읽힌다」)의 의도된 되돌림이다(제품 결정 2026-09-28): 우클릭이
 *  19줄 가운데 되는 3줄을 찾게 하던 비용을 없애고, "있지만 안 됨"과 사유는 명시 표면(명령 팔레트·속성 명령 select·도구 막대
 *  툴팁)에 남긴다. 판정 전(pending)이면 지금처럼 모든 명령을 사유 없이 흐리게 싣는다. 읽기 전용이거나 되는 것이 없으면
 *  팔레트를 여는 「명령」 한 줄이다. APG menu: 자식은 menuitem 뿐이고, 구분선은 무리가 바뀌는 보이는 항목의 윗선이다. */
export function CommandMenu({ entries, readOnly, editor, reason, onPick, onPalette }: { entries: CommandEntry[]; readOnly: boolean; editor: boolean; reason: string | null; onPick: (commandType: string) => void; onPalette: () => void }) {
  const lines = menuLines(entries, readOnly, editor);
  const palette = (describedBy?: string) => h("button", { key: "palette", type: "button", className: "authoring-menu-item", role: "menuitem", tabIndex: -1, onClick: onPalette,
    "aria-describedby": describedBy }, PALETTE_SELF);
  if (!lines) return palette(reason ? MENU_REASON_ID : undefined);
  // 결정 C: 편집면 메뉴의 「필드로 만들기」는 불가여도 선다 — 사유는 그 항목 안 윗줄의 설명(aria-describedby)이고 접근 이름은
  // 명령 이름이다. 그 밖에 되는 것이 없으면 팔레트를 여는 「명령」이 뒤따른다.
  const pinnedOnly = lines.every((line) => line.disabled && line.command === EDITOR_PINNED);
  return [...lines.map((line) => commandMenuLine(line, onPick)), pinnedOnly ? palette() : null];
}

function commandMenuLine(line: NonNullable<ReturnType<typeof menuLines>>[number],
  onPick: (commandType: string) => void): ReactNode {
  const reasonId = line.reason ? `authoring-menu-reason-${line.command}` : undefined;
  return h("button", { key: line.key, type: "button", role: "menuitem", tabIndex: -1, "aria-disabled": line.disabled || undefined,
    ...(reasonId ? { "aria-label": line.label, "aria-describedby": reasonId } : {}),
    className: `authoring-menu-item${line.alternative ? " alternative" : ""}${line.groupStart ? " group-start" : ""}${line.danger ? " danger" : ""}`,
    onClick: () => { if (!line.disabled) onPick(line.command); } },
    reasonId ? h("span", { key: "reason", id: reasonId, className: "authoring-reason" }, line.reason) : null, line.label);
}

/** 구조 변경 요약(F38) — 미리보기와 변경 영향 패널이 같은 표를 쓴다. */
export function StructureDelta({ delta }: { delta: Obj }) {
  // 선택 delta 는 Python 이 `[slot_id, option_id]` 쌍으로 준다 — 소속을 함께 읽어야 같은 이름의 선택이 갈린다.
  const name = (entry: Obj | string | string[]): string => typeof entry === "string" ? entry : Array.isArray(entry) ? entry.join(" / ") : String(entry.label || entry.id || entry.name || "");
  const row = (label: string, items?: (Obj | string)[]) => !!items?.length && h("p", { key: label }, `${label}: ${items.map(name).join(", ")}`);
  return h("div", { className: "authoring-delta", role: "group", "aria-label": "구조 변경" },
    row("추가 항목", delta.added_slots), row("없어진 항목", delta.removed_slots), row("추가 선택", delta.added_options), row("없어진 선택", delta.removed_options),
    !!delta.renamed?.length && h("ul", { "aria-label": "식별자 변경" }, ...delta.renamed.map((entry: Obj, index: number) => h("li", { key: index }, `${KIND_LABEL[entry.kind] || entry.kind} · ${entry.from} → ${entry.to}`))));
}

/** rhwp 마운트 경로 — 제품은 늘 mountRhwp 다. Node 시험은 WASM iframe 을 띄울 수 없어 여기만 바꿔 낀다. */
