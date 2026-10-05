import { createElement as h, useEffect, useRef } from "react";
import { mountLintpad, disposeLintpad, updateLintpad, editLintpad, lintpadState, lintpadCommand, navigateLintpad, setLintpadRangePick } from "../editorview/txt_lintpad.ts";
import { mountRhwp } from "../editorview/rhwp_editor.ts";
import type { AuthoringController, AuthoringEditor, Zoom } from "./authoring_controller.ts";
import { focusRequest, renameShortcut } from "./authoring_commands.ts";
import { txtProblemMarks, markerPairs } from "./authoring_outline_model.ts";
import { guideSpans } from "./authoring_guide.ts";
import type { Obj, Props } from "./authoring_primitives.ts";

const IME_BUSY = "한글 조합을 마친 뒤 다시 실행하세요.";

export const rhwpMount = { mount: mountRhwp };
/** 시험 결과 뷰어의 마운트 열쇠 — Python 이 결과 객체마다 새 revision 을 준다. 같은 결과의 재전송(push)은 같은 열쇠라
 *  뷰어를 다시 띄우지 않는다(UX-05). revision 이 없는 옛 투영은 내용 문자열로 가른다. */
export function trialViewerKey(item: Obj): unknown[] {
  return [item.media, item.trial_result?.revision ?? item.trial_result?.content];
}

/** 읽기 전용 HWPX 비교 뷰의 마운트 인자(host·콜백 제외). 본문 차례는 Python 이 그 내용에서 셈해 준 것을 그대로 넘긴다. */
export function externalDocumentSpec(item: Obj, content: string, sectionEntries?: string[]) {
  // 고정 100% 를 명시한다(IDE-06) — 편집면의 폭 맞춤이 Studio 설정에 남아 이 뷰로 번지지 않는다.
  return { content, fileName: String(item.name || ""), readOnly: true as const, sectionEntries, zoom: 100 as const };
}

export function ExternalDocument({ controller, item, content, sectionEntries, title }: Props & { item: Obj; content: string; sectionEntries?: string[]; title?: string }) {
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
/** 편집면 글 한 줄의 호스트 창 좌표(선택 끝 자리) — 편집기가 보고하고 셸은 그 아래에 선택 옆 막대를 세운다(IDE-08). */
export type LineRect = { left: number; top: number; bottom: number };
export type ShellInput = { current: { key?: (event: any) => void; menu?: (event: any) => void; palette?: () => void;
  selectionRect?: (id: string, rect: LineRect | null) => void } };

type ShellKey = { key: string; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean; target?: { closest?(selector: string): unknown } | null };
type ShellAction = "" | "save" | "search" | "editor-search" | "commands" | "rename" | "escape" | "cycle" | "undo" | "redo" | "context-menu";
/** 셸 단축키 판독(§10). 문서 편집면·입력창 안의 Ctrl+Z/Y 는 그 문맥의 실행 취소이므로 셸이 가로채지 않는다(§9.3). */
export function shellShortcut(event: ShellKey): ShellAction {
  const mod = !!(event.ctrlKey || event.metaKey);
  if (mod) return modifierShortcut(event);
  return plainShortcut(event);
}

function modifierShortcut(event: ShellKey): ShellAction {
  const key = String(event.key || "").toLowerCase();
  const inEditor = !!event.target?.closest?.(".authoring-editor-host,.cm-editor,iframe");
  if (key === "s") return "save";
  if (key === "f") return inEditor ? "editor-search" : "search";
  if (event.shiftKey && key === "p") return "commands";
  if (key === "z" || key === "y") return undoShortcut(event, key, inEditor);
  return plainShortcut(event);
}

function undoShortcut(event: ShellKey, key: string, inEditor: boolean): ShellAction {
  const inInput = inEditor || !!event.target?.closest?.("input,textarea,select,[contenteditable]");
  if (inInput) return "";
  return key === "y" || event.shiftKey ? "redo" : "undo";
}

function plainShortcut(event: ShellKey): ShellAction {
  if (event.key === "F2") return "rename";
  if (event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey)) return "context-menu";
  if (event.key === "Escape") return "escape";
  if (event.key === "F6") return "cycle";
  return "";
}

/** 속성 패널의 **적용된** 값 — 선택 대상에서 다시 유도한다. Escape 1단계는 작성 중인 값을 여기로 되돌린다(§6.2).
 *  `proposal` 은 대상에 이름이 없을 때 이름 칸이 여는 값(P-06 Python 제안)이다 — 되돌리면 그 제안으로 돌아간다. */

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

