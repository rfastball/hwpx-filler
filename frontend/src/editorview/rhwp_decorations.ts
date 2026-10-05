/* HWPX 편집면 장식의 호스트 쪽 기록 — `rhwp_editor.ts` 의 `setDecorations` 가 쓴다.
 *
 * 상한(500)을 넘겨 덜어 낸 표지 종류(마운트당 한 번 콘솔 debug — 개발자 신호, 사용자 문안이 아니다)와 마지막으로 보낸 표지의
 * 자리 신원을 든다. 링크 표지(「데이터로 필드 찾기」 제안·보류, #1158)를 누르면 Studio 가 그 표지의 차례를 알리고, 여기서
 * 자리 신원으로 바꿔 호스트에 넘긴다 — 신원은 Studio 로 가지 않는다(검사기가 모르는 키를 거절한다). */
import { DECORATION_LIMIT, fitMarkers, problemMarkers, proposalMarkers } from "./rhwp_marks.ts";
import type { Marker } from "./rhwp_marks.ts";
import type { HostLineRect } from "./rhwp_editor.ts";

type Obj = Record<string, unknown>;
type ClientRect = { x: number; y: number; width: number; height: number };
/** Studio SDK 의 링크 표지 누름 — 옛 SDK 에는 없다(그때 자리는 캐럿으로만 열린다). */
type DecorationClicks = { onDecorationClick?(listener: (click: { index: number; kind: string; rect: ClientRect }) => void): () => void };
export type SpotClick = { token: string; rect: HostLineRect | null };

export function decorationLedger(editor: DecorationClicks, onClick: ((click: SpotClick) => void) | undefined,
  disposed: () => boolean, hostRect: (rect: ClientRect) => HostLineRect | null) {
  const noted = new Set<string>();
  let tokens: (string | null)[] = [];
  const relay = (click: { index: number; rect: ClientRect }) => {
    const token = tokens[click.index];
    if (token && !disposed()) onClick!({ token, rect: hostRect(click.rect) });
  };
  const off = onClick && typeof editor.onDecorationClick === "function" ? editor.onDecorationClick(relay) : () => {};
  const dropped = (kind: string, count: number) => {
    if (noted.has(kind)) return;
    noted.add(kind);
    console.debug(`rhwp: ${count} ${kind} markers dropped (decoration cap ${DECORATION_LIMIT})`);
  };
  return {
    /** 의미 표지 뒤에 연 제안 자리·문제·제안·보류를 상한 안 차례로 잇고, 보낼 표지마다의 자리 신원을 기억한다. */
    fit(base: Marker[], sectionEntries: readonly string[], projection: Obj): Marker[] {
      const proposals = proposalMarkers(sectionEntries, projection.proposals);
      const fitted = fitMarkers(base, { open: proposals.open, proposals: proposals.proposals, held: proposals.held,
        problems: problemMarkers(sectionEntries, projection.problems) }, dropped);
      tokens = fitted.map((made) => proposals.tokens.get(made) ?? null);
      return fitted;
    },
    off,
  };
}
