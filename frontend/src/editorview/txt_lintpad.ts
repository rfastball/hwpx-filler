/* TXT 저작 린트메모장의 **vendor lifecycle owner**(S10-05 · #862 · #299 회수).
 *
 * CodeMirror 6 를 아는 **유일한** 소스 파일이다(#588 dependency containment:
 * `tests/architecture_contract.toml` `[vendor_integration.codemirror]` 의
 * `allowed_source_roots` 가 이 파일 하나를 가리키고, mount/update/dispose 소유 심볼도
 * 여기 셋뿐이다). 밖으로 나가는 타입에 CodeMirror 타입이 하나도 없다는 것이 그 봉쇄의
 * 검사 가능한 얼굴이다 — `LintpadHandle` 은 `host` 엘리먼트만 드러내고 `EditorView` 는
 * 모듈 지역 `WeakMap` 안에서만 산다.
 *
 * **판정은 여기 없다.** 무엇이 필드 토큰이고 무엇이 구간 마커인지, 표기가 어디서 깨졌는지는
 * 전부 Python 이 말한다(`tpl/txt_lint` → 링0 `scan_text_structure` ·
 * `scan_text_token_spans`). 브리지가 UTF-16 으로 번역한 오프셋을 데코레이션으로 얹는
 * 것뿐이다 — 여기서 `{{…}}` 를 다시 정규식으로 가르면 sigil 선행 분류가 두 곳에서
 * 갈리고, 같은 토큰이 표면과 백엔드에서 다른 것이 된다.
 *
 * **이름표(FB-03 #1079).** 편집면은 표기 원문 대신 HWPX 편집면과 같은 이름표를 그린다 — 필드는 이름에 필드 밑줄,
 * 항목·선택 표기는 이름 칩, 그 범위는 줄 왼쪽 막대다. 원문은 문서에 그대로 있고(오프셋은 늘 원문 좌표) 가려질
 * 뿐이다. 가린 토큰은 원자 범위라 캐럿이 그 안에 서지 않고, 지우면 토큰 하나가 통째로 지워진다(되돌리기 한 번).
 * 원문 표기는 「원문 표기」 독이 보인다. 이름·짝은 Python 이 정한다(`LintpadSpan.label` 등).
 *
 * 전용 작업대는 undo/search 키맵을 설치한다. 기존 모달에서는 키맵을 설치하지 않아
 * Escape·Tab의 모달 이탈 가드와 포커스 트랩을 유지한다. */
import { Compartment, EditorState, StateEffect, StateField, Transaction } from "@codemirror/state";
import type { Extension, Range } from "@codemirror/state";
import { Decoration, EditorView, WidgetType, keymap, lineNumbers } from "@codemirror/view";
import { history, historyKeymap, undo, redo, undoDepth, redoDepth, isolateHistory } from "@codemirror/commands";
import { search, openSearchPanel } from "@codemirror/search";
import type { DecorationSet } from "@codemirror/view";

/** Python 브리지가 UTF-16 으로 번역한 토큰 좌표 1건. */
export type LintpadSpan = {
  /** `"field"`(누름틀 토큰) 또는 `"marker"`(구간 표기). 여기서 판정하지 않는다. */
  kind: string;
  /** 0-기반 UTF-16 코드 단위 오프셋(반열린 구간). */
  start: number;
  end: number;
  /** Python 이 본 토큰 원문 — 지금 문서의 그 자리가 이것과 같을 때만 이름표로 가린다(판정 시차 방어, 다시 가르지 않는다). */
  source?: string;
  /** 이름표에 보일 이름(FB-03) — 비었거나 없으면 가리지 않고 원문을 보인다(깨진 표기는 고칠 수 있게 보인다). */
  label?: string;
  /** 마커의 범위 종류(`"slot"`·`"option"`)와 여닫음(`"open"`·`"close"`) — Python 판정 그대로. */
  region?: string;
  role?: string;
  paired?: boolean;
};

/** 이름표 표시 방식 — HWPX 편집면(`rhwp_editor.ts` `setDecorations` 의 `labels`)과 같은 어휘다.
 *  `none`(문서): 이름만 조용히 · `selected`(템플릿): 이름표, 캐럿이 든 범위만 막대를 짙게 · `all`(이름표): 전부 짙게. */
export type LintpadLabels = "none" | "selected" | "all";

/** 항목·선택 범위 1건 — Python 배치(`analysis.placements`)의 UTF-16 좌표 그대로(여는 표기 줄 머리 ~ 닫는 표기 다음 줄 머리). */
export type LintpadRegion = { kind: string; start: number; end: number };

/** 원인 자리 문제 1건(IDE-05) — Python 의 `problems[].location`(UTF-16)과 심각도·문장 그대로다. */
export type LintpadProblem = {
  /** `"error"`(실선 물결) 또는 `"warning"`(점선 물결). 모르는 심각도는 칠하지 않는다. */
  severity: string;
  start: number;
  end: number;
  /** 표지 위 `title` — Python 문장 그대로. */
  message: string;
};

/** 표지 짝 1쌍(IDE-05) — Python 의 `analysis.placements` 가 준 여는 표지 줄·닫는 표지 줄 위의 offset 하나씩.
 *  짝은 여기서 계산하지 않는다. 캐럿이 한쪽 줄에 있으면 다른 쪽 줄이 옅게 선다. */
export type LintpadPair = { open: number; close: number };

/** 마운트된 메모장 1개의 **불투명 손잡이** — vendor 타입을 밖으로 내지 않는다. */
export type LintpadHandle = {
  readonly host: HTMLElement;
};