/** 상태 막대 확대 선택(IDE-06 P-13). HWPX 는 「폭 맞춤」이 첫 항목이자 기본값이고 그동안 셸 CSS 배율은 1 이다(Studio 가
 *  쪽 폭을 맞춘다 — 곱하면 이중 배율). TXT 는 숫자 배율만 두고 폭 맞춤 값은 100% 로 읽힌다. */
export const ZOOM_STEPS = [75, 100, 125, 150, 200];
export function zoomChoice(media: string | undefined, zoom: Zoom): { value: string; options: [string, string][]; cssZoom: number } {
  const fit = media === "hwpx";
  const numeric = typeof zoom === "number" ? zoom : 100;
  return { value: fit && zoom === "fit" ? "fit" : String(numeric), cssZoom: zoom === "fit" ? 1 : numeric / 100,
    options: [...(fit ? [["fit", "폭 맞춤"] as [string, string]] : []), ...ZOOM_STEPS.map((step): [string, string] => [String(step), `${step}%`])] };
}

/** 강조 대상의 TXT 범위(UX-09) — 항목·선택은 그 위치(마커 줄 포함), 필드는 사용 위치(index 가 있으면 그 한 곳),
 *  미리보기 범위(IDE-06 P-16, kind "range")는 Python 이 준 실제 포함 범위 그대로다. */
export function highlightRanges(analysis: Obj, highlight: Obj | null | undefined): { start: number; end: number }[] {
  if (!highlight) return [];
  const usable = (place: Obj | null | undefined) => place && typeof place.start === "number" && typeof place.end === "number" ? [{ start: place.start, end: place.end }] : [];
  if (highlight.kind === "range") return usable(highlight.location);
  if (highlight.kind === "slot") return usable((analysis.slots || []).find((slot: Obj) => slot.id === highlight.id)?.location);
  if (highlight.kind === "option") return usable((analysis.slots || []).find((slot: Obj) => slot.id === highlight.slot_id)?.options?.find((option: Obj) => option.id === highlight.id)?.location);
  const field = (analysis.fields || []).find((entry: Obj) => entry.name === highlight.id);
  return (field?.occurrences || []).filter((_: Obj, at: number) => highlight.index == null || highlight.index === at + 1).flatMap(usable);
}

/** 표면이 제 입력을 비교할 뿐이다(판정 아님) — 보인 미리보기의 명령과 지금 입력으로 지은 명령이 같은가. */

