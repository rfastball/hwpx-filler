import { createElement as h } from "react";
import type { ReactNode } from "react";
import type { LintpadPair, LintpadProblem } from "../editorview/txt_lintpad.ts";
import type { AuthoringController } from "./authoring_controller.ts";
import { isCurrentTarget } from "./authoring_a11y.ts";
import type { Obj } from "./authoring_primitives.ts";

export const KIND_LABEL: Obj = { field: "필드", slot: "항목", option: "선택", text: "본문" };
export const SEVERITY_LABEL: Obj = { error: "오류", warning: "경고" };
export const CATEGORY_LABEL: Obj = { structure: "구조", compatibility: "호환성", authoring: "필드" };
/** 식별자 변경은 고급 정보지만 기존 작업 연결에 닿는 영향은 숨기지 않는다(U06·F19). */
export const IDENTIFIER_IMPACT = "식별자 변경은 기존 작업 연결에 영향을 줄 수 있습니다.";

/** Python 이 판정한 명령 한 건의 가용성(F40·P07). 판정이 아직 없으면(선택 전) 세 번째 상태 — 표면은 자기 추측으로
 *  켜 두지 않고, 사유 문장 없이 비활성(pending)으로 둔다(UX-04). */
export function commandAvailability(commands: Obj[] | undefined, type: string): Obj {
  return (commands || []).find((entry) => entry.type === type) || { type, enabled: false, pending: true, reason: null, alternative: null };
}
/** 대상별 문제 수 — 구조 tree·필드 목록의 `문제 N` 배지(F12·F13). Python 의 problems 를 target 으로 셀 뿐이다. */
export function problemCount(problems: Obj[] | undefined, target: string): number {
  return (problems || []).filter((problem) => problem.target === target).length;
}
/** 대상별 문제 수 표 — 스냅샷마다 한 번 센다(구조 목록 한 줄마다 목록을 다시 훑지 않는다). */
export function problemCounts(problems: Obj[] | undefined): Map<string, number> {
  const counts = new Map<string, number>();
  for (const problem of problems || []) counts.set(problem.target, (counts.get(problem.target) || 0) + 1);
  return counts;
}
/** 항목·선택의 종류 표지(§10) — 들여쓰기·색이 아니라 글자로 둘을 가른다. */
export const kindTag = (kind: "slot" | "option" | "field" | "text"): ReactNode => h("span", { className: "authoring-kind" }, KIND_LABEL[kind]);
/** 구조 목록 한 줄의 접근 가능한 이름(§10) — 종류·이름·사용 위치 수·상위 항목·문제 수를 글로 싣는다. */
export function outlineLabel(kind: "field" | "slot" | "option" | "occurrence", entry: Obj, problems = 0, parent = ""): string {
  const name = String(entry.name || entry.label || entry.id || "");
  const parts = kind === "occurrence" ? [name, `사용 위치 ${entry.index}/${entry.total}`, ...(entry.context ? [String(entry.context)] : [])]
    : kind === "field" ? [KIND_LABEL.field, name, `사용 위치 ${entry.count ?? 0}곳`]
    : kind === "option" ? [KIND_LABEL.option, name, `상위 항목 ${parent}`] : [KIND_LABEL.slot, name];
  return [...parts, ...(problems ? [`문제 ${problems}`] : [])].join(" · ");
}
/** 선택 한 갈래의 시험 상태 이름 — 시험 패널과 구조 트리의 점이 같은 이름을 쓴다(AC09·AC13). */
export const COVERAGE_LABEL: Obj = { current: "현재 시험 구성 확인됨", stale: "다시 시험 필요", untried: "시험하지 않음" };
/** 여러 자리에 선 같은 필드의 표지(§3.3) — 「같은 필드, i/n」. 한 곳뿐이면 사용 위치 수를 그대로 쓴다. */
export function sameFieldMeta(index: number, total: number): string {
  return total > 1 ? `같은 필드, ${index}/${total}` : `사용 위치 ${total}곳`;
}

