/* UX-04 저작 작업대 접근성 — 키보드 모델(WAI-ARIA APG tabs·toolbar·tree·menu)과 초점 복귀, 단일 live region,
   오류 문장 분할의 판정을 순수 함수로 둔다. 화면(authoring.ts)은 DOM 을 읽어 여기 넘기고 결과대로 초점만 옮긴다.
   문구는 새로 짓지 않는다 — live region 문장은 Python 이 준 문장(notice·readiness·trial_state_label)과 화면에 이미
   서 있는 표지(저장 상태·실행 취소 이름)를 그대로 옮긴다. */

type Obj = Record<string, any>;

/** 한 줄 roving 이동(APG tabs·toolbar·menu): 방향키는 감싸 돌고 Home·End 는 양 끝. 그 키가 아니면 null. */
export function rovingIndex(key: string, index: number, count: number, axis: "horizontal" | "vertical"): number | null {
  if (count <= 0) return null;
  const [back, forward] = axis === "vertical" ? ["ArrowUp", "ArrowDown"] : ["ArrowLeft", "ArrowRight"];
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === forward) return index < 0 ? 0 : (index + 1) % count;
  if (key === back) return index < 0 ? count - 1 : (index - 1 + count) % count;
  return null;
}

type KeyEvent = { key: string; target: unknown; preventDefault(): void; altKey?: boolean; ctrlKey?: boolean; metaKey?: boolean };
type Focusable = { focus(options?: FocusOptions): void; contains?(node: unknown): boolean };
type Container = { querySelectorAll(selector: string): ArrayLike<unknown> };

/** DOM 접착: container 안 selector 항목 사이에서 초점을 옮긴다. 옮겼으면 기본 동작(스크롤·select 값 변경)을 막고 true. */
export function roveFocus(event: KeyEvent, container: Container | null | undefined, selector: string, axis: "horizontal" | "vertical"): boolean {
  if (!container || event.altKey || event.ctrlKey || event.metaKey) return false;
  const items = Array.from(container.querySelectorAll(selector)) as Focusable[];
  const index = items.findIndex((item) => item === event.target || !!item.contains?.(event.target));
  if (index < 0) return false;
  const next = rovingIndex(event.key, index, items.length, axis);
  if (next === null) return false;
  event.preventDefault();
  items[next].focus();
  return true;
}

/** 초점 가능한 원소 — roving 의 대기 항목(tabindex=-1)·비활성은 Tab 순서가 아니므로 빠진다. */
export const FOCUSABLE = [
  "button:not([disabled]):not([tabindex=\"-1\"])", "input:not([disabled]):not([type=\"hidden\"]):not([tabindex=\"-1\"])",
  "select:not([disabled]):not([tabindex=\"-1\"])", "textarea:not([disabled]):not([tabindex=\"-1\"])",
  "[tabindex=\"0\"]", "[contenteditable=\"true\"]", "iframe",
].join(",");
/** 메뉴를 연 자리로 기록할 가장 가까운 초점 가능 조상(§6.1) — 글자 span 이 아니라 그 줄·버튼·편집면이다. */
export const TRIGGER = "button,[role=\"treeitem\"],[role=\"tab\"],[tabindex],[contenteditable=\"true\"],input,select,textarea";

type Element_ = { isConnected?: boolean; disabled?: boolean; closest?(selector: string): unknown; focus?(): void };
/** 초점을 돌려받을 수 있는가 — 문서에 붙어 있고, 비활성·숨김·inert 안이 아니다. */
export function focusable(element: unknown): element is Element_ & { focus(): void } {
  const el = element as Element_ | null | undefined;
  return !!el && typeof el.focus === "function" && el.isConnected !== false && !el.disabled
    && !el.closest?.("[inert],[hidden],[aria-hidden=\"true\"]");
}
/** 후보 중 처음으로 초점을 받는 것에 초점을 준다. 준 원소를 돌려준다(없으면 null). */
export function focusFirst(candidates: unknown[], active: () => unknown = () => (globalThis as Obj).document?.activeElement): unknown {
  for (const candidate of candidates) {
    if (!focusable(candidate)) continue;
    candidate.focus();
    if (active() === candidate) return candidate;
  }
  return null;
}

