/* HWPX 편집면(Studio) 표지의 **순수** 투영 — `rhwp_editor.ts` 의 `setDecorations` 가 부른다.
 *
 * 좌표 → Studio 표지 한 건, 문제 표지, 「데이터로 필드 찾기」(#1156) 제안 표지, 그리고 표지 상한(500) 안에 드는
 * 차례다. 판정은 여기 없다 — 자리·이름·문장은 Python 투영과 화면이 지은 것을 그대로 옮긴다. vendor 타입이 없어
 * 단위로 잰다. */

type Obj = Record<string, unknown>;
/** Table-cell coordinate in the Studio (camelCase) and on the Python wire (outermost table first). */
export type StudioCellPath = Array<{ parentParagraph: number; control: number; cell: number; paragraph: number }>;
export type WireCellPath = Array<{ parent_paragraph: number; control: number; cell: number; paragraph: number }>;
export type Marker = { kind: 'field' | 'slot' | 'option' | 'problem'; label: string; emphasis: 'subtle' | 'strong'; section: number;
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

/** 제안 자리 한 건(화면이 지은 것) — 자리 좌표, 포인터 설명(접근 이름), 보류 여부, 연 자리면 그 필드 이름. */
export type ProposalSpot = { place: Obj; label: string; held: boolean; open?: string };

/** 「데이터로 필드 찾기」 제안 표지(#1156). Studio 에는 제안 전용 표지가 없어 가장 가까운 모양을 빌린다 — 제안·보류는
 *  모두 점선 밑줄(`problem` subtle, 포인터 설명이 「필드 제안 …」·「보류된 제안 …」)이고, 팝오버가 연 자리는 그 위에 필드
 *  표지(면 + 이름표, 이름표는 캐럿이 든 자리에서 선다)를 하나 더 얹어 「이 이름의 필드가 될 자리」를 보인다. */
export function proposalMarkers(sectionEntries: readonly string[], spots: unknown): { open: Marker[]; proposals: Marker[]; held: Marker[] } {
  const out = { open: [] as Marker[], proposals: [] as Marker[], held: [] as Marker[] };
  for (const item of Array.isArray(spots) ? spots as ProposalSpot[] : []) {
    if (item && typeof item === "object" && item.place && typeof item.place === "object") proposalMarker(sectionEntries, item, out);
  }
  return out;
}
function proposalMarker(sectionEntries: readonly string[], item: ProposalSpot, out: { open: Marker[]; proposals: Marker[]; held: Marker[] }) {
  const made = markerAt(sectionEntries, "problem", clipped(item.label), "subtle", item.place);
  if (made) (item.held ? out.held : out.proposals).push(made);
  const open = item.open ? markerAt(sectionEntries, "field", clipped(item.open), "strong", item.place) : null;
  if (open) out.open.push(open);
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
