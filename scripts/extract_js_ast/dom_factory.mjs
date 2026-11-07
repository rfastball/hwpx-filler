/* R1-02 소유권 인벤토리 — DOM 생성 팩토리 별칭 추적.
 *
 * `domFactoryOrigin`(메인 파일에 남는 평평한 분배 표, 상시 예외)이 가리키는 변수·바인딩이
 * 실제로 `document.createElement` 류를 가리키는지 고정점(fixpoint)으로 푼다.
 * `collectDomFactoryAliases`는 원래 분기 하나에 「변수 선언 alias」·「대입 alias」·
 * 「구조분해 alias」세 성격이 섞여 복잡도 예산을 넘었다 — 성격별로 이름이 선 함수로 쪼갠다.
 * 고정점 수렴 결과(최종 aliases 맵)는 내부에서 어느 후보를 먼저 보든 같으므로 분기 순서를
 * 바꿔도 출력은 같다.
 */
import { ts } from "./runtime.mjs";
import { aliasKey } from "./identity.mjs";
import {
  bindingElementPropertyName, normalizedNodeText, propertyName, tsBindingIdentifiers,
  unwrapExpression,
} from "./ts_core.mjs";
// eslint 순환 의존 경고 대상이 아니다 — 메인 파일의 상시 예외 함수를 호출만 한다.
import { domFactoryOrigin } from "../extract_js_ast_axes.mjs";

export const DOM_FACTORY_NAMES = new Set(["createElement", "createElementNS", "insertAdjacentHTML"]);

function setAliasIfChanged(aliases, key, origin) {
  if (origin === null || aliases.get(key) === origin) return false;
  aliases.set(key, origin);
  return true;
}

function aliasFromIdentifierDeclaration(candidate, aliases, checker, sourceFile, bindings) {
  if (!candidate.initializer || !ts.isIdentifier(candidate.name)) return false;
  const origin = domFactoryOrigin(candidate.initializer, aliases, checker, sourceFile, bindings);
  const key = aliasKey(candidate.name, checker, sourceFile);
  return setAliasIfChanged(aliases, key, origin);
}

function aliasFromBindingPatternDeclaration(candidate, aliases, checker, sourceFile, bindings) {
  if (!candidate.initializer || !ts.isObjectBindingPattern(candidate.name)) return false;
  let changed = false;
  for (const element of candidate.name.elements) {
    const name = bindingElementPropertyName(element, bindings);
    if (!DOM_FACTORY_NAMES.has(name)) continue;
    const origin = `${normalizedNodeText(candidate.initializer, sourceFile)}.${name}`;
    for (const identifier of tsBindingIdentifiers(element.name)) {
      const key = aliasKey(identifier, checker, sourceFile);
      if (setAliasIfChanged(aliases, key, origin)) changed = true;
    }
  }
  return changed;
}

function aliasFromVariableDeclaration(candidate, aliases, checker, sourceFile, bindings) {
  const byIdentifier = aliasFromIdentifierDeclaration(candidate, aliases, checker, sourceFile, bindings);
  const byPattern = aliasFromBindingPatternDeclaration(candidate, aliases, checker, sourceFile, bindings);
  return byIdentifier || byPattern;
}

function aliasFromAssignment(candidate, aliases, checker, sourceFile, bindings) {
  if (candidate.operatorToken.kind !== ts.SyntaxKind.EqualsToken || !ts.isIdentifier(candidate.left)) {
    return false;
  }
  const origin = domFactoryOrigin(candidate.right, aliases, checker, sourceFile, bindings);
  const key = aliasKey(candidate.left, checker, sourceFile);
  return setAliasIfChanged(aliases, key, origin);
}

function applyAliasCandidate(candidate, aliases, checker, sourceFile, bindings) {
  return ts.isVariableDeclaration(candidate)
    ? aliasFromVariableDeclaration(candidate, aliases, checker, sourceFile, bindings)
    : aliasFromAssignment(candidate, aliases, checker, sourceFile, bindings);
}

function collectAliasCandidates(sourceFile) {
  const candidates = [];
  function collect(node) {
    if (ts.isVariableDeclaration(node) || ts.isBinaryExpression(node)) candidates.push(node);
    node.forEachChild(collect);
  }
  collect(sourceFile);
  return candidates;
}

export function collectDomFactoryAliases(sourceFile, checker, bindings) {
  const aliases = new Map();
  const candidates = collectAliasCandidates(sourceFile);
  let changed = true;
  while (changed) {
    changed = false;
    for (const candidate of candidates) {
      if (applyAliasCandidate(candidate, aliases, checker, sourceFile, bindings)) changed = true;
    }
  }
  return aliases;
}

export function invokedDomFactory(callee, aliases, checker, sourceFile, bindings) {
  const current = unwrapExpression(callee);
  if (
    current
    && (ts.isPropertyAccessExpression(current) || ts.isElementAccessExpression(current))
    && ["call", "apply"].includes(propertyName(current, bindings))
  ) {
    return domFactoryOrigin(current.expression, aliases, checker, sourceFile, bindings);
  }
  return domFactoryOrigin(current, aliases, checker, sourceFile, bindings);
}
