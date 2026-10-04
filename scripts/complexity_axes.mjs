/* 복잡도 예산의 JS/TS 측정기 — `scripts/complexity_measure.py` 의 짝.
 *
 * 범위·등급·원장 판정은 전부 Python 쪽이 소유하고, 여기는 **받은 파일을 재기만** 한다.
 * stdin 으로 `{"root": "<저장소>", "files": ["frontend/src/a.ts", ...]}` 를 받아 stdout 에
 * 단위 배열(JSON)을 낸다. 파싱 실패는 조용히 건너뛰지 않고 파일 이름과 함께 죽는다.
 *
 * ## 파서
 *
 * `vite` 가 내주는 `parseAst`(oxc) — `scripts/extract_js_ast_axes.mjs`·
 * `tests/js/pywebview_allowlist.test.js` 와 같은 파서라 새 devDependency 가 없다. `.ts`·`.tsx`
 * 는 `lang` 옵션으로 읽는다(무옵션은 TS 문법에서 죽는다). 이 파일은 `node_modules` 를
 * 해소하려고 저장소 트리 안에 산다.
 *
 * ## 세는 규칙(Python 측과 같은 뜻)
 *
 * - 문장: ESTree 문장·선언 노드. `BlockStatement`·`EmptyStatement` 는 그릇이라 세지 않고,
 *   지시어(`"use strict"`)는 독스트링처럼 빼며, `for (const x …)` 머리의 선언과 선언을 감싼
 *   `export` 껍데기는 이중 계산하지 않는다.
 * - 분기점: `if`·삼항·`for`/`for…in`/`for…of`·`while`/`do`·`catch`·`case`(`default` 제외)·
 *   논리 연산자(`&&`·`||`·`??`, 이항 노드라 n개 피연산자 → n−1)·논리 대입(`||=` 등).
 *   옵셔널 체이닝(`?.`)은 세지 않는다 — Python 쪽에 대응이 없어 두 언어의 뜻을 맞춘다.
 * - 함수 단위: 이름이 서는 함수만 — 선언·이름 있는 함수식·변수/대입/객체 프로퍼티/클래스
 *   멤버의 값·`export default`. 화면은 JSX 문법 없이 `createElement(type, props, …)`(가져오기
 *   별칭·전달 래퍼 `h`)로 그리므로, props 객체 리터럴의 함수 값(`h("button", { onClick: () => … })`)
 *   은 객체 프로퍼티 규칙으로 `<소유 함수>.onClick` 단위가 되고 컴포넌트에는 제 렌더 분기만 남는다.
 *   같은 이름이 여럿이면(한 컴포넌트의 `onClick` 여럿) 위치 번호 없이 축마다 최댓값으로 합친다
 *   (`merge_units`). 프로퍼티 값이 함수 자체가 아니면(`onClick: act(() => …)`) 아래 익명 규칙을
 *   따른다. 첫 인수가 문자열 리터럴인 호출의 익명 콜백은
 *   `callee("문자열")` 이름을 받는다(`test("…", () => …)`). 그 밖의 익명 함수는 소유 함수에
 *   접히고, 소유자가 없는 최상위 익명 함수는 `<top-level>` 단위에 접힌다.
 * - 클래스 메서드: 클래스 몸체의 메서드·추상 메서드·함수 값을 가진 필드(`h = () => …`).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

let parseAst;
try {
  ({ parseAst } = await import("vite"));
} catch (thrown) {
  throw new Error(
    "프런트 툴체인(`vite`)을 못 불렀습니다 — `npm ci` 가 먼저입니다. 복잡도 예산 게이트는 "
    + "Node·vite 를 전제하므로 부재는 스킵 사유가 아니라 실패입니다: "
    + `${thrown.message}`,
  );
}

const STATEMENTS = new Set([
  "IfStatement", "ForStatement", "ForInStatement", "ForOfStatement", "WhileStatement",
  "DoWhileStatement", "ReturnStatement", "BreakStatement", "ContinueStatement",
  "ThrowStatement", "TryStatement", "SwitchStatement", "LabeledStatement",
  "DebuggerStatement", "WithStatement", "FunctionDeclaration", "ClassDeclaration",
  "ImportDeclaration", "ExportAllDeclaration", "TSTypeAliasDeclaration",
  "TSInterfaceDeclaration", "TSEnumDeclaration", "TSModuleDeclaration",
  "TSImportEqualsDeclaration", "TSExportAssignment", "TSDeclareFunction",
]);
const DEFAULT_DECLARATIONS = new Set([
  "FunctionDeclaration", "ClassDeclaration", "TSInterfaceDeclaration", "TSDeclareFunction",
]);
const LOOP_HEADS = new Set(["ForStatement", "ForInStatement", "ForOfStatement"]);
const BRANCHES = new Set([
  "IfStatement", "ConditionalExpression", "ForStatement", "ForInStatement", "ForOfStatement",
  "WhileStatement", "DoWhileStatement", "CatchClause", "LogicalExpression",
]);
const LOGICAL_ASSIGN = new Set(["||=", "&&=", "??="]);
const FUNCTIONS = new Set(["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"]);
const CLASSES = new Set(["ClassDeclaration", "ClassExpression"]);
const MEMBER_HOSTS = new Set([
  "Property", "MethodDefinition", "PropertyDefinition", "TSAbstractMethodDefinition",
]);
const METHODS = new Set(["MethodDefinition", "TSAbstractMethodDefinition"]);
const SKIP_KEYS = new Set(["type", "start", "end", "range", "loc", "parent"]);

function langOf(rel) {
  if (rel.endsWith(".tsx")) return "tsx";
  if (rel.endsWith(".ts")) return "ts";
  return "js";
}

function lineIndex(source) {
  const starts = [0];
  for (let i = 0; i < source.length; i += 1) {
    if (source[i] === "\n") starts.push(i + 1);
  }
  return (offset) => {
    let low = 0;
    let high = starts.length - 1;
    while (low < high) {
      const mid = (low + high + 1) >> 1;
      if (starts[mid] <= offset) low = mid;
      else high = mid - 1;
    }
    return low + 1;
  };
}

/* ── 이름 ─────────────────────────────────────────────────────────── */

