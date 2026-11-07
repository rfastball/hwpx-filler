/* R1-02 소유권 인벤토리 — `typescriptAxes`의 AST 방문자가 노드마다 묻는 네 갈래 질문.
 *
 * 원래 하나의 `visit()` 안에 「문자열 토큰 markup/id 판독」·「호출식 setAttribute/팩토리
 * props/DOM 생성/리스너 짝짓기」·「대입식 dataset/innerHTML」·「JSX 속성」네 성격이 평평하게
 * 섞여 복잡도 예산을 크게 넘었다. 성격별로 이름이 선 함수로 쪼갠다 — `visit()`은 이제
 * 이 네 함수를 그대로 부르기만 한다. 각 판독 함수는 분리 전과 같은 순서로 같은 부수효과
 * (`ctx.add`·`ctx.gap`·`ctx.templateIds.push`·`ctx.directDom.push`·리스너 짝짓기)를 낸다.
 * 최종 payload의 모든 배열은 호출부에서 정렬되므로 호출 순서 자체는 출력에 드러나지 않는다.
 */
import { ts } from "./runtime.mjs";
import {
  assignmentOperator, datasetAttributeName, literalString, objectPropertyName, propertyName,
  stringTokenText, tsIdSite, unwrapExpression,
} from "./ts_core.mjs";
import { invokedDomFactory } from "./dom_factory.mjs";
import { trackListenerCall } from "./listener_tracking.mjs";
import {
  BARE_MARKUP_DATA_ATTR, DYNAMIC_MARKUP_DATA_ATTR, ID_ATTR, MARKUP_DATA_ATTR,
} from "./scope.mjs";

/* ── 문자열 토큰(템플릿·리터럴) ───────────────────────────────────── */

function checkMarkupDataAttrText(node, token, ctx) {
  if (!token.includes("<")) return;
  MARKUP_DATA_ATTR.lastIndex = 0;
  for (const match of token.matchAll(MARKUP_DATA_ATTR)) ctx.add(match[1]);
}

function isMarkupFragmentLiteral(node) {
  const literal = node.parent && ts.isTemplateExpression(node.parent) ? node.parent : node;
  const parent = literal.parent;
  return Boolean(parent && (
    (ts.isVariableDeclaration(parent) && parent.initializer === literal)
    || (ts.isArrowFunction(parent) && parent.body === literal)
  ));
}

function checkBareMarkupDataAttrText(node, token, ctx) {
  if (!isMarkupFragmentLiteral(node)) return;
  BARE_MARKUP_DATA_ATTR.lastIndex = 0;
  for (const match of token.matchAll(BARE_MARKUP_DATA_ATTR)) ctx.add(match[1]);
}

function checkDynamicMarkupName(node, token, ctx) {
  const isTemplateHeadOrMiddle = node.kind === ts.SyntaxKind.TemplateHead
    || node.kind === ts.SyntaxKind.TemplateMiddle;
  if (isTemplateHeadOrMiddle && DYNAMIC_MARKUP_DATA_ATTR.test(token)) {
    ctx.gap("dynamic-markup-name", node);
  }
}

function checkTemplateIdToken(node, token, ctx) {
  if (!ctx.usesTsOwnershipAxes) return;
  ID_ATTR.lastIndex = 0;
  for (const match of token.matchAll(ID_ATTR)) {
    const isDynamic = match[1] !== undefined;
    ctx.templateIds.push(
      `${ctx.rel}:${ctx.lineOf(node.getStart(ctx.sourceFile) + match.index)}:`
      + `${isDynamic ? "dynamic" : "static"}:${isDynamic ? match[1] : match[2]}`,
    );
  }
}

export function handleStringToken(node, ctx) {
  const token = stringTokenText(node);
  if (token === null) return;
  checkMarkupDataAttrText(node, token, ctx);
  checkBareMarkupDataAttrText(node, token, ctx);
  checkDynamicMarkupName(node, token, ctx);
  checkTemplateIdToken(node, token, ctx);
}

/* ── 호출식 ───────────────────────────────────────────────────────── */

const DOM_FACTORY_CALL_NAMES = ["createElement", "el", "h"];

function calledMethodName(callee, bindings) {
  return callee && (ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee))
    ? propertyName(callee, bindings)
    : null;
}

function checkSetAttributeCall(node, called, ctx) {
  if (called !== "setAttribute" || node.arguments.length === 0) return;
  const name = literalString(node.arguments[0], ctx.bindings);
  if (name === null) ctx.gap("dynamic-set-attribute", node.arguments[0]);
  else ctx.add(name.toLowerCase());
}

