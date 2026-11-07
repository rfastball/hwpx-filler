/* R1-02 소유권 인벤토리 — 파서 런타임 로딩.
 *
 * `extract_js_ast_axes.mjs`의 vite(oxc)·TypeScript compiler API 동적 import를 한 곳에 모은다.
 * 부재는 조용한 스킵이 아니라 사유를 말하는 실패다(아래 두 catch). 이 모듈 자체가 책임 분리
 * 단위의 하나이므로, import 실패 메시지는 분리 전과 바이트 단위로 같다.
 */

let parseAst;
try {
  ({ parseAst } = await import("vite"));
} catch (thrown) {
  throw new Error(
    "프런트 툴체인(`vite`)을 못 불렀습니다 — `npm ci` 가 먼저입니다. 이 추출기를 도는 게이트"
    + "(복잡도 예산·Node 계약 테스트)는 Node 를 전제하므로 부재는 스킵 사유가 아니라 실패입니다: "
    + `${thrown.message}`,
  );
}

let ts;
let TypeScriptAPI;
let TypeScriptSymbolFlags;
try {
  ts = await import("typescript/unstable/ast");
  ({
    API: TypeScriptAPI,
    SymbolFlags: TypeScriptSymbolFlags,
  } = await import("typescript/unstable/sync"));
} catch (thrown) {
  throw new Error(
    "TypeScript compiler API를 못 불렀습니다 — 제품 코드 DOM·state·listener 축은 정규식이 아니라 "
    + "parser를 전제로 합니다. `npm ci`가 먼저입니다: "
    + `${thrown.message}`,
  );
}

export { parseAst, ts, TypeScriptAPI, TypeScriptSymbolFlags };