export type LintpadMountSpec = {
  /** 편집기가 들어갈 빈 컨테이너. React 가 소유하는 노드이고 내용은 CodeMirror 가 채운다. */
  host: HTMLElement;
  /** 최초 본문. */
  doc: string;
  /** 컨텐츠 DOM 에 실을 `id`(기존 표면 계약 승계 — 초기 포커스·selftest 프로브가 겨눈다). */
  contentId: string;
  /** 스크린리더용 이름 — 문안 소유는 호출자(표면)다. */
  ariaLabel: string;
  /** 사용자가 친 결과. 매 변경마다 전문(全文)으로 부른다. */
  onDocChanged: (text: string) => void;
  /** 전용 작업대에서만 키맵·history를 설치한다. 기존 모달의 Escape/Tab 규칙은 유지한다. */
  authoring?: boolean;
  readOnly?: boolean;
  onSelectionChanged?: (selection: { start: number; end: number }) => void;
  /** 범위 고르기의 누름 한 번(click) — 그 자리의 UTF-16 위치. 켠 동안(`setLintpadRangePick`)만 오고 캐럿은 옮기지 않는다. */
  onRangePick?: (offset: number) => void;
  /** 선택 끝(head) 줄의 호스트 클라이언트 좌표(IDE-08) — 비어 있지 않은 선택이 **자리 잡으면** 보고한다(포인터를 누른
   *  채 끄는 동안은 보고하지 않고 놓을 때 한 번). 선택이 비거나 문서가 바뀌면 null 이다. 선택 옆 막대가 이 줄 아래에 선다. */
  onSelectionRect?: (rect: LintpadLineRect | null) => void;
  onCompositionChanged?: (composing: boolean) => void;
};

export type LintpadUpdateSpec = {
  /**
   * 외부에서 갈아 끼울 본문. 지금 문서와 같으면 아무것도 하지 않는다 — 매 키 입력마다
   * 되돌려 넣으면 캐럿이 문서 끝으로 튄다(React 값-되먹임 결함류).
   */
  doc?: string;
  /** 강조 좌표 전집. 넘기지 않으면 기존 강조를 그대로 둔다(문서 변경에 따라 매핑된다). */
  spans?: readonly LintpadSpan[];
  /** 문제 표지 전집(별도 층) — 필드·표지 강조와 겹쳐도 잘리지 않는다. 넘기지 않으면 그대로 둔다. */
  problems?: readonly LintpadProblem[];
  /** 표지 짝 전집. 넘기지 않으면 그대로 둔다. */
  pairs?: readonly LintpadPair[];
  /** 이름표 표시 방식. 넘기지 않으면 그대로 둔다(처음은 `selected`). */
  labels?: LintpadLabels;
  /** 항목·선택 범위 전집(줄 왼쪽 막대). 넘기지 않으면 그대로 둔다. */
  regions?: readonly LintpadRegion[];
};

/** 손잡이 → 실제 뷰. 이 `WeakMap` 이 vendor 타입 봉쇄의 자리다. */
const VIEWS = new WeakMap<LintpadHandle, EditorView>();

const SPAN_CLASS: Record<string, string> = {
  field: "cm-txtField",
  marker: "cm-txtMarker",
};

/** 문서 표시(`labels: "none"`)의 이름표 — 색 없이 이름만 조용히 선다(HWPX 문서 표시에 표지가 없는 것과 같은 자리). */
const QUIET_CLASS: Record<string, string> = {
  field: "cm-txtToken",
  marker: "cm-txtToken cm-txtToken-marker",
};
const NAMED_REGIONS = ["slot", "option"];
const NAMED_ROLES = ["open", "close"];

const setSpans = StateEffect.define<readonly LintpadSpan[]>();
const setLabels = StateEffect.define<LintpadLabels>();
const setRegions = StateEffect.define<readonly LintpadRegion[]>();
const setProblems = StateEffect.define<readonly LintpadProblem[]>();
const setPairs = StateEffect.define<readonly LintpadPair[]>();

const PROBLEM_CLASS: Record<string, string> = {
  error: "cm-authoring-problem-error",
  warning: "cm-authoring-problem-warning",
};

/** 문제 표지로 얹을 조각의 **순수** 투영 — vendor 타입이 없어 단위로 잰다.
 *  필드 강조(`usableSpans`)와 달리 겹침을 버리지 않는다: 문제는 제 층이 따로 있고, 같은 자리의 두 문제는 둘 다
 *  선다(마크는 겹쳐도 되고 정렬만 요구한다). 문서 길이로 자르고, 줄 전체 자리의 끝 줄바꿈은 밑줄이 설 글자가 아니라
 *  걷는다. 모르는 심각도·빈 조각은 버린다. */
export function problemMarks(
  problems: readonly LintpadProblem[], doc: string,
): { from: number; to: number; className: string; title: string }[] {
  const marks: { from: number; to: number; className: string; title: string }[] = [];
  for (const problem of problems) {
    const className = PROBLEM_CLASS[problem.severity];
    const from = Math.max(0, Math.min(problem.start, doc.length));
    let to = Math.max(from, Math.min(problem.end, doc.length));
    while (to > from && (doc[to - 1] === "\n" || doc[to - 1] === "\r")) to--;
    if (className === undefined || to <= from) continue;
    marks.push({ from, to, className, title: problem.message });
  }
  return marks.sort((a, b) => a.from - b.from || a.to - b.to);
}

