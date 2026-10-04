/* Spotlight geometry and motion inputs for the tutorial guide. Pure DOM reads and listeners only:
 * React stays in panel.ts (vendor containment), and the real product control stays the click target. */

export type Side = "top" | "right" | "bottom" | "left" | "center";
export type Box = { left: number; top: number; right: number; bottom: number; width: number; height: number };
export type Viewport = { width: number; height: number };
/** A measured anchor: its viewport box and its own corner radius, so the ring hugs the control's shape. */
export type Target = { rect: Box; radius: number };
export type SpotFrame = { x: number; y: number; width: number; height: number; radius: number };
export type Arrow = { left: number } | { top: number };
export type CoachPlacement = { x: number; y: number; width: number; height: number; side: Side; arrow: Arrow | null };

/** Ring sits this close around the control — a snug hug, not a floating frame. */
export const SPOT_PAD = 4;
/** Glide window (ms): longer than the CSS glide so a re-render during the glide never cancels it. */
export const GLIDE_WINDOW = 480;
/** Presses here belong to the guide itself and never count as a miss. */
const GUIDE_SURFACES = "#tutorialPanelRoot, #tutorialEntrySlot, #tutorialCoach";
const LAYOUT_ATTRIBUTES = ["hidden", "class", "style", "inert"];

export function visibleElement(root: ParentNode, selector: string | null): HTMLElement | null {
  if (!selector) return null;
  for (const preferred of selector.split(",")) {
    for (const candidate of root.querySelectorAll<HTMLElement>(preferred.trim())) {
      const rect = candidate.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0 && !candidate.closest("[hidden], [inert], .hidden")) return candidate;
    }
  }
  return null;
}

function cornerRadius(element: Element): number {
  const view = element.ownerDocument?.defaultView;
  const value = view ? Number.parseFloat(view.getComputedStyle(element).borderTopLeftRadius) : 0;
  return Number.isFinite(value) ? value : 0;
}

/** The part of `rect` left visible by the viewport and every clipping box, or null when nothing of it shows. */
export function visibleRect(rect: Box, clips: readonly Box[], viewport: Viewport): Box | null {
  let left = Math.max(rect.left, 0), top = Math.max(rect.top, 0);
  let right = Math.min(rect.right, viewport.width), bottom = Math.min(rect.bottom, viewport.height);
  for (const clip of clips) {
    left = Math.max(left, clip.left); top = Math.max(top, clip.top);
    right = Math.min(right, clip.right); bottom = Math.min(bottom, clip.bottom);
  }
  return right > left && bottom > top ? { left, top, right, bottom, width: right - left, height: bottom - top } : null;
}

/** Padding box of a clipping ancestor (scrollbars excluded): what its scroll area can show. */
function clientBox(node: Element): Box {
  const rect = node.getBoundingClientRect();
  const left = rect.left + node.clientLeft, top = rect.top + node.clientTop;
  return { left, top, right: left + node.clientWidth, bottom: top + node.clientHeight, width: node.clientWidth, height: node.clientHeight };
}

function clipsOverflow(style: CSSStyleDeclaration): boolean {
  return style.overflowX !== "visible" || style.overflowY !== "visible";
}

/** Boxes of the ancestors that clip `element`: every non-visible overflow box on its containing-block chain
 *  (an absolute box skips static ancestors; a fixed box escapes them all). The viewport is clipped separately. */
export function clipBoxes(element: Element): Box[] {
  const view = element.ownerDocument?.defaultView;
  const stop = element.ownerDocument?.body;
  if (!view) return [];
  const boxes: Box[] = [];
  let scheme = view.getComputedStyle(element).position;
  for (let node = element.parentElement; node && node !== stop && scheme !== "fixed"; node = node.parentElement) {
    const style = view.getComputedStyle(node);
    if (scheme === "absolute" && style.position === "static") continue;
    if (clipsOverflow(style) && node.clientWidth > 0 && node.clientHeight > 0) boxes.push(clientBox(node));
    scheme = style.position;
  }
  return boxes;
}

export type Reveal = (element: HTMLElement) => void;

/** Brings a changed anchor into view inside every scroll ancestor. Instant, so the ring settles on the final box
 *  in the same frame (the ring's own glide carries the motion, and reduced motion has none). */
export function scrollAnchor(element: HTMLElement): void {
  element.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
}

/** Reveal once per anchor: a new beat key or a replaced element scrolls; a re-measure of the same element never
 *  does, so a user who scrolls the anchor away is not pulled back. */
export function createRevealer(scroll: Reveal): (key: string) => Reveal {
  let shown: { key: string; element: HTMLElement | null } = { key: "", element: null };
  return (key) => (element) => {
    if (shown.key === key && shown.element === element) return;
    shown = { key, element };
    scroll(element);
  };
}

/** The first visible anchor inside `root`, as the box its clipping ancestors and the viewport leave visible;
 *  null when it is absent or scrolled wholly out of sight. `reveal` runs before measuring. */
export function measureTarget(root: ParentNode, selector: string | null, viewport: Viewport, reveal?: Reveal): Target | null {
  const element = visibleElement(root, selector);
  if (!element) return null;
  reveal?.(element);
  const rect = visibleRect(element.getBoundingClientRect(), clipBoxes(element), viewport);
  return rect ? { rect, radius: cornerRadius(element) } : null;
}

export function sameTarget(a: Target | null, b: Target | null): boolean {
  if (!a || !b) return a === b;
  return a.radius === b.radius && a.rect.left === b.rect.left && a.rect.top === b.rect.top
    && a.rect.width === b.rect.width && a.rect.height === b.rect.height;
}

