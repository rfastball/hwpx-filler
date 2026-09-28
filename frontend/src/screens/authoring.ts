import { createElement as h, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { mountLintpad, disposeLintpad, updateLintpad, editLintpad, lintpadState, lintpadCommand, navigateLintpad } from "../editorview/txt_lintpad.ts";
import { mountRhwp } from "../editorview/rhwp_editor.ts";
import { COMMANDS } from "./authoring_controller.ts";
import { PanelSplitter, PANEL_CYCLE, cyclePanels } from "./authoring_layout.ts";
import type { AuthoringLayout } from "./authoring_layout.ts";
import type { AuthoringController, AuthoringEditor } from "./authoring_controller.ts";
import { TPL_STATUS_COPY } from "./job_run.ts";

/** IME 조합 중에는 문서 명령을 보내지 않는다 — 조합이 끝난 뒤 같은 명령을 다시 받는다. */
const IME_BUSY = "한글 조합을 마친 뒤 다시 실행하세요.";

type Obj = Record<string, any>;
type Props = { controller: AuthoringController };
const button = (label: ReactNode | ReactNode[], click: () => void, props: Obj = {}) =>
  h("button", { type: "button", className: "btn sm", onClick: click, ...props }, ...(Array.isArray(label) ? label : [label]));
const KIND_LABEL: Obj = { field: "필드", slot: "항목", option: "선택", text: "본문" };
const SEVERITY_LABEL: Obj = { error: "오류", warning: "경고" };
const CATEGORY_LABEL: Obj = { structure: "구조", compatibility: "호환성", trial_input: "시험 입력" };
/** 식별자 변경은 고급 정보지만 기존 작업 연결에 닿는 영향은 숨기지 않는다(U06·F19). */
const IDENTIFIER_IMPACT = "식별자 변경은 기존 작업 연결에 영향을 줄 수 있습니다.";

/** Python 이 판정한 명령 한 건의 가용성(F40·P07). 판정이 아직 없으면(선택 전) 표면은 자기 추측을 더하지 않고 사용 가능으로 둔다. */
export function commandAvailability(commands: Obj[] | undefined, type: string): Obj {
  return (commands || []).find((entry) => entry.type === type) || { type, enabled: true, reason: null, alternative: null };
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
const badge = (count: number): ReactNode => count ? h("span", { className: "authoring-badge" }, `문제 ${count}`) : null;
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
/** 문제의 다음 행동(§7.2): navigate 는 그 위치로 선택을 옮기고, command 는 Python 이 준 명령을 미리보기로 보낸다. */
export function problemAction(controller: Pick<AuthoringController, "select" | "preview">, item: Obj, problem: Obj, action: Obj): Promise<void> {
  return action.kind === "command" ? controller.preview(action.command) : controller.select({ source_revision: item.revision, ...(problem.location || {}), target: problem.target });
}

type MenuEvent = { clientX: number; clientY: number; target?: unknown; preventDefault?(): void };
/** 문맥 메뉴를 좌표(셸 기준)에 연다(§6.1). trigger 는 닫힐 때 초점을 돌려줄 자리다.
 *  kind="more" 는 도구 막대 「더보기」의 작은 메뉴다 — 같은 상태·Escape·바깥 클릭 경로를 쓴다. */
export function openContextMenu(controller: Pick<AuthoringController, "update">, event: MenuEvent, root?: { getBoundingClientRect(): { left: number; top: number } } | null, kind?: "more"): void {
  event.preventDefault?.();
  const rect = root?.getBoundingClientRect();
  controller.update({ contextMenu: { x: event.clientX - (rect?.left || 0), y: event.clientY - (rect?.top || 0), trigger: event.target, ...(kind ? { kind } : {}) } });
}

/** 하단 독(§3.1 UI01~UI10)이 한 탭으로 보이는 패널 — `view.panel` 값이 곧 탭 열쇠다. 속성은 옆 패널이라 빠진다. */
export const DOCK_PANELS = ["problems", "search", "raw", "impact", "paste", "commands", "external", "comparison"];
/** 독의 탭 목록과 지금 보일 탭 하나. 기본 탭(문제·검색·원문 표기·변경 영향·결과 시험)은 문서가 열려 있으면 늘 서고,
 *  문맥 탭은 그 상태가 있을 때만 선다. 보일 탭: 열린 패널 → 사용자가 고른 탭 → 경보·비교·시험 순의 대체.
 *  `dockClosed` 는 사용자가 닫은 뒤 경보가 스스로 다시 펼치지 않게 한다(새로 선 경보는 화면이 다시 연다). */
export function dockTabs(item: Obj | undefined, view: Obj): { tabs: [string, string][]; active: string } {
  const tabs: [string, string][] = item ? [["problems", "문제"], ["search", "검색"], ["raw", "원문 표기"], ["impact", "변경 영향·작업 적용"], ["trial", "결과 시험"]] : [];
  const saveFailed = !!item && (view.panel === "external" || !!view.saveFailed);
  if (item && view.panel === "paste") tabs.push(["paste", "의미 붙여넣기"]);
  if (item && view.panel === "commands") tabs.push(["commands", "명령"]);
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
/** 같은 불가 사유를 명령마다 되풀이하지 않는다(§3.1): 불가 명령이 둘 이상이고 사유가 모두 같으면 그 한 문장, 아니면 null.
 *  사유는 Python 의 판정 문장 그대로다(P07) — 표면은 모을 뿐 새로 짓지 않는다. */
export function sharedReason(commands: Obj[] | undefined, types: string[] = COMMANDS.map(([type]) => type)): string | null {
  const reasons = types.map((type) => commandAvailability(commands, type)).filter((entry) => !entry.enabled).map((entry) => String(entry.reason || ""));
  return reasons.length > 1 && reasons.every((reason) => reason && reason === reasons[0]) ? reasons[0] : null;
}
/** Escape 한 단계(§10): 문맥 메뉴가 열려 있으면 그것만 닫고 초점을 연 자리로 돌린다("menu"); 아니면 패널을 닫는다("panel"). */
export function escapeShell(controller: Pick<AuthoringController, "update" | "viewModel">): "menu" | "panel" {
  const view = controller.viewModel.getSnapshot();
  if (view.contextMenu) { const trigger = view.contextMenu.trigger as { focus?(): void } | undefined; controller.update({ contextMenu: null }); trigger?.focus?.(); return "menu"; }
  controller.update({ panel: "", preview: null, refusal: null });
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

/** 명령 목록 — 도구 막대·팔레트·문맥 메뉴가 같은 가용성 데이터와 같은 실행 경로를 쓴다(F40). */
function CommandList({ controller, view, readOnly, menu }: Props & { view: Obj; readOnly: boolean; menu?: boolean }) {
  const pick = (commandType: string) => controller.update({ panel: "properties", commandType, contextMenu: null, preview: null, refusal: null });
  // 사유가 모두 같으면 목록 머리에 한 번만 두고, 각 불가 항목은 그 문장을 설명으로 가리킨다. 대안은 항목마다 남는다.
  const shared = sharedReason(view.commands);
  const reasonId = `authoring-command-reason-${menu ? "menu" : "palette"}`;
  return [shared && h("p", { key: "shared-reason", id: reasonId, className: "authoring-reason", role: menu ? "none" : undefined }, shared),
    ...COMMANDS.map(([commandType, label]) => {
      const available = commandAvailability(view.commands, commandType);
      const disabled = readOnly || !available.enabled;
      return h("div", { key: commandType, className: "authoring-command", role: menu ? "none" : undefined },
        button(label, () => pick(commandType), { role: menu ? "menuitem" : undefined, disabled, "aria-disabled": disabled || undefined, title: available.reason || undefined,
          "aria-describedby": shared && !available.enabled ? reasonId : undefined }),
        !shared && !available.enabled && available.reason && h("p", { className: "authoring-reason" }, available.reason),
        !available.enabled && available.alternative && button(available.alternative.label, () => pick(available.alternative!.command_type)));
    })];
}

/** 구조 변경 요약(F38) — 미리보기와 변경 영향 패널이 같은 표를 쓴다. */
function StructureDelta({ delta }: { delta: Obj }) {
  // 선택 delta 는 Python 이 `[slot_id, option_id]` 쌍으로 준다 — 소속을 함께 읽어야 같은 이름의 선택이 갈린다.
  const name = (entry: Obj | string | string[]): string => typeof entry === "string" ? entry : Array.isArray(entry) ? entry.join(" / ") : String(entry.label || entry.id || entry.name || "");
  const row = (label: string, items?: (Obj | string)[]) => !!items?.length && h("p", { key: label }, `${label}: ${items.map(name).join(", ")}`);
  return h("div", { className: "authoring-delta", "aria-label": "구조 변경" },
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
        onChanged: () => {}, onSelectionChanged: () => {}, onError: (error) => controller.update({ error: String(error) }) });
      if (disposed) handle.dispose(); else release = () => handle.dispose();
    });
    return () => { disposed = true; release?.(); };
  }, [content]);
  return h("div", { ref: host, className: "authoring-result-pages" });
}