/** 데코를 얹을 수 있는 조각만 남긴 **순수** 투영 — vendor 타입이 없어 단위로 잰다.
 *
 *  Python 의 좌표와 지금 문서 사이에는 늘 시차가 있다(디바운스 왕복). 그래서 세 규칙을
 *  여기서 집행한다: ① 문서 길이로 자른다 ② 앞 조각의 끝보다 뒤에서만 시작한다(RangeSet 은
 *  정렬을 요구하고, 겹친 마크는 얹는 순간 던진다) ③ 모르는 `kind` 는 버린다 —
 *  판정 어휘가 늘었는데 표면이 아직 모르면 **칠하지 않는 것**이 조용히 틀리는 것보다 낫다. */
export function usableSpans(
  spans: readonly LintpadSpan[], docLength: number,
): { from: number; to: number; className: string }[] {
  const usable: { from: number; to: number; className: string }[] = [];
  let cursor = 0;
  for (const span of spans) {
    const className = SPAN_CLASS[span.kind];
    const from = Math.max(cursor, Math.min(span.start, docLength));
    const to = Math.min(span.end, docLength);
    if (className === undefined || to <= from) continue;
    usable.push({ from, to, className });
    cursor = to;
  }
  return usable;
}

/** 이름표·강조 조각 1건 — `label` 이 있으면 원문을 가리는 이름표, 없으면 원문 위 강조(mark)다. */
export type LintpadPiece = { from: number; to: number; className: string; label?: string; region?: string; role?: string };

/** Python 이 준 이름표 이름 — 표면은 이름을 짓지 않고, 이름을 쓸 수 없는 표기면 null(원문을 그대로 보인다). */
function nameTag(span: LintpadSpan): string | null {
  const label = typeof span.label === "string" ? span.label : "";
  if (!label) return null;
  if (span.kind === "field") return label;
  return span.kind === "marker" && NAMED_REGIONS.includes(String(span.region)) && NAMED_ROLES.includes(String(span.role)) ? label : null;
}

/** 이름표·강조로 얹을 조각의 **순수** 투영(FB-03) — vendor 타입이 없어 단위로 잰다.
 *
 *  `usableSpans` 의 세 규칙(문서 길이로 자름·앞 조각 뒤에서만·모르는 kind 버림) 위에 둘을 더한다:
 *  ① 이름표는 토큰 전부가 그 자리에 있고 지금 문서의 글자가 Python 이 본 원문(`source`)과 같을 때만 선다 —
 *  판정 왕복 사이에 문서가 바뀌었으면 가리지 않는다(엉뚱한 글자를 이름표로 덮지 않는다). ② 문서 표시(`none`)는
 *  이름표를 조용한 모양으로만 세우고 원문 강조(mark)는 칠하지 않는다(종전 문서 표시와 같다). */
export function lintpadPieces(
  spans: readonly LintpadSpan[], doc: string, labels: LintpadLabels = "selected",
): LintpadPiece[] {
  const quiet = labels === "none";
  const pieces: LintpadPiece[] = [];
  let cursor = 0;
  for (const span of spans) {
    const className = SPAN_CLASS[span.kind];
    const from = Math.max(cursor, Math.min(span.start, doc.length));
    const to = Math.min(span.end, doc.length);
    if (className === undefined || to <= from) continue;
    cursor = to;
    const label = nameTag(span);
    const whole = from === span.start && to === span.end && (span.source === undefined || doc.slice(from, to) === span.source);
    if (label !== null && whole) {
      pieces.push({ from, to, className: quiet ? QUIET_CLASS[span.kind] : className, label,
        ...(span.kind === "marker" ? { region: String(span.region), role: String(span.role) } : {}) });
    } else if (!quiet) pieces.push({ from, to, className });
  }
  return pieces;
}

/** 원문 토큰을 가리는 이름표 — 글자는 Python 이 준 이름뿐이다. 누름은 편집기가 받아 캐럿을 토큰 앞뒤로 둔다. */
class NameTag extends WidgetType {
  readonly label: string;
  readonly className: string;
  readonly region: string;
  readonly role: string;
  constructor(label: string, className: string, region: string, role: string) {
    super();
    this.label = label; this.className = className; this.region = region; this.role = role;
  }
  eq(other: NameTag) {
    return other.label === this.label && other.className === this.className && other.region === this.region && other.role === this.role;
  }
  toDOM() {
    const tag = document.createElement("span");
    tag.className = this.className;
    if (this.region) tag.dataset.region = this.region;
    if (this.role) tag.dataset.role = this.role;
    tag.textContent = this.label;
    return tag;
  }
  ignoreEvent() { return false; }
}

/** 좌표 → 데코레이션(위 투영의 vendor 얼굴). 이름표(replace)는 원자 범위로도 따로 모은다. */
function decorate(state: EditorState, spans: readonly LintpadSpan[], labels: LintpadLabels): { deco: DecorationSet; atoms: DecorationSet } {
  const ranges: Range<Decoration>[] = [];
  const atoms: Range<Decoration>[] = [];
  for (const piece of lintpadPieces(spans, state.doc.toString(), labels)) {
    if (piece.label === undefined) {
      ranges.push(Decoration.mark({ class: piece.className }).range(piece.from, piece.to));
      continue;
    }
    const tag = Decoration.replace({ widget: new NameTag(piece.label, piece.className, piece.region || "", piece.role || "") });
    ranges.push(tag.range(piece.from, piece.to));
    atoms.push(tag.range(piece.from, piece.to));
  }
  const clamp = (offset: number) => Math.max(0, Math.min(offset, state.doc.length));
  for (const span of spans) {
    if (span.kind !== "highlight") continue;
    // 구조 트리가 가리키는 범위(UX-09)는 그 범위가 닿는 줄 전체에 선다 — 필드 표지와 겹쳐도 마크가 아니라 줄 장식이다.
    const first = state.doc.lineAt(clamp(span.start)).number;
    const last = state.doc.lineAt(clamp(Math.max(span.start, span.end - 1))).number;
    for (let number = first; number <= last; number++) ranges.push(Decoration.line({ class: "cm-authoring-highlight" }).range(state.doc.line(number).from));
  }
  return { deco: Decoration.set(ranges, true), atoms: Decoration.set(atoms, true) };
}

