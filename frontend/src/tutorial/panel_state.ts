/* What the tutorial surface (`panel.ts`) reads off the host snapshot, without React: the featured lesson and its
 * action, the live beat and the anchor it boxes, the dialog it joins, the result card and where it stands. The host
 * decides; these only pick what to show from its snapshot. */
import { SPAN_ANCHORS, anchorSelector } from "./anchors.ts";
import { placeCoach } from "./spotlight.ts";
import type { CoachPlacement, Target } from "./spotlight.ts";
import type { Lesson, TutorialBeat, TutorialSnapshot } from "./panel.ts";

export const noHost = () => null;

export function readSnapshot(value: unknown): TutorialSnapshot | null {
  if (!value || typeof value !== "object" || (value as { kind?: unknown }).kind !== "tutorial-lessons/v1") return null;
  return value as TutorialSnapshot;
}

export const viewportOf = (doc: Document) => {
  const view = doc.defaultView ?? window;
  return { width: view.innerWidth, height: view.innerHeight };
};

export function lessonAction(item: Lesson, snapshot: TutorialSnapshot): string {
  if (item.completed) return "restart";
  return item.id === snapshot.scenario_id && snapshot.paused ? "resume" : "select";
}

/** The one lesson the open panel features: the current lesson while it is in progress (a re-run of a completed
 *  lesson included), else the next unfinished one to start. */
export function featuredLesson(snapshot: TutorialSnapshot): Lesson | null {
  const current = snapshot.scenarios.find((item) => item.id === snapshot.scenario_id);
  if (current && (snapshot.active || snapshot.paused)) return current;
  const open = snapshot.scenarios.filter((item) => !item.completed);
  return open.find((item) => item.id === snapshot.scenario_id)
    ?? open.find((item) => item.recommended) ?? open[0] ?? null;
}

/** Featured primary: a running current lesson continues behind the panel ("close"), a paused current lesson resumes
 *  even when it was completed before; any other lesson follows the row action. */
export function featuredAction(item: Lesson, snapshot: TutorialSnapshot): string {
  if (item.id === snapshot.scenario_id && snapshot.active) return "close";
  if (item.id === snapshot.scenario_id && snapshot.paused) return "resume";
  return lessonAction(item, snapshot);
}

/** Where the featured lesson stands: running, started, and its primary action. */
export function featuredState(snapshot: TutorialSnapshot, featured: Lesson | null) {
  const current = !!featured && featured.id === snapshot.scenario_id;
  const running = current && snapshot.active;
  const started = !!featured && (featured.checkpoint > 0 || current && (snapshot.active || snapshot.paused));
  const primary = featured ? featuredAction(featured, snapshot) : null;
  return { running, started, primary };
}

export function continueLabel(primary: string | null, started: boolean, copy: TutorialSnapshot["copy"]): string {
  return primary === "restart" ? copy.restart : started ? copy.resume : copy.start;
}

export function coachHiddenProps(hidden: boolean | undefined): { inert?: boolean; "aria-hidden"?: boolean } {
  return { inert: hidden || undefined, "aria-hidden": hidden || undefined };
}

/** A painted text range (#1136) is one element per line: the live beat's box is then their union. */
export function spansLines(beat: TutorialBeat | null, target: string | null, beatSelector: string | null): boolean {
  return !!beat && target === beatSelector && SPAN_ANCHORS.has(beat.target ?? "");
}

export const lessonFraction = (lesson: Lesson | undefined) => lesson?.step_count ? lesson.checkpoint / lesson.step_count : 0;

/** 설정의 「튜토리얼 버튼 표시」 토글(#1147) — HUD·열린 패널을 백엔드가 낸 최종값
 *  그대로 따른다(연습 중이면 토글과 무관하게 true). 여기서 다시 판정하지 않는다.
 *  값을 실은 첫 스냅샷 전에는 서지 않는다 — 꺼 둔 버튼이 부팅마다 잠깐 비치지 않게(#1152 리뷰). 첫 당김이
 *  실패하면 서 있는다: 백엔드의 기본값(표시)과 같고, 버튼을 잃으면 다시 켤 길이 설정뿐이다. */
export function hudVisible(snapshot: TutorialSnapshot | null, initialFailed: boolean): boolean {
  return snapshot ? snapshot.entry?.visible !== false : initialFailed;
}

/** 열린 과정 목록 패널을 그릴지 — HUD 숨김(#1147)·초대 카드·overlay 점유를 한데 묻는다. */
export function lessonsPanelOpen(hudVisible: boolean, open: boolean, snapshot: TutorialSnapshot | null, overlayBusy: boolean): boolean {
  return hudVisible && open && !!snapshot && !snapshot.invitation.visible && !overlayBusy;
}

export function guideIdentity(snapshot: TutorialSnapshot | null, beat: TutorialBeat | null): string {
  return beat && snapshot ? `${snapshot.scenario_id}:${snapshot.checkpoint}:${beat.id}` : "";
}

/** The beat the surface guides: only while a lesson runs unpaused. */
export function liveBeat(snapshot: TutorialSnapshot | null): TutorialBeat | null {
  return snapshot?.active && !snapshot.paused ? snapshot.beat : null;
}

export function beatAnchor(beat: TutorialBeat | null): string | null {
  return beat ? anchorSelector(beat.target, beat.arg) : null;
}

/** Put help in the existing focus boundary when the boxed control is inside it; never create a second modal
 *  or intercept Escape. */
export function dialogHostFor(overlayHost: Element | null, beatSelector: string | null): Element | null {
  const dialogRelevant = !!overlayHost && !!beatSelector && !!overlayHost.querySelector(beatSelector);
  return dialogRelevant ? overlayHost!.querySelector(".modal-card, .sheet-card, [role='dialog']") ?? overlayHost : null;
}

/** The lesson-complete result the host asks to show, while no lesson runs and no overlay is open. */
export function shownResult(snapshot: TutorialSnapshot | null, overlayBusy: boolean): TutorialSnapshot["result"] | null {
  return snapshot?.show_result && !snapshot.active && !overlayBusy ? snapshot.result : null;
}

/** The anchor to box: the live beat's control on its screen, else the result's anchor on its screen. */
export function guideTarget(beat: TutorialBeat | null, beatSelector: string | null, canGuide: boolean,
  result: TutorialSnapshot["result"] | null, screen: string | null): string | null {
  return beat && (beat.screen === null || beat.screen === screen) && canGuide ? beatSelector
    : result && result.screen === screen ? anchorSelector(result.target) : null;
}

export function finalePosition(found: Target | null, result: TutorialSnapshot["result"] | null, doc: Document, height: number): CoachPlacement | null {
  return found && result ? placeCoach(found.rect, viewportOf(doc), "right", height) : null;
}