/** 편집면(iframe) 안에서 눌려 Studio 가 넘겨준 셸 키(§10) — 셸 onKeyDown 과 같은 길로 보낼 사건 모양. 그 밖의 키는 null. */
export function forwardedShellKey(shortcut: string, target: unknown): Obj | null {
  const key = shortcut === "Escape" ? { key: "Escape" } : shortcut === "F6" ? { key: "F6" } : shortcut === "ShiftF6" ? { key: "F6", shiftKey: true } : null;
  return key && { ...key, target, nativeEvent: {}, preventDefault() {} };
}
/** 셸의 키·문맥 메뉴 처리기 — 편집면 iframe 은 셸까지 사건을 올리지 못하므로 편집기가 이 손잡이로 넘긴다. */
type ShellInput = { current: { key?: (event: any) => void; menu?: (event: any) => void } };

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
          decorate: (analysis, mode) => {
            const spans = mode === "document" ? [] : [...(analysis.spans || [])];
            if (mode === "structure") for (const place of analysis.placements || []) {
              spans.push({ kind: `${place.kind}-start`, start: place.start, end: place.start });
              spans.push({ kind: `${place.kind}-end`, start: Math.max(place.start, place.end - 1), end: place.end });
            }
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
            else if (shortcut === "CtrlShiftP") controller.update({ panel: "commands" });
            else if (shortcut === "CtrlS") void controller.guarded(() => controller.save());
            else if (shortcut === "CtrlF") controller.update({ panel: "search" });
            else controller.update({ panel: "properties", commandType: current.selected?.kind === "field" ? "rename_field" : current.selected?.kind === "option" ? "rename_option" : "rename_slot", focusPanel: (current.focusPanel || 0) + 1 });
          },
          onChanged: (content) => controller.changed(item.id, content),
          onSelectionChanged: (selection) => controller.selection(item.id, selection),
          onError: (error) => controller.update({ error: String(error) }), readOnly: false });
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
          decorate: (analysis, mode) => { void controller.guarded(() => handle.setDecorations({ ...analysis, mode })); },
        };
        release = () => handle.dispose();
      }
      detach = controller.attach(item.id, adapter.current!);
      adapter.current!.decorate(item.analysis || {}, controller.mode(item.id));
    });
    return () => { disposed = true; detach?.(); release?.(); adapter.current = null; };
  }, [controller, item.id]);
  // 장식은 분석이 바뀔 때만 다시 보낸다 — 같은 분석의 재전송(push)은 같은 revision 이다(UX-05).
  useEffect(() => { adapter.current?.decorate(item.analysis || {}, controller.mode(item.id)); }, [item.analysis?.revision ?? item.analysis, active]);
  return h("div", { className: "authoring-document", hidden: !active, inert: !active || !!item.recovery, "aria-hidden": !active },
    h("div", { ref: host, className: "authoring-editor-host" }));
}