function checkFactoryProp(prop, ctx) {
  if (ts.isSpreadAssignment(prop)) {
    ctx.gap("jsx-spread", prop);
    return;
  }
  const name = objectPropertyName(prop, ctx.bindings);
  ctx.add(name);
  if (ctx.usesTsOwnershipAxes && name?.toLowerCase() === "id") {
    const valueNode = ts.isPropertyAssignment(prop) ? prop.initializer : null;
    ctx.templateIds.push(tsIdSite(ctx.rel, ctx.sourceFile, ctx.lineOf, prop, valueNode, ctx.bindings));
  }
}

/* `h`는 R4 screen component의 얇은 createElement 별칭이다. 인자 순서가 같은 이 호출을
   빼면 실제 React producer 75곳이 소유권 축에서 통째로 사라진다. */
function checkFactoryPropsCall(node, callee, ctx) {
  const factory = callee && ts.isIdentifier(callee) ? callee.text : null;
  if (!DOM_FACTORY_CALL_NAMES.includes(factory) || node.arguments.length <= 1) return;
  const props = unwrapExpression(node.arguments[1]);
  if (!props || !ts.isObjectLiteralExpression(props)) return;
  for (const prop of props.properties) checkFactoryProp(prop, ctx);
}

/* R5-99 B1 — DOM 생성 술어는 **제품 폐포 전체**를 본다. */
function checkDomFactoryCall(node, callee, ctx) {
  const domFactory = invokedDomFactory(callee, ctx.domFactoryAliases, ctx.checker, ctx.sourceFile, ctx.bindings);
  if (domFactory !== null) {
    ctx.directDom.push(`${ctx.rel}:${ctx.lineOf(node.getStart(ctx.sourceFile))}:${domFactory}`);
  }
}

/* 리스너 대칭 잔차는 계속 host 정의역이다 — React effect cleanup 계약이 겨누는 것이고,
   제품 전역 attach 총량은 별도 계측(listener-attach-sites)이 든다. */
function checkListenerPairCall(node, callee, called, ctx) {
  if (
    !ctx.isReactHost
    || !(ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee))
    || (called !== "addEventListener" && called !== "removeEventListener")
  ) return;
  trackListenerCall(node, callee, called, ctx);
}

export function handleCallExpression(node, ctx) {
  if (!ts.isCallExpression(node)) return;
  const callee = unwrapExpression(node.expression);
  const called = calledMethodName(callee, ctx.bindings);
  checkSetAttributeCall(node, called, ctx);
  checkFactoryPropsCall(node, callee, ctx);
  if (!callee) return;
  checkDomFactoryCall(node, callee, ctx);
  checkListenerPairCall(node, callee, called, ctx);
}

/* ── 대입식 ───────────────────────────────────────────────────────── */

function checkDatasetAssignment(node, ctx) {
  const name = datasetAttributeName(node.left, ctx.bindings);
  if (name === "<dynamic>") ctx.gap("computed-dataset", node.left);
  else ctx.add(name);
}

/* R5-99 B1 — innerHTML/outerHTML 대입도 제품 폐포 전체. */
function checkDirectDomAssignment(node, ctx) {
  const targetName = propertyName(unwrapExpression(node.left), ctx.bindings);
  if (targetName !== "innerHTML" && targetName !== "outerHTML") return;
  ctx.directDom.push(
    `${ctx.rel}:${ctx.lineOf(node.getStart(ctx.sourceFile))}:${node.left.getText(ctx.sourceFile)}`,
  );
}

export function handleAssignment(node, ctx) {
  if (!ts.isBinaryExpression(node) || !assignmentOperator(node.operatorToken.kind)) return;
  checkDatasetAssignment(node, ctx);
  checkDirectDomAssignment(node, ctx);
}

/* ── JSX 속성 ─────────────────────────────────────────────────────── */

function checkJsxAttributeName(node, ctx) {
  if (ts.isJsxAttribute(node) && ts.isIdentifier(node.name)) ctx.add(node.name.text);
}

function checkJsxAttributeId(node, ctx) {
  if (
    !ctx.usesTsOwnershipAxes
    || !ts.isJsxAttribute(node)
    || !ts.isIdentifier(node.name)
    || node.name.text.toLowerCase() !== "id"
  ) return;
  const valueNode = node.initializer && ts.isJsxExpression(node.initializer)
    ? node.initializer.expression
    : node.initializer;
  ctx.templateIds.push(tsIdSite(ctx.rel, ctx.sourceFile, ctx.lineOf, node, valueNode, ctx.bindings));
}

function checkJsxSpreadAttribute(node, ctx) {
  if (ts.isJsxSpreadAttribute(node)) ctx.gap("jsx-spread", node);
}

export function handleJsxAttribute(node, ctx) {
  checkJsxAttributeName(node, ctx);
  checkJsxAttributeId(node, ctx);
  checkJsxSpreadAttribute(node, ctx);
}