/** 강조 상태 — 문서가 바뀌면 좌표를 **매핑**해 따라가고, 새 판정이 오면 갈아 끼운다.
 *
 *  매핑이 있어야 왕복(디바운스 180ms)이 도는 사이에도 강조가 글자에 붙어 있다. 새 판정이
 *  도착하면 그 순간의 전집으로 덮으므로 매핑의 누적 오차는 남지 않는다. 표시 방식만 바뀌면(문서·템플릿·이름표)
 *  매핑해 둔 좌표로 다시 짓는다. */
type SpanState = { spans: readonly LintpadSpan[]; labels: LintpadLabels; deco: DecorationSet; atoms: DecorationSet };
const spanField = StateField.define<SpanState>({
  create: () => ({ spans: [], labels: "selected", deco: Decoration.none, atoms: Decoration.none }),
  update(value, tr) {
    let { spans, labels } = value;
    let rebuild = false;
    if (tr.docChanged) {
      spans = spans.map((span) => ({ ...span, start: tr.changes.mapPos(span.start, 1), end: tr.changes.mapPos(span.end, -1) }));
    }
    for (const effect of tr.effects) {
      if (effect.is(setSpans)) { spans = effect.value; rebuild = true; }
      if (effect.is(setLabels) && effect.value !== labels) { labels = effect.value; rebuild = true; }
    }
    if (rebuild) return { spans, labels, ...decorate(tr.state, spans, labels) };
    return tr.docChanged ? { spans, labels, deco: value.deco.map(tr.changes), atoms: value.atoms.map(tr.changes) } : value;
  },
  provide: (field) => [
    EditorView.decorations.from(field, (value) => value.deco),
    // 가린 토큰은 원자 범위다 — 캐럿·끌기·지우기가 그 안에 서지 않는다(지우면 토큰 하나가 통째로 지워진다).
    EditorView.atomicRanges.of((view) => view.state.field(field).atoms),
  ],
});

/** 가린 토큰의 [from, to] 목록 — 원자 범위의 평범한 얼굴(vendor 타입 없음). */
function atomList(state: EditorState): { from: number; to: number }[] {
  const out: { from: number; to: number }[] = [];
  state.field(spanField).atoms.between(0, state.doc.length, (from, to) => { out.push({ from, to }); });
  return out;
}

/** 밖에서 옮긴 선택을 가린 토큰 밖으로 민다 — 캐럿은 가까운 쪽 경계로, 범위는 걸친 토큰을 통째로 담는다.
 *  편집기 자신의 캐럿·끌기는 원자 범위가 이미 막는다. 이것은 문제·검색·구조 목록에서 온 좌표를 위한 것이다 —
 *  캐럿이 가린 토큰 안에 서면 다음 글자가 보이지 않는 표기 안으로 들어간다. */
export function snapOutOfTokens(atoms: readonly { from: number; to: number }[], start: number, end: number): [number, number] {
  if (start === end) {
    const inside = atoms.find((atom) => atom.from < start && start < atom.to);
    if (!inside) return [start, end];
    const side = start - inside.from <= inside.to - start ? inside.from : inside.to;
    return [side, side];
  }
  let lo = Math.min(start, end), hi = Math.max(start, end);
  for (const atom of atoms) {
    if (atom.from < lo && lo < atom.to) lo = atom.from;
    if (atom.from < hi && hi < atom.to) hi = atom.to;
  }
  return start <= end ? [lo, hi] : [hi, lo];
}

/** 항목·선택 범위의 줄 막대(FB-03) — HWPX 편집면의 범위 상자와 같은 자리다. 템플릿 표시는 캐럿이 든 범위만,
 *  이름표 표시는 전부 짙게 선다. 문서 표시는 막대가 없다. 범위는 Python 배치 그대로이고 매핑으로 따라간다. */
type RegionState = { regions: readonly LintpadRegion[]; labels: LintpadLabels; deco: DecorationSet };

function regionDecoration(state: EditorState, regions: readonly LintpadRegion[], labels: LintpadLabels): DecorationSet {
  if (labels === "none") return Decoration.none;
  const caret = state.selection.main.head;
  const clamp = (offset: number) => Math.max(0, Math.min(offset, state.doc.length));
  const lines = new Map<number, Set<string>>();
  for (const region of regions) {
    if (!NAMED_REGIONS.includes(region.kind) || !(region.end > region.start)) continue;
    const strong = labels === "all" || (region.start <= caret && caret < region.end);
    const first = state.doc.lineAt(clamp(region.start)).number;
    const last = state.doc.lineAt(clamp(region.end - 1)).number;
    for (let number = first; number <= last; number++) {
      const classes = lines.get(number) || new Set<string>();
      classes.add(`cm-txtRegion-${region.kind}`);
      if (strong) classes.add(`cm-txtRegion-${region.kind}-strong`);
      lines.set(number, classes);
    }
  }
  return Decoration.set([...lines].sort((a, b) => a[0] - b[0])
    .map(([number, classes]) => Decoration.line({ class: [...classes].sort().join(" ") }).range(state.doc.line(number).from)));
}

