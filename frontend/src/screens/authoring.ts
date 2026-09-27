import { createElement as h, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { mountLintpad, disposeLintpad, updateLintpad, editLintpad, lintpadState, lintpadCommand, navigateLintpad } from "../editorview/txt_lintpad.ts";
import { mountRhwp } from "../editorview/rhwp_editor.ts";
import { COMMANDS } from "./authoring_controller.ts";
import type { AuthoringController, AuthoringEditor } from "./authoring_controller.ts";
import { TPL_STATUS_COPY } from "./job_run.ts";

/** IME 조합 중에는 문서 명령을 보내지 않는다 — 조합이 끝난 뒤 같은 명령을 다시 받는다. */
const IME_BUSY = "한글 조합을 마친 뒤 다시 실행하세요.";

type Obj = Record<string, any>;
type Props = { controller: AuthoringController };
const button = (label: ReactNode | ReactNode[], click: () => void, props: Obj = {}) =>
  h("button", { type: "button", className: "btn sm", onClick: click, ...props }, ...(Array.isArray(label) ? label : [label]));
const KIND_LABEL: Obj = { field: "필드", slot: "항목", option: "선택" };
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
const badge = (count: number): ReactNode => count ? h("span", { className: "authoring-badge" }, `문제 ${count}`) : null;
/** 문제의 다음 행동(§7.2): navigate 는 그 위치로 선택을 옮기고, command 는 Python 이 준 명령을 미리보기로 보낸다. */
export function problemAction(controller: Pick<AuthoringController, "select" | "preview">, item: Obj, problem: Obj, action: Obj): Promise<void> {
  return action.kind === "command" ? controller.preview(action.command) : controller.select({ source_revision: item.revision, ...(problem.location || {}), target: problem.target });
}

type MenuEvent = { clientX: number; clientY: number; target?: unknown; preventDefault?(): void };
/** 문맥 메뉴를 좌표(셸 기준)에 연다(§6.1). trigger 는 닫힐 때 초점을 돌려줄 자리다. */
export function openContextMenu(controller: Pick<AuthoringController, "update">, event: MenuEvent, root?: { getBoundingClientRect(): { left: number; top: number } } | null): void {
  event.preventDefault?.();
  const rect = root?.getBoundingClientRect();
  controller.update({ contextMenu: { x: event.clientX - (rect?.left || 0), y: event.clientY - (rect?.top || 0), trigger: event.target } });
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
  return COMMANDS.map(([commandType, label]) => {
    const available = commandAvailability(view.commands, commandType);
    const disabled = readOnly || !available.enabled;
    return h("div", { key: commandType, className: "authoring-command", role: menu ? "none" : undefined },
      button(label, () => pick(commandType), { role: menu ? "menuitem" : undefined, disabled, "aria-disabled": disabled || undefined, title: available.reason || undefined }),
      !available.enabled && available.reason && h("p", { className: "authoring-reason" }, available.reason),
      !available.enabled && available.alternative && button(available.alternative.label, () => pick(available.alternative!.command_type)));
  });
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

/** 읽기 전용 HWPX 비교 뷰의 마운트 인자(host·콜백 제외). 본문 차례는 Python 이 그 내용에서 셈해 준 것을 그대로 넘긴다. */
export function externalDocumentSpec(item: Obj, content: string, sectionEntries?: string[]) {
  return { content, fileName: String(item.name || ""), readOnly: true as const, sectionEntries };
}

function ExternalDocument({ controller, item, content, sectionEntries }: Props & { item: Obj; content: string; sectionEntries?: string[] }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let disposed = false;
    let release: (() => void) | undefined;
    void controller.guarded(async () => {
      const handle = await mountRhwp({ host: host.current!, ...externalDocumentSpec(item, content, sectionEntries),
        onChanged: () => {}, onSelectionChanged: () => {}, onError: (error) => controller.update({ error: String(error) }) });
      if (disposed) handle.dispose(); else release = () => handle.dispose();
    });
    return () => { disposed = true; release?.(); };
  }, [content]);
  return h("div", { ref: host, className: "authoring-result-pages" });
}

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
/** 속성 제출 — 한글 조합 중 Enter 는 확정이 아니다(§6.2·§10). 보냈으면 true. */
export function submitProperties(controller: Pick<AuthoringController, "guarded" | "preview">, composing: boolean, command: () => Obj): boolean {
  if (composing) return false;
  void controller.guarded(() => controller.preview(command()));
  return true;
}

