import type { LiveState } from "./authoring_a11y.ts";
import type { Obj } from "./authoring_primitives.ts";

export const MODES: [string, string][] = [["document", "문서"], ["template", "템플릿"], ["structure", "이름표"]];

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
export function menuAnchor(target: HTMLElement): { left: number; top: number; bottom: number } {
  if (target.tagName === "IFRAME") { const rect = target.getBoundingClientRect(); return { left: rect.left, top: rect.top, bottom: rect.top }; }
  const selection = target.ownerDocument?.getSelection?.();
  if (target.isContentEditable && selection?.rangeCount) {
    const range = selection.getRangeAt(0);
    const rect = range.getClientRects?.()[0] || range.getBoundingClientRect();
    if (rect && (rect.width || rect.height)) return rect;
  }
  return target.getBoundingClientRect();
}