const regionField = StateField.define<RegionState>({
  create: () => ({ regions: [], labels: "selected", deco: Decoration.none }),
  update(value, tr) {
    let { regions, labels } = value;
    if (tr.docChanged) regions = regions.map((region) => ({ ...region, start: tr.changes.mapPos(region.start, -1), end: tr.changes.mapPos(region.end, 1) }));
    let changed = tr.docChanged || tr.selection !== undefined;
    for (const effect of tr.effects) {
      if (effect.is(setRegions)) { regions = effect.value; changed = true; }
      if (effect.is(setLabels)) { labels = effect.value; changed = true; }
    }
    return changed ? { regions, labels, deco: regionDecoration(tr.state, regions, labels) } : value;
  },
  provide: (field) => EditorView.decorations.from(field, (value) => value.deco),
});

/** 문제 표지 층(IDE-05) — 필드·표지 강조와 **다른** StateField 다. 같은 배열에 섞으면 `usableSpans` 가 겹친 뒤
 *  조각을 버려 문제가 사라진다. 문서가 바뀌면 매핑으로 따라가고 새 판정이 오면 갈아 끼운다. */
const problemField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    let next = value.map(tr.changes);
    for (const effect of tr.effects) {
      if (effect.is(setProblems)) {
        next = Decoration.set(problemMarks(effect.value, tr.state.doc.toString()).map((mark) =>
          Decoration.mark({ class: mark.className, attributes: { title: mark.title } }).range(mark.from, mark.to)), true);
      }
    }
    return next;
  },
  provide: (field) => EditorView.decorations.from(field),
});

/** 표지 짝 층(IDE-05) — 짝 목록(매핑으로 따라간다)과 지금 캐럿이 고른 짝 줄 장식. */
type PairState = { pairs: readonly LintpadPair[]; deco: DecorationSet };

function pairDecoration(state: EditorState, pairs: readonly LintpadPair[]): DecorationSet {
  const clamp = (offset: number) => Math.max(0, Math.min(offset, state.doc.length));
  const caret = state.doc.lineAt(state.selection.main.head).number;
  const lines = new Set<number>();
  for (const pair of pairs) {
    const open = state.doc.lineAt(clamp(pair.open)).number;
    const close = state.doc.lineAt(clamp(pair.close)).number;
    if (open === close) continue;
    if (caret === open) lines.add(close);
    else if (caret === close) lines.add(open);
  }
  return Decoration.set([...lines].sort((a, b) => a - b)
    .map((number) => Decoration.line({ class: "cm-authoring-pair" }).range(state.doc.line(number).from)));
}

const pairField = StateField.define<PairState>({
  create: () => ({ pairs: [], deco: Decoration.none }),
  update(value, tr) {
    let pairs = tr.docChanged
      ? value.pairs.map((pair) => ({ open: tr.changes.mapPos(pair.open), close: tr.changes.mapPos(pair.close) }))
      : value.pairs;
    let changed = tr.docChanged || tr.selection !== undefined;
    for (const effect of tr.effects) {
      if (effect.is(setPairs)) { pairs = effect.value; changed = true; }
    }
    return changed ? { pairs, deco: pairDecoration(tr.state, pairs) } : value;
  },
  provide: (field) => EditorView.decorations.from(field, (value) => value.deco),
});

/** 한 층이 그린 조각 1건 — 단위 창구의 평범한 얼굴. `token` 층은 원문을 가린 이름표다(`label` 이 보이는 글자). */
export type LintpadDrawn = {
  layer: "span" | "token" | "problem" | "pair" | "region"; from: number; to: number; className: string;
  title?: string; label?: string; region?: string; role?: string;
};

/** 장식 층(강조·이름표·문제·짝·범위 막대)이 한 문서에서 실제로 무엇을 그리는가 — DOM 없이 상태만 세워 확인하는 단위 창구.
 *  `edits` 는 판정을 얹은 **뒤** 친 편집이다(판정 왕복 사이의 매핑을 잰다). `atoms` 는 원자 범위 facet 이 편집기에
 *  실제로 내주는 범위다. vendor 타입은 밖으로 나가지 않는다(평범한 조각 목록만 돌려준다). */
export function lintpadDecorations(
  doc: string, spec: {
    spans?: readonly LintpadSpan[]; problems?: readonly LintpadProblem[]; pairs?: readonly LintpadPair[]; caret?: number;
    labels?: LintpadLabels; regions?: readonly LintpadRegion[]; edits?: readonly { start: number; end: number; text: string }[];
  },
): LintpadDrawn[] & { doc: string; atoms: { from: number; to: number }[] } {
  let state = EditorState.create({ doc, extensions: [spanField, regionField, problemField, pairField] });
  state = state.update({
    effects: [setSpans.of(spec.spans || []), setProblems.of(spec.problems || []), setPairs.of(spec.pairs || []),
      ...(spec.labels ? [setLabels.of(spec.labels)] : []), setRegions.of(spec.regions || [])],
    selection: spec.caret === undefined ? undefined : { anchor: spec.caret },
  }).state;
  if (spec.edits?.length) state = state.update({ changes: spec.edits.map((edit) => ({ from: edit.start, to: edit.end, insert: edit.text })) }).state;
  const out: LintpadDrawn[] = [];
  const read = (layer: LintpadDrawn["layer"], set: DecorationSet) => set.between(0, state.doc.length, (from, to, value) => {
    const widget = value.spec.widget;
    if (widget instanceof NameTag) {
      out.push({ layer: "token", from, to, className: widget.className, label: widget.label,
        ...(widget.region ? { region: widget.region, role: widget.role } : {}) });
      return;
    }
    const attributes = value.spec.attributes as Record<string, string> | undefined;
    out.push({ layer, from, to, className: String(value.spec.class), ...(attributes?.title ? { title: attributes.title } : {}) });
  });
  read("span", state.field(spanField).deco);
  read("region", state.field(regionField).deco);
  read("problem", state.field(problemField));
  read("pair", state.field(pairField).deco);
  // 원자 범위는 facet 을 거쳐 읽는다 — 편집기가 캐럿·지우기에 쓰는 바로 그 값이다(facet 함수는 view.state 만 읽는다).
  const atoms: { from: number; to: number }[] = [];
  for (const source of state.facet(EditorView.atomicRanges)) {
    source({ state } as unknown as EditorView).between(0, state.doc.length, (from, to) => { atoms.push({ from, to }); });
  }
  return Object.assign(out, { doc: state.doc.toString(), atoms });
}