/* ---------- 문서 척추(UX-09): 구조 트리의 모양은 Python 이 준 소속·차례로만 짓는다 ---------- */

/** 척추의 한 마디. 필드 사용 위치(use)는 그것을 담은 선택·항목 아래에, 어디에도 없으면 척추에 직접 선다.
 *  척추 위에 이어 선 항목 밖 사용 위치 둘 이상은 한 묶음(group — 연속 묶음)으로 접힌다. */
export type SpineUse = { kind: "use"; field: Obj; occurrence: Obj; index: number; total: number; order: number };
export type SpineNode =
  | { kind: "slot"; slot: Obj; order: number; children: SpineNode[] }
  | { kind: "option"; slot: Obj; option: Obj; order: number; children: SpineNode[] }
  | { kind: "group"; key: string; order: number; children: SpineUse[] }
  | SpineUse;
const LAST = Number.MAX_SAFE_INTEGER;
const byOrder = (a: { order: number }, b: { order: number }) => a.order - b.order;
/** 분석(Python 투영)에서 척추를 짓는다. 소속은 사용 위치의 `slot_id`·`option_id`, 차례는 `order` 그대로다 —
 *  표면은 문단을 세거나 좌표를 견주지 않는다. 차례가 없는 옛 투영은 받은 차례(항목 → 필드)를 지킨다(안정 정렬). */
export function outlineSpine(analysis: Obj | undefined): SpineNode[] {
  const spine: SpineNode[] = [];
  const slots = new Map<string, Extract<SpineNode, { kind: "slot" }>>();
  const options = new Map<string, Extract<SpineNode, { kind: "option" }>>();
  appendSlots(analysis, spine, slots, options);
  appendUses(analysis, spine, slots, options);
  const sort = (list: SpineNode[]) => { list.sort(byOrder); for (const node of list) if (node.kind === "slot" || node.kind === "option") sort(node.children); };
  sort(spine);
  return groupLooseUses(spine);
}

function appendSlots(analysis: Obj | undefined, spine: SpineNode[],
  slots: Map<string, Extract<SpineNode, { kind: "slot" }>>, options: Map<string, Extract<SpineNode, { kind: "option" }>>): void {
  for (const slot of analysis?.slots || []) {
    const node = { kind: "slot" as const, slot, order: slot.order ?? LAST, children: [] as SpineNode[] };
    slots.set(slot.id, node);
    spine.push(node);
    for (const option of slot.options || []) {
      const child = { kind: "option" as const, slot, option, order: option.order ?? LAST, children: [] as SpineNode[] };
      options.set(`${slot.id}\u0000${option.id}`, child);
      node.children.push(child);
    }
  }
}

function appendUses(analysis: Obj | undefined, spine: SpineNode[],
  slots: Map<string, Extract<SpineNode, { kind: "slot" }>>, options: Map<string, Extract<SpineNode, { kind: "option" }>>): void {
  for (const field of analysis?.fields || []) {
    const occurrences: Obj[] = field.occurrences || [];
    occurrences.forEach((occurrence, at) => {
      const use: SpineNode = { kind: "use", field, occurrence, index: at + 1, total: occurrences.length, order: occurrence.order ?? LAST };
      const home = options.get(`${occurrence.slot_id}\u0000${occurrence.option_id}`) || slots.get(occurrence.slot_id);
      (home ? home.children : spine).push(use);
    });
  }
}
/** 연속 묶음: 항목과 항목 사이에 이어 선 항목 밖 사용 위치(둘 이상)를 한 묶음 줄로 접는다 — 문서 차례는 그대로다.
 *  하나뿐인 사용 위치는 묶지 않는다(펼칠 것이 한 줄이면 묶음이 한 번 더 누르게만 한다). */