function literalText(node) {
  if (node?.type === "Literal" && ["string", "number"].includes(typeof node.value)) {
    return String(node.value);
  }
  if (node?.type === "TemplateLiteral" && node.expressions.length === 0) {
    return node.quasis.map((quasi) => quasi.value.cooked ?? quasi.value.raw).join("");
  }
  return null;
}

function staticName(node) {
  if (!node) return null;
  if (node.type === "Identifier") return node.name;
  if (node.type === "PrivateIdentifier") return `#${node.name}`;
  if (node.type === "ThisExpression") return "this";
  if (node.type !== "MemberExpression") return literalText(node);
  const property = node.computed ? literalText(node.property) : staticName(node.property);
  const object = staticName(node.object);
  return object && property ? `${object}.${property}` : property;
}

function keyName(member) {
  return member.computed ? literalText(member.key) : staticName(member.key);
}

function callbackName(call) {
  const text = literalText(call.arguments[0]);
  if (text === null) return null;
  return `${staticName(call.callee) ?? "call"}("${text.replace(/\s+/g, " ")}")`;
}

/** 부모 형식 → [함수가 놓여야 하는 자리, 이름 짓기]. 다른 자리의 함수는 익명이다. */
const NAMERS = {
  VariableDeclarator: ["init", (parent) => staticName(parent.id)],
  AssignmentExpression: ["right", (parent) => staticName(parent.left)],
  ExportDefaultDeclaration: ["declaration", () => "default"],
  CallExpression: ["arguments", callbackName],
  ...Object.fromEntries([...MEMBER_HOSTS].map((type) => [type, ["value", keyName]])),
};

function functionName(node, parent, key) {
  if (node.id) return node.id.name;
  const [slot, namer] = NAMERS[parent.type] ?? [];
  return slot === key ? namer(parent) : null;
}

function className(node, parent) {
  if (node.id) return node.id.name;
  if (parent.type === "VariableDeclarator") return staticName(parent.id) ?? "<class>";
  if (parent.type === "ExportDefaultDeclaration") return "default";
  return "<class>";
}

function topLabel(node, lineOf) {
  const target = node.declaration ?? node;
  const name = target.id?.name ?? staticName(target.declarations?.[0]?.id);
  return name ?? `${node.type}@L${lineOf(node.start)}`;
}

/* ── 판정 ─────────────────────────────────────────────────────────── */

function isStatement(node, parent, key) {
  switch (node.type) {
    case "ExpressionStatement": return !node.directive;
    case "VariableDeclaration": return !(LOOP_HEADS.has(parent.type) && (key === "init" || key === "left"));
    case "ExportNamedDeclaration": return !node.declaration;
    case "ExportDefaultDeclaration": return !DEFAULT_DECLARATIONS.has(node.declaration.type);
    default: return STATEMENTS.has(node.type);
  }
}

function branchWeight(node) {
  if (BRANCHES.has(node.type)) return 1;
  if (node.type === "SwitchCase") return node.test ? 1 : 0;
  if (node.type === "AssignmentExpression") return LOGICAL_ASSIGN.has(node.operator) ? 1 : 0;
  return 0;
}