/** 메모장 기본 모습 — 색·굵기는 제품 CSS(`frontend/css/editor.css`)가 토큰으로 소유한다.
 *  여기서는 레이아웃만 세운다(vendor 테마가 제품 팔레트를 발명하지 않게 한다). */
const BASE_THEME: Extension = EditorView.theme({
  "&": { fontSize: "var(--fs-body)" },
  "&.cm-focused": { outline: "none" },       // 초점 표지는 제품 CSS 가 그린다
  ".cm-content": { padding: "var(--sp-10)" },
  ".cm-scroller": { lineHeight: "1.6" },
});

/** 검색 패널(Ctrl+F)의 **배치**만 — 색·테두리는 `frontend/css/authoring.css` 가 토큰으로 칠한다.
 *  vendor 기본은 글자를 70~80% 로 줄이고 조작 사이를 em 여백으로 띄운다. 제품 입력·버튼과
 *  같은 크기·안쪽 여백으로 맞춘다. */
const PANEL_THEME: Extension = EditorView.theme({
  ".cm-panel.cm-search": { padding: "var(--sp-6) 2.5rem var(--sp-6) var(--sp-8)" },
  ".cm-panel.cm-search input, .cm-panel.cm-search button, .cm-panel.cm-search label": {
    margin: "var(--sp-2) var(--sp-8) var(--sp-2) 0",
  },
  ".cm-panel.cm-search label": { fontSize: "var(--fs-body)" },
  ".cm-panel.cm-search [name=close]": { top: "var(--sp-4)", right: "var(--sp-8)", fontSize: "var(--fs-strong)" },
  ".cm-textfield": { fontSize: "var(--fs-body)", padding: "var(--sp-4) var(--sp-8)" },
  ".cm-button": { fontSize: "var(--fs-body)", padding: "var(--sp-4) var(--sp-10)" },
});

/** 앱이 지금 어두운 테마인가 — `tokens.css` 와 같은 판정 순서다: `html[data-theme]` 의
 *  명시값이 이기고, 없으면(「시스템」) OS 선호를 따른다. 순수 함수라 단위로 잰다. */
export function lintpadIsDark(themeAttribute: string | null, systemDark: boolean): boolean {
  if (themeAttribute === "dark") return true;
  if (themeAttribute === "light") return false;
  return systemDark;
}

/** 어두운 테마 표지의 자리. vendor 는 이 facet 으로 `&dark`/`&light` 기본 규칙을 고른다 —
 *  넘기지 않으면 어두운 앱 안에서 검색 패널이 밝은 기본으로 그려진다. */
const darkness = new Compartment();
const darkFacet = (dark: boolean): Extension => EditorView.darkTheme.of(dark);

/** 같은 확장 조합에서 facet 이 실제로 켜지는가 — DOM 없이 상태만 세워 확인하는 단위 창구.
 *  vendor 타입은 밖으로 나가지 않는다(boolean 만 돌려준다). */
export function lintpadDarkFacet(dark: boolean): boolean {
  return EditorState.create({ extensions: [darkness.of(darkFacet(dark))] }).facet(EditorView.darkTheme);
}

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function currentDark(): boolean {
  return lintpadIsDark(document.documentElement.getAttribute("data-theme"), systemPrefersDark());
}

/** 테마 전환을 뒤따른다 — `data-theme` 속성 변화와 OS 선호 변화 둘 다. 해제 함수를 돌려준다. */
function watchTheme(view: EditorView): () => void {
  let dark = currentDark();
  const sync = () => {
    const next = currentDark();
    if (next === dark) return;
    dark = next;
    view.dispatch({ effects: darkness.reconfigure(darkFacet(next)) });
  };
  const observer = typeof MutationObserver === "function" ? new MutationObserver(sync) : null;
  observer?.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const media = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  media?.addEventListener("change", sync);
  return () => {
    observer?.disconnect();
    media?.removeEventListener("change", sync);
  };
}

/** 손잡이 → 테마 감시 해제. 뷰와 같은 수명이다. */
const THEME_WATCHES = new WeakMap<LintpadHandle, () => void>();

/** 선택 끝 줄(호스트 좌표) — 편집면 밖 표면이 그 아래에 선다(IDE-08). */
export type LintpadLineRect = { left: number; top: number; bottom: number };

/** 선택 끝 줄 보고의 **순수** 상태(IDE-08) — vendor 타입이 없어 단위로 잰다. 포인터가 눌린 동안은 끄는 중이라 재지 않고
 *  놓는 순간 잰다. 선택이 바뀌면 먼저 걷고 다시 잰다. 편집되면 걷는다. 같은 null 은 거듭 보내지 않는다. `measure` 는 지금
 *  선택의 끝 줄을 재어 `measured` 로 돌려주는 요청이다(비어 있으면 null). */
