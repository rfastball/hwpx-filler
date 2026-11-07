/* R1-02 소유권 인벤토리 — TypeScript AST 공용 판독기.
 *
 * `typescriptAxes`(및 거기서 파생하는 모든 보조 함수)가 공유하는 노드 판독 1차 함수들.
 * 값 판독(`literalString`·`propertyName`…)과 축 3 TS 쪽 모듈 상태(`tsModuleState`)를
 * 한 파일에 모은다 — 분리 전과 로직은 완전히 같다.
 */
import { ts } from "./runtime.mjs";

export function unwrapExpression(node) {
  let current = node;
  while (
    current
    && (ts.isParenthesizedExpression(current)
      || ts.isAsExpression(current)
      || ts.isTypeAssertion(current)
      || ts.isSatisfiesExpression(current)
      || ts.isNonNullExpression(current))
  ) {
    current = current.expression;
  }
  return current;
}

export function literalString(node, bindings, seen = new Set()) {
  const current = unwrapExpression(node);
  if (!current) return null;
  if (ts.isStringLiteral(current) || ts.isNoSubstitutionTemplateLiteral(current)) {
    return current.text;
  }
  if (ts.isIdentifier(current) && bindings.has(current.text) && !seen.has(current.text)) {
    seen.add(current.text);
    return literalString(bindings.get(current.text), bindings, seen);
  }
  return null;
}

export function constStringBindings(sourceFile) {
  const bindings = new Map();
  for (const statement of sourceFile.statements) {
    if (
      !ts.isVariableStatement(statement)
      || (statement.declarationList.flags & ts.NodeFlags.Const) === 0
    ) {
      continue;
    }
    for (const declaration of statement.declarationList.declarations) {
      if (ts.isIdentifier(declaration.name) && declaration.initializer) {
        bindings.set(declaration.name.text, declaration.initializer);
      }
    }
  }
  return bindings;
}

export function propertyName(node, bindings) {
  if (ts.isPropertyAccessExpression(node)) return node.name.text;
  if (ts.isElementAccessExpression(node)) {
    return literalString(node.argumentExpression, bindings);
  }
  return null;
}

export function objectPropertyName(node, bindings) {
  const name = node.name;
  if (!name) return null;
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) {
    return name.text;
  }
  if (ts.isComputedPropertyName(name)) return literalString(name.expression, bindings);
  return null;
}

export function assignmentOperator(kind) {
  return kind >= ts.SyntaxKind.FirstAssignment && kind <= ts.SyntaxKind.LastAssignment;
}

function isDatasetObject(node, bindings) {
  const current = unwrapExpression(node);
  return Boolean(
    current
    && (ts.isPropertyAccessExpression(current) || ts.isElementAccessExpression(current))
    && propertyName(current, bindings) === "dataset"
  );
}

export function datasetAttributeName(target, bindings) {
  const current = unwrapExpression(target);
  if (!current || (!ts.isPropertyAccessExpression(current) && !ts.isElementAccessExpression(current))) {
    return null;
  }
  if (!isDatasetObject(current.expression, bindings)) return null;
  const key = propertyName(current, bindings);
  if (key === null) return "<dynamic>";
  return `data-${key.replace(/([A-Z])/g, "-$1").toLowerCase()}`;
}

export function stringTokenText(node) {
  const stringKinds = new Set([
    ts.SyntaxKind.StringLiteral,
    ts.SyntaxKind.NoSubstitutionTemplateLiteral,
    ts.SyntaxKind.TemplateHead,
    ts.SyntaxKind.TemplateMiddle,
    ts.SyntaxKind.TemplateTail,
  ]);
  return stringKinds.has(node.kind) && typeof node.text === "string" ? node.text : null;
}

export function tsBindingIdentifiers(name, out = []) {
  if (!name) return out;
  if (ts.isIdentifier(name)) {
    out.push(name);
  } else if (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) {
    for (const element of name.elements) {
      if (ts.isBindingElement(element)) tsBindingIdentifiers(element.name, out);
    }
  }
  return out;
}

export function hasExportModifier(node) {
  return Boolean(node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword));
}

function tsMutableDeclarators(statements) {
  const identifiers = [];
  for (const statement of statements ?? []) {
    if (
      !ts.isVariableStatement(statement)
      || (statement.declarationList.flags & ts.NodeFlags.Const) !== 0
    ) continue;
    for (const declaration of statement.declarationList.declarations) {
      tsBindingIdentifiers(declaration.name, identifiers);
    }
  }
  return identifiers;
}

export function tsModuleState(sourceFile, rel, lineOf, { exported, includeProgram }) {
  const hits = includeProgram ? tsMutableDeclarators(sourceFile.statements) : [];
  for (const statement of sourceFile.statements) {
    if (
      ts.isFunctionDeclaration(statement)
      && Boolean(statement.body)
      && hasExportModifier(statement) === exported
    ) {
      hits.push(...tsMutableDeclarators(statement.body.statements));
    }
  }
  return hits.map(
    (identifier) => `${rel}:${lineOf(identifier.getStart(sourceFile))} ${identifier.text}`,
  );
}

export function tsIdSite(rel, sourceFile, lineOf, node, valueNode, bindings) {
  const value = literalString(valueNode, bindings);
  const current = unwrapExpression(valueNode);
  const prefix = value === null && current && ts.isTemplateExpression(current)
    ? current.head.text
    : "";
  return `${rel}:${lineOf(node.getStart(sourceFile))}:${value === null ? "dynamic" : "static"}:`
    + `${value ?? prefix}`;
}

export function normalizedNodeText(node, sourceFile) {
  return node ? node.getText(sourceFile).replace(/\s+/g, "") : "<default>";
}

export function bindingElementPropertyName(element, bindings) {
  const node = element.propertyName ?? element.name;
  if (ts.isIdentifier(node) || ts.isStringLiteral(node) || ts.isNumericLiteral(node)) {
    return node.text;
  }
  if (ts.isComputedPropertyName(node)) return literalString(node.expression, bindings);
  return null;
}
