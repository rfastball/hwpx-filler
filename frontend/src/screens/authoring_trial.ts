import { createElement as h, useEffect, useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";
import { rhwpMount, trialViewerKey } from "./authoring_editor.ts";
import { button, quiet, primary, iconButton, rowButton, rowList } from "./authoring_primitives.ts";
import type { Obj, Props } from "./authoring_primitives.ts";
import { focusable } from "./authoring_a11y.ts";
import { COVERAGE_LABEL, kindTag } from "./authoring_outline_model.ts";
import { coverageDot } from "./icons.ts";

export function trialAnchorName(view: Obj): string | null {
  return view.trialAnchor || view.selected?.name || null;
}
/** HWPX 결과의 닻 자리(IDE-08 P-02) — 닻 필드의 첫 출력 자리(Python 의 `trial_result.occurrences[].output`). 없으면 null. */
export function hwpxTrialAnchor(result: Obj | null | undefined, anchor: string | null): Obj | null {
  if (!anchor) return null;
  const hit = (result?.occurrences || []).find((occurrence: Obj) => occurrence?.name === anchor && occurrence.output && typeof occurrence.output === "object");
  return hit ? hit.output : null;
}
/** 결과 칸(스크롤 상자) 안에서 target 이 가운데 오게 하는 scrollTop. 상자만 옮기므로 입력칸을 품은 독 패널은 그대로다
 *  (scrollIntoView 는 모든 스크롤 조상을 움직인다). 값은 [0, 끝] 안으로 자른다. */
export function centeredScrollTop(scroller: { scrollTop: number; clientHeight: number; scrollHeight: number; getBoundingClientRect(): { top: number } },
  target: { getBoundingClientRect(): { top: number; height: number } }): number {
  const box = scroller.getBoundingClientRect(), rect = target.getBoundingClientRect();
  const wanted = scroller.scrollTop + (rect.top - box.top) - (scroller.clientHeight - rect.height) / 2;
  return Math.max(0, Math.min(Math.round(wanted), Math.max(0, scroller.scrollHeight - scroller.clientHeight)));
}

/** 결과 뷰어는 초점을 가져가지 않는다(IDE-04) — Studio 는 문서를 싣는 동안 제 iframe 에 초점을 준다. 마운트 전 초점이 뷰어
 *  밖에 있었고 지금 뷰어 안에 있으면 있던 자리로 돌린다(자동 갱신 중 치던 시험 입력칸·누른 「시험 시작」). */
/** 시험 결과 뷰어의 고정 배율(%) — 편집면·비교 보기는 배율을 건드리지 않는다. */
export const TRIAL_VIEW_ZOOM = 75;
export function keepFocusOutside(host: { contains(node: unknown): boolean } | null, before: unknown): void {
  const doc = (globalThis as Obj).document;
  const active = doc?.activeElement;
  if (!host || !host.contains(active) || host.contains(before)) return;
  // 초점이 어디에도 없었으면(본문) 뷰어에서 초점을 거둔다 — 본문은 초점을 받지 않는다.
  if (before !== doc?.body && focusable(before)) (before as Obj).focus({ preventScroll: true });
  else active?.blur?.();
}

export function Trial({ controller, item, view }: Props & { item: Obj; view: Obj }) {
  const result = item.trial_result;
  const output = useRef<HTMLDivElement>(null);
  // 시험 입력칸의 한글 조합 중(IDE-08) — 조합 중에는 결과 닻을 옮기지 않는다.
  const composing = useRef(false);
  useEffect(() => {
    let disposed = false;
    let release: (() => void) | undefined;
    // 결과 뷰어는 결과 칸을 채우고, 새 결과가 서면 닻 필드의 첫 출력 자리로 옮겨 간다(IDE-08 P-02, TXT 닻과 같은 규칙).
    // 이동은 초점 없는 스크롤(H4)이다 — focus/focusRange 는 결과 iframe 으로 DOM 초점을 가져가므로 쓰지 않는다. 즉시 이동이라
    // 줄인 움직임 설정에도 그대로다.
    if (item.media === "hwpx" && result?.content && output.current) void controller.guarded(async () => {
      const before = document.activeElement;
      // 75% 고정 배율(IDE-04): 결과 칸 높이에서 채운 값 줄이 쪽 머리와 함께 들어온다. 맞춤 모드는 Studio 설정에 남아
      // 다음 마운트로 새므로 쓰지 않는다.
      const editor = await rhwpMount.mount({ host: output.current!, content: result.content, fileName: "시험 결과.hwpx", title: "시험 결과", readOnly: true, zoom: TRIAL_VIEW_ZOOM,
        sectionEntries: result.section_entries, trackSelection: "visible",
        onChanged: () => {}, onSelectionChanged: (target) => controller.update({ resultSelection: target }),
        onError: (error) => controller.fail(error, "trial-view") });
      if (disposed) { editor.dispose(); return; }
      release = () => editor.dispose();
      keepFocusOutside(output.current, before);
      const anchor = hwpxTrialAnchor(result, trialAnchorName(controller.viewModel.getSnapshot()));
      if (anchor && !composing.current) await editor.scrollTo(anchor);
    }, "trial-view");
    return () => { disposed = true; release?.(); };
  }, trialViewerKey(item));
  // 추적·제외 행은 독의 결과 시험 안에서 고르는 길이다(NG-06) — 원문 위치로 옮기되 속성 패널은 열지 않는다.
  const select = (entry: Obj) => () => { void controller.guarded(() => controller.select({ ...(entry.source || entry), source_revision: result.source_revision }, { keepDock: true })); };
  const traceRow = (entry: Obj) => rowButton({ chip: kindTag("field"), text: entry.name || entry.field || "필드", value: String(entry.value ?? "") }, select(entry),
    { "aria-label": `${entry.name || entry.field || "필드"}: ${entry.value ?? ""}` });
  const coverage: Obj[] = item.trial_coverage || [];
  const cases: Obj[] = item.cases || [];
  const missingFields: string[] = item.trial_missing?.fields || [];
  const missingSlots: string[] = item.trial_missing?.slots || [];
  /** 필드 입력 전이 — 그 필드가 닻이 된다(IDE-04). */
  const input = (name: string, values: Obj) => controller.trialInput(values, controller.viewModel.getSnapshot().selectedOptions, name);
  // 결과 시험(§8.1 · UX-09 · IDE-04 점진 공개): 왼쪽 열은 입력 → 선택 구성 → 자동 갱신 → [시험 시작(주 행동)], 케이스 보관·
  // 가져오기·내보내기는 접힌 「보관한 시험 케이스」 하나(케이스가 있으면 펼친 채). 오른쪽 열은 상태 칩 + 문장 → 결과(남은
  // 높이를 채운다) → 통과 범위 문장 → 접힌 「선택별 시험 상태」·「출력·제외 이유」. 접힘은 영속하지 않는다.
  return h("section", { className: "authoring-trial", "aria-label": "결과 시험" },
    h("header", null, h("h2", null, "결과 시험"), h("p", null, "시험 자료는 템플릿 파일에 포함되지 않습니다.")),
    h("div", { className: "authoring-trial-input" },
      item.cases_error && h("p", { role: "alert" }, item.cases_error),
      h("div", { className: "authoring-trial-group" },
        // 「필드 이름 사용」(IDE-01): 손대지 않은 필드만 그 이름으로 채우는 한 번의 입력 전이 — 채울 필드(trial_missing)가
        // 없으면 비활성이다. 어느 필드를 채울지는 Python 이 정한다.
        !!item.analysis?.fields?.length && h("div", { className: "authoring-actions start" },
          button("필드 이름 사용", () => { void controller.guarded(controller.fillTrialNames); }, { disabled: !missingFields.length, "data-guide": "trial-fill-names" })),
        ...(item.analysis?.fields || []).map((field: Obj) => h("label", { key: field.name, className: "authoring-field" }, field.name,
          // 손대지 않은 필드는 입력칸이 aria-invalid 를 받고 결과 시험 탭 배지로 센다 — 결과는 빈 값 표식으로 렌더된다.
          h("input", { className: "field", "aria-invalid": missingFields.includes(field.name) || undefined, value: view.values[field.name] || "",
            onCompositionStart: () => { composing.current = true; },
            onCompositionEnd: (event: any) => { composing.current = false; void controller.guarded(() => input(field.name, { ...controller.viewModel.getSnapshot().values, [field.name]: event.currentTarget.value })); },
            onChange: (event: any) => {
              const values = { ...controller.viewModel.getSnapshot().values, [field.name]: event.target.value };
              if (event.nativeEvent.isComposing) controller.update({ values });
              else void controller.guarded(() => input(field.name, values));
            } })))),
      !!item.analysis?.slots?.length && h("div", { className: "authoring-trial-group" },
        ...(item.analysis?.slots || []).map((slot: Obj) => h("label", { key: slot.id, className: "authoring-field" }, slot.label || slot.id,
          h("select", { className: "field", "data-guide": "trial-slot", "data-slot": slot.id, "aria-invalid": missingSlots.includes(slot.id) || undefined, value: view.selectedOptions[slot.id] || "", onChange: (event: any) => { void controller.guarded(() => controller.trialInput(view.values, { ...view.selectedOptions, [slot.id]: event.target.value })); } },
            h("option", { value: "" }, "선택"), ...(slot.options || []).map((option: Obj) => h("option", { key: option.id, value: option.id }, option.label || option.id)))))),
      h("label", { className: "authoring-check" }, h("input", { type: "checkbox", checked: view.autoTrial, onChange: (event: any) => controller.update({ autoTrial: event.target.checked }) }), " 자동 갱신"),
      h("div", { className: "authoring-actions start" },
        primary("시험 시작", () => { void controller.guarded(() => controller.runTrial(), "trial"); }, { disabled: view.trialBusy })),
      h("details", { className: "authoring-fold", open: cases.length > 0 },
        h("summary", { className: "authoring-section-label" }, "보관한 시험 케이스"),
        h("div", { className: "authoring-actions start" },
          button("시험 케이스 저장", () => { void controller.guarded(() => controller.saveCase()); })),
        h("div", { className: "authoring-actions start quiet-row" },
          quiet("시험 자료 가져오기", () => { void controller.guarded(() => controller.transferCases("import")); }),
          quiet("시험 자료 내보내기", () => { void controller.guarded(() => controller.transferCases("export")); })),
        rowList("보관한 시험 케이스", cases.map((test: Obj) => h("div", { key: test.name, className: "authoring-case" },
          rowButton({ text: test.name, context: test.needs_review ? "다시 확인 필요" : null }, () => { void controller.guarded(() => controller.loadCase(test)); },
            { "aria-label": `${test.name}${test.needs_review ? " · 다시 확인 필요" : ""}` }),
          iconButton("trash", `${test.name} 삭제`, () => { void controller.guarded(() => controller.removeCase(test.name)); })))))),
    h("div", { className: "authoring-trial-output" },
      // 상태 줄은 보이는 글로만 남는다 — 화면 읽기는 셸의 단일 live region 이 결과가 바뀔 때만 한다(UX-04).
      h("div", { className: "authoring-trial-state" },
        item.trial_state_label && h("span", { className: "authoring-badge", "data-trial": item.trial_state }, item.trial_state_label),
        h("p", null, view.trialBusy ? "갱신 중 · 이전 결과" : item.trial_state_message),
        quiet("시험 결과 내보내기", () => { void controller.guarded(controller.exportResult); }, { disabled: item.trial_state !== "current" })),
      item.media === "txt"
        ? h(TxtTrialOutput, { controller, item, result, selected: view.selected, anchor: trialAnchorName(view) })
        : h("div", { className: "authoring-trial-result", ref: output }),
      h("p", { className: "authoring-reason" }, "통과 표시는 현재 값과 선택 구성에만 해당합니다."),
      // 선택별 시험 상태: 구조 트리와 같은 점(채움 모양)과 같은 이름이다. 항목이 있을 때만 선다.
      !!coverage.length && h("details", { className: "authoring-fold" },
        h("summary", { className: "authoring-section-label" }, "선택별 시험 상태"),
        h("ul", { className: "authoring-coverage", "aria-label": "선택별 시험 상태" }, ...coverage.map((entry: Obj) =>
          h("li", { key: `${entry.slot_id}/${entry.option_id}` }, h("span", { className: "authoring-coverage-dot", "data-state": entry.state }, coverageDot(entry.state)),
            `${entry.slot_id} / ${entry.option_id} · ${COVERAGE_LABEL[entry.state]}`)))),
      h("details", { className: "authoring-fold" },
        h("summary", { className: "authoring-section-label" }, "출력·제외 이유"),
        item.media === "hwpx" && view.resultSelection?.entry && h("div", null, h("h4", { className: "authoring-section-label" }, "고른 문단의 필드"),
          rowList("고른 문단의 필드", (result?.occurrences || []).filter((entry: Obj) => entry.output?.entry === view.resultSelection.entry && entry.output?.paragraph === view.resultSelection.paragraph).map(traceRow))),
        rowList("출력·제외 이유", [
          ...(result?.occurrences || result?.trace || []).map(traceRow),
          ...(result?.excluded || []).map((entry: Obj) => rowButton({ chip: kindTag("option"), text: entry.reason || entry.label || entry.option_id }, select(entry)))]))),
  );
}

/** TXT 시험 결과(읽기 전용 글, 결과 칸 자체가 스크롤 상자). 새 결과(trialViewerKey)가 서면 닻 필드의 첫 출력 자리가 이 칸
 *  가운데 오도록 이 칸의 scrollTop 만 옮긴다 — 부드러운 이동 없는 즉시 이동이라 reduced motion 에도 그대로다. 닻이 없거나
 *  결과에 그 필드가 없으면 옮기지 않는다. */
function TxtTrialOutput({ controller, item, result, selected, anchor }: Props & { item: Obj; result?: Obj; selected: Obj; anchor: string | null }) {
  const box = useRef<HTMLPreElement>(null);
  const text = String(result?.text ?? result?.content ?? "");
  const occurrences: Obj[] = result?.occurrences || [];
  const anchorIndex = anchor ? occurrences.findIndex((occurrence) => occurrence.name === anchor) : -1;
  useLayoutEffect(() => {
    const scroller = box.current;
    const target = anchorIndex >= 0 ? scroller?.querySelector(`[data-occurrence="${anchorIndex}"]`) : null;
    if (scroller && target) scroller.scrollTop = centeredScrollTop(scroller, target);
  }, trialViewerKey(item));
  const parts: ReactNode[] = [];
  let end = 0;
  for (const [index, occurrence] of occurrences.entries()) {
    parts.push(text.slice(end, occurrence.output_start));
    parts.push(h("button", { type: "button", key: index, className: "authoring-output-field", "data-occurrence": index,
      "aria-label": `${occurrence.name}: ${occurrence.value}`, "aria-pressed": selected?.name === occurrence.name,
      onClick: () => { void controller.guarded(() => controller.select({ ...occurrence, source_revision: result?.source_revision }, { keepDock: true })); } }, text.slice(occurrence.output_start, occurrence.output_end) || "∅"));
    end = occurrence.output_end;
  }
  parts.push(text.slice(end));
  return h("pre", { ref: box, className: "authoring-trial-result", tabIndex: 0, role: "group", "aria-label": "읽기 전용 시험 결과" }, ...parts);
}

/** 구조 목록 한 줄(tree 항목). children 은 펼친 뒤에만 부른다(UX-05) — 사용 위치가 많은 문서에서 보이지 않는 줄을 짓지 않는다.
 *  kind 는 안내선의 종류(항목=실선·선택=점선)를 CSS 에 알리고, highlight 는 줄에 머문 동안 편집면이 강조할 대상이다(UX-09). */