export function selectionRectTracker(report: (rect: LintpadLineRect | null) => void) {
  let shown = false, pointerDown = false;
  const hide = () => { if (shown) { shown = false; report(null); } };
  return {
    press() { pointerDown = true; hide(); },
    release(measure: () => void) { pointerDown = false; measure(); },
    selected(empty: boolean, measure: () => void) { hide(); if (!pointerDown && !empty) measure(); },
    edited() { hide(); },
    measured(rect: LintpadLineRect | null) { if (!rect) { hide(); return; } shown = true; report(rect); },
  };
}

/** 선택 끝 줄 좌표의 측정 열쇠 — 같은 틀 안의 여러 요청은 한 번만 잰다. */
const RECT_MEASURE = {};

/** 위 상태의 vendor 얼굴 — mousedown·선택·편집을 CodeMirror 에서 받아 끝(head) 좌표를 잰다. */
function selectionRectExtension(report: (rect: LintpadLineRect | null) => void): Extension {
  const tracker = selectionRectTracker(report);
  const measure = (view: EditorView) => () => view.requestMeasure({ key: RECT_MEASURE,
    read: (current) => {
      const main = current.state.selection.main;
      if (main.empty) return null;
      // 앞으로 고른 범위의 끝은 앞 글자 쪽, 뒤로 고른 범위의 끝은 뒤 글자 쪽 좌표다 — 줄 끝에서 다음 줄로 넘어가지 않는다.
      const coords = current.coordsAtPos(main.head, main.head === main.to ? -1 : 1);
      return coords ? { left: coords.left, top: coords.top, bottom: coords.bottom } : null;
    },
    write: (rect) => tracker.measured(rect) });
  return [
    EditorView.domEventHandlers({
      mousedown: (_event, view) => {
        tracker.press();
        // 닫힌 뷰(dom 이 문서에서 떨어진 뒤)에 늦게 온 mouseup 은 재지 않는다.
        view.dom.ownerDocument.defaultView?.addEventListener("mouseup", () => tracker.release(view.dom.isConnected ? measure(view) : () => {}), { once: true });
        return false;
      },
    }),
    EditorView.updateListener.of((update) => {
      if (update.docChanged) tracker.edited();
      else if (update.selectionSet) tracker.selected(update.state.selection.main.empty, measure(update.view));
    }),
  ];
}

/* ---------- 범위 고르기(두 번 누름): 누른 자리를 알리고, 시작부터 포인터 아래까지 고무줄 범위를 칠한다 ---------- */
const setPickBand = StateEffect.define<{ from: number; to: number } | null>();
const pickField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    let next = value.map(tr.changes);
    for (const effect of tr.effects) {
      if (!effect.is(setPickBand)) continue;
      const band = effect.value;
      if (!band) { next = Decoration.none; continue; }
      const from = Math.max(0, Math.min(band.from, band.to, tr.state.doc.length));
      const to = Math.min(tr.state.doc.length, Math.max(band.from, band.to));
      next = to > from ? Decoration.set([Decoration.mark({ class: "cm-authoring-rangepick" }).range(from, to)])
        : Decoration.set([Decoration.line({ class: "cm-authoring-rangepick-line" }).range(tr.state.doc.lineAt(from).from)]);
    }
    return next;
  },
  provide: (field) => EditorView.decorations.from(field),
});
/** 누름과 뗌 사이의 이동이 이보다 작으면 끌기가 아니라 누름이다(CSS px). */
const PICK_SLOP = 5;
type PickState = { on: boolean; start: number | null; pointer: { x: number; y: number } | null; press: { x: number; y: number } | null; frame: number };
const PICKS = new WeakMap<EditorView, PickState>();

function pickBand(view: EditorView) {
  const pick = PICKS.get(view);
  if (!pick || pick.frame) return;
  pick.frame = requestAnimationFrame(() => {
    pick.frame = 0;
    if (!pick.on || pick.start === null) { view.dispatch({ effects: setPickBand.of(null) }); return; }
    const under = pick.pointer ? view.posAtCoords(pick.pointer) : null;
    view.dispatch({ effects: setPickBand.of({ from: pick.start, to: under ?? pick.start }) });
  });
}

/** 켠 동안 문서 누름은 캐럿을 옮기지 않고 끌기도 시작하지 않는다 — 뗌이 누름 자리 곁이면 그 위치를 알린다. 키는 그대로다. */
function rangePickExtension(onPick: (offset: number) => void): Extension {
  return [pickField, EditorView.domEventHandlers({
    mousedown(event, view) {
      const pick = PICKS.get(view);
      if (!pick?.on || event.button !== 0) return false;
      event.preventDefault();
      pick.press = { x: event.clientX, y: event.clientY };
      const release = (up: MouseEvent) => {
        view.dom.ownerDocument.removeEventListener("mouseup", release, true);
        const press = pick.press;
        pick.press = null;
        if (!pick.on || !press || Math.hypot(up.clientX - press.x, up.clientY - press.y) > PICK_SLOP) return;
        const at = view.posAtCoords({ x: up.clientX, y: up.clientY });
        if (at !== null) onPick(at);
      };
      view.dom.ownerDocument.addEventListener("mouseup", release, true);
      return true;
    },
    mousemove(event, view) {
      const pick = PICKS.get(view);
      if (!pick?.on) return false;
      pick.pointer = { x: event.clientX, y: event.clientY };
      pickBand(view);
      return false;
    },
    scroll(_event, view) { if (PICKS.get(view)?.on) pickBand(view); return false; },
  })];
}

/** 범위 고르기를 켜고 끈다 — `false` 끔, `null` 켬(시작 전), 수는 그 시작에서 포인터 아래까지 칠한다. */
export function setLintpadRangePick(handle: LintpadHandle, state: number | null | false): void {
  const view = VIEWS.get(handle);
  const pick = view && PICKS.get(view);
  if (!view || !pick) return;
  pick.on = state !== false;
  pick.start = typeof state === "number" ? state : null;
  if (!pick.on) { pick.pointer = null; pick.press = null; }
  pickBand(view);
}

