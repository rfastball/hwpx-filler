/* R1-02 소유권 인벤토리 — React effect cleanup 리스너 대칭 축.
 *
 * `addEventListener`/`removeEventListener` 호출을 (대상·타입·핸들러·옵션) 신원으로 짝지어
 * add 만 있거나 remove 만 있는 잔차를 낸다. 신원은 메인의 `expressionIdentity`(상시 예외)를
 * 그대로 쓴다.
 */
import { normalizedNodeText } from "./ts_core.mjs";
// eslint 순환 의존 경고 대상이 아니다 — 메인 파일의 상시 예외 함수를 호출만 한다.
import { expressionIdentity } from "../extract_js_ast_axes.mjs";

function buildListenerSignature(node, callee, ctx) {
  return [
    ctx.rel,
    expressionIdentity(callee.expression, ctx.checker, ctx.sourceFile, ctx.iterationBindings),
    normalizedNodeText(node.arguments[0], ctx.sourceFile),
    expressionIdentity(node.arguments[1], ctx.checker, ctx.sourceFile, ctx.iterationBindings),
    normalizedNodeText(node.arguments[2], ctx.sourceFile),
  ].join("|");
}

export function trackListenerCall(node, callee, called, ctx) {
  const signature = buildListenerSignature(node, callee, ctx);
  const pair = ctx.listenerPairs.get(signature) ?? { adds: [], removes: [] };
  const entry = {
    rel: ctx.rel,
    line: ctx.lineOf(node.getStart(ctx.sourceFile)),
    text: node.getText(ctx.sourceFile).replace(/\s+/g, " "),
  };
  pair[called === "addEventListener" ? "adds" : "removes"].push(entry);
  ctx.listenerPairs.set(signature, pair);
}

export function computeCleanupGaps(listenerPairs) {
  const cleanupGaps = [];
  for (const pair of listenerPairs.values()) {
    if (pair.adds.length > pair.removes.length) {
      for (const entry of pair.adds.slice(pair.removes.length)) {
        cleanupGaps.push(`add:${entry.rel}:${entry.line}:${entry.text}`);
      }
    } else if (pair.removes.length > pair.adds.length) {
      for (const entry of pair.removes.slice(pair.adds.length)) {
        cleanupGaps.push(`remove:${entry.rel}:${entry.line}:${entry.text}`);
      }
    }
  }
  return cleanupGaps;
}