function DocumentEditor({ controller, item, active }: Props & { item: Obj; active: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const [compatibility, setCompatibility] = useState<Obj | null>(null);
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
        const handle = await mountRhwp({ host: host.current, content: initial.content, fileName: item.name,
          sectionEntries: initial.section_entries,
          preflight: async (content) => {
            const result = await controller.preflight(item.id, initial.revision, content);
            return { editable: result.editable, diagnostics: result.diagnostics };
          },
          onCompatibility: setCompatibility,
          onShortcut: (shortcut) => {
            const current = controller.viewModel.getSnapshot();
            if (shortcut === "CtrlShiftP") controller.update({ panel: "commands" });
            else if (shortcut === "CtrlS") void controller.guarded(() => controller.save());
            else if (shortcut === "CtrlF") controller.update({ panel: "search" });
            else controller.update({ panel: "properties", commandType: current.selected?.kind === "field" ? "rename_field" : current.selected?.kind === "option" ? "rename_option" : "rename_slot" });
          },
          onChanged: (content) => controller.changed(item.id, content),
          onSelectionChanged: (selection) => controller.selection(item.id, selection),
          onError: (error) => controller.update({ error: String(error) }), readOnly: false });
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
  useEffect(() => { adapter.current?.decorate(item.analysis || {}, controller.mode(item.id)); }, [item.analysis, active]);
  return h("div", { className: "authoring-document", hidden: !active, inert: !active || !!item.recovery, "aria-hidden": !active },
    compatibility && !compatibility.editable && h("div", { className: "authoring-error", role: "alert" },
      h("strong", null, "읽기 전용 · 보존 확인 필요"),
      ...(compatibility.diagnostics || []).map((diagnostic: Obj | string, index: number) => h("p", { key: index }, typeof diagnostic === "string" ? diagnostic : diagnostic.message))),
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
  const field = (label: string, value: string, onChange: (value: string) => void) => h("label", { className: "authoring-field" }, label,
      h("input", { className: "field", value, ref: label.includes("이름") ? nameInput : undefined, list: label === "필드 이름" ? "authoring-existing-fields" : undefined, onChange: (event: any) => onChange(event.target.value) }));
  return h("form", { className: "authoring-properties", onCompositionStart: () => { composing.current = true; }, onCompositionEnd: () => { composing.current = false; },
    onSubmit: (event: any) => { event.preventDefault(); submitProperties(controller, composing.current, command); },
    // Escape 1단계: 입력창의 작성 중인 값만 적용값으로 되돌린다. 2단계(되돌릴 것이 없을 때)는 셸이 패널을 닫고 선택으로 돌아간다.
    onKeyDown: (event: any) => {
      if (event.key !== "Escape" || event.nativeEvent?.isComposing) return;
      if (escapeStage(selected, { name, identifier, parent, text }) === "revert") { event.stopPropagation(); revert(); }
    } },
    h("h2", null, "속성"),
    selected && h("p", null, selected.name || selected.label || selected.id),
    h("label", { className: "authoring-field" }, "명령", h("select", { className: "field", value: type, "aria-disabled": !available.enabled || undefined, title: available.reason || undefined, onChange: (event: any) => switchType(event.target.value) },
      ...COMMANDS.map(([value, label]) => { const entry = commandAvailability(view.commands, value); return h("option", { key: value, value, disabled: !entry.enabled, title: entry.reason || undefined }, label); }))),
    // 비활성 사유와 대안은 Python 의 판정을 그대로 보인다(P07) — 툴팁만이 유일한 경로가 되지 않도록 본문에도 선다(§10).
    !available.enabled && available.reason && h("p", { className: "authoring-reason", role: "status" }, available.reason),
    !available.enabled && available.alternative && button(available.alternative.label, () => switchType(available.alternative!.command_type)),
    h("p", { className: "authoring-context" }, `${selected?.slot_id || view.context?.slot_id || "문서"}${selected?.option_id || view.context?.option_id ? ` / ${selected?.option_id || view.context?.option_id}` : ""}${selection.start != null ? ` · ${selection.start}–${selection.end ?? selection.start}` : ""}`),
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
      // 미리보기는 보낸 명령(view.command)의 것이다 — 문장의 새 이름도 그 명령에서 읽는다.
      type === "rename_field" ? h("p", null, `현재 문서의 사용 위치 ${affected}곳이 ‘${view.command?.name || name}’으로 변경됩니다.`) : h("p", null, `사용 위치 ${affected}곳`),
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
        if (type === "create_field" && keepValue && name && captured) {
          const current = controller.viewModel.getSnapshot();
          if (!(name in current.values)) await controller.trialInput({ ...current.values, [name]: captured }, current.selectedOptions);
        }
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
      const editor = await mountRhwp({ host: output.current!, content: result.content, fileName: "시험 결과.hwpx", readOnly: true,
        sectionEntries: result.section_entries,
        onChanged: () => {}, onSelectionChanged: (target) => controller.update({ resultSelection: target }),
        onError: (error) => controller.update({ error: String(error) }) });
      if (disposed) editor.dispose(); else release = () => editor.dispose();
    });
    return () => { disposed = true; release?.(); };
  }, [result]);
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
      h("p", { role: "status" }, view.trialBusy ? "갱신 중 · 이전 결과" : ({ current: "현재 시험 구성 통과", failed: item.trial_error || "시험 실패", untried: "아직 시험하지 않았습니다.", stale: "마지막 시험 이후 문서 또는 입력이 바뀌었습니다." } as Obj)[item.trial_state]),
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