function groupLooseUses(spine: SpineNode[]): SpineNode[] {
  const grouped: SpineNode[] = [];
  let run: SpineUse[] = [];
  const close = () => {
    if (run.length > 1) grouped.push({ kind: "group", key: outlineKey.group(run[0].field.name, run[0].index), order: run[0].order, children: run });
    else grouped.push(...run);
    run = [];
  };
  for (const node of spine) {
    if (node.kind === "use") run.push(node);
    else { close(); grouped.push(node); }
  }
  close();
  return grouped;
}
/** 구조 경로의 연속 묶음 조상 — 묶음 안 사용 위치가 지금 위치면 그 묶음 열쇠를 앞에 세운다(펼침 동기화의 기준). */
export function groupedPath(spine: SpineNode[], path: string[]): string[] {
  if (path.length !== 1) return path;
  const group = spine.find((node) => node.kind === "group" && node.children.some((use) => outlineKey.use(use.field.name, use.index) === path[0]));
  return group && group.kind === "group" ? [group.key, ...path] : path;
}
/** 필드 목록의 차례 — 문서에서 처음 쓰인 순서(§3.3·F13). 차례는 Python 의 `order` 다. */
export function fieldsInFirstUse(analysis: Obj | undefined): Obj[] {
  const first = (field: Obj) => Math.min(LAST, ...(field.occurrences || []).map((occurrence: Obj) => occurrence.order ?? LAST));
  return [...(analysis?.fields || [])].map((field, at) => ({ field, at, first: first(field) }))
    .sort((a, b) => a.first - b.first || a.at - b.at).map((entry) => entry.field);
}
/** 트리 줄의 열쇠 — 구조 탭과 필드 탭이 같은 규칙으로 짓는다(현재 위치 동기화가 이 열쇠로 줄을 찾는다). */
export const outlineKey = {
  slot: (slotId: string) => `slot:${slotId}`,
  option: (slotId: string, optionId: string) => `option:${slotId}/${optionId}`,
  use: (name: string, index: number) => `use:${name}#${index}`,
  group: (name: string, index: number) => `group:${name}#${index}`,
  field: (name: string) => `field:${name}`,
  occurrence: (name: string, index: number) => `occurrence:${name}#${index - 1}`,
};
/** 지금 위치의 의미가 가리키는 줄의 경로(바깥 → 안) — 구조 탭과 필드 탭 각각. 판정은 브레드크럼과 같다:
 *  명시 선택(`selected`)이 먼저, 없으면 캐럿의 일치 후보(`matches`)에서 가장 안쪽(사용 위치 → 선택 → 항목)이다. */
export function outlineCurrent(analysis: Obj | undefined, selected: Obj | null | undefined, matches: Obj[] = []): { structure: string[]; fields: string[] } {
  const candidates = [selected, ...matches.map((match) => match.kind === "field" ? { ...(match.location || {}), name: match.name, kind: "field" } : match)].filter(Boolean) as Obj[];
  if (selected?.kind === "field" && Array.isArray(selected.occurrences)) return { structure: [], fields: [outlineKey.field(selected.name)] };
  for (const candidate of candidates) {
    const field = currentField(analysis, candidate);
    if (field) return field;
  }
  return currentContainer(candidates);
}

function currentField(analysis: Obj | undefined, candidate: Obj): { structure: string[]; fields: string[] } | null {
  if (candidate.kind !== "field") return null;
  const field = (analysis?.fields || []).find((entry: Obj) => entry.name === candidate.name);
  const at = (field?.occurrences || []).findIndex((occurrence: Obj) => isCurrentTarget("occurrence", { ...occurrence, name: field.name }, candidate));
  if (at < 0) return null;
  const occurrence = field.occurrences[at];
  const slot = (analysis?.slots || []).find((entry: Obj) => entry.id === occurrence.slot_id);
  const option = slot && (slot.options || []).find((entry: Obj) => entry.id === occurrence.option_id);
  return { structure: [...(slot ? [outlineKey.slot(slot.id)] : []), ...(option ? [outlineKey.option(slot.id, option.id)] : []), outlineKey.use(field.name, at + 1)],
    fields: [outlineKey.field(field.name), outlineKey.occurrence(field.name, at + 1)] };
}

