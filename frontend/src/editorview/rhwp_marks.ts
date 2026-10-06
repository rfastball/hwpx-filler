/* HWPX 편집면(Studio) 표지의 **순수** 투영 — `rhwp_editor.ts` 의 `setDecorations` 가 부른다.
 *
 * 좌표 → Studio 표지 한 건, 문제 표지, 「데이터로 필드 찾기」(#1156) 제안 표지, 그리고 표지 상한(500) 안에 드는
 * 차례다. 판정은 여기 없다 — 자리·이름·문장은 Python 투영과 화면이 지은 것을 그대로 옮긴다. vendor 타입이 없어
 * 단위로 잰다. */

type Obj = Record<string, unknown>;
/** Table-cell coordinate in the Studio (camelCase) and on the Python wire (outermost table first). */
/** A document line in host client coordinates (what a popover anchors to). */
export type HostLineRect = { left: number; top: number; bottom: number };
export type StudioCellPath = Array<{ parentParagraph: number; control: number; cell: number; paragraph: number }>;
export type WireCellPath = Array<{ parent_paragraph: number; control: number; cell: number; paragraph: number }>;
/** Studio 선택(구역 하나)의 Python 좌표 — 문단·글자 위치, 표 칸이면 그 경로. */
export type WireSelection = { entry: string; paragraph: number; start_paragraph: number; end_paragraph: number; start: number; end: number;
  cell_path?: WireCellPath };
export type Marker = { kind: 'field' | 'slot' | 'option' | 'problem' | 'proposal' | 'held'; label: string; emphasis: 'subtle' | 'strong'; section: number;
  startParagraph: number; startOffset: number; endParagraph: number; endOffset: number | null; cellPath?: StudioCellPath };

/** Studio markers per setDecorations call (the SDK validator throws `invalid decoration count` above it). */
export const DECORATION_LIMIT = 500;
/** Studio marker label length (validator). A problem's label is its hover tooltip — Python's sentence. */
const LABEL_LIMIT = 160;
const PROBLEM_EMPHASIS: Record<string, 'strong' | 'subtle'> = { error: 'strong', warning: 'subtle' };
const CELL_PATH_LIMIT = 16;
const isIndex = (n: unknown): n is number => Number.isSafeInteger(n) && (n as number) >= 0;

/** `undefined` = body paragraph location; `null` = a cell_path is present but malformed. */
export function studioCellPath(place: Obj): StudioCellPath | null | undefined {
  const raw = place.cell_path;
  if (raw === undefined || raw === null) return undefined;
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > CELL_PATH_LIMIT) return null;
  const path: StudioCellPath = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") return null;
    const { parent_paragraph, control, cell, paragraph } = item as Obj;
    if (![parent_paragraph, control, cell, paragraph].every(isIndex)) return null;
    path.push({ parentParagraph: parent_paragraph as number, control: control as number, cell: cell as number, paragraph: paragraph as number });
  }
  return path;
}

/** Studio 가 보고한 셀 경로 → Python 좌표. 비었거나 너무 깊거나 순번이 아니면 null(그 선택은 쓰지 않는다). */
export function wireCellPath(path: StudioCellPath): WireCellPath | null {
  if (path.length === 0 || path.length > CELL_PATH_LIMIT
    || !path.every((entry) => [entry.parentParagraph, entry.control, entry.cell, entry.paragraph].every(isIndex))) return null;
  return path.map((entry) => ({ parent_paragraph: entry.parentParagraph, control: entry.control, cell: entry.cell, paragraph: entry.paragraph }));
}

/** A Studio selection range as the wire selection — null when it spans sections, names no known section, carries a
 *  bad index, or has a table-cell path that cannot be read. Studio reports cellPath only when both edges share one
 *  table cell; paragraphs are then cell-level. */
export function wireSelection(range: any, sectionEntries: readonly string[]): WireSelection | null {
  const entry = range && range.start.section === range.end.section ? sectionEntries[range.start.section] : undefined;
  const cellPath = range?.cellPath ? wireCellPath(range.cellPath) : undefined;
  if (!entry || cellPath === null) return null;
  const { start, end } = range;
  const next: WireSelection = { entry, paragraph: start.paragraph, start_paragraph: start.paragraph,
    end_paragraph: end.paragraph, start: start.charOffset, end: end.charOffset, ...(cellPath ? { cell_path: cellPath } : {}) };
  return [start.paragraph, end.paragraph, next.start, next.end].every(isIndex) ? next : null;
}