export function AuthoringScreen({ controller }: Props): ReactNode {
  const snapshot = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot) || {};
  const view = useSyncExternalStore(controller.viewModel.subscribe, controller.viewModel.getSnapshot, controller.viewModel.getSnapshot);
  const tabs: Obj[] = snapshot.tabs || [];
  const item = tabs.find((tab) => tab.id === snapshot.active_id);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    root.current?.querySelector<HTMLElement>(view.panel === "properties" ? ".authoring-properties input" : view.panel === "search" ? '[name="query"]' : view.panel === "commands" || view.panel === "external" ? ".authoring-bottom button" : ".authoring-shell-placeholder")?.focus();
  }, [view.panel, view.commandType]);
  useEffect(() => {
    const focus = () => { void controller.guarded(controller.checkExternal); };
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [controller]);
  // 문맥 메뉴(§6.1): 열리면 첫 활성 항목에 초점, 바깥 클릭이면 닫는다. Escape 는 셸 단축키가 처리한다.
  useEffect(() => {
    if (!view.contextMenu) return;
    root.current?.querySelector<HTMLElement>('[role="menu"] [role="menuitem"]:not([disabled])')?.focus();
    const outside = (event: MouseEvent) => { if (!(event.target as Element | null)?.closest?.('[role="menu"]')) controller.update({ contextMenu: null }); };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [view.contextMenu]);
  const act = (work: () => unknown) => () => { void controller.guarded(work); };
  const select = (entry: Obj) => act(() => controller.select({ source_revision: item?.revision, ...entry }));
  const contextMenu = (event: any, entry?: Obj) => { if (entry) select(entry)(); openContextMenu(controller, event, root.current); };
  const editorState = item ? controller.editorState(item.id) : null;
  const readOnly = !!item && item.media === "hwpx" && item.rhwp_editable !== true;
  const rename = () => controller.update({ panel: "properties", commandType: view.selected?.kind === "field" ? "rename_field" : view.selected?.kind === "option" ? "rename_option" : "rename_slot" });
  return h("div", { className: "authoring-shell", ref: root, onKeyDown: (event: any) => {
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
      const panels = [...(root.current?.querySelectorAll<HTMLElement>(".authoring-outline,.authoring-canvas,.authoring-properties,.authoring-bottom") || [])];
      const current = panels.findIndex((panel) => panel.contains(document.activeElement));
      panels[(current + (event.shiftKey ? panels.length - 1 : 1)) % panels.length]?.querySelector<HTMLElement>("button,input,select,textarea,[contenteditable],iframe")?.focus();
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
    item?.recovery && h("section", { className: "authoring-bottom", role: "alert" }, h("h2", null, "중단 전 복구 초안"),
      h("p", null, "복구 여부를 선택한 뒤 편집을 계속하세요. 원본 파일은 아직 변경하지 않았습니다."),
      button("초안과 원본 비교", act(() => controller.compareRecovery(item.recovery_key))),
      button("복구", act(() => controller.recover(item.id))), button("폐기", act(() => controller.discardRecovery(item.id)))),
    !item && h("div", { className: "authoring-empty" }, h("p", null, "변경할 문구를 선택해 필드로 만들어 보세요."),
      ...(snapshot.recoverable || []).map((draft: Obj) => h("div", { key: draft.key }, draft.name || draft.path || "저장하지 않은 초안",
        draft.updated_at && h("time", { dateTime: draft.updated_at }, new Date(draft.updated_at).toLocaleString()),
        draft.error && h("p", { role: "alert" }, draft.error),
        button("초안과 원본 비교", act(() => controller.compareRecovery(draft.key)), { disabled: !!draft.error }),
        button("복구", act(() => controller.recover(draft.key)), { disabled: !!draft.error }), button("폐기", act(() => controller.discardRecovery(draft.key)))))),
    view.recoveryPreview && h("section", { className: "authoring-bottom" }, h("h2", null, "초안과 원본 비교"),
      h("div", { className: "authoring-compare" }, ...[["원본", view.recoveryPreview.original_content], ["복구 초안", view.recoveryPreview.content]].map(([name, content]) => h("div", { key: name }, h("h3", null, name),
        content == null ? h("p", null, "원본 파일 없음") : view.recoveryPreview.media === "txt" ? h("pre", null, content)
          : h(ExternalDocument, { controller, item: { name }, content, sectionEntries: name === "원본" ? view.recoveryPreview.original_section_entries : view.recoveryPreview.section_entries })))),
      button("복구", act(() => controller.recover(item?.recovery ? item.id : view.recoveryPreview.key))), button("비교 닫기", () => controller.update({ recoveryPreview: null }))),
    item && h("div", { className: "authoring-toolbar", "aria-label": "문서 명령" },
      button(`문서 실행 취소${view.lastCommandLabel ? `: ${view.lastCommandLabel}` : ""}`, act(() => controller.command("undo")), { disabled: editorState ? !editorState.canUndo : false }),
      button("문서 다시 실행", act(() => controller.command("redo")), { disabled: editorState ? !editorState.canRedo : false }),
      h("label", null, "표시 ", h("select", { className: "field", value: view.mode, onChange: (event: any) => controller.setMode(event.target.value) },
        h("option", { value: "document" }, "문서"), h("option", { value: "template" }, "템플릿"), h("option", { value: "structure" }, "구조"))),
      ...COMMANDS.slice(0, 3).map(([commandType, label]) => { const available = commandAvailability(view.commands, commandType); const disabled = readOnly || !available.enabled;
        return button(label, () => controller.update({ panel: "properties", commandType, preview: null, refusal: null }), { key: commandType, disabled, "aria-disabled": disabled || undefined, title: available.reason || undefined }); }),
      button("명령", () => controller.update({ panel: "commands" })),
      button("의미 복사", act(controller.copy)), button("붙여넣기", () => controller.update({ panel: "paste" }), { disabled: !controller.clipboard() }),
      button("검색", () => controller.update({ panel: "search" })), button("문제", () => controller.update({ panel: "problems" })),
      button("원문 표기", act(controller.raw)), button("변경 영향·작업 적용", act(controller.impact)),
      button("이전 위치로", act(controller.back)), button("결과 시험", () => controller.update({ trial: !view.trial })),
      h("label", null, "확대 ", h("select", { className: "field", value: view.zoom, onChange: (event: any) => controller.update({ zoom: Number(event.target.value) }) }, ...[75,100,125,150,200].map((value) => h("option", { key: value, value }, `${value}%`))))),
    h("div", { className: `authoring-body${view.panel === "properties" ? " with-properties" : ""}` },
      item && h("aside", { className: "authoring-outline", "aria-label": "템플릿 구조", onContextMenu: (event: any) => contextMenu(event) }, h("h2", null, "템플릿 구조"),
        ...(item.analysis?.slots || []).map((slot: Obj) => { const slotEntry = { ...slot, ...slot.location, kind: "slot", slot_id: slot.id }; return h("details", { open: true, key: slot.id },
          h("summary", null, button([slot.label || slot.id, badge(problemCount(item.problems, slot.id))], select(slotEntry), { onContextMenu: (event: any) => { event.stopPropagation(); contextMenu(event, slotEntry); } })),
          ...(slot.options || []).map((option: Obj) => { const optionEntry = { ...option, ...option.location, kind: "option", slot_id: slot.id, option_id: option.id };
            return button([option.label || option.id, badge(problemCount(item.problems, option.id))], select(optionEntry), { key: option.id, onContextMenu: (event: any) => { event.stopPropagation(); contextMenu(event, optionEntry); } }); })); }),
        h("h2", null, "필드"), ...(item.analysis?.fields || []).map((field: Obj) => { const fieldEntry = { ...field, kind: "field" }; return h("details", { key: field.name },
          h("summary", null, button([`${field.name} · ${field.count}`, badge(problemCount(item.problems, field.name))], select(fieldEntry), { onContextMenu: (event: any) => { event.stopPropagation(); contextMenu(event, fieldEntry); } })),
          ...(field.occurrences || []).map((occ: Obj, index: number) => { const occEntry = { ...occ, name: field.name, kind: "field" };
            return button(`${index + 1}. ${occ.context || field.name}`, select(occEntry), { key: index, onContextMenu: (event: any) => { event.stopPropagation(); contextMenu(event, occEntry); } }); })); })),
      h("main", { className: "authoring-canvas", "aria-label": "원문 편집", style: { zoom: view.zoom / 100 }, onContextMenu: (event: any) => contextMenu(event) }, ...tabs.map((tab) => h(DocumentEditor, { key: `${tab.id}:${controller.editorGeneration(tab.id)}`, item: tab, active: tab.id === snapshot.active_id, controller }))),
      item && view.panel === "properties" && h(SemanticForm, { key: item.id, controller, selected: view.selected, selection: view.selection, preview: view.preview })),
    item && view.contextMenu && h("div", { className: "authoring-context-menu", role: "menu", "aria-label": "문맥 명령", style: { left: view.contextMenu.x, top: view.contextMenu.y } },
      h(CommandList, { controller, view, readOnly, menu: true })),
    item && !!view.matches?.length && h("div", { className: "authoring-selection", "aria-label": "현재 위치의 의미" },
      ...view.matches.map((match: Obj, index: number) => button(`${({ field: "필드", slot: "항목", option: "선택" } as Obj)[match.kind]} · ${match.name || match.label || match.option_id || match.slot_id}${match.approximate ? " · 문단 내 후보" : ""}`, select(match), { key: index }))),
    item && view.trial && h(Trial, { controller, item, view }),
    item && view.panel === "paste" && h("section", { className: "authoring-bottom" }, h("h2", null, "의미 붙여넣기"),
      h("p", null, "문서에서 붙여넣을 위치를 선택하세요. 같은 이름의 필드 연결과 새 식별자를 확인한 뒤 적용합니다."),
      h("form", { onSubmit: (event: any) => { event.preventDefault(); const data = new FormData(event.currentTarget); act(() => controller.paste(data.has("meaning"), String(data.get("new_id") || ""), data.has("link_existing")))(); } },
        h("label", null, h("input", { type: "checkbox", name: "meaning", defaultChecked: true }), "의미 포함"),
        h("label", null, h("input", { type: "checkbox", name: "link_existing" }), "같은 이름의 기존 필드에 연결"),
        h("label", null, "새 연결 식별자 ", h("input", { name: "new_id", className: "field" })),
        h("button", { className: "btn sm", disabled: !controller.clipboard() }, "붙여넣기 미리보기")),
      view.command?.type === "paste" && view.preview && h("div", { className: "authoring-preview" },
        h("pre", { "aria-label": "변경 전" }, view.preview.before), h("pre", { "aria-label": "변경 후" }, view.preview.after),
        button("붙여넣기 적용", act(controller.applyPreview)), button("취소", () => controller.update({ preview: null })))),
    item && view.panel === "search" && h("section", { className: "authoring-bottom" }, h("h2", null, "검색"),
      h("form", { onSubmit: (event: any) => { event.preventDefault(); const values = new FormData(event.currentTarget); act(() => controller.search(String(values.get("query")), String(values.get("kind")), values.has("all")))(); } },
        h("input", { className: "field", name: "query", "aria-label": "검색어", defaultValue: view.query }),
        h("select", { className: "field", name: "kind", "aria-label": "검색 대상" }, h("option", { value: "body" }, "본문"), h("option", { value: "field" }, "필드"), h("option", { value: "structure" }, "항목·선택"), h("option", { value: "all" }, "전체")),
        h("label", null, h("input", { type: "checkbox", name: "all" }), "열린 모든 문서"), h("button", { className: "btn sm" }, "찾기")),
      ...view.hits.map((hit: Obj, index: number) => button(`${hit.document} · ${hit.context || hit.name || hit.label}`, select(hit), { key: index }))),
    item && view.panel === "commands" && h("section", { className: "authoring-bottom", "aria-label": "명령 팔레트" }, h("h2", null, "명령"),
      h(CommandList, { controller, view, readOnly })),
    // 원문 표기(F26·UI09): Python 이 지은 문법 표현을 본문 항목별로 읽기 전용으로 보인다.
    item && view.panel === "raw" && h("section", { className: "authoring-bottom", "aria-label": "원문 표기" }, h("h2", null, "원문 표기"),
      view.syntax?.note && h("p", null, view.syntax.note),
      ...(view.syntax?.sections || []).map((section: Obj, index: number) => h("div", { key: index, className: "authoring-syntax" },
        h("h3", null, section.entry), h("pre", { tabIndex: 0, "aria-label": `${section.entry} 원문 표기` }, section.text))),
      button("복사", act(() => copyText((view.syntax?.sections || []).map((section: Obj) => section.text).join("\n\n"))), { disabled: !view.syntax?.sections?.length })),
    item && view.panel === "impact" && h("section", { className: "authoring-bottom", "aria-label": "변경 영향·작업 적용" }, h("h2", null, "변경 영향·작업 적용"),
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
        button("기존 작업에 적용", act(controller.confirmJob), { disabled: !view.jobApply.change_token }), button("취소", () => controller.update({ jobApply: null })))),
    // 문제 한 건(§7.2·F24): 심각도·종류는 색이 아닌 글자로(P14), 대상·설명·다음 행동을 Python 의 problems 그대로 보인다.
    item && view.panel === "problems" && h("section", { className: "authoring-bottom", "aria-label": "문제" }, h("h2", null, "문제"),
      !item.problems?.length && h("p", null, "문제 없음"),
      ...(item.problems || []).map((problem: Obj, index: number) => h("div", { key: index, className: "authoring-problem" },
        h("p", null, h("strong", null, SEVERITY_LABEL[problem.severity] || problem.severity), ` · ${CATEGORY_LABEL[problem.category] || problem.category}`, problem.target ? ` · ${problem.target}` : ""),
        h("p", null, problem.message),
        ...(problem.actions || []).map((action: Obj, actionIndex: number) => button(action.label, act(() => problemAction(controller, item, problem, action)), { key: actionIndex })))),
      view.command?.type === "repair_marker" && view.preview && h("div", { className: "authoring-preview" },
        h("h3", null, "수정 제안"), h("pre", { "aria-label": "변경 전" }, view.preview.before), h("pre", { "aria-label": "변경 후" }, view.preview.after),
        button("구조 표기 수정", act(controller.applyPreview)), button("취소", () => controller.update({ preview: null })))),
    item?.external_changed && view.panel !== "external" && h("section", { className: "authoring-bottom", role: "alert" }, h("h2", null, "외부 파일 변경"),
      button("양쪽 내용 확인", act(controller.compareExternal)), button("현재 작업을 다른 이름으로 저장", act(() => controller.save(item.id, true))), button("외부 파일 다시 열기", act(controller.reload))),
    // 저장 실패(AC24·§9.2): 변경은 그대로 남고, 같은 세 복구 동사에 「다시 저장」이 더해진다.
    item && view.panel === "external" && h("section", { className: "authoring-bottom", role: "alert", "aria-label": "저장 실패" }, h("h2", null, "저장 실패"),
      button("양쪽 내용 확인", act(controller.compareExternal)), button("현재 작업을 다른 이름으로 저장", act(() => controller.save(item.id, true))),
      button("외부 파일 다시 열기", act(controller.reload)), button("다시 저장", act(() => controller.save(item.id)))),
    item && view.panel === "comparison" && view.comparison && h("section", { className: "authoring-bottom", "aria-label": "외부 파일 내용" }, h("h2", null, "외부 파일 내용"),
      h("div", { className: "authoring-compare" }, ...[["현재 작업", view.comparison.current_content, view.comparison.current_section_entries], ["외부 파일 내용", view.comparison.content, view.comparison.section_entries]].map(([label, content, sectionEntries]) =>
        h("div", { key: label }, h("h3", null, label), item.media === "txt" ? h("pre", null, content) : h(ExternalDocument, { controller, item, content, sectionEntries })))),
      button("비교 닫기", () => controller.update({ panel: "" }))),
    item && h("footer", { className: "authoring-status", role: "status" },
      // 저장·검사·시험은 서로 다른 상태다(P09·§9.1): 저장됨 뒤에 Python 의 readiness(초안/사용 준비)를 붙인다.
      h("span", null, view.saveFailed ? "저장 실패" : controller.pending(item.id) ? "편집 내용 반영 중" : item.save_as_required ? "새 템플릿 저장 필요" : item.dirty ? "저장하지 않은 변경"
        : item.readiness?.state === "ready" ? "저장됨 · 사용 준비" : item.readiness?.state === "draft" ? "저장됨 · 초안" : "저장됨"),
      h("span", null, `구조 오류 ${item.readiness?.errors ?? 0}개 · 경고 ${item.readiness?.warnings ?? 0}개`),
      h("span", null, item.trial_state === "current" ? "현재 시험 구성 확인됨" : "다시 시험 필요"),
      h("span", null, item.cases_dirty ? "시험 자료: 저장하지 않은 변경" : item.cases?.length ? "시험 자료: 로컬 보관" : "시험 자료 없음"),
      item.recovery_saved_at && h("span", null, "복구 초안 저장됨 · ", h("time", { dateTime: item.recovery_saved_at }, new Date(item.recovery_saved_at).toLocaleTimeString())),
      item.recovery && h("span", null, "복구 여부 선택 필요")),
  );
}