function SemanticForm({ controller, selected, selection, preview }: Props & { selected: Obj; selection: Obj; preview: Obj | null }) {
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
  // 화면 읽기(§10): 이름 칸은 대상(종류·사용 위치)과 소속(상위 항목/선택·범위)을 설명으로 함께 읽힌다.
  const field = (label: string, value: string, onChange: (value: string) => void) => h("label", { className: "authoring-field" }, label,
      h("input", { className: "field", value, ref: label.includes("이름") ? nameInput : undefined, list: label === "필드 이름" ? "authoring-existing-fields" : undefined,
        "aria-describedby": label.includes("이름") ? "authoring-properties-target authoring-properties-context" : undefined, onChange: (event: any) => onChange(event.target.value) }));
  return h("form", { className: "authoring-properties", "aria-labelledby": "authoring-properties-title", onCompositionStart: () => { composing.current = true; }, onCompositionEnd: () => { composing.current = false; },
    onSubmit: (event: any) => { event.preventDefault(); submitProperties(controller, composing.current, command); },
    // Escape 1단계: 입력창의 작성 중인 값만 적용값으로 되돌린다. 2단계(되돌릴 것이 없을 때)는 셸이 패널을 닫고 선택으로 돌아간다.
    onKeyDown: (event: any) => {
      if (event.key !== "Escape" || event.nativeEvent?.isComposing) return;
      if (escapeStage(selected, { name, identifier, parent, text }) === "revert") { event.stopPropagation(); revert(); }
    } },
    // 닫기(§3.1): 모든 폭에서 머리 오른쪽에 선다 — Escape 의 닫기 단계와 같은 일(패널을 닫고 선택으로 돌아간다).
    h("div", { className: "authoring-properties-head" }, h("h2", { id: "authoring-properties-title" }, "속성"),
      button("닫기", () => { controller.update({ panel: "", preview: null, refusal: null }); void controller.guarded(controller.focusSelection); })),
    selected && h("p", { id: "authoring-properties-target" }, selected.kind === "field" && selected.occurrences
      ? outlineLabel("field", { ...selected, count: selected.count ?? selected.occurrences.length }, problemCount(controller.tab().problems, selected.name))
      : selected.name || selected.label || selected.id),
    h("label", { className: "authoring-field" }, "명령", h("select", { className: "field", value: type, "aria-disabled": !available.enabled || undefined, title: available.reason || undefined, onChange: (event: any) => switchType(event.target.value) },
      ...COMMANDS.map(([value, label]) => { const entry = commandAvailability(view.commands, value); return h("option", { key: value, value, disabled: !entry.enabled, title: entry.reason || undefined }, label); }))),
    // 비활성 사유와 대안은 Python 의 판정을 그대로 보인다(P07) — 툴팁만이 유일한 경로가 되지 않도록 본문에도 선다(§10).
    !available.enabled && available.reason && h("p", { className: "authoring-reason", role: "status" }, available.reason),
    !available.enabled && available.alternative && button(available.alternative.label, () => switchType(available.alternative!.command_type)),
    h("p", { className: "authoring-context", id: "authoring-properties-context" }, `${selected?.slot_id || view.context?.slot_id || "문서"}${selected?.option_id || view.context?.option_id ? ` / ${selected?.option_id || view.context?.option_id}` : ""}${selection.start != null ? ` · ${selection.start}–${selection.end ?? selection.start}` : ""}`),
    field(type.includes("field") ? "필드 이름" : "표시 이름", name, setName),
    type === "create_field" && h("datalist", { id: "authoring-existing-fields" }, ...candidates.map((candidate: Obj) => h("option", { key: candidate.name, value: candidate.name, label: `${candidate.name} · 사용 위치 ${candidate.count ?? 0}곳` }))),
    !["create_field", "rename_field", "relink_field", "unset_field"].includes(type) && field("연결 식별자", identifier, setIdentifier),
    type === "create_option" ? h("p", null, `상위 항목: ${view.context?.slot_id || "없음"}`) :
      ["rename_option", "adjust_range", "unwrap", "delete", "duplicate", "move"].includes(type) && field("상위 항목", parent, setParent),
    type === "unset_field" && field("남길 본문", text, setText),
    type === "unset_field" && h("div", null,
      button("필드 이름 사용", () => setText(selected?.name || "")),
      button("시험값 사용", () => setText(String(view.values[selected?.name] ?? "")), { disabled: !(selected?.name in view.values) })),
    type === "create_field" && h("label", null, h("input", { type: "checkbox", checked: keepValue, onChange: (event: any) => setKeepValue(event.target.checked) }), " 선택 문구를 시험값으로 보관"),
    type === "unwrap" && h("label", null, h("input", { type: "checkbox", checked: cascade, onChange: (event: any) => setCascade(event.target.checked) }), " 하위 의미 함께 해제"),
    h("button", { className: "btn sm", type: "submit", disabled: readOnly || !available.enabled, "aria-disabled": (readOnly || !available.enabled) || undefined, title: available.reason || undefined }, "변경 미리보기"),
    // 기본 범위는 현재 선택 한 곳이다(U03) — 같은 문구의 다른 자리는 별도 검색으로만 찾는다.
    type === "create_field" && !!view.lastCreatedText && button("다른 같은 문구 찾기", () => { const text = view.lastCreatedText; controller.update({ lastCreatedText: "" }); void controller.guarded(() => controller.search(text, "body")); }),
    // 거절(U07·AC08·AC10): Python 의 판정 문장을 그대로 보이고, 다음 행동만 버튼으로 세운다.
    refusal && h("section", { className: "authoring-preview authoring-refusal", role: "alert", "aria-label": "변경 불가" },
      h("p", null, refusal.message),
      refusal.code === "cascade_required" && h("ul", { "aria-label": "함께 해제될 하위 의미" }, ...(refusal.children || []).map((child: Obj, index: number) =>
        h("li", { key: index }, `${KIND_LABEL[child.kind] || child.kind} · ${child.label || child.id}${child.count != null ? ` · ${child.count}` : ""}`))),
      h("div", null,
        refusal.code === "name_conflict" && button("다른 이름 입력", () => { nameInput.current?.focus(); nameInput.current?.select(); }),
        refusal.code === "name_conflict" && singleOccurrence && button("기존 필드에 연결", () => { setName(String(refusal.name || "")); switchType("relink_field"); }),
        refusal.code === "cascade_required" && button("하위 의미 함께 해제", () => { setCascade(true); submitProperties(controller, composing.current, () => ({ ...command(), cascade: true })); }, { className: "btn sm primary" }),
        button("취소", cancel))),
    preview && h("section", { className: "authoring-preview", "aria-label": "변경 영향" },
      h("h3", null, "변경 영향"),
      preview.expanded && h("p", null, "선택을 문단 전체로 확장합니다. 포함될 내용을 확인하세요."),
      // 전체 이름 변경의 문장(§13)은 조사까지 Python 이 짓는다(preview.message) — 표면은 그대로 보인다.
      h("p", null, preview.message || `사용 위치 ${affected}곳`),
      preview.counts && h("p", null, `문단 ${preview.counts.paragraphs ?? 0} · 필드 ${preview.counts.fields ?? 0} · 선택 ${preview.counts.options ?? 0} · 표 ${preview.counts.tables ?? 0}`),
      preview.included != null && (Array.isArray(preview.included)
        ? h("ul", { "aria-label": "포함될 내용" }, ...preview.included.map((entry: Obj | string, index: number) => h("li", { key: index }, typeof entry === "string" ? entry : entry.label || entry.text || entry.id)))
        : h("pre", { "aria-label": "포함될 내용" }, String(preview.included))),
      !!preview.children?.length && h("ul", { "aria-label": "하위 의미" }, ...preview.children.map((child: Obj, index: number) =>
        h("li", { key: index }, `${KIND_LABEL[child.kind] || child.kind} · ${child.label || child.id}${child.count != null ? ` · ${child.count}` : ""}`))),
      preview.links_existing && h("p", null, `기존 필드에 연결 · 사용 위치 ${preview.existing_count ?? 0}곳`),
      (preview.before || preview.original) && h("pre", { "aria-label": "변경 전" }, preview.before || preview.original),
      preview.after && h("pre", { "aria-label": "변경 후" }, preview.after),
      preview.structure_delta && h(StructureDelta, { delta: preview.structure_delta }),
      !!preview.structure_delta?.renamed?.length && h("p", null, IDENTIFIER_IMPACT),
      preview.body_changed && h("p", null, "본문 변경 있음"),
      !!preview.linked_jobs?.length && h("p", null, `연결된 작업: ${preview.linked_jobs.join(", ")}`),
      !!preview.impact_unverified && h("p", null, "연결된 작업의 영향은 확인하지 않았습니다."),
      preview.field_delta && h("p", null, `추가 필드: ${(preview.field_delta.added_fields || []).join(", ") || "없음"} · 없어진 필드: ${(preview.field_delta.removed_fields || []).join(", ") || "없음"}`),
      ...(preview.edits || []).map((edit: Obj, index: number) => h("pre", { key: index }, edit.text)),
      button(COMMANDS.find(([value]) => value === type)?.[1] || "적용", () => { void controller.guarded(async () => {
        if (composing.current) return;
        const captured = preview.original;
        await controller.applyPreview();
        if (type === "create_field" && captured) controller.update({ lastCreatedText: String(captured) });
        if (type === "create_field" && keepValue && name && captured) await controller.keepTrialValue(name, String(captured));
      }); }, { className: "btn sm primary" }),
      button("취소", cancel)),
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
        onError: (error) => controller.update({ error: String(error) }) });
      if (disposed) editor.dispose(); else release = () => editor.dispose();
    });
    return () => { disposed = true; release?.(); };
  }, trialViewerKey(item));
  return h("section", { className: "authoring-trial", "aria-label": "결과 시험" },
    h("header", null, h("h2", null, "결과 시험"), h("p", null, "시험 자료는 템플릿 파일에 포함되지 않습니다."), button("원문으로", () => controller.update({ trial: false }))),
    h("div", { className: "authoring-trial-input" },
      item.cases_error && h("p", { role: "alert" }, item.cases_error),
      ...(item.analysis?.fields || []).map((field: Obj) => h("label", { key: field.name, className: "authoring-field" }, field.name,
        result?.report?.missing_fields?.includes(field.name) && h("span", null, "직전 시험: 미입력"),
        h("input", { className: "field", "aria-invalid": !!result?.report?.missing_fields?.includes(field.name), value: view.values[field.name] || "",
          onCompositionEnd: (event: any) => { void controller.guarded(() => controller.trialInput({ ...controller.viewModel.getSnapshot().values, [field.name]: event.currentTarget.value }, controller.viewModel.getSnapshot().selectedOptions)); },
          onChange: (event: any) => {
            const values = { ...controller.viewModel.getSnapshot().values, [field.name]: event.target.value };
            if (event.nativeEvent.isComposing) controller.update({ values });
            else void controller.guarded(() => controller.trialInput(values, controller.viewModel.getSnapshot().selectedOptions));
          } }))),
      ...(item.analysis?.slots || []).map((slot: Obj) => h("label", { key: slot.id, className: "authoring-field" }, slot.label || slot.id,
        h("select", { className: "field", value: view.selectedOptions[slot.id] || "", onChange: (event: any) => { void controller.guarded(() => controller.trialInput(view.values, { ...view.selectedOptions, [slot.id]: event.target.value })); } },
          h("option", { value: "" }, "선택"), ...(slot.options || []).map((option: Obj) => h("option", { key: option.id, value: option.id }, option.label || option.id))))),
      h("label", null, h("input", { type: "checkbox", checked: view.autoTrial, onChange: (event: any) => controller.update({ autoTrial: event.target.checked }) }), " 자동 갱신"),
      button("시험 시작", () => { void controller.guarded(() => controller.runTrial()); }, { disabled: view.trialBusy }),
      button("시험 케이스 저장", () => { void controller.guarded(() => controller.saveCase()); }),
      button("시험 결과 내보내기", () => { void controller.guarded(controller.exportResult); }, { disabled: item.trial_state !== "current" }),
      h("h3", null, "보관한 시험 케이스"),
      ...(item.cases || []).map((test: Obj) => h("div", { key: test.name },
        button(`${test.name}${test.needs_review ? " · 다시 확인 필요" : ""}`, () => { void controller.guarded(() => controller.loadCase(test)); }),
        button("삭제", () => { void controller.guarded(() => controller.removeCase(test.name)); }, { "aria-label": `${test.name} 삭제` }))),
      button("시험 자료 가져오기", () => { void controller.guarded(() => controller.transferCases("import")); }),
      button("시험 자료 내보내기", () => { void controller.guarded(() => controller.transferCases("export")); })),
    h("div", { className: "authoring-trial-output" },
      h("p", { role: "status" }, view.trialBusy ? "갱신 중 · 이전 결과" : item.trial_state_message),
      h("p", null, "통과 표시는 현재 값과 선택 구성에만 해당합니다."),
      h("ul", { className: "authoring-coverage", "aria-label": "선택별 시험 상태" }, ...(item.trial_coverage || []).map((coverage: Obj) =>
        h("li", { key: `${coverage.slot_id}/${coverage.option_id}` }, `${coverage.slot_id} / ${coverage.option_id} · ${({ current: "현재 시험 구성 확인됨", stale: "다시 시험 필요", untried: "시험하지 않음" } as Obj)[coverage.state]}`))),
      item.media === "txt" ? h(TxtTrialOutput, { controller, result, selected: view.selected }) : h("div", { className: "authoring-result-pages", ref: output }),
      h("h3", null, "출력·제외 이유"),
      item.media === "hwpx" && view.resultSelection?.entry && h("div", null, h("h4", null, "선택한 문단의 필드"),
        ...(result?.occurrences || []).filter((entry: Obj) => entry.output?.entry === view.resultSelection.entry && entry.output?.paragraph === view.resultSelection.paragraph).map((entry: Obj, index: number) =>
          button(`${entry.name}: ${entry.value}`, () => { void controller.guarded(() => controller.select({ ...entry.source, source_revision: result.source_revision })); }, { key: index }))),
      ...(result?.occurrences || result?.trace || []).map((entry: Obj, index: number) => button(`${entry.name || entry.field || "필드"}: ${entry.value ?? ""}`, () => { void controller.guarded(() => controller.select({ ...(entry.source || entry), source_revision: result.source_revision })); }, { key: `field-${index}` })),
      ...(result?.excluded || []).map((entry: Obj, index: number) => button(entry.reason || entry.label || entry.option_id, () => { void controller.guarded(() => controller.select({ ...(entry.source || entry), source_revision: result.source_revision })); }, { key: `excluded-${index}` }))),
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
  return h("pre", { tabIndex: 0, "aria-label": "읽기 전용 시험 결과" }, ...parts);
}

