/* 선택 옆 사각형 보고(IDE-08 H3) — `rhwp_editor.ts` 의 `mountRhwp` 가 쓴다.
 *
 * 사각형이 속한 선택 키, 그 선택에서 마지막으로 본 사각형("" = 아직 없음, 예: 끌기 중), 호스트가 보이고 있는지,
 * 다시 돌아오면 안 되는지(편집·이동됨)를 든다. 호스트가 정한 선택(`focus`) 뒤에는 Studio 의 가운데 맞춤 스크롤이 첫
 * 보고 뒤에 내려앉는다 — 그 시각까지 움직인 줄은 사용자의 스크롤이 아니라 그 스크롤의 정착이라 사각형이 따라간다. */
import type { HostLineRect } from "./rhwp_marks.ts";

export type StudioRect = { x: number; y: number; width: number; height: number };
type RectSink = { onSelectionRect?: (rect: HostLineRect | null) => void };

export function selectionRectReporter(spec: RectSink, visibleRect: (rect: StudioRect | null) => HostLineRect | null) {
  let rectKey = "", rectSeen = "", rectShown = false, rectSpent = false;
  let hostMoveUntil = 0;
  const hide = (spent: boolean) => {
    if (spent) rectSpent = true;
    if (rectShown) { rectShown = false; spec.onSelectionRect?.(null); }
  };
  /** Shows the rect when it is visible inside the frame; false when it is not. */
  const show = (rect: StudioRect | null) => {
    const place = visibleRect(rect);
    if (place) { rectShown = true; spec.onSelectionRect!(place); }
    return !!place;
  };
  const restart = (key: string) => { rectKey = key; rectSeen = ""; rectSpent = false; hide(false); };
  /** A new reading for the current selection key. */
  const settle = (first: boolean, rect: StudioRect | null) => {
    // The line moved under an unchanged selection (scroll, zoom, relayout): hide and wait for a new selection —
    // except while a host-set selection's own scroll settles (the rect then follows the line).
    if (!first && !rectSpent && performance.now() < hostMoveUntil) {
      if (!show(rect)) hide(false);
      return;
    }
    if (!first || rectSpent) { hide(true); return; }
    show(rect);
  };
  const report = (key: string, rect: StudioRect | null) => {
    if (!spec.onSelectionRect) return;
    const seen = rect ? JSON.stringify(rect) : "";
    if (!key) { restart(""); return; }
    if (key !== rectKey) restart(key);
    if (seen === rectSeen) return;
    const first = rectSeen === "";
    rectSeen = seen;
    settle(first, rect);
  };
  return {
    hide, report,
    /** A host-set selection's centring scroll may move the reported line until `until` (performance.now time). */
    holdHostMove(until: number) { hostMoveUntil = until; },
  };
}
