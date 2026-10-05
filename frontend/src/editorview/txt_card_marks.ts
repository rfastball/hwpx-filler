/* 검토·복사 작업대 본문의 **표식 층**(#1148 PR B) — `txt_lintpad.ts` 편집면에 얹는 값 칠·빈 자리 표지.
 *
 * 편집면의 vendor 수명(mount/update/dispose)은 여전히 `txt_lintpad.ts` 하나가 소유한다. 이 파일은 그 편집면이
 * 설치하는 상태 필드 하나와 그 효과·읽기 창구만 든다(`tests/architecture_contract.toml` 의 codemirror 배치 경로).
 * **판정은 여기 없다** — 표식의 종류·자리·채움은 Python 이 낸 그대로이고, 여기서는 문서 변경을 따라 자리를 옮기고
 * 그리기만 한다. */
import { StateEffect, StateField } from "@codemirror/state";
import type { EditorState, Range } from "@codemirror/state";
import { Decoration, EditorView, WidgetType } from "@codemirror/view";
import type { DecorationSet } from "@codemirror/view";

/** 본문 위 표식 1건(#1148 검토·복사 작업대) — 좌표는 UTF-16, 판정은 Python 이 낸 그대로다.
 *  길이 0 이고 `label` 이 있으면 그 자리에 표지(위젯)가 서고, 범위면 글자에 칠한다. 범위는 문서
 *  변경을 따라 옮겨 다니고(시작은 끼어든 글자 앞, 끝은 뒤), 그래서 표지 자리에 친 글자는 그 표식의
 *  범위가 된다 — 그때는 `filledClassName` 으로 칠한다. 표지 문구는 표면(호출자)이 소유한다. */
export type LintpadMark = {
  start: number;
  end: number;
  className: string;
  filledClassName?: string;
  label?: string;
  /** 표지·칠에 실을 `data-token`(필드 이름) — 튜토리얼 앵커·프로브가 이 신원으로 겨눈다. */
  token?: string;
  /** 표지(길이 0)를 보조 기술에서 숨긴다 — 본문 글자로 읽히면 안 되는 장식 표지(#1156 제안 이름표). */
  decorative?: boolean;
};

const setMarks = StateEffect.define<readonly LintpadMark[]>();

/** 길이 0 표식의 표지 — 글자가 아니라 자리라서 캐럿이 그 앞에 서고, 친 글자는 표식 범위로 들어간다. */
class HoleTag extends WidgetType {
  readonly label: string;
  readonly className: string;
  readonly token: string;
  readonly decorative: boolean;
  constructor(label: string, className: string, token: string, decorative = false) {
    super();
    this.label = label; this.className = className; this.token = token; this.decorative = decorative;
  }
  eq(other: HoleTag): boolean {
    return other.label === this.label && other.className === this.className && other.token === this.token && other.decorative === this.decorative;
  }
  toDOM(): HTMLElement {
    const el = document.createElement("span");
    el.className = this.className;
    if (this.token) el.dataset.token = this.token;
    if (this.decorative) el.setAttribute("aria-hidden", "true");
    el.textContent = this.label;
    return el;
  }
  ignoreEvent(): boolean { return false; }
}

function markDecoration(marks: readonly LintpadMark[]): DecorationSet {
  const ranges: Range<Decoration>[] = [];
  for (const mark of marks) {
    const attributes = mark.token ? { "data-token": mark.token } : undefined;
    if (mark.start === mark.end) {
      if (mark.label) {
        ranges.push(Decoration.widget({
          widget: new HoleTag(mark.label, mark.className, mark.token || "", mark.decorative === true), side: 1,
        }).range(mark.start));
      }
    } else {
      const filled = mark.label !== undefined && mark.filledClassName !== undefined;
      ranges.push(Decoration.mark({
        class: filled ? mark.filledClassName : mark.className, attributes,
      }).range(mark.start, mark.end));
    }
  }
  return Decoration.set(ranges, true);
}

type MarkState = { marks: readonly LintpadMark[]; deco: DecorationSet };

export const markField = StateField.define<MarkState>({
  create: () => ({ marks: [], deco: Decoration.none }),
  update(value, tr) {
    let marks = value.marks;
    if (tr.docChanged) {
      marks = marks.map((mark) => {
        const start = tr.changes.mapPos(mark.start, -1);
        return { ...mark, start, end: Math.max(start, tr.changes.mapPos(mark.end, 1)) };
      });
    }
    for (const effect of tr.effects) if (effect.is(setMarks)) marks = effect.value;
    return marks === value.marks ? value : { marks, deco: markDecoration(marks) };
  },
  provide: (field) => EditorView.decorations.from(field, (value) => value.deco),
});

/** 받은 표식 전집 → 상태 효과. 없거나 `current` 가 아니면(Python 이 본 문서가 지금 문서와 다르면) 효과 없음 —
 *  편집면이 들고 있는 표식을 변경에 따라 옮겨 둔 그대로 둔다. */
export function markEffects(marks: readonly LintpadMark[] | undefined, current = true) {
  return current && marks !== undefined ? [setMarks.of(marks)] : [];
}

/** 표식 층이 지금 그리는 조각 — 단위 창구(`lintpadDecorations`)의 `mark` 층. */
export function markPieces(state: EditorState) {
  const out: { layer: "mark"; from: number; to: number; className: string; label?: string }[] = [];
  state.field(markField).deco.between(0, state.doc.length, (from, to, value) => {
    const widget = value.spec.widget;
    out.push(widget instanceof HoleTag
      ? { layer: "mark", from, to, className: widget.className, label: widget.label }
      : { layer: "mark", from, to, className: String(value.spec.class) });
  });
  return out;
}
