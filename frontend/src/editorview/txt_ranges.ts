/* TXT 편집기의 범위 산술 — vendor 타입이 없는 순수 함수만 둔다(편집기 소유자 `txt_lintpad.ts` 가 쓴다). */

/** 튜토리얼이 고르라고 한 범위의 칠(#1136) — 한 줄 글자 칠(`guide`)이나 줄 칠(이 클래스)이다. */
export const GUIDE_CLASS = "cm-tutorial-range";

/** 튜토리얼 범위가 칠해져 있는가. 칠해진 동안 편집기는 고른 글 끌어 옮기기 대신 새 범위를 고른다(#1146). */
export function guidePainted(spans: readonly { kind: string; className?: string }[]): boolean {
  return spans.some((span) => span.kind === "guide" || span.className === GUIDE_CLASS);
}

/** 밖에서 옮긴 선택을 가린 토큰 밖으로 민다 — 캐럿은 가까운 쪽 경계로, 범위는 걸친 토큰을 통째로 담는다.
 *  편집기 자신의 캐럿·끌기는 원자 범위가 이미 막는다. 이것은 문제·검색·구조 목록에서 온 좌표를 위한 것이다 —
 *  캐럿이 가린 토큰 안에 서면 다음 글자가 보이지 않는 표기 안으로 들어간다. */
export function snapOutOfTokens(atoms: readonly { from: number; to: number }[], start: number, end: number): [number, number] {
  if (start === end) return snapCaret(atoms, start);
  let lo = Math.min(start, end), hi = Math.max(start, end);
  for (const atom of atoms) {
    if (atom.from < lo && lo < atom.to) lo = atom.from;
    if (atom.from < hi && hi < atom.to) hi = atom.to;
  }
  return start <= end ? [lo, hi] : [hi, lo];
}

/** 캐럿은 그것이 선 가린 토큰의 가까운 쪽 경계로 민다. */
function snapCaret(atoms: readonly { from: number; to: number }[], at: number): [number, number] {
  const inside = atoms.find((atom) => atom.from < at && at < atom.to);
  if (!inside) return [at, at];
  const side = at - inside.from <= inside.to - at ? inside.from : inside.to;
  return [side, side];
}