/** 마운트 — vendor 인스턴스 생성의 **유일한** 자리(`mount_owner`). */
export function mountLintpad(spec: LintpadMountSpec): LintpadHandle {
  const handle: LintpadHandle = { host: spec.host };
  const view = new EditorView({
    parent: spec.host,
    state: EditorState.create({
      doc: spec.doc,
      extensions: [
        ...(spec.authoring ? [history(), keymap.of(historyKeymap), search(), lineNumbers()] : []),
        EditorState.readOnly.of(!!spec.readOnly),
        EditorView.editable.of(!spec.readOnly),
        EditorView.domEventHandlers({
          compositionstart: () => { spec.onCompositionChanged?.(true); return false; },
          compositionend: () => { spec.onCompositionChanged?.(false); return false; },
        }),
        EditorView.lineWrapping,
        EditorView.contentAttributes.of({
          id: spec.contentId,
          "aria-label": spec.ariaLabel,
        }),
        ...(spec.onSelectionRect ? [selectionRectExtension(spec.onSelectionRect)] : []),
        ...(spec.onRangePick ? [rangePickExtension(spec.onRangePick)] : []),
        spanField,
        regionField,
        problemField,
        pairField,
        BASE_THEME,
        PANEL_THEME,
        darkness.of(darkFacet(currentDark())),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) spec.onDocChanged(update.state.doc.toString());
          if (update.selectionSet || update.docChanged) {
            const range = update.state.selection.main;
            spec.onSelectionChanged?.({ start: range.from, end: range.to });
          }
        }),
      ],
    }),
  });
  VIEWS.set(handle, view);
  if (spec.onRangePick) PICKS.set(view, { on: false, start: null, pointer: null, press: null, frame: 0 });
  THEME_WATCHES.set(handle, watchTheme(view));
  return handle;
}

/** 작업대 명령은 vendor 객체를 노출하지 않고 기존 view를 조작한다. */
export function lintpadState(handle: LintpadHandle) {
  const view = VIEWS.get(handle);
  if (!view) throw new Error("TXT 편집기가 닫혔습니다.");
  return {
    text: view.state.doc.toString(),
    start: view.state.selection.main.from,
    end: view.state.selection.main.to,
    canUndo: undoDepth(view.state) > 0,
    canRedo: redoDepth(view.state) > 0,
    composing: view.composing,
  };
}

export function editLintpad(handle: LintpadHandle, edits: readonly { start: number; end: number; text: string }[]) {
  const view = VIEWS.get(handle);
  if (!view) throw new Error("TXT 편집기가 닫혔습니다.");
  if (view.composing) return false;
  view.dispatch({
    changes: edits.map((edit) => ({ from: edit.start, to: edit.end, insert: edit.text })),
    annotations: [isolateHistory.of("full"), Transaction.userEvent.of("input.authoring")],
    scrollIntoView: true,
  });
  view.focus();
  return true;
}

export function navigateLintpad(handle: LintpadHandle, start: number, end = start) {
  const view = VIEWS.get(handle);
  if (!view) return;
  const limit = view.state.doc.length;
  if (view.composing) return;
  const clamp = (offset: number) => Math.max(0, Math.min(offset, limit));
  // 밖에서 온 좌표가 가린 토큰 안이면 경계로 민다 — 캐럿이 보이지 않는 표기 안에 서지 않는다(FB-03).
  const [anchor, head] = snapOutOfTokens(atomList(view.state), clamp(start), clamp(end));
  view.dispatch({ selection: { anchor, head }, scrollIntoView: true });
  view.focus();
}

export function lintpadCommand(handle: LintpadHandle, command: "undo" | "redo" | "search") {
  const view = VIEWS.get(handle);
  if (!view || view.composing) return false;
  return ({ undo, redo, search: openSearchPanel })[command](view);
}

/** 외부 상태 → 뷰(`update_owner`). 문서 교체와 강조 갱신을 **한 트랜잭션**으로 보낸다. */
export function updateLintpad(handle: LintpadHandle, spec: LintpadUpdateSpec): void {
  const view = VIEWS.get(handle);
  if (view === undefined) return;
  // 강조만 바꾸는 호출(장식)은 문서 전체를 문자열로 만들지 않는다 — 비교할 새 문서가 있을 때만 읽는다.
  const replacing = spec.doc !== undefined && spec.doc !== view.state.doc.toString();
  const effects = [
    ...(spec.labels === undefined ? [] : [setLabels.of(spec.labels)]),
    ...(spec.spans === undefined ? [] : [setSpans.of(spec.spans)]),
    ...(spec.regions === undefined ? [] : [setRegions.of(spec.regions)]),
    ...(spec.problems === undefined ? [] : [setProblems.of(spec.problems)]),
    ...(spec.pairs === undefined ? [] : [setPairs.of(spec.pairs)]),
  ];
  if (!replacing && !effects.length) return;
  view.dispatch({
    changes: replacing
      ? { from: 0, to: view.state.doc.length, insert: spec.doc }
      : undefined,
    effects,
  });
}

/** 해제(`dispose_owner`) — React 언마운트가 부른다. 두 번 불러도 안전하다. */
export function disposeLintpad(handle: LintpadHandle): void {
  const view = VIEWS.get(handle);
  if (view === undefined) return;
  VIEWS.delete(handle);
  THEME_WATCHES.get(handle)?.();
  THEME_WATCHES.delete(handle);
  view.destroy();
}
