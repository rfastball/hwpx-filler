/* 저작 작업대의 **패널 폭 조절**(UX-08 #1027) — 구조↔문서면, 문서면↔속성 사이 분할선.
 *
 * 폭의 주인은 셸 개인화 서비스다(`shell/preferences.ts`): 값을 `.app` 의 CSS 변수로 싣고,
 * 놓을 때 Python 설정(settings.json `authoring_widths`)에 남긴다. 여기는 끌기·키보드를
 * 폭 값으로 번역할 뿐이다. 단위는 **기준 px**(뿌리 글자 16px 기준)이고 화면은 rem 으로
 * 그리므로 글자 배율을 따라 함께 자란다. 좁은 폭(속성 시트·구조 레일)의 전환은 CSS 컨테이너
 * 질의가 소유한다 — 분할선은 그 폭에서 숨는다. */
import { createElement as h, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AUTHORING_WIDTH_BOUNDS } from "../shell/preferences.ts";
import type { AuthoringPanel } from "../shell/preferences.ts";

export type { AuthoringPanel };

/** 화면이 쓰는 개인화 서비스의 좁은 면. 부팅 전(시험 렌더)에는 없을 수 있다. */
export type AuthoringLayout = {
  authoringWidth(panel: AuthoringPanel): number | null;
  setAuthoringWidth(panel: AuthoringPanel, width: unknown): number | null;
  saveAuthoringWidth(panel: AuthoringPanel, width: unknown): number | null;
};

/** 키보드 한 번 = 1rem(기준 px 16). */
export const WIDTH_STEP = 16;

/** 분할선 쪽에서 본 패널 방향 — 구조는 왼쪽(오른쪽으로 끌면 넓어짐), 속성은 오른쪽(왼쪽으로 끌면 넓어짐). */
const GROWS_RIGHT: Record<AuthoringPanel, boolean> = { outline: true, properties: false };

function clamp(panel: AuthoringPanel, value: number): number {
  const { min, max } = AUTHORING_WIDTH_BOUNDS[panel];
  return Math.max(min, Math.min(max, Math.round(value)));
}

/** 키 → 다음 폭. 폭을 바꾸지 않는 키면 null(기본 동작을 막지 않는다). */
export function keyedWidth(panel: AuthoringPanel, current: number, key: string): number | null {
  const { min, max } = AUTHORING_WIDTH_BOUNDS[panel];
  const sign = GROWS_RIGHT[panel] ? 1 : -1;
  if (key === "ArrowRight") return clamp(panel, current + sign * WIDTH_STEP);
  if (key === "ArrowLeft") return clamp(panel, current - sign * WIDTH_STEP);
  if (key === "Home") return min;
  if (key === "End") return max;
  return null;
}

/** 끌기 → 다음 폭. `deltaPx` 는 화면 px 이동량, `rootPx` 는 지금 뿌리 글자 크기다
 *  (150% 배율에서 24px 을 끌면 기준 px 로는 16 이다). */
export function draggedWidth(panel: AuthoringPanel, start: number, deltaPx: number, rootPx: number): number {
  const scale = rootPx > 0 ? 16 / rootPx : 1;
  return clamp(panel, start + (GROWS_RIGHT[panel] ? 1 : -1) * deltaPx * scale);
}

function rootFontPx(): number {
  if (typeof getComputedStyle !== "function") return 16;
  return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
}

/** 패널의 지금 폭(기준 px) — 저장값이 없으면 실제로 그려진 폭을 잰다. 그려지지 않았으면(0) null. */
function measured(panel: Element | null): number | null {
  if (panel === null || typeof panel.getBoundingClientRect !== "function") return null;
  const width = panel.getBoundingClientRect().width;
  return width > 0 ? Math.round(width * 16 / rootFontPx()) : null;
}

type SplitterProps = {
  panel: AuthoringPanel;
  /** 접근 가능한 이름 — 문안 소유는 호출자다. */
  label: string;
  layout?: AuthoringLayout | null;
};

/** 세로 분할선 1개. 이웃 패널은 DOM 형제로 찾는다(구조=앞, 속성=뒤). */
export function PanelSplitter({ panel, label, layout }: SplitterProps): ReactNode {
  const { min, max } = AUTHORING_WIDTH_BOUNDS[panel];
  const self = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState<number>(() => layout?.authoringWidth(panel) ?? min);
  const neighbour = () => {
    const element = self.current;
    return (GROWS_RIGHT[panel] ? element?.previousElementSibling : element?.nextElementSibling) ?? null;
  };
  // 저장값이 없으면 기본 폭(창 폭 비례)이 선다 — 그 실제 값을 따라가야 화면 읽기가 맞는 값을 말한다.
  useEffect(() => {
    const target = neighbour();
    const sync = () => { const value = measured(target); if (value !== null) setNow(value); };
    sync();
    if (target === null || typeof ResizeObserver !== "function") return;
    const observer = new ResizeObserver(sync);
    observer.observe(target);
    return () => observer.disconnect();
  }, [panel]);
  // 보이는 폭이 기준이다 — 저장값이 창 비율 상한(max-width)에 눌려 있으면 끌기·화살표가 헛돌지 않게 한다.
  const current = () => clamp(panel, measured(neighbour()) ?? layout?.authoringWidth(panel) ?? now);
  const onKeyDown = (event: any) => {
    const next = keyedWidth(panel, current(), event.key);
    if (next === null || !layout) return;
    event.preventDefault();
    event.stopPropagation();
    setNow(layout.saveAuthoringWidth(panel, next) ?? next);
  };
  const onPointerDown = (event: any) => {
    if (event.button !== 0 || !layout) return;
    const element = self.current;
    if (element === null) return;
    event.preventDefault();
    const pointer = event.pointerId as number;
    const startX = event.clientX as number;
    const start = current();
    const rootPx = rootFontPx();
    let last = start;
    element.setPointerCapture?.(pointer);
    document.body.classList.add("resizing-authoring");
    const move = (next: PointerEvent) => {
      last = draggedWidth(panel, start, next.clientX - startX, rootPx);
      setNow(layout.setAuthoringWidth(panel, last) ?? last);
    };
    // 놓기·취소·포획 상실·창 이탈 어느 쪽으로 끝나도 한 번만 정리하고 한 번만 남긴다.
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerup", finish);
      element.removeEventListener("pointercancel", finish);
      element.removeEventListener("lostpointercapture", finish);
      window.removeEventListener("blur", finish);
      document.body.classList.remove("resizing-authoring");
      if (element.hasPointerCapture?.(pointer)) element.releasePointerCapture(pointer);
      if (last !== start) layout.saveAuthoringWidth(panel, last);
    };
    element.addEventListener("pointermove", move);
    element.addEventListener("pointerup", finish);
    element.addEventListener("pointercancel", finish);
    element.addEventListener("lostpointercapture", finish);
    window.addEventListener("blur", finish);
  };
  return h("div", {
    ref: self, role: "separator", tabIndex: 0, className: `authoring-splitter authoring-splitter-${panel}`,
    "aria-orientation": "vertical", "aria-label": label,
    "aria-valuemin": min, "aria-valuemax": max, "aria-valuenow": clamp(panel, now),
    onKeyDown, onPointerDown,
  });
}