/** 메뉴의 trigger: 사건 대상의 가장 가까운 초점 가능 조상. 대상이 closest 를 모르면(시험 대역) 그대로 쓴다. */
export function menuTrigger(target: unknown): unknown {
  const el = target as Element_ | null | undefined;
  if (!el) return null;
  return typeof el.closest === "function" ? el.closest(TRIGGER) ?? null : el;
}

/** 문맥 메뉴 위치(창 좌표): 아래로 열되 창 아래가 모자라고 위가 더 넉넉하면 위로 뒤집고, 그래도 넘치면 가장자리에 붙인다. */
export function clampMenu(anchor: { x: number; y: number }, size: { width: number; height: number },
  viewport: { width: number; height: number }, margin = 4): { left: number; top: number } {
  const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(value, Math.max(low, high)));
  const below = viewport.height - margin - anchor.y;
  const above = anchor.y - margin;
  const top = size.height <= below || below >= above ? anchor.y : anchor.y - size.height;
  return {
    left: clamp(anchor.x, margin, viewport.width - margin - size.width),
    top: clamp(top, margin, viewport.height - margin - size.height),
  };
}

/** 오류 문장(§10·P09): 호스트 호출 표지(`authoring/save:`)·둘째 줄 이후·첫 문장 뒤의 한글 없는 꼬리는 기술 세부로
 *  나눈다. 보이는 줄은 첫 문장이고 세부는 「자세히」 안에 둔다. 한글 문장이 이어지면(사용자 안내) 그대로 보인다. */
export function errorParts(message: string): { summary: string; detail: string } {
  const details: string[] = [];
  let text = String(message ?? "").trim();
  const label = /^([A-Za-z_][\w./-]*):\s+/.exec(text);
  if (label) { details.push(label[1]); text = text.slice(label[0].length); }
  const [first, ...rest] = text.split(/\r?\n/);
  let summary = first.trim();
  const sentence = /^(.*?[.!?。])\s+(.+)$/.exec(summary);
  if (sentence && !/[가-힣]/.test(sentence[2])) { summary = sentence[1]; details.push(sentence[2]); }
  details.push(...rest.map((line) => line.trimEnd()).filter(Boolean));
  return { summary: summary || String(message ?? ""), detail: details.join("\n") };
}
/** 던져진 값의 보일 문장 — Error 는 message 만(「Error:」 접두 없이), 그 밖은 문자열 그대로. */
export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error ?? "");
}

/** 문서 탭 한 장의 접근 가능한 이름 — 미저장 상태는 보이는 「 ·」 기호만이 아니라 이름에 싣는다. */
export function tabName(name: string, dirty: boolean): string {
  return dirty ? `${name}, 저장하지 않은 변경` : name;
}

/* ---------- 구조 tree (APG treeview) ---------- */

export type TreeRow = { key: string; parent: string | null; expandable: boolean; expanded: boolean };
export type TreeAction = { focus?: string; expand?: string; collapse?: string; select?: string };
/** 보이는 줄(평탄) 위의 한 키: ↑↓ 이동, Home·End, → 펼침/첫 자식, ← 접힘/부모, Enter·Space 선택. 해당 없으면 null. */
export function treeKey(key: string, rows: TreeRow[], current: string): TreeAction | null {
  const index = rows.findIndex((row) => row.key === current);
  if (index < 0) return rows.length && ["ArrowDown", "ArrowUp", "Home", "End"].includes(key) ? { focus: rows[key === "End" || key === "ArrowUp" ? rows.length - 1 : 0].key } : null;
  const row = rows[index];
  if (key === "ArrowDown") return index + 1 < rows.length ? { focus: rows[index + 1].key } : {};
  if (key === "ArrowUp") return index > 0 ? { focus: rows[index - 1].key } : {};
  if (key === "Home") return { focus: rows[0].key };
  if (key === "End") return { focus: rows[rows.length - 1].key };
  if (key === "ArrowRight") {
    if (row.expandable && !row.expanded) return { expand: row.key };
    const child = rows[index + 1];
    return row.expanded && child?.parent === row.key ? { focus: child.key } : {};
  }
  if (key === "ArrowLeft") {
    if (row.expandable && row.expanded) return { collapse: row.key };
    return row.parent ? { focus: row.parent } : {};
  }
  if (key === "Enter" || key === " ") return { select: row.key };
  return null;
}