export function DocumentEditor({ controller, item, active, shell }: Props & { item: Obj; active: boolean; shell: ShellInput }) {
  const host = useRef<HTMLDivElement>(null);
  const adapter = useRef<AuthoringEditor | null>(null);
  // 장식이 읽는 최신 문제 목록(IDE-05) — TXT 의 문제는 분석과 같은 투영에서 오므로 분석 revision 이 바뀔 때 함께 바뀐다.
  const latest = useRef(item);
  latest.current = item;
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
          // 캐럿이 제안 자리(#1156)에 서면 그 팝오버가 선다 — 판정(locate)과 같은 보고다.
          onSelectionChanged: (selection) => { if (!composing) { controller.selection(item.id, selection); controller.proposal.caret(item.id, selection); } },
          onSelectionRect: (rect) => shell.current.selectionRect?.(item.id, rect),
          onRangePick: (offset) => controller.pickClick(item.id, { entry: "", paragraph: 0, offset, cell: false }),
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
          // TXT 에는 캐럿을 두고 뷰만 옮기는 길이 없다 — 캐럿을 그 자리 머리에 둔다(빈 선택이라 선택 옆 막대는 서지 않는다).
          scrollTo: async (target) => { navigateLintpad(handle, target.start, target.start); return true; },
          rangePick: (state) => setLintpadRangePick(handle, state === false || state === null ? state : state.offset),
          command: async (command) => { lintpadCommand(handle, command); },
          state: () => { const state = lintpadState(handle); return { canUndo: state.canUndo, canRedo: state.canRedo }; },
          decorate: (analysis, mode, highlight) => {
            // 이름표(FB-03)는 모든 표시에서 원문 표기를 대신한다 — 표시 방식은 HWPX 편집면의 labels 어휘다(문서 none·템플릿
            // selected·이름표 all). 항목·선택 범위 막대는 Python 배치(placements) 그대로다.
            // 튜토리얼 범위 단계(#1136)가 고르라고 한 범위 — Python 좌표 그대로 칠한다(판정은 Python 이 한다).
            const guide = controller.guideOf(item.id);
            const spans = guide ? guideSpans(analysis.spans || [], analysis.source_text || "", guide) : [...(analysis.spans || [])];
            // 구조 트리 줄의 강조(UX-09)는 그 범위의 줄 전체에 선다 — 문서 모드에서도(표시만, 본문은 그대로).
            for (const range of highlightRanges(analysis, highlight)) spans.push({ kind: "highlight", ...range });
            // 문제 밑줄(IDE-05)은 별도 층이며 문서 모드에서도 선다(문제는 표시가 아니라 경보다). 표지 짝 강조는 표시라 걷는다.
            updateLintpad(handle, { sourceDoc: analysis.source_text, spans, labels: mode === "document" ? "none" : mode === "structure" ? "all" : "selected",
              regions: analysis.placements || [], problems: txtProblemMarks(latest.current.problems), pairs: mode === "document" ? [] : markerPairs(analysis),
              // 「데이터로 필드 찾기」 제안(#1156)은 본문 표식 층 — 띠가 켜진 동안 모든 표시 방식에서 선다.
              marks: controller.proposal.marks(item.id) });
          },
        };
        release = () => disposeLintpad(handle);
      } else {
        const report = compatibilityReporter(controller, item.id, initial.revision);
        const mountedFit = controller.zoom(item.id) === "fit";
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
          onSelectionChanged: (selection, caret) => { controller.selection(item.id, selection); controller.proposal.caret(item.id, selection, caret); },
          // 캐럿 줄만 옮겨 가면(편집면 스크롤) 문서에서 연 제안 팝오버가 따라가거나 숨는다(#1156).
          onCaretRect: (caret) => controller.proposal.caretRect(item.id, caret),
          onSelectionRect: (rect) => shell.current.selectionRect?.(item.id, rect),
          onRangePick: (point) => controller.pickClick(item.id, point),
          onError: (error) => controller.fail(error, "editor"), readOnly: false,
          // 배율 방식은 마운트마다 명시한다(IDE-06) — 폭 맞춤이면 Studio 가, 고정 배율이면 셸 CSS 가 키운다(곱하지 않는다).
          zoom: mountedFit ? "fit" : 100 });
        } catch (error) {
          // 마운트가 무너져도 안내는 남는다 — Python 이 판정 없음을 기록하고 투영한다. 보이는 오류는 원래의 것이다.
          if (!disposed) await report.onMountError(error).catch(() => undefined);
          throw error;
        }
        if (disposed) { handle.dispose(); return; }
        adapter.current = {
          flush: () => handle.flushChanges(),
          content: () => handle.content(), apply: (content, _edits, label, expectedContent) => handle.applySnapshot(content, label, expectedContent),
          focus: (target) => handle.focus(target), scrollTo: (target) => handle.scrollTo(target),
          command: async (command) => { if (command === "undo") await handle.undo(); else if (command === "redo") await handle.redo(); else controller.update({ panel: "search" }); },
          // 문제 밑줄(IDE-08 P-08)은 TXT 와 같은 규칙이다 — Python 의 problems 를 그대로 넘기고 문서 모드에서도 선다.
          // 「데이터로 필드 찾기」 제안 자리(#1156)도 같은 장식 호출에 싣는다 — 표지 상한은 보류·제안·문제 차례로 덜어 낸다.
          decorate: (analysis, mode, highlight) => { void controller.guarded(() => handle.setDecorations({ ...analysis, mode, highlight: highlight || null, problems: latest.current.problems || [],
            proposals: controller.proposal.spots(item.id) }), "editor"); },
          zoom: (mode) => handle.setZoom(mode === "fit" ? "fit" : 100),
          rangePick: (state) => handle.rangePick(state),
        };
        release = () => handle.dispose();
        // 마운트 중에 확대를 바꿨으면(편집기가 붙기 전이라 알림을 못 받았다) 지금 방식을 맞춘다.
        if ((controller.zoom(item.id) === "fit") !== mountedFit) await adapter.current.zoom!(mountedFit ? "fixed" : "fit");
      }
      detach = controller.attach(item.id, adapter.current!);
      adapter.current!.decorate(item.analysis || {}, controller.mode(item.id), controller.highlightOf(item.id));
    }, "editor");
    return () => { disposed = true; detach?.(); release?.(); adapter.current = null; };
  }, [controller, item.id]);
  // 장식은 분석이 바뀔 때만 다시 보낸다 — 같은 분석의 재전송(push)은 같은 revision 이다(UX-05).
  useEffect(() => { adapter.current?.decorate(item.analysis || {}, controller.mode(item.id), controller.highlightOf(item.id)); }, [item.analysis?.revision ?? item.analysis, active, controller.proposal.key(item)]);
  return h("div", { className: "authoring-document", hidden: !active, inert: !active, "aria-hidden": !active },
    h("div", { ref: host, className: "authoring-editor-host" }));
}

/** 만들기 명령 — 명시 진입(도구 막대·문맥 메뉴·팔레트)으로 연 폼은 「명령」 선택 없이 그 명령만 싣는다(NG-05). */