/** 닫힌 <details> 의 본문은 펼친 뒤에 그린다(UX-05) — 사용 위치가 많은 문서에서 보이지 않는 줄을 매번 짓지 않는다.
 *  펼침 상태는 details 원소와 같은 수명의 컴포넌트 상태라, React 가 원소를 다시 쓰면 상태도 함께 남는다. */
function LazyDetails({ summary, body }: { summary: ReactNode; body: () => ReactNode[] }) {
  const [open, setOpen] = useState(false);
  return h("details", { onToggle: (event: any) => setOpen(!!event.currentTarget.open) }, summary, ...(open ? body() : []));
}

const MODES: [string, string][] = [["document", "문서"], ["template", "템플릿"], ["structure", "구조"]];

export function AuthoringScreen({ controller, layout }: Props & { layout?: AuthoringLayout | null }): ReactNode {
  const snapshot = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot) || {};
  const view = useSyncExternalStore(controller.viewModel.subscribe, controller.viewModel.getSnapshot, controller.viewModel.getSnapshot);
  const tabs: Obj[] = snapshot.tabs || [];
  const item = tabs.find((tab) => tab.id === snapshot.active_id);
  const root = useRef<HTMLDivElement>(null);
  // 좁은 폭(컨테이너 64rem 이하)에서만 쓰이는 구조 레일의 펼침 — 넓은 폭에서는 CSS 가 무시한다.
  const [outlineOpen, setOutlineOpen] = useState(false);
  const shellInput: ShellInput = useRef<ShellInput["current"]>({});
  const dock = dockTabs(item, view);
  const counts = useMemo(() => problemCounts(item?.problems), [item?.problems]);
  useEffect(() => {
    root.current?.querySelector<HTMLElement>(view.panel === "properties" ? ".authoring-properties input" : view.panel === "search" ? '[name="query"]' : view.panel === "commands" || view.panel === "external" || view.panel === "problems" ? ".authoring-bottom button" : ".authoring-shell-placeholder")?.focus();
  }, [view.panel, view.commandType, view.focusPanel]);
  useEffect(() => {
    const focus = () => { void controller.guarded(controller.checkExternal); };
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [controller]);
  // 문맥 메뉴(§6.1): 열리면 첫 활성 항목에 초점, 바깥 클릭이면 닫는다. Escape 는 셸 단축키가 처리한다.
  // 「더보기」 메뉴는 여는 버튼 자체의 누름을 바깥으로 치지 않는다 — 그 버튼이 여닫기를 맡는다.
  useEffect(() => {
    if (!view.contextMenu) return;
    root.current?.querySelector<HTMLElement>('[role="menu"] [role="menuitem"]:not([disabled])')?.focus();
    const trigger = view.contextMenu.kind === "more" ? view.contextMenu.trigger as Element | null : null;
    const outside = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (!target?.closest?.('[role="menu"]') && !(target && trigger?.contains?.(target))) controller.update({ contextMenu: null });
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [view.contextMenu]);
  // 경보(복구 초안·외부 파일 변경)와 초안 비교는 새로 서는 순간 독의 제 탭을 펼친다 — 닫아 둔 독도 다시 연다.
  const forced = view.recoveryPreview ? "recovery_preview" : item?.recovery ? "recovery" : dock.tabs.some(([key]) => key === "external_changed") ? "external_changed" : "";
  useEffect(() => {
    if (!forced) return;
    const current = controller.viewModel.getSnapshot();
    controller.update({ dock: forced, dockClosed: false, ...(DOCK_PANELS.includes(current.panel) && current.panel !== "comparison" ? { panel: "" } : {}) });
  }, [forced, item?.id, view.recoveryPreview]);
  const act = (work: () => unknown) => () => { void controller.guarded(work); };
  const select = (entry: Obj) => act(() => controller.select({ source_revision: item?.revision, ...entry }));
  const contextMenu = (event: any, entry?: Obj) => { if (entry) select(entry)(); openContextMenu(controller, event, root.current); };
  const editorState = item ? controller.editorState(item.id) : null;
  const readOnly = !!item && item.media === "hwpx" && item.rhwp_editable !== true;
  // F2(§10): 패널이 이미 열려 있어도 이름 칸으로 초점을 옮긴다 — focusPanel 은 그 요청의 차례 번호다.
  const rename = () => controller.update({ panel: "properties", commandType: view.selected?.kind === "field" ? "rename_field" : view.selected?.kind === "option" ? "rename_option" : "rename_slot", focusPanel: (view.focusPanel || 0) + 1 });
  // 도구 막대에서 빠진 세 동작 — 「더보기」 메뉴와 명령 팔레트가 같은 실행 경로를 쓴다.
  const moreActions: [string, () => void, boolean][] = [
    ["의미 복사", act(controller.copy), false],
    ["붙여넣기", () => controller.update({ panel: "paste", contextMenu: null }), !controller.clipboard()],
    ["이전 위치로", act(controller.back), false]];
  // 독 탭 하나를 펼친다: 패널 탭은 view.panel 로, 나머지(시험·경보·비교)는 view.dock 으로. 옆 속성 패널은 건드리지 않는다.
  const openDock = (key: string) => {
    if (key === dock.active) return;
    if (key === "raw") return act(controller.raw)();
    if (key === "impact") return act(controller.impact)();
    if (DOCK_PANELS.includes(key)) return controller.update({ panel: key, contextMenu: null });
    controller.update({ dock: key, dockClosed: false, contextMenu: null, ...(key === "trial" ? { trial: true } : {}), ...(DOCK_PANELS.includes(view.panel) ? { panel: "" } : {}) });
  };
  const closeDock = () => {
    root.current?.querySelector<HTMLElement>(`#authoring-dock-tab-${dock.active}`)?.focus();
    controller.update({ ...(DOCK_PANELS.includes(view.panel) ? { panel: "" } : {}), trial: false, dock: "", dockClosed: true, dockMax: false });
  };
  const trialShown = dock.active === "trial";
  const dockContent = (key: string): ReactNode => {
    if (key === "trial" && item) return h(Trial, { controller, item, view });
    if (key === "recovery" && item) return h("section", { className: "authoring-bottom", role: "alert", "aria-label": "중단 전 복구 초안" }, h("h2", null, "중단 전 복구 초안"),
      h("p", null, "복구 여부를 선택한 뒤 편집을 계속하세요. 원본 파일은 아직 변경하지 않았습니다."),
      button("초안과 원본 비교", act(() => controller.compareRecovery(item.recovery_key))),
      button("복구", act(() => controller.recover(item.id))), button("폐기", act(() => controller.discardRecovery(item.id))));
    if (key === "recovery_preview" && view.recoveryPreview) return h("section", { className: "authoring-bottom", "aria-label": "초안과 원본 비교" }, h("h2", null, "초안과 원본 비교"),
      h("div", { className: "authoring-compare" }, ...[["원본", view.recoveryPreview.original_content], ["복구 초안", view.recoveryPreview.content]].map(([name, content]) => h("div", { key: name }, h("h3", null, name),
        content == null ? h("p", null, "원본 파일 없음") : view.recoveryPreview.media === "txt" ? h("pre", null, content)
          : h(ExternalDocument, { controller, item: { name }, content, sectionEntries: name === "원본" ? view.recoveryPreview.original_section_entries : view.recoveryPreview.section_entries })))),
      button("복구", act(() => controller.recover(item?.recovery ? item.id : view.recoveryPreview.key))), button("비교 닫기", () => controller.update({ recoveryPreview: null })));
    if (!item) return null;
    if (key === "paste") return h("section", { className: "authoring-bottom", "aria-label": "의미 붙여넣기" }, h("h2", null, "의미 붙여넣기"),
      h("p", null, "문서에서 붙여넣을 위치를 선택하세요. 같은 이름의 필드 연결과 새 식별자를 확인한 뒤 적용합니다."),
      h("form", { onSubmit: (event: any) => { event.preventDefault(); const data = new FormData(event.currentTarget); act(() => controller.paste(data.has("meaning"), String(data.get("new_id") || ""), data.has("link_existing")))(); } },
        h("label", null, h("input", { type: "checkbox", name: "meaning", defaultChecked: true }), "의미 포함"),
        h("label", null, h("input", { type: "checkbox", name: "link_existing" }), "같은 이름의 기존 필드에 연결"),
        h("label", null, "새 연결 식별자 ", h("input", { name: "new_id", className: "field" })),
        h("button", { className: "btn sm", disabled: !controller.clipboard() }, "붙여넣기 미리보기")),
      view.command?.type === "paste" && view.preview && h("div", { className: "authoring-preview" },
        h("pre", { "aria-label": "변경 전" }, view.preview.before), h("pre", { "aria-label": "변경 후" }, view.preview.after),
        button("붙여넣기 적용", act(controller.applyPreview)), button("취소", () => controller.update({ preview: null }))));
    if (key === "search") return h("section", { className: "authoring-bottom", "aria-label": "검색" }, h("h2", null, "검색"),
      h("form", { onSubmit: (event: any) => { event.preventDefault(); const values = new FormData(event.currentTarget); act(() => controller.search(String(values.get("query")), String(values.get("kind")), values.has("all")))(); } },
        h("input", { className: "field", name: "query", "aria-label": "검색어", defaultValue: view.query }),
        h("select", { className: "field", name: "kind", "aria-label": "검색 대상" }, h("option", { value: "body" }, "본문"), h("option", { value: "field" }, "필드"), h("option", { value: "structure" }, "항목·선택"), h("option", { value: "all" }, "전체")),
        h("label", null, h("input", { type: "checkbox", name: "all" }), "열린 모든 문서"), h("button", { className: "btn sm" }, "찾기")),
      // 요약과 종류는 Python 이 센 것·준 것 그대로다(§6.3). 여러 문서를 찾으면 문서마다 한 줄씩 선다.
      ...(view.searchSummaries || []).map((entry: Obj, index: number) => h("p", { key: `summary-${index}`, className: "authoring-search-summary", role: "status" },
        view.searchSummaries.length > 1 ? `${entry.document} · ${entry.summary}` : entry.summary)),
      ...view.hits.map((hit: Obj, index: number) => button([KIND_LABEL[hit.kind] ? kindTag(hit.kind) : null, `${hit.document} · ${hit.context || hit.name || hit.label}`], select(hit), { key: index })));
    if (key === "commands") return h("section", { className: "authoring-bottom", "aria-label": "명령 팔레트" }, h("h2", null, "명령"),
      h(CommandList, { controller, view, readOnly }),
      h("div", { className: "authoring-command-more" }, ...moreActions.map(([label, run, disabled]) => button(label, run, { key: label, disabled }))));
    // 원문 표기(F26·UI09): Python 이 지은 문법 표현을 본문 항목별로 읽기 전용으로 보인다.
    if (key === "raw") return h("section", { className: "authoring-bottom", "aria-label": "원문 표기" }, h("h2", null, "원문 표기"),
      view.syntax?.note && h("p", null, view.syntax.note),
      ...(view.syntax?.sections || []).map((section: Obj, index: number) => h("div", { key: index, className: "authoring-syntax" },
        h("h3", null, section.entry), h("pre", { tabIndex: 0, "aria-label": `${section.entry} 원문 표기` }, section.text))),
      button("복사", act(() => copyText((view.syntax?.sections || []).map((section: Obj) => section.text).join("\n\n"))), { disabled: !view.syntax?.sections?.length }));
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
        button("기존 작업에 적용", act(controller.confirmJob), { disabled: !view.jobApply.change_token }), button("취소", () => controller.update({ jobApply: null }))));
    // 문제 한 건(§7.2·F24): 심각도·종류는 색이 아닌 글자로(P14), 대상·설명·다음 행동을 Python 의 problems 그대로 보인다.
    if (key === "problems") return h("section", { className: "authoring-bottom", "aria-label": "문제" }, h("h2", null, "문제"),
      !item.problems?.length && h("p", null, "문제 없음"),
      ...(item.problems || []).map((problem: Obj, index: number) => h("div", { key: index, className: "authoring-problem" },
        h("p", null, h("strong", null, SEVERITY_LABEL[problem.severity] || problem.severity), ` · ${CATEGORY_LABEL[problem.category] || problem.category}`, problem.target ? ` · ${problem.target}` : ""),
        h("p", null, problem.message),
        ...(problem.actions || []).map((action: Obj, actionIndex: number) => button(action.label, act(() => problemAction(controller, item, problem, action)), { key: actionIndex })))),
      view.command?.type === "repair_marker" && view.preview && h("div", { className: "authoring-preview" },
        h("h3", null, "수정 제안"), h("pre", { "aria-label": "변경 전" }, view.preview.before), h("pre", { "aria-label": "변경 후" }, view.preview.after),
        button("구조 표기 수정", act(controller.applyPreview)), button("취소", () => controller.update({ preview: null }))));
    if (key === "external_changed") return h("section", { className: "authoring-bottom", role: "alert", "aria-label": "외부 파일 변경" }, h("h2", null, "외부 파일 변경"),
      button("양쪽 내용 확인", act(controller.compareExternal)), button("현재 작업을 다른 이름으로 저장", act(() => controller.save(item.id, true))), button("외부 파일 다시 열기", act(controller.reload)));
    // 저장 실패(AC24·§9.2): 변경은 그대로 남고, 같은 세 복구 동사에 「다시 저장」이 더해진다.
    if (key === "external") return h("section", { className: "authoring-bottom", role: "alert", "aria-label": "저장 실패" }, h("h2", null, "저장 실패"),
      button("양쪽 내용 확인", act(controller.compareExternal)), button("현재 작업을 다른 이름으로 저장", act(() => controller.save(item.id, true))),
      button("외부 파일 다시 열기", act(controller.reload)), button("다시 저장", act(() => controller.save(item.id))));
    if (key === "comparison" && view.comparison) return h("section", { className: "authoring-bottom", "aria-label": "외부 파일 내용" }, h("h2", null, "외부 파일 내용"),
      h("div", { className: "authoring-compare" }, ...[["현재 작업", view.comparison.current_content, view.comparison.current_section_entries], ["외부 파일 내용", view.comparison.content, view.comparison.section_entries]].map(([label, content, sectionEntries]) =>
        h("div", { key: label }, h("h3", null, label), item.media === "txt" ? h("pre", null, content) : h(ExternalDocument, { controller, item, content, sectionEntries, title: label })))),
      button("비교 닫기", () => controller.update({ panel: "" })));
    return null;
  };
  return h("div", { className: `authoring-shell${dock.active && view.dockMax ? " dock-max" : ""}`, ref: root, onKeyDown: shellInput.current.key = (event: any) => {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    const shortcut = shellShortcut(event);
    if (!shortcut) return;
    if (shortcut === "context-menu") {
      const target = event.target as HTMLElement;
      if (!item || !target.closest?.(".authoring-outline,.authoring-canvas")) return;
      const rect = target.getBoundingClientRect();
      event.preventDefault();
      openContextMenu(controller, { clientX: rect.left, clientY: rect.bottom, target }, root.current);
      return;
    }
    if (shortcut !== "escape") event.preventDefault();
    if (shortcut === "save") act(() => controller.save())();
    else if (shortcut === "search") controller.update({ panel: "search" });
    else if (shortcut === "editor-search") act(() => controller.command("search"))();
    else if (shortcut === "commands") controller.update({ panel: "commands" });
    else if (shortcut === "rename") rename();
    else if (shortcut === "undo" || shortcut === "redo") act(() => controller.command(shortcut))();
    else if (shortcut === "escape") { if (escapeShell(controller) === "panel") act(controller.focusSelection)(); }
    else if (shortcut === "cycle") {
      // 패널 간 초점 이동(§10): 그려진 패널만 돌고, 접힌 구조는 레일 버튼이 대신 선다(authoring_layout.ts).
      cyclePanels([...(root.current?.querySelectorAll<HTMLElement>(PANEL_CYCLE) || [])], document.activeElement, !!event.shiftKey);
    }
  } },
    h("header", { className: "authoring-head" },
      button("돌아가기", act(() => controller.leaveTo(controller.returnScreen()))),
      h("h1", null, "템플릿 저작"),
      button("문서 열기", act(controller.openFile)), button("새 TXT", act(controller.create)),
      button("저장", act(() => controller.save()), { disabled: !item }),
      button("다른 이름으로 저장", act(() => controller.save(item?.id, true)), { disabled: !item })),
    h("div", { className: "authoring-tabs", role: "tablist", "aria-label": "열린 문서" }, ...tabs.map((tab) => h("div", { key: tab.id, className: "authoring-tab" },
      button(`${tab.name}${tab.dirty || controller.pending(tab.id) ? " ·" : ""}`, act(() => controller.activate(tab.id)), { role: "tab", "aria-selected": tab.id === snapshot.active_id }),
      button("닫기", act(() => controller.close(tab.id)), { "aria-label": `${tab.name} 닫기` })))),
    view.error && h("div", { role: "alert", className: "authoring-error" }, view.error),
    // 저장 결과의 알림(AC14·P09) — Python 이 준 문장만 보이고, 다음 편집에서 사라진다.
    view.notice && h("p", { role: "status", className: "authoring-notice" }, view.notice),
    // 호환성 경고(U01·§7.1·P16): Python 판정이 서는 즉시 편집기 마운트와 무관하게 보이고, 마운트가 무너져도 남는다.
    // 원본은 그대로 둔 채 확인(원문 표기)하거나 다른 이름으로 사본을 남기는 길을 함께 세운다.
    item?.compatibility?.state === "limited" && h("section", { className: "authoring-compat", role: "alert", "aria-label": "호환성 경고" },
      h("strong", null, "읽기 전용 · 보존 확인 필요"),
      item.compatibility.message && h("p", null, item.compatibility.message),
      ...(item.compatibility.diagnostics || []).map((diagnostic: Obj | string, index: number) => typeof diagnostic === "string" ? h("p", { key: index }, diagnostic)
        : h("div", { key: index }, h("p", null, diagnostic.message), diagnostic.detail && h("p", { className: "authoring-reason" }, diagnostic.detail))),
      h("div", null, button("다른 이름으로 저장", act(() => controller.save(item.id, true))), button("원문 표기", act(controller.raw)))),
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
          button("복구", act(() => controller.recover(draft.key)), { disabled: !!draft.error }), button("폐기", act(() => controller.discardRecovery(draft.key)))))))),
    // 도구 막대(§3.1): 한 줄, 줄바꿈 없음 — 넘치면 가로 스크롤. 보조 패널을 여는 동사는 하단 독의 탭으로 옮겼다.
    item && h("div", { className: "authoring-toolbar", role: "toolbar", "aria-label": "문서 명령" },
      h("div", { className: "authoring-toolbar-group" },
        button(`문서 실행 취소${view.lastCommandLabel ? `: ${view.lastCommandLabel}` : ""}`, act(() => controller.command("undo")), { disabled: editorState ? !editorState.canUndo : false }),
        button("문서 다시 실행", act(() => controller.command("redo")), { disabled: editorState ? !editorState.canRedo : false })),
      h("div", { className: "authoring-toolbar-group" }, h("div", { className: "authoring-mode", role: "group", "aria-label": "표시" },
        ...MODES.map(([value, label]) => h("button", { key: value, type: "button", value, "aria-pressed": view.mode === value, onClick: () => controller.setMode(value) }, label)))),
      h("div", { className: "authoring-toolbar-group" },
        ...COMMANDS.slice(0, 3).map(([commandType, label]) => { const available = commandAvailability(view.commands, commandType); const disabled = readOnly || !available.enabled;
          return button(label, () => controller.update({ panel: "properties", commandType, preview: null, refusal: null }), { key: commandType, disabled, "aria-disabled": disabled || undefined, title: available.reason || undefined }); })),
      h("div", { className: "authoring-toolbar-group" },
        button("명령", () => controller.update({ panel: "commands" })),
        h("button", { type: "button", className: "btn sm", "aria-haspopup": "menu", "aria-expanded": view.contextMenu?.kind === "more",
          onClick: (event: any) => { if (view.contextMenu?.kind === "more") { controller.update({ contextMenu: null }); return; }
            const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
            openContextMenu(controller, { clientX: rect.left, clientY: rect.bottom, target: event.currentTarget }, root.current, "more"); } }, "더보기")),
      h("div", { className: "authoring-toolbar-group authoring-toolbar-end" },
        button("결과 시험", () => { if (trialShown) controller.update({ trial: false, dock: "" }); else openDock("trial"); }, { "aria-pressed": trialShown }),
        h("select", { className: "field", "aria-label": "확대", value: view.zoom, onChange: (event: any) => controller.update({ zoom: Number(event.target.value) }) }, ...[75,100,125,150,200].map((value) => h("option", { key: value, value }, `${value}%`))))),
    tabs.length > 0 && h("div", { className: `authoring-body${view.panel === "properties" ? " with-properties" : ""}${outlineOpen ? " outline-open" : ""}` },
      item && h("button", { type: "button", className: "authoring-rail-toggle", "aria-expanded": outlineOpen, onClick: () => setOutlineOpen(!outlineOpen) }, outlineOpen ? "구조 패널 숨기기" : "구조 패널 보기"),
      item && h("aside", { className: "authoring-outline", "aria-label": "템플릿 구조", onContextMenu: (event: any) => contextMenu(event) }, h("h2", null, "템플릿 구조"),
        ...(item.analysis?.slots || []).map((slot: Obj) => { const slotEntry = { ...slot, ...slot.location, kind: "slot", slot_id: slot.id }; return h("details", { open: true, key: slot.id },
          h("summary", null, button([kindTag("slot"), slot.label || slot.id, badge(counts.get(slot.id) || 0)], select(slotEntry), { "aria-label": outlineLabel("slot", slot, counts.get(slot.id) || 0), onContextMenu: (event: any) => { event.stopPropagation(); contextMenu(event, slotEntry); } })),
          ...(slot.options || []).map((option: Obj) => { const optionEntry = { ...option, ...option.location, kind: "option", slot_id: slot.id, option_id: option.id };
            return button([kindTag("option"), option.label || option.id, badge(counts.get(option.id) || 0)], select(optionEntry), { key: option.id, "aria-label": outlineLabel("option", option, counts.get(option.id) || 0, slot.label || slot.id), onContextMenu: (event: any) => { event.stopPropagation(); contextMenu(event, optionEntry); } }); })); }),
        h("h2", null, "필드"), ...(item.analysis?.fields || []).map((field: Obj) => { const fieldEntry = { ...field, kind: "field" }; return h(LazyDetails, { key: field.name,
          summary: h("summary", null, button([`${field.name} · ${field.count}`, badge(counts.get(field.name) || 0)], select(fieldEntry), { "aria-label": outlineLabel("field", field, counts.get(field.name) || 0), onContextMenu: (event: any) => { event.stopPropagation(); contextMenu(event, fieldEntry); } })),
          body: () => (field.occurrences || []).map((occ: Obj, index: number) => { const occEntry = { ...occ, name: field.name, kind: "field" };
            return button(`${index + 1}. ${occ.context || field.name}`, select(occEntry), { key: index, "aria-label": outlineLabel("occurrence", { name: field.name, index: index + 1, total: field.occurrences.length, context: occ.context }), onContextMenu: (event: any) => { event.stopPropagation(); contextMenu(event, occEntry); } }); }) }); })),
      item && h(PanelSplitter, { panel: "outline", label: "구조 패널 너비", layout }),
      // 가운데 열: 현재 위치의 의미(한 줄 경로) 바로 아래에 문서 편집면이 선다. 줄은 항상 자리를 지켜 캐럿 이동에 편집면이 밀리지 않는다.
      h("div", { className: "authoring-center" },
        item && h("div", { className: "authoring-selection", role: "group", "aria-label": "현재 위치의 의미" },
          h("span", { className: "authoring-selection-label", "aria-hidden": true }, "현재 위치의 의미"),
          ...(view.matches || []).map((match: Obj, index: number) => button(`${({ field: "필드", slot: "항목", option: "선택" } as Obj)[match.kind]} · ${match.name || match.label || match.option_id || match.slot_id}${match.approximate ? " · 문단 내 후보" : ""}`, select(match), { key: index }))),
        h("main", { className: "authoring-canvas", "aria-label": "원문 편집", style: { zoom: view.zoom / 100 }, onContextMenu: shellInput.current.menu = (event: any) => contextMenu(event) }, ...tabs.map((tab) => h(DocumentEditor, { key: `${tab.id}:${controller.editorGeneration(tab.id)}`, item: tab, active: tab.id === snapshot.active_id, controller, shell: shellInput })))),
      item && view.panel === "properties" && h(PanelSplitter, { panel: "properties", label: "속성 패널 너비", layout }),
      item && view.panel === "properties" && h(SemanticForm, { key: item.id, controller, selected: view.selected, selection: view.selection, preview: view.preview }),
      // 좁은 폭의 속성 시트 뒤 가림막 — 누르면 「닫기」와 같은 일을 한다(넓은 폭에서는 CSS 가 숨긴다).
      item && view.panel === "properties" && h("div", { className: "authoring-scrim", "aria-hidden": true,
        onClick: () => { controller.update({ panel: "", preview: null, refusal: null }); void controller.guarded(controller.focusSelection); } })),
    // 하단 독(§3.1): 보조 패널은 한 번에 한 탭만 보인다. 탭 줄은 늘 남아 닫은 뒤에도 다시 열 길이 된다.
    (item || view.recoveryPreview) && h("section", { className: `authoring-dock${dock.active ? " open" : ""}`, role: "region", "aria-label": "보조 패널" },
      h("div", { className: "authoring-dock-bar" },
        h("div", { className: "authoring-dock-tabs", role: "tablist", "aria-label": "보조 패널" }, ...dock.tabs.map(([key, label]) => {
          const count = key === "problems" ? item?.problems?.length || 0 : 0;
          return h("button", { key, type: "button", role: "tab", id: `authoring-dock-tab-${key}`, className: "authoring-dock-tab", "aria-selected": key === dock.active,
            "aria-controls": key === dock.active ? "authoring-dock-panel" : undefined, onClick: () => openDock(key) },
            label, count ? " " : null, count ? h("span", { className: "authoring-badge" }, String(count)) : null);
        })),
        dock.active && h("div", { className: "authoring-dock-actions" },
          button(view.dockMax ? "복원" : "최대화", () => controller.update({ dockMax: !view.dockMax })),
          button("닫기", closeDock))),
      dock.active && h("div", { className: "authoring-dock-panel", id: "authoring-dock-panel", role: "tabpanel", "aria-labelledby": `authoring-dock-tab-${dock.active}` }, dockContent(dock.active))),
    item && view.contextMenu && h("div", { className: "authoring-context-menu", role: "menu", "aria-label": view.contextMenu.kind === "more" ? "더보기" : "문맥 명령", style: { left: view.contextMenu.x, top: view.contextMenu.y } },
      view.contextMenu.kind === "more"
        ? moreActions.map(([label, run, disabled]) => h("div", { key: label, className: "authoring-command", role: "none" },
          button(label, () => { (view.contextMenu.trigger as HTMLElement | undefined)?.focus?.(); controller.update({ contextMenu: null }); run(); }, { role: "menuitem", disabled })))
        : h(CommandList, { controller, view, readOnly, menu: true })),
    item && h("footer", { className: "authoring-status", role: "status" },
      // 왼쪽: 저장·준비와 구조 검사. 오른쪽: 보존·복원·시험·복구 초안. 구분선은 CSS 가 그린다(글자가 아니다).
      h("div", { className: "authoring-status-group" },
        // 저장·검사·시험은 서로 다른 상태다(P09·§9.1): 저장됨 뒤에 Python 의 readiness(초안/사용 준비)를 붙인다.
        h("span", null, view.saveFailed ? "저장 실패" : controller.pending(item.id) ? "편집 내용 반영 중" : item.save_as_required ? "새 템플릿 저장 필요" : item.dirty ? "저장하지 않은 변경"
          : item.readiness?.state === "ready" ? "저장됨 · 사용 준비" : item.readiness?.state === "draft" ? "저장됨 · 초안" : "저장됨"),
        // 구조 오류가 있으면 Python 의 준비 문장(readiness.message)을, 없으면 개수를 보인다.
        h("span", null, item.readiness?.message || `구조 오류 ${item.readiness?.errors ?? 0}개 · 경고 ${item.readiness?.warnings ?? 0}개`)),
      h("div", { className: "authoring-status-group authoring-status-end" },
        // 준비 상태 옆의 보존 판정 칩 — Python 의 compatibility.state 를 이름으로 옮길 뿐이다(마운트 전에도 선다).
        item.compatibility?.state === "checking" && h("span", { "data-compat": "checking" }, "보존 확인 중"),
        item.compatibility?.state === "limited" && h("span", { "data-compat": "limited" }, "읽기 전용 · 보존 확인 필요"),
        item.restore?.message && h("span", { "data-restore": item.restore.state }, item.restore.message),
        // 결과 시험 상태는 상태마다 한 표현이다 — Python 의 trial_state_label 그대로(P09·§9.1).
        item.trial_state_label && h("span", { "data-trial": item.trial_state }, item.trial_state_label),
        h("span", null, item.cases_dirty ? "시험 자료: 저장하지 않은 변경" : item.cases?.length ? "시험 자료: 로컬 보관" : "시험 자료 없음"),
        item.recovery_saved_at && h("span", null, "복구 초안 저장됨 · ", h("time", { dateTime: item.recovery_saved_at }, new Date(item.recovery_saved_at).toLocaleTimeString())),
        item.recovery && h("span", null, "복구 여부 선택 필요"))),
  );
}