/** 한 자리(Python 좌표)의 Studio 표지 — 구역·문단·셀 경로를 읽을 수 없으면 null(그 자리는 칠하지 않는다). */
export function markerAt(sectionEntries: readonly string[], kind: Marker["kind"], label: string, emphasis: 'subtle' | 'strong', place: Obj): Marker | null {
  const section = sectionEntries.indexOf(String(place.entry));
  const startParagraph = place.paragraph ?? place.start_paragraph;
  const endParagraph = place.end_paragraph ?? startParagraph;
  const cellPath = studioCellPath(place);
  if (section < 0 || !Number.isSafeInteger(startParagraph) || !Number.isSafeInteger(endParagraph) || cellPath === null) return null;
  return { kind, label, emphasis, section, startParagraph: startParagraph as number,
    startOffset: typeof place.start === "number" ? place.start : 0,
    endParagraph: endParagraph as number, endOffset: typeof place.end === "number" ? place.end : null,
    ...(cellPath ? { cellPath } : {}) };
}

/** 표지 이름표 — Studio 검사기의 길이 안으로 줄인다(넘치면 말줄임). */
function clipped(text: unknown): string {
  const chars = Array.from(String(text ?? ""));
  return chars.length > LABEL_LIMIT ? `${chars.slice(0, LABEL_LIMIT - 1).join("")}…` : chars.join("");
}

/** 문제 표지(IDE-08 P-08) — Python 의 problems[].location 에 선다. 오류는 물결(strong), 경고는 점선(subtle)이고 문장은
 *  포인터 설명이다. 모르는 심각도·위치 없는 문제는 칠하지 않는다. */
export function problemMarkers(sectionEntries: readonly string[], problems: unknown): Marker[] {
  return (Array.isArray(problems) ? problems : []).map((item) => problemMarker(sectionEntries, item)).filter((made): made is Marker => !!made);
}
function problemMarker(sectionEntries: readonly string[], item: unknown): Marker | null {
  const problem = item && typeof item === "object" ? item as Obj : null;
  const emphasis = problem ? PROBLEM_EMPHASIS[String(problem.severity)] : undefined;
  if (!problem || !emphasis || !problem.location || typeof problem.location !== "object") return null;
  return markerAt(sectionEntries, "problem", clipped(problem.message), emphasis, problem.location as Obj);
}

/** 제안 자리 한 건(화면이 지은 것) — 자리 신원(`token`, 팝오버가 여는 자리 id), 자리 좌표, 이름표(필드 이름), 보류 여부,
 *  팝오버가 연 자리인가. */
export type ProposalSpot = { token: string; place: Obj; label: string; held: boolean; open?: boolean };
/** 제안 표지와 그 자리 신원 — 신원은 표지 객체에 묶여 호스트에 남는다(Studio 검사기는 모르는 키를 거절한다). */
export type ProposalMarkers = { open: Marker[]; proposals: Marker[]; held: Marker[]; tokens: Map<Marker, string> };

/** 「데이터로 필드 찾기」 제안 표지(#1156) — 누름틀처럼 한 덩어리인 링크 표지다. 제안은 `proposal`(초록)·보류는 `held`(회색)
 *  점선 밑줄이고, 포인터를 올리면 자리 전체에 면·포인터 커서·이름표(필드 이름)가 서며, 누르면 Studio 가 자리 전체를 고르고
 *  `onDecorationClick` 을 낸다. 팝오버가 연 자리는 같은 표지가 `strong`(면 + 테두리)이다. */
export function proposalMarkers(sectionEntries: readonly string[], spots: unknown): ProposalMarkers {
  const out: ProposalMarkers = { open: [], proposals: [], held: [], tokens: new Map() };
  for (const item of Array.isArray(spots) ? spots : []) {
    const made = spotMarker(sectionEntries, item);
    if (!made) continue;
    (item.open ? out.open : item.held ? out.held : out.proposals).push(made);
    if (item.token) out.tokens.set(made, String(item.token));
  }
  return out;
}
/** 자리 한 건의 링크 표지 — 자리 좌표가 없거나 읽을 수 없으면 null. */
function spotMarker(sectionEntries: readonly string[], item: ProposalSpot | null): Marker | null {
  if (!item || typeof item !== "object" || !item.place || typeof item.place !== "object") return null;
  return markerAt(sectionEntries, item.held ? "held" : "proposal", clipped(item.label), item.open ? "strong" : "subtle", item.place);
}

/** 표지 상한 안의 차례 — 의미 표지(필드·항목·선택·미리보기)가 먼저, 다음이 연 제안 자리·문제·제안·보류다.
 *  넘치면 보류부터, 다음은 제안, 마지막에 문제를 덜어 낸다(상한을 넘기면 장식 호출 전체가 던진다). 덜어 낸 종류는
 *  `dropped` 로 한 번씩 알린다(개발자 신호 — 사용자 문안이 아니다). */
export function fitMarkers(base: Marker[], extra: { open?: Marker[]; problems?: Marker[]; proposals?: Marker[]; held?: Marker[] },
  dropped: (kind: string, count: number) => void): Marker[] {
  const markers = [...base];
  for (const kind of ["open", "problems", "proposals", "held"] as const) {
    const list = extra[kind] || [];
    const room = Math.max(0, DECORATION_LIMIT - markers.length);
    if (list.length > room) dropped(kind === "problems" ? "problem" : kind, list.length - room);
    markers.push(...list.slice(0, room));
  }
  return markers;
}
