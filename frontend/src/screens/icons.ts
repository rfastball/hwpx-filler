import { createElement as h } from "react";
import type { ReactNode } from "react";

/* 저작 작업대의 공용 아이콘(UX-09) — `pool_column.ts`·`refresh_button.ts` 의 인라인 SVG 관례를 따른다:
   20 격자 viewBox, 선 1.5, 색은 currentColor(칠은 CSS `.icon` 이 진다). 글자·이모지를 아이콘으로 쓰지 않는다.
   아이콘은 늘 aria-hidden 이다 — 이름은 그것을 담은 단추(aria-label·title)나 줄이 싣는다. */

type Part = [tag: string, attrs: Record<string, string | number>];
const common = (className: string) => ({ className, viewBox: "0 0 20 20", "aria-hidden": "true", focusable: "false" });
const draw = (className: string, parts: Part[]): ReactNode =>
  h("svg", common(className), ...parts.map(([tag, attrs], index) => h(tag, { key: index, ...attrs })));
const path = (d: string): Part => ["path", { d }];
const dot = (cx: number): Part => ["circle", { cx, cy: 10, r: 1.4, fill: "currentColor", stroke: "none" }];

const ICONS: Record<string, Part[]> = {
  close: [path("M5.5 5.5l9 9M14.5 5.5l-9 9")],
  maximize: [path("M4 8V4h4M12 4h4v4M16 12v4h-4M8 16H4v-4")],
  restore: [path("M8 4v4H4M16 8h-4V4M12 16v-4h4M4 12h4v4")],
  more: [dot(4.5), dot(10), dot(15.5)],
  "chevron-left": [path("M12 4.5L6.5 10l5.5 5.5")],
  "chevron-right": [path("M8 4.5l5.5 5.5L8 15.5")],
  "chevron-down": [path("M5 8l5 5 5-5")],
  check: [path("M5 10.5l3.2 3.2L15 6.8")],
  "arrow-down": [path("M10 3.5v13M5 11.5l5 5 5-5")],
  "arrow-up": [path("M10 16.5v-13M5 8.5l5-5 5 5")],
  expand: [path("M12 3.5h4.5V8M16.5 3.5L11 9M8 16.5H3.5V12M3.5 16.5L9 11")],
  undo: [path("M7.5 4.5L4 8l3.5 3.5"), path("M4 8h7.5a4.5 4.5 0 0 1 0 9H9")],
  redo: [path("M12.5 4.5L16 8l-3.5 3.5"), path("M16 8H8.5a4.5 4.5 0 0 0 0 9H11")],
  trash: [path("M4 6h12M8 6V4h4v2M5.5 6l.8 10h7.4l.8-10M8.5 9v4.5M11.5 9v4.5")],
  search: [["circle", { cx: 8.5, cy: 8.5, r: 5 }], path("M12.3 12.3L16.5 16.5")],
};

/** 동작 아이콘 하나(닫기·최대화·복원·더보기·화살표·확인 표지·펼침·실행 취소·다시 실행·삭제·찾기). */
export function icon(name: keyof typeof ICONS | string): ReactNode {
  return draw("icon", ICONS[name] || []);
}

/** 의미 요소의 종류 그림(§10) — 편집면의 어휘와 같다: 항목=실선 상자, 선택=점선 상자, 필드=자리 표지 [ ].
 *  색이 아니라 선 모양으로 가르고, 종류 이름은 곁의 글자 표지가 싣는다. */
export function kindGlyph(kind: "slot" | "option" | "field"): ReactNode {
  if (kind === "slot") return draw("icon glyph", [["rect", { x: 4, y: 4, width: 12, height: 12, rx: 1.5 }]]);
  if (kind === "option") return draw("icon glyph", [["rect", { x: 4, y: 4, width: 12, height: 12, rx: 1.5, strokeDasharray: "2.4 2" }]]);
  return draw("icon glyph", [path("M7.5 4.5H5v11h2.5M12.5 4.5H15v11h-2.5")]);
}

/** 선택 한 갈래의 시험 상태 점(AC09·AC13) — 색이 아니라 **채움 모양**이 다르다: 확인됨=찬 원, 다시 시험 필요=반쪽,
 *  시험하지 않음=빈 원. 상태 이름은 그 줄의 접근 가능한 이름이 싣는다. */
export function coverageDot(state: string): ReactNode {
  const ring: Part = ["circle", { cx: 10, cy: 10, r: 5 }];
  if (state === "current") return draw("icon coverage", [["circle", { cx: 10, cy: 10, r: 5, fill: "currentColor" }]]);
  if (state === "stale") return draw("icon coverage", [ring, ["path", { d: "M10 5a5 5 0 0 0 0 10z", fill: "currentColor", stroke: "none" }]]);
  return draw("icon coverage", [ring]);
}