function isMethod(member) {
  if (METHODS.has(member.type)) return true;
  return member.type === "PropertyDefinition" && FUNCTIONS.has(member.value?.type);
}

/* ── 순회 ─────────────────────────────────────────────────────────── */

function children(node) {
  const out = [];
  for (const key of Object.keys(node)) {
    if (SKIP_KEYS.has(key)) continue;
    const value = node[key];
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item && typeof item === "object" && typeof item.type === "string") out.push([key, item]);
    }
  }
  return out;
}

function newFunction(state, qual) {
  const unit = { qual, kind: "function", stmts: 0, complexity: 1, blocks: [] };
  state.functions.push(unit);
  return unit;
}

function topLevelOwner(state) {
  state.topLevel ??= newFunction(state, "<top-level>");
  return state.topLevel;
}

function enterFunction(node, parent, key, ctx, state) {
  const name = functionName(node, parent, key);
  if (name === null) return ctx.owner ? ctx : { ...ctx, owner: topLevelOwner(state) };
  const unit = newFunction(state, ctx.prefix + name);
  if (node.body?.type !== "BlockStatement") unit.stmts += 1;
  return { ...ctx, owner: unit, prefix: `${ctx.prefix}${name}.`, block: null, ownBody: node.body };
}

function enterClass(node, parent, ctx, state) {
  const name = className(node, parent);
  const methods = node.body.body.filter(isMethod).map((member) => keyName(member) ?? "<computed>");
  state.classes.push({ qual: ctx.prefix + name, methods });
  return { ...ctx, prefix: `${ctx.prefix}${name}.` };
}

function enter(node, parent, key, ctx, state) {
  if (FUNCTIONS.has(node.type)) return enterFunction(node, parent, key, ctx, state);
  if (CLASSES.has(node.type)) return enterClass(node, parent, ctx, state);
  if (node.type === "ObjectExpression" && parent.type === "VariableDeclarator" && key === "init") {
    const name = staticName(parent.id);
    if (name) return { ...ctx, prefix: `${ctx.prefix}${name}.` };
  }
  return ctx;
}

function tally(node, parent, key, ctx, state) {
  if (isStatement(node, parent, key)) {
    state.statements += 1;
    ctx.top[1] += 1;
    if (ctx.owner) ctx.owner.stmts += 1;
    if (ctx.block) ctx.block[2] += 1;
  }
  const weight = branchWeight(node);
  if (weight && ctx.owner) ctx.owner.complexity += weight;
  if (weight && ctx.block) ctx.block[3] += weight;
}

function visit(node, parent, key, ctx, state) {
  tally(node, parent, key, ctx, state);
  const inner = enter(node, parent, key, ctx, state);
  for (const [childKey, child] of children(node)) {
    if (child === inner.ownBody && child.type === "BlockStatement") {
      visitBody(child, inner, state);
    } else {
      visit(child, node, childKey, inner, state);
    }
  }
}

/** 함수 몸체 직속 문장마다 블록 기록을 연다 — 실패 메시지의 「가장 큰 블록」 처방 근거. */
function visitBody(block, ctx, state) {
  for (const statement of block.body) {
    const record = [state.lineOf(statement.start), statement.type, 0, 0];
    ctx.owner.blocks.push(record);
    visit(statement, block, "body", { ...ctx, block: record, ownBody: null }, state);
  }
}

function measureFile(rel, text) {
  let program;
  try {
    program = parseAst(text, { lang: langOf(rel) });
  } catch (thrown) {
    throw new Error(`${rel} 파싱 실패 — 예산을 잴 수 없습니다: ${thrown.message}`);
  }
  const state = { lineOf: lineIndex(text), statements: 0, functions: [], classes: [], tops: [] };
  for (const child of program.body) {
    const record = [topLabel(child, state.lineOf), 0];
    state.tops.push(record);
    visit(child, program, "body", { owner: null, prefix: "", top: record, block: null }, state);
  }
  return [
    { path: rel, qual: "", kind: "module", metrics: { module_statements: state.statements }, detail: state.tops },
    ...state.classes.map(({ qual, methods }) => ({
      path: rel, qual, kind: "class", metrics: { class_methods: methods.length }, detail: methods,
    })),
    ...state.functions.map(({ qual, stmts, complexity, blocks }) => ({
      path: rel,
      qual,
      kind: "function",
      metrics: { function_complexity: complexity, function_statements: stmts },
      detail: blocks,
    })),
  ];
}

const request = JSON.parse(readFileSync(0, "utf8"));
const units = request.files.flatMap(
  (rel) => measureFile(rel, readFileSync(join(request.root, rel), "utf8").replace(/^﻿/, "")),
);
process.stdout.write(JSON.stringify(units));