/** 지금 선택된 대상이 이 구조 목록 줄인가(aria-current) — Python 이 locate 로 돌려준 selected 의 정체로만 가른다. */
const OCCURRENCE_KEYS = ["entry", "occurrence", "pairing_id", "paragraph", "cell_path", "start", "end"];
export function isCurrentTarget(kind: "slot" | "option" | "field" | "occurrence", entry: Obj, selected: Obj | null | undefined): boolean {
  if (!selected) return false;
  if (kind === "slot") return selected.kind === "slot" && selected.slot_id === entry.id;
  if (kind === "option") return selected.kind === "option" && selected.slot_id === entry.slot_id && selected.option_id === entry.id;
  if (selected.kind !== "field" || selected.name !== entry.name) return false;
  if (kind === "field") return Array.isArray(selected.occurrences);
  if (Array.isArray(selected.occurrences)) return false;
  const keys = OCCURRENCE_KEYS.filter((key) => key in entry);
  return keys.length > 0 && keys.every((key) => JSON.stringify(selected[key]) === JSON.stringify(entry[key]));
}

/* ---------- 단일 live region ---------- */

/** live region 이 비교하는 한 순간의 상태. 문장은 이미 지어진 것만 싣는다. */
export type LiveState = {
  id: string; save: string; error: boolean; readiness: string; readinessText: string;
  trial: string; trialLabel: string; notice: string; command: number; commandText: string;
  search: unknown; searchText: string;
};
/** 전이 한 번의 알림 문장과 다음 기준 상태. 문서가 바뀌거나 처음이면 알리지 않고 기준만 잡는다.
 *  알리는 전이: 알림(notice)이 선 순간 · 저장됨으로 바뀐 순간(알림이 없을 때) · 오류 띠 없는 저장 실패 ·
 *  초안↔사용 준비 · 시험 결과가 **다른 결과**로 바뀐 순간(오래됨은 결과가 아니다) · 명령 적용/실행 취소 · 검색 완료.
 *  경보(role=alert)가 따로 읽히는 전이(호환성 제한·외부 변경·오류)는 여기서 되풀이하지 않는다. */
export function liveStep(prev: (LiveState & { trialResult?: string }) | null, next: LiveState): { state: LiveState & { trialResult: string }; message: string } {
  const trialResult = next.trial && next.trial !== "stale" ? next.trial : prev?.id === next.id ? prev?.trialResult || "" : "";
  const state = { ...next, trialResult };
  if (!prev || prev.id !== next.id) return { state, message: "" };
  const saved = (label: string) => label.startsWith("저장됨");
  const parts: string[] = [];
  if (next.notice && next.notice !== prev.notice) parts.push(next.notice);
  else if (saved(next.save) && !saved(prev.save)) parts.push(next.save);
  if (next.save === "저장 실패" && prev.save !== "저장 실패" && !next.error) parts.push(next.save);
  if (next.readiness && prev.readiness && next.readiness !== prev.readiness && next.readinessText) parts.push(next.readinessText);
  if (trialResult && prev.trialResult && trialResult !== prev.trialResult && next.trialLabel) parts.push(next.trialLabel);
  if (next.command !== prev.command && next.commandText) parts.push(next.commandText);
  if (next.search !== prev.search && next.searchText) parts.push(next.searchText);
  return { state, message: parts.join(" · ") };
}
