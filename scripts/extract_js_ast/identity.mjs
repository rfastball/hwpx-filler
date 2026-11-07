/* R1-02 소유권 인벤토리 — 심볼 신원·for-of 바인딩 별칭.
 *
 * `expressionIdentity`(메인 파일에 남는 평평한 분배 표, 상시 예외)가 쓰는 심볼 해소와
 * for-of 반복 변수의 origin 별칭을 모은다. `collectIterationBindings`는 메인의
 * `expressionIdentity`를 되부른다 — 순환 의존이지만 둘 다 호출 시점(런타임)에만 쓰이고
 * 모듈 평가 시점에는 쓰이지 않으므로 ESM의 라이브 바인딩으로 안전하다.
 */
import { ts, TypeScriptSymbolFlags } from "./runtime.mjs";
import { tsBindingIdentifiers } from "./ts_core.mjs";
// eslint 순환 의존 경고 대상이 아니다 — 메인 파일의 상시 예외 함수를 호출만 한다.
import { expressionIdentity } from "../extract_js_ast_axes.mjs";

export function symbolProvenance(checker, node) {
  let symbol = checker.getSymbolAtLocation(node);
  if (!symbol) return null;
  if ((symbol.flags & TypeScriptSymbolFlags.Alias) !== 0) {
    try {
      symbol = checker.getAliasedSymbol(symbol);
    } catch {
      // 깨진 alias도 아래 선언 좌표로 fail-closed 식별한다.
    }
  }
  return `symbol:${symbol.id}`;
}

export function aliasKey(identifier, checker, sourceFile) {
  return symbolProvenance(checker, identifier)
    ?? `${sourceFile.fileName}:${identifier.getStart(sourceFile)}`;
}

export function collectIterationBindings(sourceFile, checker) {
  const bindings = new Map();
  function collect(node) {
    if (ts.isForOfStatement(node) && ts.isVariableDeclarationList(node.initializer)) {
      const origin = `for-of:${expressionIdentity(node.expression, checker, sourceFile)}`;
      for (const declaration of node.initializer.declarations) {
        for (const identifier of tsBindingIdentifiers(declaration.name)) {
          bindings.set(aliasKey(identifier, checker, sourceFile), origin);
        }
      }
    }
    node.forEachChild(collect);
  }
  collect(sourceFile);
  return bindings;
}
