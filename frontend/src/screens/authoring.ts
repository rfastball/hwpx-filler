import { createElement as h, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { mountLintpad, disposeLintpad, updateLintpad, editLintpad, lintpadState, lintpadCommand, navigateLintpad } from "../editorview/txt_lintpad.ts";
import { mountRhwp } from "../editorview/rhwp_editor.ts";
import { COMMANDS } from "./authoring_controller.ts";
import { PanelSplitter, PANEL_CYCLE, cyclePanels } from "./authoring_layout.ts";
import type { AuthoringLayout } from "./authoring_layout.ts";
import type { AuthoringController, AuthoringEditor } from "./authoring_controller.ts";
import { TPL_STATUS_COPY } from "./job_run.ts";
import { FOCUSABLE, clampMenu, errorParts, focusFirst, focusable, isCurrentTarget, liveStep, menuTrigger, roveFocus, tabName, treeKey } from "./authoring_a11y.ts";
import type { LiveState, TreeRow } from "./authoring_a11y.ts";
import { coverageDot, icon, kindGlyph } from "./icons.ts";
import { CommandPalette, ariaKeys, menuLines } from "./command_palette.ts";
import type { CommandEntry, PaletteAction } from "./command_palette.ts";

/** IME 조합 중에는 문서 명령을 보내지 않는다 — 조합이 끝난 뒤 같은 명령을 다시 받는다. */
const IME_BUSY = "한글 조합을 마친 뒤 다시 실행하세요.";

type Obj = Record<string, any>;
type Props = { controller: AuthoringController };
/* 단추 어휘(UX-09 · #1039) — 역할이 곧 모양이다. 보조 행동 `.btn`(테두리)이 기본이고, 구획마다 하나뿐인 주 행동은
   `.btn.primary`(채움·굵게), 물러서는 행동(취소·닫기·복사…)은 `.btn.quiet`(테두리 없음), 되돌릴 수 없는 행동은
   `.btn.danger`(채움 + 동사), 그림만 선 단추는 `.btn.icon`(이름은 aria-label·title). 이동하는 줄은 단추 모양이 아니다
   — `rowButton`(목록 행)·트리 행·브레드크럼 조각·메뉴 항목이 따로 선다. 편집기 틀(머리 띠·도구 막대)은 명령을
   `.btn.quiet` 로 두고 띠마다 실행 행동 하나(저장·결과 시험)만 테두리·채움으로 세운다. */
const button = (label: ReactNode | ReactNode[], click: (event: any) => void, props: Obj = {}) =>
  h("button", { type: "button", className: "btn", onClick: click, ...props }, ...(Array.isArray(label) ? label : [label]));
const quiet = (label: ReactNode | ReactNode[], click: (event: any) => void, props: Obj = {}) => button(label, click, { className: "btn quiet", ...props });
const primary = (label: ReactNode | ReactNode[], click: () => void, props: Obj = {}) => button(label, click, { className: "btn primary", ...props });
const danger = (label: ReactNode | ReactNode[], click: () => void, props: Obj = {}) => button(label, click, { className: "btn danger", ...props });
/** 아이콘 단추 — 보이는 글자 대신 그림이 서고, 기존 이름은 접근 가능한 이름과 툴팁으로 남는다(새 문구 없음). */
const iconButton = (name: string, label: string, click: (event: any) => void, props: Obj = {}) =>
  h("button", { type: "button", className: "btn icon", "aria-label": label, title: label, onClick: click, ...props }, icon(name));
/** 목록 행(UX-09): 종류/심각도 칩 · 본문 · 흐린 문맥 · 오른쪽 이동 화살표. 단추가 아니라 원문으로 옮겨 가는 줄이다. */
const rowButton = (parts: { chip?: ReactNode; text: ReactNode; value?: ReactNode; context?: ReactNode }, click: () => void, props: Obj = {}) =>
  h("button", { type: "button", className: "authoring-row", onClick: click, ...props },
    parts.chip || null, h("span", { className: "authoring-row-text" }, parts.text),
    parts.value != null ? h("span", { className: "authoring-row-value" }, parts.value) : null,
    parts.context ? h("span", { className: "authoring-row-context" }, parts.context) : null,
    h("span", { className: "authoring-row-go" }, icon("chevron-right")));
/** 행 목록 — role=list 로 목록임을 밝힌다(목록 스타일을 걷어도 읽기 도구가 목록으로 센다). */
const rowList = (label: string, rows: ReactNode[], className = "") => rows.length
  ? h("ul", { className: `authoring-rows${className ? ` ${className}` : ""}`, role: "list", "aria-label": label }, ...rows.map((row, index) => h("li", { key: index }, row))) : null;
/** 구획 이름(UX-09): 내용과 겨루지 않는 caption 크기의 이름표다 — 제목 이동을 위해 h2 의미는 그대로 둔다. */
const sectionLabel = (text: string, props: Obj = {}) => h("h2", { className: "authoring-section-label", ...props }, text);
const KIND_LABEL: Obj = { field: "필드", slot: "항목", option: "선택", text: "본문" };
const SEVERITY_LABEL: Obj = { error: "오류", warning: "경고" };
const CATEGORY_LABEL: Obj = { structure: "구조", compatibility: "호환성" };
/** 식별자 변경은 고급 정보지만 기존 작업 연결에 닿는 영향은 숨기지 않는다(U06·F19). */
const IDENTIFIER_IMPACT = "식별자 변경은 기존 작업 연결에 영향을 줄 수 있습니다.";

/** Python 이 판정한 명령 한 건의 가용성(F40·P07). 판정이 아직 없으면(선택 전) 세 번째 상태 — 표면은 자기 추측으로
 *  켜 두지 않고, 사유 문장 없이 비활성(pending)으로 둔다(UX-04). */
export function commandAvailability(commands: Obj[] | undefined, type: string): Obj {
  return (commands || []).find((entry) => entry.type === type) || { type, enabled: false, pending: true, reason: null, alternative: null };
}
/** 대상별 문제 수 — 구조 tree·필드 목록의 `문제 N` 배지(F12·F13). Python 의 problems 를 target 으로 셀 뿐이다. */
export function problemCount(problems: Obj[] | undefined, target: string): number {
  return (problems || []).filter((problem) => problem.target === target).length;
}
/** 대상별 문제 수 표 — 스냅샷마다 한 번 센다(구조 목록 한 줄마다 목록을 다시 훑지 않는다). */
export function problemCounts(problems: Obj[] | undefined): Map<string, number> {
  const counts = new Map<string, number>();
  for (const problem of problems || []) counts.set(problem.target, (counts.get(problem.target) || 0) + 1);
  return counts;
}
/** 항목·선택의 종류 표지(§10) — 들여쓰기·색이 아니라 글자로 둘을 가른다. */
const kindTag = (kind: "slot" | "option" | "field" | "text"): ReactNode => h("span", { className: "authoring-kind" }, KIND_LABEL[kind]);
/** 구조 목록 한 줄의 접근 가능한 이름(§10) — 종류·이름·사용 위치 수·상위 항목·문제 수를 글로 싣는다. */
export function outlineLabel(kind: "field" | "slot" | "option" | "occurrence", entry: Obj, problems = 0, parent = ""): string {
  const name = String(entry.name || entry.label || entry.id || "");
  const parts = kind === "occurrence" ? [name, `사용 위치 ${entry.index}/${entry.total}`, ...(entry.context ? [String(entry.context)] : [])]
    : kind === "field" ? [KIND_LABEL.field, name, `사용 위치 ${entry.count ?? 0}곳`]
    : kind === "option" ? [KIND_LABEL.option, name, `상위 항목 ${parent}`] : [KIND_LABEL.slot, name];
  return [...parts, ...(problems ? [`문제 ${problems}`] : [])].join(" · ");
}
/** 선택 한 갈래의 시험 상태 이름 — 시험 패널과 구조 트리의 점이 같은 이름을 쓴다(AC09·AC13). */
export const COVERAGE_LABEL: Obj = { current: "현재 시험 구성 확인됨", stale: "다시 시험 필요", untried: "시험하지 않음" };
/** 여러 자리에 선 같은 필드의 표지(§3.3) — 「같은 필드, i/n」. 한 곳뿐이면 사용 위치 수를 그대로 쓴다. */
export function sameFieldMeta(index: number, total: number): string {
  return total > 1 ? `같은 필드, ${index}/${total}` : `사용 위치 ${total}곳`;
}

/* ---------- 문서 척추(UX-09): 구조 트리의 모양은 Python 이 준 소속·차례로만 짓는다 ---------- */

/** 척추의 한 마디. 필드 사용 위치(use)는 그것을 담은 선택·항목 아래에, 어디에도 없으면 척추에 직접 선다. */
export type SpineNode =
  | { kind: "slot"; slot: Obj; order: number; children: SpineNode[] }
  | { kind: "option"; slot: Obj; option: Obj; order: number; children: SpineNode[] }
  | { kind: "use"; field: Obj; occurrence: Obj; index: number; total: number; order: number };
const LAST = Number.MAX_SAFE_INTEGER;
const byOrder = (a: { order: number }, b: { order: number }) => a.order - b.order;
/** 분석(Python 투영)에서 척추를 짓는다. 소속은 사용 위치의 `slot_id`·`option_id`, 차례는 `order` 그대로다 —
 *  표면은 문단을 세거나 좌표를 견주지 않는다. 차례가 없는 옛 투영은 받은 차례(항목 → 필드)를 지킨다(안정 정렬). */
export function outlineSpine(analysis: Obj | undefined): SpineNode[] {
  const spine: SpineNode[] = [];
  const slots = new Map<string, Extract<SpineNode, { kind: "slot" }>>();
  const options = new Map<string, Extract<SpineNode, { kind: "option" }>>();
  for (const slot of analysis?.slots || []) {
    const node = { kind: "slot" as const, slot, order: slot.order ?? LAST, children: [] as SpineNode[] };
    slots.set(slot.id, node);
    spine.push(node);
    for (const option of slot.options || []) {
      const child = { kind: "option" as const, slot, option, order: option.order ?? LAST, children: [] as SpineNode[] };
      options.set(`${slot.id}\u0000${option.id}`, child);
      node.children.push(child);
    }
  }
  for (const field of analysis?.fields || []) {
    const occurrences: Obj[] = field.occurrences || [];
    occurrences.forEach((occurrence, at) => {
      const use: SpineNode = { kind: "use", field, occurrence, index: at + 1, total: occurrences.length, order: occurrence.order ?? LAST };
      const home = options.get(`${occurrence.slot_id}\u0000${occurrence.option_id}`) || slots.get(occurrence.slot_id);
      (home ? home.children : spine).push(use);
    });
  }
  const sort = (list: SpineNode[]) => { list.sort(byOrder); for (const node of list) if (node.kind !== "use") sort(node.children); };
  sort(spine);
  return spine;
}
/** 필드 목록의 차례 — 문서에서 처음 쓰인 순서(§3.3·F13). 차례는 Python 의 `order` 다. */
export function fieldsInFirstUse(analysis: Obj | undefined): Obj[] {
  const first = (field: Obj) => Math.min(LAST, ...(field.occurrences || []).map((occurrence: Obj) => occurrence.order ?? LAST));
  return [...(analysis?.fields || [])].map((field, at) => ({ field, at, first: first(field) }))
    .sort((a, b) => a.first - b.first || a.at - b.at).map((entry) => entry.field);
}
/** 트리 줄의 열쇠 — 구조 탭과 필드 탭이 같은 규칙으로 짓는다(현재 위치 동기화가 이 열쇠로 줄을 찾는다). */
export const outlineKey = {
  slot: (slotId: string) => `slot:${slotId}`,
  option: (slotId: string, optionId: string) => `option:${slotId}/${optionId}`,
  use: (name: string, index: number) => `use:${name}#${index}`,
  field: (name: string) => `field:${name}`,
  occurrence: (name: string, index: number) => `occurrence:${name}#${index - 1}`,
};
/** 지금 위치의 의미가 가리키는 줄의 경로(바깥 → 안) — 구조 탭과 필드 탭 각각. 판정은 브레드크럼과 같다:
 *  명시 선택(`selected`)이 먼저, 없으면 캐럿의 일치 후보(`matches`)에서 가장 안쪽(사용 위치 → 선택 → 항목)이다. */
export function outlineCurrent(analysis: Obj | undefined, selected: Obj | null | undefined, matches: Obj[] = []): { structure: string[]; fields: string[] } {
  const candidates = [selected, ...matches.map((match) => match.kind === "field" ? { ...(match.location || {}), name: match.name, kind: "field" } : match)].filter(Boolean) as Obj[];
  if (selected?.kind === "field" && Array.isArray(selected.occurrences)) return { structure: [], fields: [outlineKey.field(selected.name)] };
  for (const candidate of candidates) {
    if (candidate.kind !== "field") continue;
    const field = (analysis?.fields || []).find((entry: Obj) => entry.name === candidate.name);
    const at = (field?.occurrences || []).findIndex((occurrence: Obj) => isCurrentTarget("occurrence", { ...occurrence, name: field.name }, candidate));
    if (at < 0) continue;
    const occurrence = field.occurrences[at];
    const slot = (analysis?.slots || []).find((entry: Obj) => entry.id === occurrence.slot_id);
    const option = slot && (slot.options || []).find((entry: Obj) => entry.id === occurrence.option_id);
    return { structure: [...(slot ? [outlineKey.slot(slot.id)] : []), ...(option ? [outlineKey.option(slot.id, option.id)] : []), outlineKey.use(field.name, at + 1)],
      fields: [outlineKey.field(field.name), outlineKey.occurrence(field.name, at + 1)] };
  }
  const option = candidates.find((candidate) => candidate.kind === "option" && candidate.slot_id && candidate.option_id);
  if (option) return { structure: [outlineKey.slot(option.slot_id), outlineKey.option(option.slot_id, option.option_id)], fields: [] };
  const slot = candidates.find((candidate) => candidate.kind === "slot" && candidate.slot_id);
  return { structure: slot ? [outlineKey.slot(slot.slot_id)] : [], fields: [] };
}
/** 구조 필터 — 이름·표시 이름·식별자·문맥에 입력이 들어 있는가(대소문자 무시). */
export function filterMatch(query: string, ...texts: unknown[]): boolean {
  const wanted = query.trim().toLocaleLowerCase();
  return !wanted || texts.some((text) => text != null && String(text).toLocaleLowerCase().includes(wanted));
}
/** 문제의 다음 행동(§7.2): navigate 는 그 위치로 선택을 옮기고, command 는 Python 이 준 명령을 미리보기로 보낸다. */
export function problemAction(controller: Pick<AuthoringController, "select" | "preview">, item: Obj, problem: Obj, action: Obj): Promise<void> {
  return action.kind === "command" ? controller.preview(action.command) : controller.select({ source_revision: item.revision, ...(problem.location || {}), target: problem.target });
}

type MenuEvent = { clientX: number; clientY: number; anchorTop?: number; target?: unknown; preventDefault?(): void };
/** 문맥 메뉴를 좌표(셸 기준)에 연다(§6.1). trigger 는 닫힐 때 초점을 돌려줄 자리 — 사건 대상의 가장 가까운 초점 가능
 *  조상이다(글자 span 이 아니다). anchor 는 창 좌표로, 그린 뒤 창 안에 들도록 위치를 다시 잰다(UX-04).
 *  kind="more" 는 도구 막대 「더보기」, kind="file" 은 머리 띠 「파일」의 작은 메뉴다 — 같은 상태·Escape·바깥 클릭 경로를 쓴다. */
export function openContextMenu(controller: Pick<AuthoringController, "update">, event: MenuEvent, root?: { getBoundingClientRect(): { left: number; top: number } } | null, kind?: "more" | "file"): void {
  event.preventDefault?.();
  const rect = root?.getBoundingClientRect();
  controller.update({ contextMenu: { x: event.clientX - (rect?.left || 0), y: event.clientY - (rect?.top || 0), anchor: { x: event.clientX, y: event.clientY, ...(event.anchorTop != null ? { top: event.anchorTop } : {}) },
    trigger: menuTrigger(event.target), ...(kind ? { kind } : {}) }, palette: 0 });
}
/** 초점 요청(UX-04) — 초점은 사용자가 패널을 연 순간(속성·독 탭)·F2 에서만 옮긴다. 명령 select 의 값 변경,
 *  경보가 스스로 연 독, 선택 판정의 도착은 초점을 끌어가지 않는다. focusPanel 은 요청의 차례 번호다. */
export function focusRequest(view: Obj, target: "properties" | "dock"): Obj {
  return { focusTarget: target, focusPanel: (view.focusPanel || 0) + 1 };
}

/** 독 탭의 수 배지(IDE-01) — 「문제」는 Python 의 problems 수, 「결과 시험」은 손대지 않은 시험 입력(trial_missing)의
 *  필드+선택 수다. 표면은 어느 탭에 둘지만 고르고 세는 대상은 Python 이 정한다. 그 밖의 탭은 0(배지 없음). */
export function dockBadge(item: Obj | undefined, key: string): number {
  if (key === "problems") return item?.problems?.length || 0;
  if (key === "trial") return (item?.trial_missing?.fields?.length || 0) + (item?.trial_missing?.slots?.length || 0);
  return 0;
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
  if ("open" in choice) { controller.update({ panel: "properties", commandType: choice.open, selectionNote: null, ...focusRequest(view, "properties") }); return; }
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
/** 독의 탭 목록과 지금 보일 탭 하나. 기본 탭(문제·검색·원문 표기·변경 영향·결과 시험)은 문서가 열려 있으면 늘 서고,
 *  문맥 탭은 그 상태가 있을 때만 선다. 보일 탭: 열린 패널 → 사용자가 고른 탭 → 경보·비교·시험 순의 대체.
 *  `dockClosed` 는 사용자가 닫은 뒤 경보가 스스로 다시 펼치지 않게 한다(새로 선 경보는 화면이 다시 연다). */
export function dockTabs(item: Obj | undefined, view: Obj): { tabs: [string, string][]; active: string } {
  const tabs: [string, string][] = item ? [["problems", "문제"], ["search", "검색"], ["raw", "원문 표기"], ["impact", "변경 영향·작업 적용"], ["trial", "결과 시험"]] : [];
  const saveFailed = !!item && (view.panel === "external" || !!view.saveFailed);
  if (item && view.panel === "paste") tabs.push(["paste", "의미 붙여넣기"]);
  if (saveFailed) tabs.push(["external", "저장 실패"]);
  if (item?.external_changed && !saveFailed) tabs.push(["external_changed", "외부 파일 변경"]);
  if (item?.recovery) tabs.push(["recovery", "중단 전 복구 초안"]);
  if (view.recoveryPreview) tabs.push(["recovery_preview", "초안과 원본 비교"]);
  if (item && view.panel === "comparison" && view.comparison) tabs.push(["comparison", "외부 파일 내용"]);
  const has = (key: string) => !!key && tabs.some(([tab]) => tab === key);
  const open = (key: string) => has(key) && (key !== "trial" || !!view.trial) && (!DOCK_PANELS.includes(key) || view.panel === key);
  const fallback = view.dockClosed ? ["trial"] : ["recovery_preview", "recovery", "external_changed", "trial"];
  const active = DOCK_PANELS.includes(view.panel) && has(view.panel) ? view.panel : open(view.dock) ? view.dock : fallback.find(open) || "";
  return { tabs, active };
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
 *  되지 않는다(사유 문장은 짓지 않는다 — 호환성 안내가 이미 선다). 대안도 읽기 전용에서는 싣지 않는다. */
export function commandEntries(commands: Obj[] | undefined, readOnly: boolean): CommandEntry[] {
  return COMMANDS.map(([type, label]) => {
    const available = commandAvailability(commands, type);
    return { type, label, enabled: !readOnly && !!available.enabled, pending: !!available.pending, reason: available.enabled ? null : available.reason || null,
      alternative: readOnly || available.enabled ? null : available.alternative || null };
  });
}
/** 작은 메뉴(「더보기」·「파일」)의 한 항목: 이름 · 실행 · 불가 · 단축키 표기(있을 때만). */
type MenuAction = [string, () => void, boolean, string?];
/** 「더보기」의 첫 항목이자 빈 문맥 메뉴의 한 줄 — 명령 팔레트를 연다. 팔레트 자신에는 서지 않는다(자기를 여는 줄이 된다). */
const PALETTE_SELF = "명령";

/** 문맥 메뉴(IDE-02 · P-04)는 자동 표면이다 — 되는 명령과 불가 명령의 대안만 싣고, 불가 항목·사유 줄은 싣지 않는다.
 *  이것은 UX-04·UX-10 R5(「불가 항목도 초점을 받아 사유를 읽힌다」)의 의도된 되돌림이다(제품 결정 2026-09-28): 우클릭이
 *  19줄 가운데 되는 3줄을 찾게 하던 비용을 없애고, "있지만 안 됨"과 사유는 명시 표면(명령 팔레트·속성 명령 select·도구 막대
 *  툴팁)에 남긴다. 판정 전(pending)이면 지금처럼 모든 명령을 사유 없이 흐리게 싣는다. 읽기 전용이거나 되는 것이 없으면
 *  팔레트를 여는 「명령」 한 줄이다. APG menu: 자식은 menuitem 뿐이고, 구분선은 무리가 바뀌는 보이는 항목의 윗선이다. */
function CommandMenu({ entries, readOnly, onPick, onPalette }: { entries: CommandEntry[]; readOnly: boolean; onPick: (commandType: string) => void; onPalette: () => void }) {
  const lines = menuLines(entries, readOnly);
  if (!lines) return h("button", { type: "button", className: "authoring-menu-item", role: "menuitem", tabIndex: -1, onClick: onPalette }, PALETTE_SELF);
  return lines.map((line) => h("button", { key: line.key, type: "button", role: "menuitem", tabIndex: -1, "aria-disabled": line.disabled || undefined,
    className: `authoring-menu-item${line.alternative ? " alternative" : ""}${line.groupStart ? " group-start" : ""}${line.danger ? " danger" : ""}`,
    onClick: () => { if (!line.disabled) onPick(line.command); } }, line.label));
}

/** 구조 변경 요약(F38) — 미리보기와 변경 영향 패널이 같은 표를 쓴다. */
function StructureDelta({ delta }: { delta: Obj }) {
  // 선택 delta 는 Python 이 `[slot_id, option_id]` 쌍으로 준다 — 소속을 함께 읽어야 같은 이름의 선택이 갈린다.
  const name = (entry: Obj | string | string[]): string => typeof entry === "string" ? entry : Array.isArray(entry) ? entry.join(" / ") : String(entry.label || entry.id || entry.name || "");
  const row = (label: string, items?: (Obj | string)[]) => !!items?.length && h("p", { key: label }, `${label}: ${items.map(name).join(", ")}`);
  return h("div", { className: "authoring-delta", role: "group", "aria-label": "구조 변경" },
    row("추가 항목", delta.added_slots), row("없어진 항목", delta.removed_slots), row("추가 선택", delta.added_options), row("없어진 선택", delta.removed_options),
    !!delta.renamed?.length && h("ul", { "aria-label": "식별자 변경" }, ...delta.renamed.map((entry: Obj, index: number) => h("li", { key: index }, `${KIND_LABEL[entry.kind] || entry.kind} · ${entry.from} → ${entry.to}`))));
}

/** rhwp 마운트 경로 — 제품은 늘 mountRhwp 다. Node 시험은 WASM iframe 을 띄울 수 없어 여기만 바꿔 낀다. */
export const rhwpMount = { mount: mountRhwp };
/** 시험 결과 뷰어의 마운트 열쇠 — Python 이 결과 객체마다 새 revision 을 준다. 같은 결과의 재전송(push)은 같은 열쇠라
 *  뷰어를 다시 띄우지 않는다(UX-05). revision 이 없는 옛 투영은 내용 문자열로 가른다. */
export function trialViewerKey(item: Obj): unknown[] {
  return [item.media, item.trial_result?.revision ?? item.trial_result?.content];
}

/** 읽기 전용 HWPX 비교 뷰의 마운트 인자(host·콜백 제외). 본문 차례는 Python 이 그 내용에서 셈해 준 것을 그대로 넘긴다. */
export function externalDocumentSpec(item: Obj, content: string, sectionEntries?: string[]) {
  return { content, fileName: String(item.name || ""), readOnly: true as const, sectionEntries };
}

function ExternalDocument({ controller, item, content, sectionEntries, title }: Props & { item: Obj; content: string; sectionEntries?: string[]; title?: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let disposed = false;
    let release: (() => void) | undefined;
    void controller.guarded(async () => {
      const handle = await rhwpMount.mount({ host: host.current!, ...externalDocumentSpec(item, content, sectionEntries), trackSelection: "never", title: title || String(item.name || ""),
        onChanged: () => {}, onSelectionChanged: () => {}, onError: (error) => controller.fail(error, "compare-view") });
      if (disposed) handle.dispose(); else release = () => handle.dispose();
    }, "compare-view");
    return () => { disposed = true; release?.(); };
  }, [content]);
  return h("div", { ref: host, className: "authoring-result-pages" });
}

/** 편집면(iframe) 안에서 눌려 Studio 가 넘겨준 셸 키(§10) — 셸 onKeyDown 과 같은 길로 보낼 사건 모양. 그 밖의 키는 null. */
export function forwardedShellKey(shortcut: string, target: unknown): Obj | null {
  const key = shortcut === "Escape" ? { key: "Escape" } : shortcut === "F6" ? { key: "F6" } : shortcut === "ShiftF6" ? { key: "F6", shiftKey: true } : null;
  return key && { ...key, target, nativeEvent: {}, preventDefault() {} };
}
/** 셸의 키·문맥 메뉴·명령 팔레트 처리기 — 편집면 iframe 은 셸까지 사건을 올리지 못하므로 편집기가 이 손잡이로 넘긴다. */
type ShellInput = { current: { key?: (event: any) => void; menu?: (event: any) => void; palette?: () => void } };

type ShellKey = { key: string; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean; target?: { closest?(selector: string): unknown } | null };
/** 셸 단축키 판독(§10). 문서 편집면·입력창 안의 Ctrl+Z/Y 는 그 문맥의 실행 취소이므로 셸이 가로채지 않는다(§9.3). */
export function shellShortcut(event: ShellKey): "" | "save" | "search" | "editor-search" | "commands" | "rename" | "escape" | "cycle" | "undo" | "redo" | "context-menu" {
  const mod = !!(event.ctrlKey || event.metaKey);
  const key = String(event.key || "").toLowerCase();
  const inEditor = !!event.target?.closest?.(".authoring-editor-host,.cm-editor,iframe");
  const inInput = inEditor || !!event.target?.closest?.("input,textarea,select,[contenteditable]");
  if (mod && key === "s") return "save";
  if (mod && key === "f") return inEditor ? "editor-search" : "search";
  if (mod && event.shiftKey && key === "p") return "commands";
  if (mod && !inInput && key === "z") return event.shiftKey ? "redo" : "undo";
  if (mod && !inInput && key === "y") return "redo";
  if (event.key === "F2") return "rename";
  if (event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey)) return "context-menu";
  if (event.key === "Escape") return "escape";
  if (event.key === "F6") return "cycle";
  return "";
}

/** 속성 패널의 **적용된** 값 — 선택 대상에서 다시 유도한다. Escape 1단계는 작성 중인 값을 여기로 되돌린다(§6.2). */
export function appliedProperties(selected: Obj | null | undefined) {
  return { name: selected?.name || selected?.label || "", identifier: selected?.option_id || selected?.slot_id || selected?.id || "",
    parent: selected?.slot_id || "", text: String(selected?.raw?.value ?? selected?.name ?? "") };
}
/** Escape 의 단계: 작성 중인 값이 적용값과 다르면 입력만 되돌리고(revert), 같으면 패널을 닫는다(close). */
export function escapeStage(selected: Obj | null | undefined, draft: ReturnType<typeof appliedProperties>): "revert" | "close" {
  const applied = appliedProperties(selected);
  return (Object.keys(applied) as (keyof typeof applied)[]).some((key) => applied[key] !== draft[key]) ? "revert" : "close";
}
/** 편집기 마운트의 보존 판정 보고(U01·§7.1). 판정·안내는 Python 투영(tab.compatibility) 하나에서 선다 —
 *  Python 판정이 돌아오기 전에 편집기가 스스로 막았거나(내보내기·검사 호출 실패) 마운트가 무너지면
 *  그 사실만 Python 에 알린다. 이미 판정을 받은 뒤의 차단은 Python 이 안다(다시 알리지 않는다). */
export function compatibilityReporter(controller: Pick<AuthoringController, "preflight" | "unverified">, id: string, revision: number) {
  let judged = false;
  let reported = false;
  const report = async (detail: string) => { if (reported) return; reported = true; await controller.unverified(id, revision, detail); };
  return {
    preflight: async (content: string) => {
      const result = await controller.preflight(id, revision, content);
      judged = true;
      return { editable: result.editable, diagnostics: result.diagnostics };
    },
    onCompatibility: async (result: { editable: boolean; diagnostics?: unknown[] }) => { if (!judged && !result.editable) await report(String(result.diagnostics?.[0] ?? "")); },
    onMountError: (error: unknown) => report(error instanceof Error ? error.message : String(error)),
  };
}

/** 강조 대상의 TXT 범위(UX-09) — 항목·선택은 그 위치(마커 줄 포함), 필드는 사용 위치(index 가 있으면 그 한 곳). */
export function highlightRanges(analysis: Obj, highlight: Obj | null | undefined): { start: number; end: number }[] {
  if (!highlight) return [];
  const usable = (place: Obj | null | undefined) => place && typeof place.start === "number" && typeof place.end === "number" ? [{ start: place.start, end: place.end }] : [];
  if (highlight.kind === "slot") return usable((analysis.slots || []).find((slot: Obj) => slot.id === highlight.id)?.location);
  if (highlight.kind === "option") return usable((analysis.slots || []).find((slot: Obj) => slot.id === highlight.slot_id)?.options?.find((option: Obj) => option.id === highlight.id)?.location);
  const field = (analysis.fields || []).find((entry: Obj) => entry.name === highlight.id);
  return (field?.occurrences || []).filter((_: Obj, at: number) => highlight.index == null || highlight.index === at + 1).flatMap(usable);
}

/** 속성 제출 — 한글 조합 중 Enter 는 확정이 아니다(§6.2·§10). 보냈으면 true. */
export function submitProperties(controller: Pick<AuthoringController, "guarded" | "preview">, composing: boolean, command: () => Obj): boolean {
  if (composing) return false;
  void controller.guarded(() => controller.preview(command()));
  return true;
}

function DocumentEditor({ controller, item, active, shell }: Props & { item: Obj; active: boolean; shell: ShellInput }) {
  const host = useRef<HTMLDivElement>(null);
  const adapter = useRef<AuthoringEditor | null>(null);
  useEffect(() => {
    let disposed = false;
    let release: (() => void) | undefined;
    let detach: (() => void) | undefined;
    void controller.guarded(async () => {
      const initial = await controller.content(item.id);
      if (disposed || !host.current) return;
      if (item.media === "txt") {
        let composing = false;
        const handle = mountLintpad({ host: host.current, doc: initial.content,
          contentId: `authoring-text-${item.id}`, ariaLabel: "TXT 템플릿 원문", authoring: true,
          onDocChanged: (content) => { if (!composing) controller.changed(item.id, content); },
          onSelectionChanged: (selection) => { if (!composing) controller.selection(item.id, selection); },
          onCompositionChanged: (active) => { composing = active; if (!active) queueMicrotask(() => controller.changed(item.id, lintpadState(handle).text)); },
        });
        adapter.current = {
          flush: async () => { if (lintpadState(handle).composing) throw new Error(IME_BUSY); },
          content: async () => lintpadState(handle).text,
          apply: async (content, edits, _label, expectedContent) => {
            if (expectedContent !== undefined && lintpadState(handle).text !== expectedContent) throw new Error("문서가 변경되었습니다. 변경 미리보기를 다시 실행하세요.");
            const changes = edits.length ? [...edits].sort((a, b) => a.start - b.start) : [{ start: 0, end: lintpadState(handle).text.length, text: content }];
            if (!editLintpad(handle, changes as { start: number; end: number; text: string }[])) throw new Error(IME_BUSY);
          },
          focus: async (target) => { if (target.start != null) navigateLintpad(handle, target.start, target.end ?? target.start); },
          command: async (command) => { lintpadCommand(handle, command); },
          state: () => { const state = lintpadState(handle); return { canUndo: state.canUndo, canRedo: state.canRedo }; },
          decorate: (analysis, mode, highlight) => {
            const spans = mode === "document" ? [] : [...(analysis.spans || [])];
            if (mode === "structure") for (const place of analysis.placements || []) {
              spans.push({ kind: `${place.kind}-start`, start: place.start, end: place.start });
              spans.push({ kind: `${place.kind}-end`, start: Math.max(place.start, place.end - 1), end: place.end });
            }
            // 구조 트리 줄의 강조(UX-09)는 그 범위의 줄 전체에 선다 — 문서 모드에서도(표시만, 본문은 그대로).
            for (const range of highlightRanges(analysis, highlight)) spans.push({ kind: "highlight", ...range });
            updateLintpad(handle, { spans });
          },
        };
        release = () => disposeLintpad(handle);
      } else {
        const report = compatibilityReporter(controller, item.id, initial.revision);
        let handle: Awaited<ReturnType<typeof mountRhwp>>;
        try {
          handle = await rhwpMount.mount({ host: host.current, content: initial.content, fileName: item.name,
          sectionEntries: initial.section_entries, trackSelection: "visible",
          preflight: report.preflight,
          onCompatibility: (result) => { void controller.guarded(() => report.onCompatibility(result)); },
          title: item.name,
          // 초점을 돌려받을 자리는 편집면 iframe 이다(메뉴를 닫는 Escape·F6 순환의 출발점).
          onContextMenu: (point) => shell.current.menu?.({ clientX: point.x, clientY: point.y, target: host.current?.querySelector("iframe") || host.current }),
          onShortcut: (shortcut) => {
            const current = controller.viewModel.getSnapshot();
            const forwarded = forwardedShellKey(shortcut, host.current?.querySelector("iframe") || host.current);
            if (forwarded) shell.current.key?.(forwarded);
            else if (shortcut === "CtrlShiftP") shell.current.palette?.();
            else if (shortcut === "CtrlS") void controller.guarded(() => controller.save(), "save");
            else if (shortcut === "CtrlF") controller.update({ panel: "search", ...focusRequest(current, "dock") });
            else renameShortcut(controller);
          },
          onChanged: (content) => controller.changed(item.id, content),
          onSelectionChanged: (selection) => controller.selection(item.id, selection),
          onError: (error) => controller.fail(error, "editor"), readOnly: false });
        } catch (error) {
          // 마운트가 무너져도 안내는 남는다 — Python 이 판정 없음을 기록하고 투영한다. 보이는 오류는 원래의 것이다.
          if (!disposed) await report.onMountError(error).catch(() => undefined);
          throw error;
        }
        if (disposed) { handle.dispose(); return; }
        adapter.current = {
          flush: () => handle.flushChanges(),
          content: () => handle.content(), apply: (content, _edits, label, expectedContent) => handle.applySnapshot(content, label, expectedContent),
          focus: (target) => handle.focus(target),
          command: async (command) => { if (command === "undo") await handle.undo(); else if (command === "redo") await handle.redo(); else controller.update({ panel: "search" }); },
          decorate: (analysis, mode, highlight) => { void controller.guarded(() => handle.setDecorations({ ...analysis, mode, highlight: highlight || null }), "editor"); },
        };
        release = () => handle.dispose();
      }
      detach = controller.attach(item.id, adapter.current!);
      adapter.current!.decorate(item.analysis || {}, controller.mode(item.id));
    }, "editor");
    return () => { disposed = true; detach?.(); release?.(); adapter.current = null; };
  }, [controller, item.id]);
  // 장식은 분석이 바뀔 때만 다시 보낸다 — 같은 분석의 재전송(push)은 같은 revision 이다(UX-05).
  useEffect(() => { adapter.current?.decorate(item.analysis || {}, controller.mode(item.id)); }, [item.analysis?.revision ?? item.analysis, active]);
  return h("div", { className: "authoring-document", hidden: !active, inert: !active || !!item.recovery, "aria-hidden": !active },
    h("div", { ref: host, className: "authoring-editor-host" }));
}

function SemanticForm({ controller, selected, selection, preview, onClose }: Props & { selected: Obj; selection: Obj; preview: Obj | null; onClose: () => void }) {
  const view = controller.viewModel.getSnapshot();
  const [type, setType] = useState(view.commandType || "create_field");
  const [name, setName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [parent, setParent] = useState("");
  const [text, setText] = useState("");
  const [cascade, setCascade] = useState(false);
  const [keepValue, setKeepValue] = useState(true);
  const composing = useRef(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const readOnly = controller.tab().media === "hwpx" && controller.tab().rhwp_editable !== true;
  const available = commandAvailability(view.commands, type);
  const refusal: Obj | null = view.refusal;
  const switchType = (next: string) => { setType(next); controller.update({ preview: null, refusal: null, commandType: next }); };
  const cancel = () => controller.update({ preview: null, refusal: null });
  // 기존 필드에 연결(U07)은 개별 사용 위치 한 곳이 선택됐을 때만 뜻이 있다 — 필드 전체 선택은 사용 위치 묶음(occurrences)을 가진다.
  const singleOccurrence = selected?.kind === "field" && !selected?.occurrences;
  const candidates: Obj[] = preview?.candidates || controller.tab().analysis?.fields || [];
  const affected = preview?.affected ?? preview?.edits?.length ?? 0;
  const revert = () => { const applied = appliedProperties(selected); setName(applied.name); setIdentifier(applied.identifier); setParent(applied.parent); setText(applied.text); };
  useEffect(() => { revert(); if (selected?.occurrences) setType("rename_field"); }, [selected]);
  useEffect(() => { if (view.commandType) setType(view.commandType); }, [view.commandType]);
  const command = (): Obj => ({ ...selected, ...(["create_field", "create_slot", "create_option", "adjust_range"].includes(type) ? selection : {}), type, name, old_name: selected?.name || name,
    id: identifier || name, label: name, slot_id: type === "create_option" ? view.context?.slot_id : parent || selected?.slot_id || selected?.id,
    option_id: selected?.option_id, kind: selected?.kind || "slot", text, cascade,
    destination: selection.start, destination_entry: selection.entry, destination_paragraph: selection.start_paragraph ?? selection.paragraph, new_id: identifier || name });
  // 문맥 줄(UX-10 R2): Python 의 location_label(담긴 항목/선택 · 문단·행 범위)만 보인다 — 원시 좌표는 싣지 않는다.
  const locationLabel = String(view.context?.location_label || "");
  // 선택한 문구 카드(UX-10 R2): 의미가 아직 없는 글자 범위를 고른 채 속성을 열면(필드로 만들기) 무엇을 만드는지 보인다.
  const textRange = !selected && selection.start != null && selection.end != null && (selection.start !== selection.end
    || (selection.start_paragraph ?? selection.paragraph) !== (selection.end_paragraph ?? selection.start_paragraph ?? selection.paragraph));
  // 화면 읽기(§10): 이름 칸은 대상(종류·사용 위치)과 소속(상위 항목/선택·범위)을 설명으로 함께 읽힌다.
  const describedBy = [(selected || textRange) && "authoring-properties-target", locationLabel && "authoring-properties-context"].filter(Boolean).join(" ") || undefined;
  const field = (label: string, value: string, onChange: (value: string) => void) => h("label", { className: "authoring-field" }, label,
      h("input", { className: "field", value, ref: label.includes("이름") ? nameInput : undefined, list: label === "필드 이름" ? "authoring-existing-fields" : undefined,
        "aria-describedby": label.includes("이름") ? describedBy : undefined, onChange: (event: any) => onChange(event.target.value) }));
  const close = () => { controller.update({ panel: "", preview: null, refusal: null }); onClose(); };
  // 대상 카드(UX-09): 종류 표지 · 굵은 이름 · 메타 한 줄. 이름 칸의 설명(aria-describedby)은 카드 전체의 접근 이름이다.
  const whole = selected?.kind === "field" && Array.isArray(selected?.occurrences);
  const kind: "field" | "slot" | "option" | null = selected?.kind === "field" || selected?.kind === "slot" || selected?.kind === "option" ? selected.kind : null;
  const problems = problemCount(controller.tab().problems, selected?.kind === "field" ? selected?.name : selected?.option_id || selected?.slot_id || selected?.name);
  const targetMeta = selected?.kind === "field"
    ? [selected.occurrences ? `사용 위치 ${selected.count ?? selected.occurrences.length}곳` : "", selected.occurrences ? "" : String(selected.context || ""), problems ? `문제 ${problems}` : ""]
    : [String(selected?.location_label || ""), problems ? `문제 ${problems}` : ""];
  const applyLabel = COMMANDS.find(([value]) => value === type)?.[1] || "적용";
  const apply = () => { void controller.guarded(async () => {
    if (composing.current || !preview) return;
    const captured = preview.original;
    await controller.applyPreview();
    if (type === "create_field" && captured) controller.update({ lastCreatedText: String(captured) });
    if (type === "create_field" && keepValue && name && captured) await controller.keepTrialValue(name, String(captured));
  }); };
  return h("form", { className: "authoring-properties", "aria-labelledby": "authoring-properties-title", onCompositionStart: () => { composing.current = true; }, onCompositionEnd: () => { composing.current = false; },
    onSubmit: (event: any) => { event.preventDefault(); submitProperties(controller, composing.current, command); },
    // Escape 1단계: 입력창의 작성 중인 값만 적용값으로 되돌린다. 2단계(되돌릴 것이 없을 때)는 셸이 패널을 닫고 선택으로 돌아간다.
    onKeyDown: (event: any) => {
      if (event.key !== "Escape" || event.nativeEvent?.isComposing) return;
      if (escapeStage(selected, { name, identifier, parent, text }) === "revert") { event.stopPropagation(); revert(); }
    } },
    // 닫기(§3.1): 모든 폭에서 머리 오른쪽에 선다 — Escape 의 닫기 단계와 같은 일(패널을 닫고 선택으로 돌아간다).
    h("div", { className: "authoring-properties-head" }, sectionLabel("속성", { id: "authoring-properties-title" }),
      iconButton("close", "닫기", close)),
    selected && h("div", { className: "authoring-target" },
      kind && h("span", { className: "authoring-target-kind" }, kindGlyph(kind), h("span", { className: "authoring-kind" }, KIND_LABEL[kind])),
      // 필드 전체는 이름 칸의 설명이 outlineLabel 전체(종류·이름·사용 위치 수·문제)다 — 보이는 것은 굵은 이름과 메타 줄이고,
      // 종류·수는 화면 읽기용 글로만 이름에 붙는다(보이는 표지·메타와 같은 글이라 두 번 읽히지 않게 메타는 숨긴다).
      whole ? h("p", { id: "authoring-properties-target", className: "authoring-target-name" },
          h("span", { className: "authoring-sr" }, `${KIND_LABEL.field} · `), selected.name,
          h("span", { className: "authoring-sr" }, ` · ${[`사용 위치 ${selected.count ?? selected.occurrences.length}곳`, ...(problems ? [`문제 ${problems}`] : [])].join(" · ")}`))
        : h("p", { id: "authoring-properties-target", className: "authoring-target-name" }, selected.name || selected.label || selected.id),
      targetMeta.some(Boolean) && h("p", { className: "authoring-target-meta", "aria-hidden": whole || undefined }, targetMeta.filter(Boolean).join(" · "))),
    // 카드 전체가 이름 칸의 설명이다(종류 「선택한 문구」 + 글자). 글자를 확정할 수 없으면(문단을 넘는 범위 등) 종류만 선다.
    textRange && h("div", { className: "authoring-target", id: "authoring-properties-target" },
      h("span", { className: "authoring-target-kind" }, h("span", { className: "authoring-kind" }, "선택한 문구")),
      !!view.context?.selected_text && h("p", { className: "authoring-target-name quote", title: String(view.context.selected_text) }, String(view.context.selected_text))),
    // 명령을 바꿔도 초점은 이 select 에 남는다(WCAG 3.2.2) — 닫힌 select 의 ↑↓ 는 값마다 change 를 쏜다.
    h("label", { className: "authoring-field" }, "명령", h("select", { className: "field", value: type, "aria-disabled": !available.enabled || undefined, title: available.reason || undefined,
      "aria-describedby": !available.enabled && available.reason ? "authoring-properties-reason" : undefined, onChange: (event: any) => switchType(event.target.value) },
      ...COMMANDS.map(([value, label]) => { const entry = commandAvailability(view.commands, value); return h("option", { key: value, value, disabled: !entry.enabled, title: entry.reason || undefined }, label); }))),
    // 비활성 사유와 대안은 Python 의 판정을 그대로 보인다(P07) — 툴팁만이 유일한 경로가 되지 않도록 본문에도 선다(§10).
    !available.enabled && available.reason && h("p", { className: "authoring-reason", id: "authoring-properties-reason" }, available.reason),
    !available.enabled && available.alternative && h("div", null, button(available.alternative.label, () => switchType(available.alternative!.command_type))),
    locationLabel && h("p", { className: "authoring-context", id: "authoring-properties-context" }, locationLabel),
    field(type.includes("field") ? "필드 이름" : "표시 이름", name, setName),
    type === "create_field" && h("datalist", { id: "authoring-existing-fields" }, ...candidates.map((candidate: Obj) => h("option", { key: candidate.name, value: candidate.name, label: `${candidate.name} · 사용 위치 ${candidate.count ?? 0}곳` }))),
    !["create_field", "rename_field", "relink_field", "unset_field"].includes(type) && field("연결 식별자", identifier, setIdentifier),
    type === "create_option" ? h("p", null, `상위 항목: ${view.context?.slot_id || "없음"}`) :
      ["rename_option", "adjust_range", "unwrap", "delete", "duplicate", "move"].includes(type) && field("상위 항목", parent, setParent),
    type === "unset_field" && field("남길 본문", text, setText),
    type === "unset_field" && h("div", { className: "authoring-actions start" },
      quiet("필드 이름 사용", () => setText(selected?.name || "")),
      quiet("시험값 사용", () => setText(String(view.values[selected?.name] ?? "")), { disabled: !(selected?.name in view.values) })),
    type === "create_field" && h("label", null, h("input", { type: "checkbox", checked: keepValue, onChange: (event: any) => setKeepValue(event.target.checked) }), " 선택 문구를 시험값으로 보관"),
    type === "unwrap" && h("label", null, h("input", { type: "checkbox", checked: cascade, onChange: (event: any) => setCascade(event.target.checked) }), " 하위 의미 함께 해제"),
    // 기본 범위는 현재 선택 한 곳이다(U03) — 같은 문구의 다른 자리는 별도 검색으로만 찾는다.
    type === "create_field" && !!view.lastCreatedText && h("div", null, quiet("다른 같은 문구 찾기", () => { const text = view.lastCreatedText; controller.update({ lastCreatedText: "" }); void controller.guarded(() => controller.search(text, "body")); })),
    // 거절(U07·AC08·AC10): Python 의 판정 문장을 그대로 보이고, 다음 행동만 버튼으로 세운다.
    refusal && h("section", { className: "authoring-preview authoring-refusal", role: "alert", "aria-label": "변경 불가" },
      h("p", null, refusal.message),
      refusal.code === "cascade_required" && h("ul", { "aria-label": "함께 해제될 하위 의미" }, ...(refusal.children || []).map((child: Obj, index: number) =>
        h("li", { key: index }, `${KIND_LABEL[child.kind] || child.kind} · ${child.label || child.id}${child.count != null ? ` · ${child.count}` : ""}`))),
      h("div", { className: "authoring-actions" },
        button("취소", cancel, { className: "btn quiet" }),
        refusal.code === "name_conflict" && quiet("다른 이름 입력", () => { nameInput.current?.focus(); nameInput.current?.select(); }),
        refusal.code === "name_conflict" && singleOccurrence && button("기존 필드에 연결", () => { setName(String(refusal.name || "")); switchType("relink_field"); }),
        refusal.code === "cascade_required" && primary("하위 의미 함께 해제", () => { setCascade(true); submitProperties(controller, composing.current, () => ({ ...command(), cascade: true })); }))),
    preview && h("section", { className: "authoring-preview", "aria-label": "변경 영향" },
      h("h3", { className: "authoring-section-label" }, "변경 영향"),
      preview.expanded && h("p", null, "선택을 문단 전체로 확장합니다. 포함될 내용을 확인하세요."),
      // 전체 이름 변경의 문장(§13)은 조사까지 Python 이 짓는다(preview.message) — 표면은 그대로 보인다.
      h("p", null, preview.message || `사용 위치 ${affected}곳`),
      preview.counts && h("p", null, `문단 ${preview.counts.paragraphs ?? 0} · 필드 ${preview.counts.fields ?? 0} · 선택 ${preview.counts.options ?? 0} · 표 ${preview.counts.tables ?? 0}`),
      preview.included != null && (Array.isArray(preview.included)
        ? h("ul", { "aria-label": "포함될 내용" }, ...preview.included.map((entry: Obj | string, index: number) => h("li", { key: index }, typeof entry === "string" ? entry : entry.label || entry.text || entry.id)))
        : h("pre", { role: "group", "aria-label": "포함될 내용" }, String(preview.included))),
      !!preview.children?.length && h("ul", { "aria-label": "하위 의미" }, ...preview.children.map((child: Obj, index: number) =>
        h("li", { key: index }, `${KIND_LABEL[child.kind] || child.kind} · ${child.label || child.id}${child.count != null ? ` · ${child.count}` : ""}`))),
      preview.links_existing && h("p", null, `기존 필드에 연결 · 사용 위치 ${preview.existing_count ?? 0}곳`),
      (preview.before || preview.original) && h("pre", { role: "group", "aria-label": "변경 전" }, preview.before || preview.original),
      preview.after && h("pre", { role: "group", "aria-label": "변경 후" }, preview.after),
      preview.structure_delta && h(StructureDelta, { delta: preview.structure_delta }),
      !!preview.structure_delta?.renamed?.length && h("p", null, IDENTIFIER_IMPACT),
      preview.body_changed && h("p", null, "본문 변경 있음"),
      !!preview.linked_jobs?.length && h("p", null, `연결된 작업: ${preview.linked_jobs.join(", ")}`),
      !!preview.impact_unverified && h("p", null, "연결된 작업의 영향은 확인하지 않았습니다."),
      preview.field_delta && h("p", null, `추가 필드: ${(preview.field_delta.added_fields || []).join(", ") || "없음"} · 없어진 필드: ${(preview.field_delta.removed_fields || []).join(", ") || "없음"}`),
      ...(preview.edits || []).map((edit: Obj, index: number) => h("pre", { key: index }, edit.text))),
    // 바닥 행동 줄(UX-09): 오른쪽 정렬 — 미리보기 전에는 [취소][변경 미리보기], 미리보기 뒤에는 적용(명령 이름)이 이 구획의
    // 주 행동이 된다. 미리보기 단추는 그대로 남아 입력을 고친 뒤 다시 볼 수 있고, Enter 제출도 이 단추가 받는다.
    h("div", { className: "authoring-actions authoring-properties-actions" },
      quiet("취소", preview ? cancel : close),
      h("button", { className: "btn", type: "submit", disabled: readOnly || !available.enabled, "aria-disabled": (readOnly || !available.enabled) || undefined, title: available.reason || undefined }, "변경 미리보기"),
      preview && primary(applyLabel, apply)),
  );
}

function Trial({ controller, item, view }: Props & { item: Obj; view: Obj }) {
  const result = item.trial_result;
  const output = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let disposed = false;
    let release: (() => void) | undefined;
    if (item.media === "hwpx" && result?.content && output.current) void controller.guarded(async () => {
      const editor = await rhwpMount.mount({ host: output.current!, content: result.content, fileName: "시험 결과.hwpx", title: "시험 결과", readOnly: true,
        sectionEntries: result.section_entries, trackSelection: "visible",
        onChanged: () => {}, onSelectionChanged: (target) => controller.update({ resultSelection: target }),
        onError: (error) => controller.fail(error, "trial-view") });
      if (disposed) editor.dispose(); else release = () => editor.dispose();
    }, "trial-view");
    return () => { disposed = true; release?.(); };
  }, trialViewerKey(item));
  const select = (entry: Obj) => () => { void controller.guarded(() => controller.select({ ...(entry.source || entry), source_revision: result.source_revision })); };
  const traceRow = (entry: Obj) => rowButton({ chip: kindTag("field"), text: entry.name || entry.field || "필드", value: String(entry.value ?? "") }, select(entry),
    { "aria-label": `${entry.name || entry.field || "필드"}: ${entry.value ?? ""}` });
  const coverage: Obj[] = item.trial_coverage || [];
  const missingFields: string[] = item.trial_missing?.fields || [];
  const missingSlots: string[] = item.trial_missing?.slots || [];
  // 결과 시험(§8.1 · UX-09): 왼쪽 열은 입력 → 선택 구성 → 자동 갱신 → [시험 시작(주 행동)][시험 케이스 저장], 가져오기·내보내기는
  // 물러선 한 줄, 보관 케이스는 행. 오른쪽 열은 상태 칩 + 문장 → 선택별 시험 상태 → 결과 → 출력·제외 이유(행).
  return h("section", { className: "authoring-trial", "aria-label": "결과 시험" },
    h("header", null, h("h2", null, "결과 시험"), h("p", null, "시험 자료는 템플릿 파일에 포함되지 않습니다.")),
    h("div", { className: "authoring-trial-input" },
      item.cases_error && h("p", { role: "alert" }, item.cases_error),
      h("div", { className: "authoring-trial-group" },
        // 「필드 이름 사용」(IDE-01): 손대지 않은 필드만 그 이름으로 채우는 한 번의 입력 전이 — 채울 필드(trial_missing)가
        // 없으면 비활성이다. 어느 필드를 채울지는 Python 이 정한다.
        !!item.analysis?.fields?.length && h("div", { className: "authoring-actions start" },
          button("필드 이름 사용", () => { void controller.guarded(controller.fillTrialNames); }, { disabled: !missingFields.length })),
        ...(item.analysis?.fields || []).map((field: Obj) => h("label", { key: field.name, className: "authoring-field" }, field.name,
          // 손대지 않은 필드는 입력칸이 aria-invalid 를 받고 결과 시험 탭 배지로 센다 — 결과는 빈 값 표식으로 렌더된다.
          h("input", { className: "field", "aria-invalid": missingFields.includes(field.name) || undefined, value: view.values[field.name] || "",
            onCompositionEnd: (event: any) => { void controller.guarded(() => controller.trialInput({ ...controller.viewModel.getSnapshot().values, [field.name]: event.currentTarget.value }, controller.viewModel.getSnapshot().selectedOptions)); },
            onChange: (event: any) => {
              const values = { ...controller.viewModel.getSnapshot().values, [field.name]: event.target.value };
              if (event.nativeEvent.isComposing) controller.update({ values });
              else void controller.guarded(() => controller.trialInput(values, controller.viewModel.getSnapshot().selectedOptions));
            } })))),
      !!item.analysis?.slots?.length && h("div", { className: "authoring-trial-group" },
        ...(item.analysis?.slots || []).map((slot: Obj) => h("label", { key: slot.id, className: "authoring-field" }, slot.label || slot.id,
          h("select", { className: "field", "aria-invalid": missingSlots.includes(slot.id) || undefined, value: view.selectedOptions[slot.id] || "", onChange: (event: any) => { void controller.guarded(() => controller.trialInput(view.values, { ...view.selectedOptions, [slot.id]: event.target.value })); } },
            h("option", { value: "" }, "선택"), ...(slot.options || []).map((option: Obj) => h("option", { key: option.id, value: option.id }, option.label || option.id)))))),
      h("label", { className: "authoring-check" }, h("input", { type: "checkbox", checked: view.autoTrial, onChange: (event: any) => controller.update({ autoTrial: event.target.checked }) }), " 자동 갱신"),
      h("div", { className: "authoring-actions start" },
        primary("시험 시작", () => { void controller.guarded(() => controller.runTrial(), "trial"); }, { disabled: view.trialBusy }),
        button("시험 케이스 저장", () => { void controller.guarded(() => controller.saveCase()); })),
      h("div", { className: "authoring-actions start quiet-row" },
        quiet("시험 자료 가져오기", () => { void controller.guarded(() => controller.transferCases("import")); }),
        quiet("시험 자료 내보내기", () => { void controller.guarded(() => controller.transferCases("export")); })),
      h("h3", { className: "authoring-section-label" }, "보관한 시험 케이스"),
      rowList("보관한 시험 케이스", (item.cases || []).map((test: Obj) => h("div", { key: test.name, className: "authoring-case" },
        rowButton({ text: test.name, context: test.needs_review ? "다시 확인 필요" : null }, () => { void controller.guarded(() => controller.loadCase(test)); },
          { "aria-label": `${test.name}${test.needs_review ? " · 다시 확인 필요" : ""}` }),
        iconButton("trash", `${test.name} 삭제`, () => { void controller.guarded(() => controller.removeCase(test.name)); }))))),
    h("div", { className: "authoring-trial-output" },
      // 상태 줄은 보이는 글로만 남는다 — 화면 읽기는 셸의 단일 live region 이 결과가 바뀔 때만 한다(UX-04).
      h("div", { className: "authoring-trial-state" },
        item.trial_state_label && h("span", { className: "authoring-badge", "data-trial": item.trial_state }, item.trial_state_label),
        h("p", null, view.trialBusy ? "갱신 중 · 이전 결과" : item.trial_state_message),
        quiet("시험 결과 내보내기", () => { void controller.guarded(controller.exportResult); }, { disabled: item.trial_state !== "current" })),
      h("p", { className: "authoring-reason" }, "통과 표시는 현재 값과 선택 구성에만 해당합니다."),
      // 선택별 시험 상태: 구조 트리와 같은 점(채움 모양)과 같은 이름이다.
      !!coverage.length && h("ul", { className: "authoring-coverage", "aria-label": "선택별 시험 상태" }, ...coverage.map((entry: Obj) =>
        h("li", { key: `${entry.slot_id}/${entry.option_id}` }, h("span", { className: "authoring-coverage-dot", "data-state": entry.state }, coverageDot(entry.state)),
          `${entry.slot_id} / ${entry.option_id} · ${COVERAGE_LABEL[entry.state]}`))),
      item.media === "txt" ? h(TxtTrialOutput, { controller, result, selected: view.selected }) : h("div", { className: "authoring-result-pages", ref: output }),
      h("h3", { className: "authoring-section-label" }, "출력·제외 이유"),
      item.media === "hwpx" && view.resultSelection?.entry && h("div", null, h("h4", { className: "authoring-section-label" }, "선택한 문단의 필드"),
        rowList("선택한 문단의 필드", (result?.occurrences || []).filter((entry: Obj) => entry.output?.entry === view.resultSelection.entry && entry.output?.paragraph === view.resultSelection.paragraph).map(traceRow))),
      rowList("출력·제외 이유", [
        ...(result?.occurrences || result?.trace || []).map(traceRow),
        ...(result?.excluded || []).map((entry: Obj) => rowButton({ chip: kindTag("option"), text: entry.reason || entry.label || entry.option_id }, select(entry)))])),
  );
}

function TxtTrialOutput({ controller, result, selected }: Props & { result?: Obj; selected: Obj }) {
  const text = String(result?.text ?? result?.content ?? "");
  const parts: ReactNode[] = [];
  let end = 0;
  for (const [index, occurrence] of (result?.occurrences || []).entries()) {
    parts.push(text.slice(end, occurrence.output_start));
    parts.push(h("button", { type: "button", key: index, className: "authoring-output-field",
      "aria-label": `${occurrence.name}: ${occurrence.value}`, "aria-pressed": selected?.name === occurrence.name,
      onClick: () => { void controller.guarded(() => controller.select({ ...occurrence, source_revision: result?.source_revision })); } }, text.slice(occurrence.output_start, occurrence.output_end) || "∅"));
    end = occurrence.output_end;
  }
  parts.push(text.slice(end));
  return h("pre", { tabIndex: 0, role: "group", "aria-label": "읽기 전용 시험 결과" }, ...parts);
}

/** 구조 목록 한 줄(tree 항목). children 은 펼친 뒤에만 부른다(UX-05) — 사용 위치가 많은 문서에서 보이지 않는 줄을 짓지 않는다.
 *  kind 는 안내선의 종류(항목=실선·선택=점선)를 CSS 에 알리고, highlight 는 줄에 머문 동안 편집면이 강조할 대상이다(UX-09). */
type TreeNode = { key: string; label: string; content: ReactNode[]; entry: Obj; kind?: string; highlight?: Obj; open?: boolean; children?: () => TreeNode[] };
type TreeHandlers = { onSelect(entry: Obj, element: HTMLElement): void; onMenu(entry: Obj, element: HTMLElement, anchor: { x: number; y: number; top?: number }): void };

/** 구조 목록(§3.3·§10)은 APG treeview 다: 한 번의 Tab 으로 들어오고(roving tabindex), ↑↓ 이동·→ 펼침/첫 자식·
 *  ← 접힘/부모·Home·End, Enter·Space 로 고른다. 지금 위치(current — 바깥에서 안쪽으로의 열쇠 경로)는 **보이는 가장 안쪽**
 *  줄 하나에 aria-current 와 색이 아닌 표지(왼쪽 막대·굵기)로 서고, 바뀌면 그 줄이 보이도록 목록을 옮긴다.
 *  이름은 outlineLabel 그대로다. 펼침 상태는 이 목록의 수명(문서 탭 하나)만큼 남는다. */
function OutlineTree({ labelledBy, nodes, current, inactive, onSelect, onMenu, onHighlight }: TreeHandlers & { labelledBy: string; nodes: TreeNode[]; current: string[]; inactive?: boolean; onHighlight(target: Obj | null): void }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [focusKey, setFocusKey] = useState("");
  const elements = useRef(new Map<string, HTMLElement>());
  // 보이는 줄의 평탄한 차례 — 키보드 이동의 기준. 펼친 줄의 자식만 여기서 짓는다.
  const rows: (TreeRow & { node: TreeNode })[] = [];
  const kids = new Map<string, TreeNode[]>();
  const walk = (list: TreeNode[], parent: string | null) => {
    for (const node of list) {
      const expandable = !!node.children;
      const open = expandable && (expanded[node.key] ?? !!node.open);
      rows.push({ key: node.key, parent, expandable, expanded: open, node });
      if (open) { const children = node.children!(); kids.set(node.key, children); walk(children, node.key); }
    }
  };
  walk(nodes, null);
  const byKey = new Map(rows.map((row) => [row.key, row]));
  const currentKey = [...current].reverse().find((key) => byKey.has(key));
  const active = byKey.has(focusKey) ? focusKey : currentKey ?? rows[0]?.key;
  // 현재 위치 따라가기(F15): 캐럿이 옮긴 줄이 목록 밖이면 가장 가까운 쪽으로 스크롤한다(초점은 옮기지 않는다).
  useEffect(() => { if (currentKey) elements.current.get(currentKey)?.scrollIntoView?.({ block: "nearest" }); }, [currentKey]);
  const toggle = (key: string, open: boolean) => setExpanded((state) => ({ ...state, [key]: open }));
  const own = (event: any) => event.target?.closest?.('[role="treeitem"]') === event.currentTarget;
  const render = (node: TreeNode): ReactNode => {
    const row = byKey.get(node.key)!;
    // 숨은 보기(다른 탭)의 tree 는 Tab·F6 의 입구를 두지 않는다(inactive).
    return h("li", { key: node.key, role: "treeitem", "data-tree-key": node.key, "data-kind": node.kind, tabIndex: !inactive && node.key === active ? 0 : -1, "aria-label": node.label,
      "aria-expanded": row.expandable ? row.expanded : undefined, "aria-current": node.key === currentKey ? "true" : undefined,
      ref: (element: HTMLElement | null) => { if (element) elements.current.set(node.key, element); else elements.current.delete(node.key); },
      onClick: (event: any) => { if (own(event)) onSelect(node.entry, event.currentTarget); },
      onContextMenu: (event: any) => { if (!own(event)) return; event.preventDefault(); event.stopPropagation(); onMenu(node.entry, event.currentTarget, { x: event.clientX, y: event.clientY }); } },
      h("span", { className: "authoring-tree-row", onMouseEnter: () => onHighlight(node.highlight || null) },
        // 펼침 표지는 마우스용이다(키보드는 →·←). 글자가 아니라 CSS 가 그린다.
        h("span", { className: "authoring-tree-toggle", "aria-hidden": true, "data-leaf": row.expandable ? undefined : "",
          onClick: row.expandable ? (event: any) => { event.stopPropagation(); toggle(node.key, !row.expanded); } : undefined }),
        ...node.content),
      row.expanded && h("ul", { role: "group" }, ...(kids.get(node.key) || []).map(render)));
  };
  return h("ul", { className: "authoring-tree", role: "tree", "aria-labelledby": labelledBy,
    onMouseLeave: () => onHighlight(null),
    onBlur: (event: any) => { if (!event.currentTarget?.contains?.(event.relatedTarget)) onHighlight(null); },
    onFocus: (event: any) => {
      const key = event.target?.getAttribute?.("data-tree-key");
      if (!key) return;
      if (key !== focusKey) setFocusKey(key);
      // 키보드로 옮긴 줄도 편집면에서 강조한다 — 마우스와 같은 길(§10).
      onHighlight(byKey.get(key)?.node.highlight || null);
    },
    onKeyDown: (event: any) => {
      const element = event.target?.closest?.('[role="treeitem"]') as HTMLElement | null;
      const key = element?.getAttribute("data-tree-key");
      const row = key ? byKey.get(key) : undefined;
      if (!element || !row || event.nativeEvent?.isComposing) return;
      // Shift+F10·메뉴 키는 이 줄을 고른 뒤 그 줄 아래에 문맥 메뉴를 연다(§6.1) — 셸의 일반 경로로 가지 않는다.
      if (shellShortcut(event) === "context-menu") {
        event.preventDefault(); event.stopPropagation();
        const rect = (element.querySelector(".authoring-tree-row") || element).getBoundingClientRect();
        onMenu(row.node.entry, element, { x: rect.left, y: rect.bottom, top: rect.top });
        return;
      }
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const action = treeKey(event.key, rows, row.key);
      if (!action) return;
      event.preventDefault();
      if (action.expand) toggle(action.expand, true);
      if (action.collapse) toggle(action.collapse, false);
      if (action.focus) { setFocusKey(action.focus); elements.current.get(action.focus)?.focus(); }
      if (action.select) onSelect(row.node.entry, element);
    } }, ...nodes.map(render));
}

/** 브레드크럼 차례(UX-09): 바깥에서 안쪽으로 — 항목 › 선택 › 필드. Python 이 준 일치 후보를 종류 차례로만 세운다. */
export function crumbs(matches: Obj[] | undefined): Obj[] {
  const rank: Obj = { slot: 0, option: 1, field: 2 };
  return [...(matches || [])].map((match, at) => ({ match, at })).sort((a, b) => (rank[a.match.kind] ?? 3) - (rank[b.match.kind] ?? 3) || a.at - b.at).map((entry) => entry.match);
}
/** 문자 몇 개를 「 · 」 로 잇는다 — 빈 것은 뺀다. */
const joined = (...parts: unknown[]) => parts.filter((part) => part !== null && part !== undefined && part !== false && part !== "" && part !== 0).join(" · ");
/** 대상별 가장 무거운 심각도(오류 > 경고) — 문제 줄의 글리프 자리에 글자 칩으로 선다(§10: 색이 아니라 글자). */
export function problemSeverities(problems: Obj[] | undefined): Map<string, string> {
  const severities = new Map<string, string>();
  for (const problem of problems || []) if (problem.target != null && severities.get(problem.target) !== "error") severities.set(problem.target, problem.severity);
  return severities;
}
type RowParts = { severity?: string; tag?: boolean; dot?: ReactNode; meta?: string };
/** 트리 한 줄의 보이는 내용: [글리프 또는 심각도 칩] [종류 표지] [시험 점] [이름 — 한 줄 말줄임, 전체는 title] … [흐린 메타]. */
function rowContent(kind: "slot" | "option" | "field", name: string, parts: RowParts): ReactNode[] {
  return [
    h("span", { key: "glyph", className: "authoring-tree-glyph" }, parts.severity
      ? h("span", { className: "authoring-badge", "data-severity": parts.severity }, SEVERITY_LABEL[parts.severity] || parts.severity) : kindGlyph(kind)),
    parts.tag === false ? null : h("span", { key: "kind", className: "authoring-kind" }, KIND_LABEL[kind]),
    parts.dot || null,
    h("span", { key: "name", className: "authoring-tree-name", title: name }, name),
    parts.meta ? h("span", { key: "meta", className: "authoring-tree-meta" }, parts.meta) : null,
  ];
}
const EMPTY_STRUCTURE = "항목·선택이 없습니다. 문단을 고르고 「항목으로 만들기」를 누르세요.";
const EMPTY_FIELDS = "필드가 없습니다. 문구를 고르고 「필드로 만들기」를 누르세요.";

/** 왼쪽 템플릿 구조(§3.1 UI03·UI04·§3.3 · UX-09): 한 패널의 두 보기.
 *  - 구조: 문서 순서의 척추 — 항목(실선 안내선) 아래 선택(점선 안내선), 필드 사용 위치는 그것을 담은 자리에 잎으로 선다.
 *    선택 앞의 점은 시험 상태(채움 모양), 여러 자리에 선 필드는 「같은 필드, i/n」.
 *  - 필드: 이름별 묶음(처음 쓰인 순서) — 펼치면 사용 위치(문맥과 소속). 사용 위치 줄은 펼친 뒤에만 짓는다(UX-05).
 *  필터는 두 보기 모두에서 일치하는 줄과 그 조상을 남긴다. 줄에 마우스·초점이 머물면 편집면이 그 범위를 강조한다. */
function Outline({ controller, item, view, counts, onSelect, onMenu, onContext }: Props & TreeHandlers & { item: Obj; view: Obj; counts: Map<string, number>; onContext(event: any): void }) {
  const [tab, setTab] = useState<"structure" | "fields">("structure");
  const [query, setQuery] = useState("");
  const analysis: Obj = item.analysis || {};
  const version = analysis.revision ?? analysis;
  const spine = useMemo(() => outlineSpine(analysis), [version]);
  const fields = useMemo(() => fieldsInFirstUse(analysis), [version]);
  const severities = useMemo(() => problemSeverities(item.problems), [item.problems]);
  const current = outlineCurrent(analysis, view.selected, view.matches);
  const coverage = new Map<string, string>((item.trial_coverage || []).map((entry: Obj) => [`${entry.slot_id}\u0000${entry.option_id}`, entry.state]));
  // 강조 요청은 줄을 훑는 동안 마지막 것만 보낸다 — 문서 장식을 줄마다 다시 그리지 않는다.
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const highlight = (target: Obj | null) => {
    if (pending.current) clearTimeout(pending.current);
    pending.current = setTimeout(() => { pending.current = null; controller.highlight(target); }, 60);
  };
  useEffect(() => () => { if (pending.current) clearTimeout(pending.current); }, [item.id]);
  const filtering = !!query.trim();
  const problemsOf = (target: string) => counts.get(target) || 0;

  const spineNodes = (list: SpineNode[], matched: boolean): TreeNode[] => list.flatMap((node): TreeNode[] => {
    if (node.kind === "use") {
      const { field, occurrence, index, total } = node;
      if (!matched && !filterMatch(query, field.name, occurrence.context)) return [];
      const problems = problemsOf(field.name);
      return [{ key: outlineKey.use(field.name, index), kind: "use", label: joined(KIND_LABEL.field, field.name, sameFieldMeta(index, total), problems && `문제 ${problems}`),
        content: rowContent("field", field.name, { severity: severities.get(field.name), meta: joined(sameFieldMeta(index, total), problems && `문제 ${problems}`) }),
        entry: { ...occurrence, name: field.name, kind: "field" }, highlight: { kind: "field", id: field.name, index } }];
    }
    const own = node.kind === "slot" ? node.slot : node.option;
    const name = String(own.label || own.id);
    const self = matched || filterMatch(query, own.label, own.id);
    const children = filtering ? spineNodes(node.children, self) : null;
    if (filtering && !self && !children!.length) return [];
    const problems = problemsOf(own.id);
    const build = () => children ?? spineNodes(node.children, true);
    const expandable = filtering ? !!children!.length : node.children.length > 0;
    if (node.kind === "slot") {
      const slot = node.slot;
      return [{ key: outlineKey.slot(slot.id), kind: "slot", label: joined(outlineLabel("slot", slot), slot.location_label, problems && `문제 ${problems}`),
        content: rowContent("slot", name, { severity: severities.get(slot.id), meta: joined(slot.location_label, problems && `문제 ${problems}`) }),
        entry: { ...slot, ...slot.location, kind: "slot", slot_id: slot.id }, highlight: { kind: "slot", id: slot.id }, open: true,
        children: expandable ? build : undefined }];
    }
    const { slot, option } = node;
    const state = coverage.get(`${slot.id}\u0000${option.id}`);
    const dot = state ? h("span", { key: "dot", className: "authoring-coverage-dot", "data-state": state, title: COVERAGE_LABEL[state] }, coverageDot(state)) : null;
    return [{ key: outlineKey.option(slot.id, option.id), kind: "option",
      label: joined(outlineLabel("option", option, 0, slot.label || slot.id), option.location_label, state && COVERAGE_LABEL[state], problems && `문제 ${problems}`),
      content: rowContent("option", name, { severity: severities.get(option.id), dot, meta: joined(option.location_label, problems && `문제 ${problems}`) }),
      entry: { ...option, ...option.location, kind: "option", slot_id: slot.id, option_id: option.id }, highlight: { kind: "option", id: option.id, slot_id: slot.id }, open: true,
      children: expandable ? build : undefined }];
  });

  const slotName = (id: string) => { const slot = (analysis.slots || []).find((entry: Obj) => entry.id === id); return slot ? String(slot.label || slot.id) : ""; };
  const optionName = (slotId: string, id: string) => { const option = (analysis.slots || []).find((entry: Obj) => entry.id === slotId)?.options?.find((entry: Obj) => entry.id === id); return option ? String(option.label || option.id) : ""; };
  const occurrenceNode = (field: Obj, occurrence: Obj, at: number, total: number): TreeNode => {
    const slot = occurrence.slot_id ? slotName(occurrence.slot_id) : "";
    const option = occurrence.slot_id && occurrence.option_id ? optionName(occurrence.slot_id, occurrence.option_id) : "";
    const place = [slot, option].filter(Boolean).join(" / ");
    return { key: outlineKey.occurrence(field.name, at + 1), kind: "occurrence",
      label: joined(outlineLabel("occurrence", { name: field.name, index: at + 1, total, context: occurrence.context }), slot && `${KIND_LABEL.slot} ${slot}`, option && `${KIND_LABEL.option} ${option}`),
      content: [h("span", { key: "name", className: "authoring-tree-name", title: occurrence.context || field.name }, `${at + 1}. ${occurrence.context || field.name}`),
        place ? h("span", { key: "meta", className: "authoring-tree-meta", title: place }, place) : null],
      entry: { ...occurrence, name: field.name, kind: "field" }, highlight: { kind: "field", id: field.name, index: at + 1 } };
  };
  const fieldNodes = fields.flatMap((field: Obj): TreeNode[] => {
    const occurrences: Obj[] = field.occurrences || [];
    const byName = filterMatch(query, field.name);
    const hits = filtering && !byName ? occurrences.map((occurrence, at) => ({ occurrence, at })).filter(({ occurrence }) => filterMatch(query, occurrence.context)) : null;
    if (hits && !hits.length) return [];
    const problems = problemsOf(field.name);
    return [{ key: outlineKey.field(field.name), kind: "field", label: outlineLabel("field", field, problems),
      // 수는 글로 선다(§10): 「사용 위치 n곳」 — 이름(outlineLabel)과 같은 표현이다.
      content: rowContent("field", field.name, { severity: severities.get(field.name), tag: false, meta: joined(`사용 위치 ${field.count ?? 0}곳`, problems && `문제 ${problems}`) }),
      entry: { ...field, kind: "field" }, highlight: { kind: "field", id: field.name }, open: !!hits,
      children: occurrences.length ? () => (hits || occurrences.map((occurrence, at) => ({ occurrence, at }))).map(({ occurrence, at }) => occurrenceNode(field, occurrence, at, occurrences.length)) : undefined }];
  });
  const structureNodes = spineNodes(spine, !filtering);

  const tabButton = (key: "structure" | "fields", id: string, label: ReactNode[]) => h("button", { key, type: "button", role: "tab", id, className: "authoring-outline-tab",
    tabIndex: tab === key ? 0 : -1, "aria-selected": tab === key, "aria-controls": `${id}-panel`, onClick: () => setTab(key), onFocus: () => setTab(key) }, ...label);
  const tree = (key: "structure" | "fields", labelledBy: string, nodes: TreeNode[], path: string[]) => nodes.length > 0 && h(OutlineTree, { key: `${item.id}:${key}:${filtering ? "filter" : "all"}`,
    labelledBy, nodes, current: path, inactive: tab !== key, onSelect, onMenu, onHighlight: highlight });
  return h("aside", { className: "authoring-outline", "aria-label": "템플릿 구조", onContextMenu: onContext },
    h("div", { className: "authoring-outline-head" },
      sectionLabel("템플릿 구조", { id: "authoring-outline-title" }),
      // 두 보기는 한 쌍의 APG tabs 다(자동 활성화 — ←→ 로 옮기면 그 보기가 선다).
      h("div", { className: "authoring-outline-tabs", role: "tablist", "aria-labelledby": "authoring-outline-title",
        onKeyDown: (event: any) => { roveFocus(event, event.currentTarget, '[role="tab"]', "horizontal"); } },
        tabButton("structure", "authoring-outline-structure", ["구조"]),
        tabButton("fields", "authoring-outline-fields", ["필드", " ", h("span", { key: "count", className: "authoring-tab-count" }, String(fields.length))])),
      h("label", { className: "authoring-filter" }, icon("search"),
        h("input", { className: "field", type: "search", "aria-label": "구조 필터", value: query, onChange: (event: any) => setQuery(event.target.value),
          onKeyDown: (event: any) => { if (event.key === "Escape" && query && !event.nativeEvent?.isComposing) { event.preventDefault(); event.stopPropagation(); setQuery(""); } } }))),
    h("div", { className: "authoring-outline-panel", role: "tabpanel", id: "authoring-outline-structure-panel", "aria-labelledby": "authoring-outline-structure", hidden: tab !== "structure" },
      tree("structure", "authoring-outline-structure", structureNodes, current.structure),
      !filtering && !(analysis.slots || []).length && h("p", { className: "authoring-outline-empty" }, EMPTY_STRUCTURE)),
    h("div", { className: "authoring-outline-panel", role: "tabpanel", id: "authoring-outline-fields-panel", "aria-labelledby": "authoring-outline-fields", hidden: tab !== "fields" },
      tree("fields", "authoring-outline-fields", fieldNodes, current.fields),
      !filtering && !fields.length && h("p", { className: "authoring-outline-empty" }, EMPTY_FIELDS)));
}

const MODES: [string, string][] = [["document", "문서"], ["template", "템플릿"], ["structure", "구조"]];

/** 상태 막대의 저장 상태 한 표현(P09·§9.1) — 저장·준비는 서로 다른 상태라 저장됨 뒤에 Python 의 readiness 를 붙인다. */
export function saveLabel(item: Obj, view: Obj, pending: boolean): string {
  return view.saveFailed ? "저장 실패" : pending ? "편집 내용 반영 중" : item.save_as_required ? "새 템플릿 저장 필요" : item.dirty ? "저장하지 않은 변경"
    : item.readiness?.state === "ready" ? "저장됨 · 사용 준비" : item.readiness?.state === "draft" ? "저장됨 · 초안" : "저장됨";
}
/** 상태 막대의 준비 표현 — 구조 오류가 있으면 Python 의 준비 문장(readiness.message), 없으면 개수. */
export function readinessText(item: Obj): string {
  return item.readiness?.message || `구조 오류 ${item.readiness?.errors ?? 0}개 · 경고 ${item.readiness?.warnings ?? 0}개`;
}
/** live region 이 비교할 지금의 상태(UX-04). 문장은 Python 의 것과 화면에 이미 선 표지뿐이다. */
export function liveState(item: Obj | undefined, view: Obj, pending: boolean): LiveState {
  const note = view.commandNote;
  const summaries: Obj[] = view.searchSummaries || [];
  return {
    id: item?.id || "", save: item ? saveLabel(item, view, pending) : "", error: !!view.error,
    readiness: item?.readiness?.state || "", readinessText: item ? readinessText(item) : "",
    trial: item?.trial_state || "", trialLabel: item?.trial_state_label || "", notice: view.notice || "",
    command: note?.seq || 0,
    commandText: !note ? "" : note.kind === "apply" ? String(note.label || "") : note.kind === "undo" ? `문서 실행 취소${note.label ? `: ${note.label}` : ""}` : "문서 다시 실행",
    search: view.searchSummaries,
    searchText: summaries.map((entry) => summaries.length > 1 ? `${entry.document} · ${entry.summary}` : entry.summary).join(" · "),
  };
}

/** 키보드 문맥 메뉴의 자리 — 편집면이면 캐럿, 아니면 그 원소의 왼쪽 아래(§6.1·UX-04). 편집면 iframe 자체(팔레트의
 *  「문맥 메뉴」가 그 자리에서 누른 키)는 캐럿을 모르므로 편집면의 왼쪽 위다 — 아래 끝에 세우면 편집면 밖으로 뒤집힌다. */
function menuAnchor(target: HTMLElement): { left: number; top: number; bottom: number } {
  if (target.tagName === "IFRAME") { const rect = target.getBoundingClientRect(); return { left: rect.left, top: rect.top, bottom: rect.top }; }
  const selection = target.ownerDocument?.getSelection?.();
  if (target.isContentEditable && selection?.rangeCount) {
    const range = selection.getRangeAt(0);
    const rect = range.getClientRects?.()[0] || range.getBoundingClientRect();
    if (rect && (rect.width || rect.height)) return rect;
  }
  return target.getBoundingClientRect();
}

export function AuthoringScreen({ controller, layout }: Props & { layout?: AuthoringLayout | null }): ReactNode {
  const snapshot = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot) || {};
  const view = useSyncExternalStore(controller.viewModel.subscribe, controller.viewModel.getSnapshot, controller.viewModel.getSnapshot);
  const tabs: Obj[] = snapshot.tabs || [];
  const item = tabs.find((tab) => tab.id === snapshot.active_id);
  const root = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // 패널·독을 연 자리(초점 복귀 대상, UX-04). 요청자가 먼저 알면 pendingOpener 로 넘기고, 아니면 초점을 옮기기 직전의 원소다.
  const openers = useRef<Record<string, unknown>>({});
  const pendingOpener = useRef<unknown>(null);
  // 명령 팔레트를 연 자리(IDE-02) — 닫으면 그리로 초점을 돌린다.
  const paletteOpener = useRef<unknown>(null);
  const pendingTabFocus = useRef("");
  const liveRef = useRef<ReturnType<typeof liveStep>["state"] | null>(null);
  const [toolbarKey, setToolbarKey] = useState("");
  // 좁은 폭(컨테이너 64rem 이하)에서만 쓰이는 구조 레일의 펼침 — 넓은 폭에서는 CSS 가 무시한다.
  const [outlineOpen, setOutlineOpen] = useState(false);
  const shellInput: ShellInput = useRef<ShellInput["current"]>({});
  const dock = dockTabs(item, view);
  const counts = useMemo(() => problemCounts(item?.problems), [item?.problems]);
  const act = (work: () => unknown, kind?: string) => () => { void controller.guarded(work, kind); };
  const toolbarEntry = () => root.current?.querySelector<HTMLElement>('.authoring-toolbar [data-rove][tabindex="0"]');
  /** 닫힌 패널에서 초점을 돌린다: 속성은 §10 대로 선택 자리 먼저, 독·메뉴·오류는 연 자리 먼저. 마지막은 도구 막대. */
  const returnFocus = (slot: "properties" | "dock" | "error") => act(async () => {
    const opener = openers.current[slot];
    openers.current[slot] = null;
    if (slot === "properties" && await controller.focusSelection()) return;
    if (focusFirst([opener])) return;
    if (slot !== "properties" && await controller.focusSelection()) return;
    focusFirst([toolbarEntry(), root.current?.querySelector(".authoring-head button")]);
  }, "focus")();
  // 초점 요청(focusRequest)만 초점을 옮긴다 — 패널 값·명령 종류·판정 도착은 옮기지 않는다(WCAG 3.2.2).
  // 문맥 메뉴가 열려 있으면 메뉴가 초점을 쥔다.
  useEffect(() => {
    const shell = root.current;
    if (!view.focusPanel || !shell || view.contextMenu) return;
    const slot = view.focusTarget === "dock" ? "dock" : "properties";
    const panel = shell.querySelector<HTMLElement>(slot === "dock" ? "#authoring-dock-panel" : ".authoring-properties");
    const active = shell.ownerDocument?.activeElement;
    const opener = pendingOpener.current ?? (active && active !== shell.ownerDocument?.body && !panel?.contains(active) ? active : null);
    pendingOpener.current = null;
    if (opener) openers.current[slot] = opener;
    const target = slot === "dock" ? panel?.querySelector<HTMLElement>(FOCUSABLE) || panel : shell.querySelector<HTMLElement>(".authoring-properties input");
    target?.focus();
  }, [view.focusPanel]);
  useEffect(() => {
    const focus = () => { void controller.guarded(controller.checkExternal, "external"); };
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [controller]);
  // 문맥 메뉴(§6.1): 열리면 첫 사용 가능 항목(없으면 첫 항목)에 초점, 바깥 클릭이면 닫는다. Escape 는 셸 단축키가 처리한다.
  // 「더보기」·「파일」 메뉴는 여는 버튼 자체의 누름을 바깥으로 치지 않는다 — 그 버튼이 여닫기를 맡는다.
  useEffect(() => {
    if (!view.contextMenu) return;
    const items = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') || [])];
    (items.find((entry) => entry.getAttribute("aria-disabled") !== "true") || items[0])?.focus();
    const trigger = view.contextMenu.kind ? view.contextMenu.trigger as Element | null : null;
    const outside = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (!target?.closest?.(".authoring-context-menu") && !(target && trigger?.contains?.(target))) controller.update({ contextMenu: null });
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [view.contextMenu]);
  // 메뉴는 그린 뒤 실제 크기로 창 안에 든다 — 아래가 모자라면 위로 뒤집고, 그래도 넘치면 가장자리에 붙인다(UX-04).
  useLayoutEffect(() => {
    const menu = menuRef.current;
    const shell = root.current;
    const anchor = view.contextMenu?.anchor;
    const win = shell?.ownerDocument?.defaultView;
    if (!menu || !shell || !anchor || !win?.innerWidth || typeof menu.getBoundingClientRect !== "function") return;
    const size = menu.getBoundingClientRect();
    const place = clampMenu(anchor, { width: size.width, height: size.height }, { width: win.innerWidth, height: win.innerHeight });
    const base = shell.getBoundingClientRect();
    menu.style.left = `${place.left - base.left - (shell.clientLeft || 0) + (shell.scrollLeft || 0)}px`;
    menu.style.top = `${place.top - base.top - (shell.clientTop || 0) + (shell.scrollTop || 0)}px`;
  }, [view.contextMenu]);
  // 문서 탭을 닫은 뒤에는 이웃 탭에 초점(APG tabs). 탭이 하나도 남지 않으면 빈 작업대의 첫 행동으로.
  useEffect(() => {
    const wanted = pendingTabFocus.current;
    const shell = root.current;
    if (!wanted || !shell) return;
    const all = [...shell.querySelectorAll<HTMLElement>('[role="tab"][data-tab]')];
    const next = all.find((tab) => tab.getAttribute("data-tab") === wanted) || all.find((tab) => tab.getAttribute("aria-selected") === "true");
    pendingTabFocus.current = "";
    if (next) next.focus();
    else focusFirst([shell.querySelector(".authoring-empty-actions button"), shell.querySelector(".authoring-head button")]);
  });
  // 단일 live region(UX-04): 전이 때만 한 번 쓴다 — 키 입력마다 바뀌는 상태 막대는 읽지 않는다.
  const liveNow = liveState(item, view, item ? controller.pending(item.id) : false);
  useEffect(() => {
    const { state, message } = liveStep(liveRef.current, liveNow);
    liveRef.current = state;
    if (message) controller.announce(message);
  });
  // 경보(복구 초안·외부 파일 변경)와 초안 비교는 새로 서는 순간 독의 제 탭을 펼친다 — 닫아 둔 독도 다시 연다. 초점은 옮기지 않는다(경보가 읽힌다).
  const forced = view.recoveryPreview ? "recovery_preview" : item?.recovery ? "recovery" : dock.tabs.some(([key]) => key === "external_changed") ? "external_changed" : "";
  useEffect(() => {
    if (!forced) return;
    const current = controller.viewModel.getSnapshot();
    controller.update({ dock: forced, dockClosed: false, ...(DOCK_PANELS.includes(current.panel) && current.panel !== "comparison" ? { panel: "" } : {}) });
  }, [forced, item?.id, view.recoveryPreview]);
  const select = (entry: Obj) => act(() => controller.select({ source_revision: item?.revision, ...entry }));
  const contextMenu = (event: any) => openContextMenu(controller, event, root.current);
  // 구조 목록에서 고르면 속성 패널이 그 대상으로 열리고 이름 칸으로 간다(§10). 메뉴가 열려 있으면 메뉴가 초점을 쥔다.
  const chooseFromOutline = (entry: Obj, element: HTMLElement) => act(async () => {
    await controller.select({ source_revision: item?.revision, ...entry });
    const current = controller.viewModel.getSnapshot();
    if (current.contextMenu) return;
    pendingOpener.current = element;
    controller.update(focusRequest(current, "properties"));
  })();
  // 구조 목록 줄의 문맥 메뉴(오른쪽 클릭·Shift+F10): 그 줄을 고른 **뒤에** 연다 — 선택이 편집면으로 초점을 옮기므로
  // 먼저 열면 메뉴가 초점을 잃는다. trigger 는 그 줄이다.
  const outlineMenu = (entry: Obj, element: HTMLElement, anchor: { x: number; y: number; top?: number }) => act(async () => {
    await controller.select({ source_revision: item?.revision, ...entry });
    openContextMenu(controller, { clientX: anchor.x, clientY: anchor.y, anchorTop: anchor.top, target: element }, root.current);
  })();
  const editorState = item ? controller.editorState(item.id) : null;
  const readOnly = !!item && item.media === "hwpx" && item.rhwp_editable !== true;
  // F2(§10): 패널이 이미 열려 있어도 이름 칸으로 초점을 옮긴다 — focusPanel 은 그 요청의 차례 번호다.
  // 되는 이름 변경이 없으면 패널 대신 위치 줄에 사유가 선다(IDE-01) — 편집면이 넘긴 F2 와 같은 함수다.
  const rename = () => renameShortcut(controller);
  // 명령 하나를 고르면 속성 패널이 그 명령으로 열리고 이름 칸으로 간다. 메뉴에서 골랐으면 메뉴를 연 자리가 복귀 대상이다.
  const pick = (commandType: string) => {
    const current = controller.viewModel.getSnapshot();
    if (current.contextMenu) pendingOpener.current = current.contextMenu.trigger;
    controller.update({ panel: "properties", commandType, contextMenu: null, preview: null, refusal: null, ...focusRequest(current, "properties") });
  };
  const openPanel = (panel: string) => controller.update({ panel, contextMenu: null, ...focusRequest(controller.viewModel.getSnapshot(), "dock") });
  // 명령 팔레트(IDE-02 · P-10): 독 탭이 아니라 머리 띠 아래의 비모달 오버레이다 — 열어도 독(시험·문제)과 view.panel 은
  // 그대로다. 연 자리를 기억해 닫으면 그리로 돌린다. 팔레트 안에서 다시 열면(Ctrl+Shift+P) 연 자리는 바뀌지 않는다.
  const openPalette = (opener?: unknown) => {
    const doc = root.current?.ownerDocument;
    const active = doc?.activeElement as Element | null | undefined;
    if (opener !== undefined) paletteOpener.current = opener;
    else if (!active?.closest?.(".authoring-command-palette")) paletteOpener.current = active && active !== doc?.body ? active : null;
    controller.update({ palette: (controller.viewModel.getSnapshot().palette || 0) + 1, contextMenu: null });
  };
  const closePalette = (restore: boolean) => {
    const opener = paletteOpener.current;
    paletteOpener.current = null;
    controller.update({ palette: 0 });
    if (restore && !focusFirst([opener])) focusFirst([toolbarEntry()]);
  };
  const commandTable = commandEntries(view.commands, readOnly);
  shellInput.current.palette = () => openPalette();
  // 도구 막대에서 빠진 동작 — 「더보기」 메뉴와 명령 팔레트가 같은 실행 경로를 쓴다. 첫 항목 「명령」은 팔레트 자신을 여는
  // 길이라 팔레트 안에는 서지 않는다(PALETTE_SELF).
  const moreActions: MenuAction[] = [
    [PALETTE_SELF, () => openPalette(), false],
    ["의미 복사", act(async () => { await controller.copy(); controller.update(focusRequest(controller.viewModel.getSnapshot(), "dock")); }), false],
    ["붙여넣기", () => openPanel("paste"), !controller.clipboard()],
    ["이전 위치로", act(controller.back), false]];
  // 머리 띠 「파일」 메뉴 — 파일 동사 넷. 저장·다른 이름으로 저장은 열린 문서가 있어야 한다(불가 항목도 초점을 받는다).
  const fileActions: MenuAction[] = [
    ["문서 열기", act(controller.openFile), false],
    ["새 TXT", act(controller.create), false],
    ["저장", act(() => controller.save(), "save"), !item, "Ctrl+S"],
    ["다른 이름으로 저장", act(() => controller.save(item?.id, true), "save"), !item]];
  /** 「더보기」·「파일」을 여닫는 단추의 누름 — 열린 제 메뉴면 닫고, 아니면 단추 아래에 연다. */
  const menuToggle = (kind: "more" | "file") => (event: any) => {
    if (view.contextMenu?.kind === kind) { controller.update({ contextMenu: null }); return; }
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    openContextMenu(controller, { clientX: rect.left, clientY: rect.bottom, target: event.currentTarget }, root.current, kind);
  };
  const menuButton = (kind: "more" | "file") => ({ "aria-haspopup": "menu", "aria-expanded": view.contextMenu?.kind === kind, "aria-controls": view.contextMenu?.kind === kind ? "authoring-menu" : undefined });
  // 독 탭 하나를 펼친다: 패널 탭은 view.panel 로, 나머지(시험·경보·비교)는 view.dock 으로. 옆 속성 패널은 건드리지 않는다.
  // 사용자가 연 탭은 그 패널의 첫 제어로 초점을 옮긴다(이미 펼친 탭이면 초점만). 내용이 Python 에서 오는 탭은 도착한 뒤 옮긴다.
  const openDock = (key: string) => {
    const request = () => controller.update(focusRequest(controller.viewModel.getSnapshot(), "dock"));
    if (key === dock.active) return request();
    if (key === "raw") return act(async () => { await controller.raw(); request(); })();
    if (key === "impact") return act(async () => { await controller.impact(); request(); })();
    if (DOCK_PANELS.includes(key)) return openPanel(key);
    controller.update({ dock: key, dockClosed: false, contextMenu: null, ...(key === "trial" ? { trial: true } : {}), ...(DOCK_PANELS.includes(view.panel) ? { panel: "" } : {}), ...focusRequest(view, "dock") });
  };
  const closeDock = () => {
    controller.update({ ...(DOCK_PANELS.includes(view.panel) ? { panel: "" } : {}), trial: false, dock: "", dockClosed: true, dockMax: false });
    returnFocus("dock");
  };
  const closePanel = (patch: Obj) => { controller.update(patch); returnFocus("dock"); };
  const closeTab = (id: string) => act(async () => {
    const ids = tabs.map((tab) => tab.id);
    const at = ids.indexOf(id);
    const neighbour = ids[at + 1] ?? ids[at - 1] ?? "";
    if (!(await controller.close(id))) return;
    pendingTabFocus.current = neighbour || "-";
    controller.update({});
  })();
  // 팔레트의 셸 동작(1부) — 키 학습 표면이다(L-50): 셸 키가 있는 동작은 그 키를 곁에 싣는다. 실행 경로는 「파일」·「더보기」·
  // 셸 키와 같다. 영역 이동·문맥 메뉴는 팔레트가 연 자리로 초점을 돌린 뒤 그 자리에서 누른 키와 같다.
  const pressHere = (key: string, shiftKey: boolean) => {
    const target = root.current?.ownerDocument?.activeElement as HTMLElement | null | undefined;
    const KeyboardEvent = (target?.ownerDocument?.defaultView as Obj | null | undefined)?.KeyboardEvent;
    // 진짜 키 사건을 그 자리에 쏘면 구조 목록처럼 제 키를 먼저 받는 곳(줄을 고른 뒤 메뉴)도 사람이 누른 것과 같게 간다.
    if (target && KeyboardEvent && typeof target.dispatchEvent === "function") target.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true }));
    else shellInput.current.key?.({ key, shiftKey, target, nativeEvent: {}, preventDefault() {} });
  };
  const paletteActions: PaletteAction[] = ([
    ...fileActions.filter(([label]) => label === "저장" || label === "다른 이름으로 저장"),
    ["찾기", () => openPanel("search"), false, "Ctrl+F"],
    ["결과 시험", () => openDock("trial"), false],
    ...moreActions.filter(([label]) => label !== PALETTE_SELF),
    ["다음 영역으로", () => pressHere("F6", false), false, "F6"],
    ["이전 영역으로", () => pressHere("F6", true), false, "Shift+F6"],
    ["문맥 메뉴", () => pressHere("F10", true), false, "Shift+F10"],
  ] as MenuAction[]).map(([label, run, disabled, keys]) => ({ label, run, disabled, keys }));
  const trialShown = dock.active === "trial";
  /** 외부 변경·저장 실패의 결정 동사(AC24·§9.2) — 경보 구획과 비교 구획이 같은 배열·같은 실행 경로를 쓴다(IDE-01).
   *  저장 실패면 「다시 저장」이 더해지고 그것이 그 구획의 주 행동이다. */
  const externalVerbs = (saveFailed: boolean): ReactNode[] => !item ? [] : [
    button("현재 작업을 다른 이름으로 저장", act(() => controller.save(item.id, true), "save"), { key: "save-as" }),
    button("외부 파일 다시 열기", act(controller.reload), { key: "reload" }),
    ...(saveFailed ? [primary("다시 저장", act(() => controller.save(item.id), "save"), { key: "save" })] : [])];
  const dockContent = (key: string): ReactNode => {
    if (key === "trial" && item) return h(Trial, { controller, item, view });
    if (key === "recovery" && item) return h("section", { className: "authoring-bottom", role: "alert", "aria-label": "중단 전 복구 초안" }, h("h2", null, "중단 전 복구 초안"),
      h("p", null, "복구 여부를 선택한 뒤 편집을 계속하세요. 원본 파일은 아직 변경하지 않았습니다."),
      h("div", { className: "authoring-actions" },
        button("초안과 원본 비교", act(() => controller.compareRecovery(item.recovery_key))),
        danger("폐기", act(() => controller.discardRecovery(item.id))), primary("복구", act(() => controller.recover(item.id)))));
    if (key === "recovery_preview" && view.recoveryPreview) return h("section", { className: "authoring-bottom", "aria-label": "초안과 원본 비교" }, h("h2", null, "초안과 원본 비교"),
      h("div", { className: "authoring-compare" }, ...[["원본", view.recoveryPreview.original_content], ["복구 초안", view.recoveryPreview.content]].map(([name, content]) => h("div", { key: name }, h("h3", null, name),
        content == null ? h("p", null, "원본 파일 없음") : view.recoveryPreview.media === "txt" ? h("pre", null, content)
          : h(ExternalDocument, { controller, item: { name }, content, sectionEntries: name === "원본" ? view.recoveryPreview.original_section_entries : view.recoveryPreview.section_entries })))),
      h("div", { className: "authoring-actions" },
        quiet("비교 닫기", () => closePanel({ recoveryPreview: null })), primary("복구", act(() => controller.recover(item?.recovery ? item.id : view.recoveryPreview.key)))));
    if (!item) return null;
    if (key === "paste") return h("section", { className: "authoring-bottom", "aria-label": "의미 붙여넣기" }, h("h2", null, "의미 붙여넣기"),
      h("p", null, "문서에서 붙여넣을 위치를 선택하세요. 같은 이름의 필드 연결과 새 식별자를 확인한 뒤 적용합니다."),
      h("form", { onSubmit: (event: any) => { event.preventDefault(); const data = new FormData(event.currentTarget); act(() => controller.paste(data.has("meaning"), String(data.get("new_id") || ""), data.has("link_existing")))(); } },
        h("label", null, h("input", { type: "checkbox", name: "meaning", defaultChecked: true }), "의미 포함"),
        h("label", null, h("input", { type: "checkbox", name: "link_existing" }), "같은 이름의 기존 필드에 연결"),
        h("label", null, "새 연결 식별자 ", h("input", { name: "new_id", className: "field" })),
        h("button", { className: "btn", disabled: !controller.clipboard() }, "붙여넣기 미리보기")),
      view.command?.type === "paste" && view.preview && h("div", { className: "authoring-preview" },
        h("pre", { role: "group", "aria-label": "변경 전" }, view.preview.before), h("pre", { role: "group", "aria-label": "변경 후" }, view.preview.after),
        h("div", { className: "authoring-actions" }, quiet("취소", () => controller.update({ preview: null })), primary("붙여넣기 적용", act(controller.applyPreview)))));
    if (key === "search") return h("section", { className: "authoring-bottom", "aria-label": "검색" }, h("h2", null, "검색"),
      h("form", { onSubmit: (event: any) => { event.preventDefault(); const values = new FormData(event.currentTarget); act(() => controller.search(String(values.get("query")), String(values.get("kind")), values.has("all")))(); } },
        h("input", { className: "field", name: "query", "aria-label": "검색어", defaultValue: view.query }),
        h("select", { className: "field", name: "kind", "aria-label": "검색 대상" }, h("option", { value: "body" }, "본문"), h("option", { value: "field" }, "필드"), h("option", { value: "structure" }, "항목·선택"), h("option", { value: "all" }, "전체")),
        h("label", null, h("input", { type: "checkbox", name: "all" }), "열린 모든 문서"), h("button", { className: "btn" }, "찾기")),
      // 요약과 종류는 Python 이 센 것·준 것 그대로다(§6.3). 여러 문서를 찾으면 문서마다 한 줄씩 선다. 읽기는 셸의 live region 이 한다.
      ...(view.searchSummaries || []).map((entry: Obj, index: number) => h("p", { key: `summary-${index}`, className: "authoring-search-summary" },
        view.searchSummaries.length > 1 ? `${entry.document} · ${entry.summary}` : entry.summary)),
      // 적중은 원문으로 옮겨 가는 행이다(UX-09): 종류 칩 · 문맥 · 흐린 문서 이름 · 이동 화살표.
      rowList("검색 결과", view.hits.map((hit: Obj) => rowButton({ chip: KIND_LABEL[hit.kind] ? kindTag(hit.kind) : null, text: hit.context || hit.name || hit.label, context: hit.document }, select(hit)))));
    // 원문 표기(F26·UI09): Python 이 지은 문법 표현을 본문 항목별로 읽기 전용으로 보인다.
    if (key === "raw") return h("section", { className: "authoring-bottom", "aria-label": "원문 표기" }, h("h2", null, "원문 표기"),
      view.syntax?.note && h("p", null, view.syntax.note),
      ...(view.syntax?.sections || []).map((section: Obj, index: number) => h("div", { key: index, className: "authoring-syntax" },
        h("h3", null, section.entry), h("pre", { tabIndex: 0, role: "group", "aria-label": `${section.entry} 원문 표기` }, section.text))),
      quiet("복사", act(() => copyText((view.syntax?.sections || []).map((section: Obj) => section.text).join("\n\n"))), { disabled: !view.syntax?.sections?.length }));
    if (key === "impact") return h("section", { className: "authoring-bottom", "aria-label": "변경 영향·작업 적용" }, h("h2", null, "변경 영향·작업 적용"),
      view.impact?.save_required && h("p", null, "템플릿을 저장한 뒤 적용할 작업을 확인하세요."),
      view.impact?.structure_delta && h(StructureDelta, { delta: view.impact.structure_delta }),
      !!view.impact?.identifier_changes?.length && h("ul", { "aria-label": "식별자 변경" }, ...view.impact.identifier_changes.map((entry: Obj | string, index: number) =>
        h("li", { key: index }, typeof entry === "string" ? entry : `${KIND_LABEL[entry.kind] || entry.kind || ""} · ${entry.from ?? entry.id ?? ""}${entry.to != null ? ` → ${entry.to}` : ""}`))),
      (!!view.impact?.structure_delta?.renamed?.length || !!view.impact?.identifier_changes?.length) && h("p", null, IDENTIFIER_IMPACT),
      view.impact?.content_changed_since_save && h("p", null, "저장 이후 본문 변경 있음"),
      (!view.impact?.available || !!view.impact.unverified_jobs?.length) && h("p", null, "연결된 작업의 영향은 확인하지 않았습니다."),
      !!view.impact?.unverified_jobs?.length && h("p", null, `확인하지 않은 작업 ${view.impact.unverified_jobs.length}개`),
      view.impact?.available && !view.impact.jobs?.length && h("p", null, "연결된 작업 없음"),
      ...(view.impact?.jobs || []).map((job: Obj) => { const blocked = view.impact.save_required || view.impact.usable === false; return h("div", { key: job.name }, h("strong", null, job.name),
        job.change_status && h("p", null, TPL_STATUS_COPY[job.change_status] || job.change_status),
        h("p", null, `추가 필드: ${(job.added_fields || []).join(", ") || "없음"} · 없어진 필드: ${(job.removed_fields || job.unmapped_fields || []).join(", ") || "없음"}`),
        button("적용 영향 확인", act(() => controller.applyJob(job.name)), { disabled: blocked, "aria-disabled": blocked || undefined, title: (blocked && job.blocked_reason) || undefined }),
        blocked && job.blocked_reason && h("p", { className: "authoring-reason" }, job.blocked_reason)); }),
      view.jobApply && h("div", null, h("p", null, TPL_STATUS_COPY[view.jobApply.preparation?.status] || view.jobApply.message),
        ...(view.jobApply.preparation?.diagnostics || []).map((entry: Obj, index: number) => h("p", { key: index }, entry.message)),
        h("div", { className: "authoring-actions" }, quiet("취소", () => controller.update({ jobApply: null })), primary("기존 작업에 적용", act(controller.confirmJob), { disabled: !view.jobApply.change_token }))));
    // 문제 한 건(§7.2·F24): 심각도·종류는 색이 아닌 글자로(P14), 대상·설명·다음 행동을 Python 의 problems 그대로 보인다.
    // 문제 한 건은 행이다(UX-09): 심각도 글자 칩 · 종류 · 설명 · 흐린 대상. 이동하는 다음 행동(「원문으로 이동」)은 그 행 자체이고
    // 그 동사가 행 이름의 첫머리·툴팁으로 남는다. 명령형 다음 행동(구조 표기 수정 등)은 행 곁의 보조 단추다.
    if (key === "problems") return h("section", { className: "authoring-bottom", "aria-label": "문제" }, h("h2", null, "문제"),
      !item.problems?.length && h("p", { className: "authoring-reason" }, "문제 없음"),
      rowList("문제", (item.problems || []).map((problem: Obj, index: number) => {
        const actions: Obj[] = problem.actions || [];
        const navigate = actions.find((action) => action.kind !== "command");
        const chip = h("span", { className: "authoring-badge", "data-severity": problem.severity }, SEVERITY_LABEL[problem.severity] || problem.severity);
        const body = [h("span", { key: "category", className: "authoring-problem-category" }, CATEGORY_LABEL[problem.category] || problem.category), " ", problem.message];
        return h("div", { key: index, className: "authoring-problem" },
          // 이름은 다음 행동(동사)이 먼저, 이어서 심각도·종류·대상·설명 — 보이는 행과 같은 글이다.
          navigate ? rowButton({ chip, text: body, context: problem.target || null }, act(() => problemAction(controller, item, problem, navigate)), { title: navigate.label,
            "aria-label": joined(navigate.label, SEVERITY_LABEL[problem.severity] || problem.severity, CATEGORY_LABEL[problem.category] || problem.category, problem.target, problem.message) })
            : h("div", { className: "authoring-row static" }, chip, h("span", { className: "authoring-row-text" }, ...body), problem.target ? h("span", { className: "authoring-row-context" }, problem.target) : null),
          ...actions.filter((action) => action !== navigate).map((action: Obj, actionIndex: number) => button(action.label, act(() => problemAction(controller, item, problem, action)), { key: actionIndex })));
      })),
      view.command?.type === "repair_marker" && view.preview && h("div", { className: "authoring-preview" },
        h("h3", null, "수정 제안"), h("pre", { role: "group", "aria-label": "변경 전" }, view.preview.before), h("pre", { role: "group", "aria-label": "변경 후" }, view.preview.after),
        h("div", { className: "authoring-actions" }, quiet("취소", () => controller.update({ preview: null })), primary("구조 표기 수정", act(controller.applyPreview)))));
    if (key === "external_changed") return h("section", { className: "authoring-bottom", role: "alert", "aria-label": "외부 파일 변경" }, h("h2", null, "외부 파일 변경"),
      h("div", { className: "authoring-actions start" },
        button("양쪽 내용 확인", act(controller.compareExternal)), ...externalVerbs(false)));
    // 저장 실패(AC24·§9.2): 변경은 그대로 남고, 같은 세 복구 동사에 「다시 저장」이 더해진다 — 이 구획의 주 행동이다.
    if (key === "external") return h("section", { className: "authoring-bottom", role: "alert", "aria-label": "저장 실패" }, h("h2", null, "저장 실패"),
      h("div", { className: "authoring-actions start" },
        button("양쪽 내용 확인", act(controller.compareExternal)), ...externalVerbs(true)));
    // 비교 안에서 결정한다(IDE-01): 경보 구획과 같은 동사·같은 실행 경로가 비교 아래에도 선다. 「비교 닫기」는 물러선 행동이다.
    if (key === "comparison" && view.comparison) return h("section", { className: "authoring-bottom", "aria-label": "외부 파일 내용" }, h("h2", null, "외부 파일 내용"),
      h("div", { className: "authoring-compare" }, ...[["현재 작업", view.comparison.current_content, view.comparison.current_section_entries], ["외부 파일 내용", view.comparison.content, view.comparison.section_entries]].map(([label, content, sectionEntries]) =>
        h("div", { key: label }, h("h3", null, label), item.media === "txt" ? h("pre", null, content) : h(ExternalDocument, { controller, item, content, sectionEntries, title: label })))),
      h("div", { className: "authoring-actions" }, quiet("비교 닫기", () => closePanel({ panel: "" })),
        ...(view.saveFailed ? externalVerbs(true) : item.external_changed ? externalVerbs(false) : [])));
    return null;
  };
  // 도구 막대(§3.1·APG toolbar): 한 번의 Tab 으로 들어오고 ←→·Home·End 로 옮긴다(roving tabindex). 비활성 버튼은 건너뛴다.
  const undoDisabled = editorState ? !editorState.canUndo : false;
  const redoDisabled = editorState ? !editorState.canRedo : false;
  const creates = COMMANDS.slice(0, 3).map(([commandType, label]) => { const available = commandAvailability(view.commands, commandType); return { commandType, label, available, disabled: readOnly || !available.enabled }; });
  const toolbarKeys = [...(undoDisabled ? [] : ["undo"]), ...(redoDisabled ? [] : ["redo"]), ...MODES.map(([value]) => `mode-${value}`),
    ...creates.filter((entry) => !entry.disabled).map((entry) => entry.commandType), "more", "trial"];
  const toolbarActive = toolbarKeys.includes(toolbarKey) ? toolbarKey : toolbarKeys[0];
  const rove = (key: string) => ({ "data-rove": key, tabIndex: key === toolbarActive ? 0 : -1 });
  const dockEntry = dock.active || dock.tabs[0]?.[0];
  const errorView = view.error ? errorParts(view.error) : null;
  return h("div", { className: `authoring-shell${dock.active && view.dockMax ? " dock-max" : ""}`, ref: root, onKeyDown: shellInput.current.key = (event: any) => {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    const shortcut = shellShortcut(event);
    if (!shortcut) return;
    if (shortcut === "context-menu") {
      const target = event.target as HTMLElement;
      if (!item || !target.closest?.(".authoring-outline,.authoring-canvas")) return;
      const rect = menuAnchor(target);
      event.preventDefault();
      openContextMenu(controller, { clientX: rect.left, clientY: rect.bottom, anchorTop: rect.top, target }, root.current);
      return;
    }
    if (shortcut !== "escape") event.preventDefault();
    if (shortcut === "save") act(() => controller.save(), "save")();
    else if (shortcut === "search") openPanel("search");
    else if (shortcut === "editor-search") act(() => controller.command("search"))();
    else if (shortcut === "commands") openPalette();
    else if (shortcut === "rename") rename();
    else if (shortcut === "undo" || shortcut === "redo") act(() => controller.command(shortcut))();
    else if (shortcut === "escape") {
      const closing = view.panel;
      if (escapeShell(controller) === "panel") returnFocus(closing && closing !== "properties" ? "dock" : "properties");
      else if (!focusable(view.contextMenu?.trigger)) focusFirst([toolbarEntry()]);
    }
    else if (shortcut === "cycle") {
      // 패널 간 초점 이동(§10): 그려진 패널만 돌고, 접힌 구조는 레일 버튼이 대신 선다(authoring_layout.ts).
      // roving 묶음(탭·도구 막대·구조 목록)은 제 대기 항목(tabindex=0)으로 들어간다(UX-04).
      cyclePanels([...(root.current?.querySelectorAll<HTMLElement>(PANEL_CYCLE) || [])], document.activeElement, !!event.shiftKey);
    }
  } },
    // 단일 live region(UX-04) — 보이지 않고, 전이 때만 한 줄이 선다. 차례 번호가 바뀌면 같은 문장도 다시 읽힌다.
    h("p", { className: "authoring-live", role: "status" }, view.live?.text ? h("span", { key: view.live.seq }, view.live.text) : null),
    // 머리 띠(편집기 제목 줄): 돌아가기 그림 · 제목 · 「파일」 메뉴 · 열린 문서 탭(가운데, 넘치면 가로 스크롤) · 저장.
    // 파일 동사(열기·새 TXT·다른 이름으로 저장)는 「파일」 메뉴 안에 선다 — 띠에 보이는 행동은 저장 하나다.
    h("header", { className: "authoring-head" },
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
      button("저장", act(() => controller.save(), "save"), { disabled: !item,
        className: item && (item.dirty || item.save_as_required || controller.pending(item.id)) ? "btn primary" : "btn quiet" })),
    // 오류 띠(§10·UX-04): 첫 문장만 보이고 기술 세부는 「자세히」 안에 둔다. 사용자가 닫거나 같은 종류의 작업이 성공해야 걷힌다.
    errorView && h("div", { className: "authoring-error" },
      h("p", { key: view.errorSeq, role: "alert" }, errorView.summary),
      errorView.detail && h("details", null, h("summary", null, "자세히"), h("pre", null, errorView.detail)),
      button("닫기", () => { controller.dismissError(); returnFocus("error"); })),
    // 저장 결과의 알림(AC14·P09) — Python 이 준 문장만 보이고, 다음 편집에서 사라진다. 읽기는 live region 이 한다.
    view.notice && h("p", { className: "authoring-notice" }, view.notice),
    // 호환성 경고(U01·§7.1·P16): Python 판정이 서는 즉시 편집기 마운트와 무관하게 보이고, 마운트가 무너져도 남는다.
    // 원본은 그대로 둔 채 확인(원문 표기)하거나 다른 이름으로 사본을 남기는 길을 함께 세운다.
    item?.compatibility?.state === "limited" && h("section", { className: "authoring-compat", role: "alert", "aria-label": "호환성 경고" },
      h("strong", null, "읽기 전용 · 보존 확인 필요"),
      item.compatibility.message && h("p", null, item.compatibility.message),
      ...(item.compatibility.diagnostics || []).map((diagnostic: Obj | string, index: number) => typeof diagnostic === "string" ? h("p", { key: index }, diagnostic)
        : h("div", { key: index }, h("p", null, diagnostic.message), diagnostic.detail && h("p", { className: "authoring-reason" }, diagnostic.detail))),
      h("div", null, button("다른 이름으로 저장", act(() => controller.save(item.id, true), "save")), button("원문 표기", act(controller.raw)))),
    // 빈 작업대: 지금 할 수 있는 두 행동(머리의 것과 같은 실행 경로)과 복구 가능한 작업만 둔다.
    // 「변경할 문구를 선택해…」는 처음 여는 일반 문서의 안내라 Python 의 notice 로 선다(§13).
    !item && h("div", { className: "authoring-empty" }, h("p", null, "HWPX·TXT 문서를 열거나 새 TXT를 만드세요."),
      h("div", { className: "authoring-empty-actions" }, button("문서 열기", act(controller.openFile), { className: "btn primary" }), button("새 TXT", act(controller.create), { className: "btn" })),
      !!snapshot.recoverable?.length && h("ul", { className: "authoring-drafts", "aria-label": "복구 가능한 작업" }, ...snapshot.recoverable.map((draft: Obj) => h("li", { key: draft.key },
        h("strong", null, draft.name || draft.path || "저장하지 않은 초안"),
        draft.updated_at && h("time", { dateTime: draft.updated_at }, new Date(draft.updated_at).toLocaleString()),
        draft.error && h("p", { role: "alert" }, draft.error),
        h("span", { className: "authoring-drafts-actions" },
          button("초안과 원본 비교", act(() => controller.compareRecovery(draft.key)), { disabled: !!draft.error }),
          button("복구", act(() => controller.recover(draft.key)), { disabled: !!draft.error }), danger("폐기", act(() => controller.discardRecovery(draft.key)))))))),
    // 도구 막대(§3.1): 한 줄, 줄바꿈 없음 — 넘치면 가로 스크롤. 보조 패널을 여는 동사는 하단 독의 탭으로 옮겼다.
    item && h("div", { className: "authoring-toolbar", role: "toolbar", "aria-label": "문서 명령",
      onKeyDown: (event: any) => { roveFocus(event, event.currentTarget, "[data-rove]:not([disabled])", "horizontal"); },
      onFocus: (event: any) => { const key = event.target?.getAttribute?.("data-rove"); if (key && key !== toolbarKey) setToolbarKey(key); } },
      // 실행 취소·다시 실행은 그림 단추다 — 되돌릴 명령의 이름은 툴팁·이름과 live region 이 싣는다(새 문구 없음).
      h("div", { className: "authoring-toolbar-group" },
        iconButton("undo", `문서 실행 취소${view.lastCommandLabel ? `: ${view.lastCommandLabel}` : ""}`, act(() => controller.command("undo")), { disabled: undoDisabled, ...rove("undo") }),
        iconButton("redo", "문서 다시 실행", act(() => controller.command("redo")), { disabled: redoDisabled, ...rove("redo") })),
      h("div", { className: "authoring-toolbar-group" }, h("div", { className: "authoring-mode", role: "group", "aria-label": "표시" },
        ...MODES.map(([value, label]) => h("button", { key: value, type: "button", value, "aria-pressed": view.mode === value, ...rove(`mode-${value}`), onClick: () => controller.setMode(value) }, label)))),
      h("div", { className: "authoring-toolbar-group" },
        ...creates.map(({ commandType, label, available, disabled }) =>
          quiet(label, () => pick(commandType), { key: commandType, disabled, "aria-disabled": disabled || undefined, title: available.reason || undefined, ...rove(commandType) }))),
      // 명령 팔레트(Ctrl+Shift+P)·복사·붙여넣기·이전 위치로는 「더보기」 메뉴 안에 선다.
      h("div", { className: "authoring-toolbar-group" },
        iconButton("more", "더보기", menuToggle("more"), { ...menuButton("more"), ...rove("more") })),
      // 막대의 실행 단추는 결과 시험 하나다 — 테두리 단추로 남는 유일한 명령이다.
      h("div", { className: "authoring-toolbar-group authoring-toolbar-end" },
        button("결과 시험", () => { if (trialShown) controller.update({ trial: false, dock: "" }); else openDock("trial"); }, { "aria-pressed": trialShown, ...rove("trial") }))),
    tabs.length > 0 && h("div", { className: `authoring-body${view.panel === "properties" ? " with-properties" : ""}${outlineOpen ? " outline-open" : ""}` },
      // 좁은 폭의 구조 레일(UX-08): 몸통 높이 띠의 그림 단추 — 이름은 기존 문장 그대로 aria-label·title 이다.
      item && h("button", { type: "button", className: "authoring-rail-toggle", "aria-expanded": outlineOpen, "aria-label": outlineOpen ? "구조 패널 숨기기" : "구조 패널 보기",
        title: outlineOpen ? "구조 패널 숨기기" : "구조 패널 보기", onClick: () => setOutlineOpen(!outlineOpen) }, icon(outlineOpen ? "chevron-left" : "chevron-right")),
      item && h(Outline, { key: item.id, controller, item, view, counts, onSelect: chooseFromOutline, onMenu: outlineMenu, onContext: contextMenu }),
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
        h("section", { className: "authoring-canvas", id: "authoring-canvas", "aria-label": "원문 편집", style: { zoom: view.zoom / 100 }, onContextMenu: shellInput.current.menu = contextMenu }, ...tabs.map((tab) => h(DocumentEditor, { key: `${tab.id}:${controller.editorGeneration(tab.id)}`, item: tab, active: tab.id === snapshot.active_id, controller, shell: shellInput })))),
      item && view.panel === "properties" && h(PanelSplitter, { panel: "properties", label: "속성 패널 너비", layout }),
      item && view.panel === "properties" && h(SemanticForm, { key: item.id, controller, selected: view.selected, selection: view.selection, preview: view.preview, onClose: () => returnFocus("properties") }),
      // 좁은 폭의 속성 시트 뒤 가림막 — 누르면 「닫기」와 같은 일을 한다(초점도 같은 자리로, 넓은 폭에서는 CSS 가 숨긴다).
      item && view.panel === "properties" && h("div", { className: "authoring-scrim", "aria-hidden": true,
        onClick: () => { controller.update({ panel: "", preview: null, refusal: null }); returnFocus("properties"); } })),
    // 하단 독(§3.1·APG tabs): 보조 패널은 한 번에 한 탭만 보인다. 탭 줄은 늘 남아 닫은 뒤에도 다시 열 길이 된다.
    // ←→·Home·End 로 탭을 옮기고 Enter·Space 로 펼치면 그 패널의 첫 제어로 간다.
    (item || view.recoveryPreview) && h("section", { className: `authoring-dock${dock.active ? " open" : ""}`, role: "region", "aria-label": "보조 패널" },
      h("div", { className: "authoring-dock-bar" },
        h("div", { className: "authoring-dock-tabs", role: "tablist", "aria-label": "보조 패널", onKeyDown: (event: any) => { roveFocus(event, event.currentTarget, '[role="tab"]', "horizontal"); } }, ...dock.tabs.map(([key, label]) => {
          const count = dockBadge(item, key);
          return h("button", { key, type: "button", role: "tab", id: `authoring-dock-tab-${key}`, className: "authoring-dock-tab", tabIndex: key === dockEntry ? 0 : -1, "aria-selected": key === dock.active,
            "aria-controls": key === dock.active ? "authoring-dock-panel" : undefined, onClick: () => openDock(key) },
            label, count ? " " : null, count ? h("span", { className: "authoring-badge" }, String(count)) : null);
        })),
        dock.active && h("div", { className: "authoring-dock-actions" },
          iconButton(view.dockMax ? "restore" : "maximize", view.dockMax ? "복원" : "최대화", () => controller.update({ dockMax: !view.dockMax })),
          iconButton("close", "닫기", closeDock))),
      dock.active && h("div", { className: "authoring-dock-panel", id: "authoring-dock-panel", role: "tabpanel", tabIndex: -1, "aria-labelledby": `authoring-dock-tab-${dock.active}` }, dockContent(dock.active))),
    // 문맥 메뉴·더보기(§6.1·APG menu): ↑↓·Home·End 로 옮기고 Tab 은 메뉴를 닫는다. 문맥 메뉴는 되는 명령과 대안만 싣는다
    // (IDE-02) — 불가 사유는 명령 팔레트가 읽힌다. 「더보기」·「파일」의 불가 항목은 초점을 받는다(자리를 기억하는 메뉴다).
    view.contextMenu && (item || view.contextMenu.kind === "file") && h("div", { className: "authoring-context-menu", ref: menuRef, style: { left: view.contextMenu.x, top: view.contextMenu.y },
      onKeyDown: (event: any) => {
        if (roveFocus(event, event.currentTarget, '[role="menuitem"]', "vertical")) return;
        if (event.key === "Tab") { const trigger = view.contextMenu?.trigger; controller.update({ contextMenu: null }); if (focusable(trigger)) trigger.focus(); }
      } },
      h("div", { className: "authoring-menu", id: "authoring-menu", role: "menu", "aria-label": view.contextMenu.kind === "more" ? "더보기" : view.contextMenu.kind === "file" ? "파일" : "문맥 명령" },
        view.contextMenu.kind
          ? (view.contextMenu.kind === "file" ? fileActions : moreActions).map(([label, run, disabled, keys]) => h("button", { key: label, type: "button",
            className: `authoring-menu-item${keys ? " with-key" : ""}`, role: "menuitem", tabIndex: -1, "aria-disabled": disabled || undefined, "aria-keyshortcuts": ariaKeys(keys),
            onClick: () => { if (disabled) return; const trigger = view.contextMenu?.trigger; if (focusable(trigger)) trigger.focus(); controller.update({ contextMenu: null }); run(); } },
            label, keys ? h("kbd", { className: "authoring-key", "aria-hidden": true }, keys) : null))
          : h(CommandMenu, { entries: commandTable, readOnly, onPick: pick, onPalette: () => { const trigger = view.contextMenu?.trigger; controller.update({ contextMenu: null }); openPalette(trigger); } }))),
    // 명령 팔레트(IDE-02): 비모달 오버레이 — 여는 차례 번호가 열쇠라 다시 열면 입력이 비고 초점이 입력칸으로 간다.
    item && view.palette ? h(CommandPalette, { key: view.palette, entries: commandTable, actions: paletteActions, onPick: pick, onClose: closePalette }) : null,
    // 상태 막대: 줄마다 바뀌는 상태라 live region 이 아니다(읽기는 위의 단일 live region 이 전이 때만 한다).
    item && h("footer", { className: "authoring-status", role: "group" },
      // 왼쪽: 저장·준비와 구조 검사. 오른쪽: 보존·복원·시험·복구 초안. 구분선은 CSS 가 그린다(글자가 아니다).
      h("div", { className: "authoring-status-group" },
        // 저장·검사·시험은 서로 다른 상태다(P09·§9.1): 저장됨 뒤에 Python 의 readiness(초안/사용 준비)를 붙인다.
        h("span", null, liveNow.save),
        // 구조 오류가 있으면 Python 의 준비 문장(readiness.message)을, 없으면 개수를 보인다. 수는 문제 탭 배지와 같은
        // problems 에서 센다 — 문제가 있으면 그 표현이 문제 탭으로 가는 글 링크 모양 단추다(IDE-01).
        item.problems?.length ? h("button", { type: "button", className: "authoring-status-link", onClick: () => openDock("problems") }, liveNow.readinessText)
          : h("span", null, liveNow.readinessText)),
      h("div", { className: "authoring-status-group authoring-status-end" },
        // 준비 상태 옆의 보존 판정 칩 — Python 의 compatibility.state 를 이름으로 옮길 뿐이다(마운트 전에도 선다).
        item.compatibility?.state === "checking" && h("span", { "data-compat": "checking" }, "보존 확인 중"),
        item.compatibility?.state === "limited" && h("span", { "data-compat": "limited" }, "읽기 전용 · 보존 확인 필요"),
        item.restore?.message && h("span", { "data-restore": item.restore.state }, item.restore.message),
        // 결과 시험 상태는 상태마다 한 표현이다 — Python 의 trial_state_label 그대로(P09·§9.1). 시험을 한 뒤에만 서고,
        // 누르면 결과 시험 탭을 연다(IDE-01). 시험 자료 표지는 보관한 케이스나 저장하지 않은 입력이 있을 때만 선다.
        item.trial_state !== "untried" && item.trial_state_label && h("button", { type: "button", className: "authoring-status-link", "data-trial": item.trial_state, onClick: () => openDock("trial") }, item.trial_state_label),
        (item.cases_dirty || !!item.cases?.length) && h("span", null, item.cases_dirty ? "시험 자료: 저장하지 않은 변경" : "시험 자료: 로컬 보관"),
        item.recovery_saved_at && h("span", null, "복구 초안 저장됨 · ", h("time", { dateTime: item.recovery_saved_at }, new Date(item.recovery_saved_at).toLocaleTimeString())),
        item.recovery && h("span", null, "복구 여부 선택 필요"),
        // 확대는 상태 막대 끝의 작은 선택이다(편집기 관례) — 도구 막대의 roving 묶음 밖, 보통 Tab 순서다.
        h("select", { className: "field authoring-zoom", "aria-label": "확대", value: view.zoom, onChange: (event: any) => controller.update({ zoom: Number(event.target.value) }) },
          ...[75, 100, 125, 150, 200].map((value) => h("option", { key: value, value }, `${value}%`))))),
  );
}
