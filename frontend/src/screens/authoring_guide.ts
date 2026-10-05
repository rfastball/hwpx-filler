/* 튜토리얼 범위 단계가 고르라고 한 범위(#1136)를 저작 편집면이 칠하는 자리.
 *
 * 범위(탭·UTF-16 좌표)는 Python 이 연습 문서에서 정하고 셸이 튜토리얼 투영에서 옮겨 준다. 여기는 그 범위를 탭별로 들고,
 * TXT 장식 좌표(편집기 vendor 소유자의 `LintpadSpan` 어휘)로 바꿀 뿐이다 — 무엇을 고르면 되는지는 다시 판정하지 않는다. */

export type GuideRange = { session_id: string; start: number; end: number };
type Span = { kind: string; start: number; end: number; className?: string };

/** 칠할 범위를 들고, 바뀌면 그 범위가 가리켰거나 가리키는 탭만 다시 칠하게 한다(`repaint`). 같은 범위의 재전송은 무시한다. */
export function guideFeed(repaint: (id: string) => void) {
  let current: GuideRange | null = null;
  return {
    /** 튜토리얼 범위 단계의 범위 — null 이면 걷는다. 선택·초점은 옮기지 않는다. */
    guide(range: GuideRange | null) {
      const next = range ? { session_id: range.session_id, start: range.start, end: range.end } : null;
      if (JSON.stringify(next) === JSON.stringify(current)) return;
      const touched = new Set([current?.session_id, next?.session_id]);
      current = next;
      for (const id of touched) if (id) repaint(id);
    },
    /** 그 탭에 칠할 범위 — 없으면 null. 편집기가 장식을 다시 보낼 때 함께 싣는다. */
    guideOf: (id: string): GuideRange | null => current && current.session_id === id ? current : null,
  };
}

/** 범위를 TXT 장식에 얹는다. 한 줄 안의 글자 범위는 그 글자만 칠한다(분석 조각과 겹치지 않을 때, 순서를 지켜 끼운다).
 *  그 밖(빈 범위·줄 전체·여러 줄)은 시작 줄부터 끝 자리가 든 줄까지 줄 전체를 칠한다 — 끝 자리가 다음 줄 머리면 그 줄까지가
 *  끌어 닿을 곳이다. 줄 강조는 끝 글자의 줄까지 칠하므로 끝을 한 칸 늘려 넘긴다. */
export function guideSpans(spans: readonly Span[], text: string, range: { start: number; end: number }): Span[] {
  const { start, end } = range;
  const lineStart = text.lastIndexOf("\n", start - 1) + 1;
  const lineEnd = text.indexOf("\n", start) < 0 ? text.length : text.indexOf("\n", start);
  const inLine = start < end && end <= lineEnd && (start > lineStart || end < lineEnd);
  if (inLine && spans.every((span) => span.end <= start || span.start >= end)) {
    const at = spans.findIndex((span) => span.start >= end);
    const mark = { kind: "guide", start, end };
    return at < 0 ? [...spans, mark] : [...spans.slice(0, at), mark, ...spans.slice(at)];
  }
  return [...spans, { kind: "highlight", className: "cm-tutorial-range", start, end: end + 1 }];
}