/** Ring frame: the control's box grown by `pad`, its own radius grown by the same pad (concentric corners),
 *  never rounder than a pill of the frame's short side. */
export function spotFrame(target: Target, pad = SPOT_PAD): SpotFrame {
  const width = target.rect.width + 2 * pad, height = target.rect.height + 2 * pad;
  return { x: target.rect.left - pad, y: target.rect.top - pad, width, height,
    radius: Math.min(target.radius + pad, Math.min(width, height) / 2) };
}

/** Arrow offset along the coach edge facing the target; null when clamping pushed the card onto the target. */
function arrowFor(side: Side, target: Box, box: { x: number; y: number; width: number; height: number }): Arrow | null {
  const along = (value: number, size: number) => Math.max(16, Math.min(value - 6, size - 28));
  const apart = { bottom: box.y >= target.bottom, top: box.y + box.height <= target.top,
    right: box.x >= target.right, left: box.x + box.width <= target.left, center: false }[side];
  if (!apart) return null;
  return side === "top" || side === "bottom" ? { left: along(target.left + target.width / 2 - box.x, box.width) }
    : { top: along(target.top + target.height / 2 - box.y, box.height) };
}

export function placeCoach(target: Box, viewport: Viewport, preferred: Side, coachHeight = 162): CoachPlacement {
  const gap = 18, pad = 12, coachW = Math.min(320, viewport.width - 2 * pad), coachH = coachHeight;
  const space = { top: target.top, bottom: viewport.height - target.bottom, left: target.left, right: viewport.width - target.right };
  const fit = (side: Exclude<Side, "center">) => space[side] >= (side === "top" || side === "bottom" ? coachH : coachW) + gap;
  let side = preferred;
  if (side !== "center" && !fit(side)) {
    const ordered: Array<Exclude<Side, "center">> = ["bottom", "top", "right", "left"];
    ordered.sort((a, b) => space[b] - space[a]);
    side = ordered[0];
  }
  const centerX = target.left + target.width / 2;
  const centerY = target.top + target.height / 2;
  const rawX = side === "right" ? target.right + gap : side === "left" ? target.left - coachW - gap : centerX - coachW / 2;
  const rawY = side === "bottom" ? target.bottom + gap : side === "top" ? target.top - coachH - gap : centerY - coachH / 2;
  const box = {
    x: Math.max(pad, Math.min(rawX, viewport.width - coachW - pad)),
    y: Math.max(pad, Math.min(rawY, viewport.height - coachH - pad)),
    width: coachW, height: coachH,
  };
  return { ...box, side, arrow: arrowFor(side, target, box) };
}

/** A primary press outside the ring during an action beat. Presses on the guide's own surfaces never count. */
export function pressMissesTarget(point: { x: number; y: number }, frame: SpotFrame | null, onGuide: boolean): boolean {
  if (!frame || onGuide) return false;
  return point.x < frame.x || point.y < frame.y || point.x > frame.x + frame.width || point.y > frame.y + frame.height;
}

/** Observe (never intercept) presses: the product still receives every click; the guide only reacts. */
export function watchMissedPress(doc: Document, frame: SpotFrame, onMiss: () => void): () => void {
  const listener = (event: PointerEvent) => {
    const origin = event.target as Element | null;
    const onGuide = !!origin?.closest?.(GUIDE_SURFACES);
    if (event.button === 0 && pressMissesTarget({ x: event.clientX, y: event.clientY }, frame, onGuide)) onMiss();
  };
  doc.addEventListener("pointerdown", listener, true);
  return () => doc.removeEventListener("pointerdown", listener, true);
}

/** A pressed control that cannot act (disabled, or dimmed with `aria-disabled`) is not a press of that control. */
function inert(element: Element): boolean {
  return (element as HTMLButtonElement).disabled === true || element.getAttribute("aria-disabled") === "true";
}

/** Observe (never intercept) an activation of the boxed control — the first visible match of `selector`.
 *  `click` covers the pointer and the keyboard alike; the product still handles the click itself. */
export function watchBoxedPress(doc: Document, selector: string, onPress: () => void): () => void {
  const listener = (event: Event) => {
    const boxed = visibleElement(doc, selector);
    const origin = event.target as Node | null;
    if (boxed && origin && boxed.contains(origin) && !inert(boxed)) onPress();
  };
  doc.addEventListener("click", listener, true);
  return () => doc.removeEventListener("click", listener, true);
}

function guideOwned(mutation: MutationRecord): boolean {
  return !!(mutation.target as Element).closest?.("#tutorialPanelRoot, #tutorialCoach, .tutorial-spot");
}

/** Re-measure once per frame after any product layout change: DOM, scroll, resize, or a finished transition
 *  (a dialog card settles from its open scale only at transitionend). */
export function watchLayout(doc: Document, onChange: () => void): () => void {
  const view = doc.defaultView ?? window;
  let frame = 0;
  const update = () => { view.cancelAnimationFrame(frame); frame = view.requestAnimationFrame(onChange); };
  const observer = new MutationObserver((mutations) => { if (!mutations.every(guideOwned)) update(); });
  observer.observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: LAYOUT_ATTRIBUTES });
  const events = ["scroll", "transitionend", "animationend"];
  for (const type of events) doc.addEventListener(type, update, true);
  view.addEventListener("resize", update);
  return () => {
    view.cancelAnimationFrame(frame); observer.disconnect();
    for (const type of events) doc.removeEventListener(type, update, true);
    view.removeEventListener("resize", update);
  };
}

/** Alternating animation token: flipping between two identical keyframe names restarts a CSS animation. */
export function parity(count: number): "a" | "b" {
  return count % 2 ? "b" : "a";
}