function currentContainer(candidates: Obj[]): { structure: string[]; fields: string[] } {
  const option = candidates.find((candidate) => candidate.kind === "option" && candidate.slot_id && candidate.option_id);
  if (option) return { structure: [outlineKey.slot(option.slot_id), outlineKey.option(option.slot_id, option.option_id)], fields: [] };
  const slot = candidates.find((candidate) => candidate.kind === "slot" && candidate.slot_id);
  return { structure: slot ? [outlineKey.slot(slot.slot_id)] : [], fields: [] };
}
/** 구조 필터 — 이름·표시 이름·식별자·문맥에 입력이 들어 있는가(대소문자 무시). */
export function filterMatch(query: string, ...texts: unknown[]): boolean {
  const wanted = query.trim().toLocaleLowerCase();
  return !wanted || texts.some((text) => text != null && String(text).toLocaleLowerCase().includes(wanted));
}
/** 문제의 다음 행동(§7.2): navigate 는 그 위치로 선택을 옮기고, command 는 Python 이 준 명령을 미리보기로 보낸다.
 *  옮기기는 독에서 시작한 선택이라 문제 탭을 남긴다(NG-06 keepDock) — 속성 패널은 열지 않는다. */
/** 문제 행의 명령 행동(자동 수정·필드 연결 변경·누름틀 변환)이 낸 미리보기인가 — 그 행동을 돌려준다. 문제 탭은 그
 *  미리보기를 「수정 제안」으로 보이고 그 행동 이름으로 확정한다(새 이름을 짓지 않는다). */
export function problemFix(problems: Obj[] | undefined, command: Obj | null | undefined): Obj | null {
  if (!command) return null;
  const wanted = JSON.stringify(command);
  for (const problem of problems || []) for (const action of problem.actions || [])
    if (action.kind === "command" && JSON.stringify(action.command) === wanted) return action;
  return null;
}

/** TXT 편집면의 문제 표지(IDE-05) — Python 문제 가운데 글자 자리(`location.start/end`)가 있는 것만, 문장·심각도 그대로다. */
export function txtProblemMarks(problems: Obj[] | undefined): LintpadProblem[] {
  return (problems || []).filter((problem) => typeof problem.location?.start === "number" && typeof problem.location?.end === "number")
    .map((problem) => ({ severity: String(problem.severity), start: problem.location.start, end: problem.location.end, message: String(problem.message || "") }));
}

/** 표지 짝(IDE-05) — Python `analysis.placements` 의 여는 표지 줄 머리(`start`)와 닫는 표지 줄(`end` 바로 앞 글자). 짝은 계산하지 않는다. */
export function markerPairs(analysis: Obj): LintpadPair[] {
  return (analysis.placements || []).filter((place: Obj) => typeof place.start === "number" && typeof place.end === "number" && place.end > place.start)
    .map((place: Obj) => ({ open: place.start, close: place.end - 1 }));
}

export async function problemAction(controller: Pick<AuthoringController, "select" | "preview" | "applyPreview">, item: Obj, problem: Obj, action: Obj): Promise<unknown> {
  if (action.kind !== "command") return controller.select({ source_revision: item.revision, ...(problem.location || {}), target: problem.target }, { keepDock: true });
  // 명령 행동도 Python 확인 등급(P-01)을 따른다 — `none`(예: 누름틀 변환)은 곧바로 적용하고, 그 밖은 문제 탭의 「수정 제안」에서 확정한다.
  const prepared = await controller.preview(action.command);
  if (prepared && !prepared.refusal && prepared.confirm === "none") await controller.applyPreview(prepared);
  return prepared;
}
