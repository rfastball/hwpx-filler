/* R1-02 소유권 인벤토리 — 제품 코드의 DOM·state·listener 축을 **AST 로** 뽑는 유일한 추출기.
 *
 * ## 왜 파서인가
 *
 * 이 저장소는 같은 축을 정규식으로 세다가 네 번 틀렸다: `data-*`(CSS 클래스 이름 6개 오탐) ·
 * JS 생성 id(템플릿 변수 오독) · `innerHTML` 대입(`[^=]` 가 줄 끝 대입 11을 놓침) ·
 * 모듈 상태(2칸 들여쓰기 관례가 0칸 최상위 4를 못 보고 비-export 함수 지역 12를 상태로 오독).
 * 앞의 셋은 「정규식이 틀렸다」이고 넷째는 「술어의 커버리지를 안 물었다」로 성질이 다르다.
 * 그래서 이 파일은 두 가지를 함께 낸다 — **값**과 **그 값이 못 보는 것의 크기**(사각 프로브).
 *
 * ## 파서
 *
 * `vite` 가 내주는 `parseAst`(oxc). `tests/js/n10_global_hygiene.test.js` 가 이미 쓰는 것과
 * 같은 파서라 새 devDependency 가 없다. 부재는 조용한 스킵이 아니라 **사유를 말하는 실패**다 —
 * Node·npm 은 이 저장소의 빌드 전제조건이고 CI contract 잡은 pytest 앞에서 프런트 툴체인을
 * 설치한다.
 *
 * ## 이 파일이 저장소 안에 있어야 하는 이유
 *
 * 스크래치패드에 두면 Node 가 `vite` 를 해소하지 못한다(`ERR_MODULE_NOT_FOUND`, 실증).
 * 추출기는 `node_modules` 와 같은 트리에 살아야 한다.
 *
 * ## 출력
 *
 * stdout 에 JSON 하나. 키는 축 이름이고 값은 **정렬된 멤버 키 배열**이다. 멤버 키가 원장의
 * 노드 좌표와 같은 문자열이라 폐포(M−C·C−M)가 집합 연산으로 닫힌다.
 *
 *   node scripts/extract_js_ast_axes.mjs [--repo-root <path>]
 */
import { readFileSync, globSync, statSync } from "node:fs";
import { extname, join, resolve, sep } from "node:path";

let parseAst;
try {
  ({ parseAst } = await import("vite"));
} catch (thrown) {
  throw new Error(
    "프런트 툴체인(`vite`)을 못 불렀습니다 — `npm ci` 가 먼저입니다. 이 추출기를 도는 게이트"
    + "(pytest contract 집합)는 Node 를 전제하므로 부재는 스킵 사유가 아니라 실패입니다: "
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

/* ── 인자 ─────────────────────────────────────────────────────────── */

function parseArgs(argv) {
  let repoRoot = process.cwd();
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--repo-root") {
      repoRoot = argv[i + 1];
      if (!repoRoot) throw new Error("--repo-root 에 경로가 없습니다.");
      i += 1;
    } else {
      throw new Error(`알 수 없는 인자: ${argv[i]}`);
    }
  }
  return { repoRoot };
}

/* ── 공통 ─────────────────────────────────────────────────────────── */

/** 파일 오프셋 → 1-기반 줄 번호. 좌표가 원장 증거의 단위라 반올림하지 않는다. */
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

const SKIP_KEYS = new Set(["type", "start", "end", "range", "loc", "parent"]);

function walk(node, visit) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) {
    for (const child of node) walk(child, visit);
    return;
  }
  if (typeof node.type === "string") visit(node);
  for (const key of Object.keys(node)) {
    if (!SKIP_KEYS.has(key)) walk(node[key], visit);
  }
}

/* ── 범위 ──────────────────────────────────────────────────────────
 *
 * 확장자를 열거하지 않는다. 정적 폐포 계약(#490)이 코드가 **아닌** 접미사만 들고, 제품
 * 프런트 전수에서 그것을 감산한다. 새 `.tsx`·다음 코드 형식은 자동 편입되며, 파서가 못
 * 읽는 형식이면 조용히 누락되지 않고 실패한다.
 */
const STATIC_CLOSURE = JSON.parse(readFileSync(
  new URL("../tests/static_closure_contract.json", import.meta.url),
  "utf8",
));
const NON_CODE_SUFFIXES = STATIC_CLOSURE.non_code_suffixes;
const PRODUCT_SCOPE = ["frontend/**/*"];
const OXC_SUFFIXES = new Set([".js", ".mjs"]);
const SELFTEST_SCOPE = ["frontend/src/selftest/**/*.js", "frontend/src/selftest/**/*.mjs"];
const SELFTEST_PREFIX = "frontend/src/selftest/";
/* R5-99 B1·S1 뒤 이 목록이 가리는 것은 **리스너 대칭 잔차 하나**다 — DOM 생성 술어는
   제품 폐포 전체를 보고, 여기는 React effect cleanup 계약의 정의역(overlay·shell·screens)만
   남는다. 선언 scope(원장·게이트)와 이 목록은 같은 셋이어야 한다 — 어긋나면 S1 재발. */
const REACT_HOST_PREFIXES = [
  "frontend/src/overlay/",
  "frontend/src/shell/",
  "frontend/src/screens/",
];

/** 멤버 키는 **저장소 상대 POSIX 경로**다 — OS 마다 달라지면 원장이 못 산다. */
function sources(root, patterns, { excludeSelftest = false, excludeNonCode = false } = {}) {
  const seen = new Map();
  for (const pattern of [].concat(patterns)) {
    for (const raw of globSync(pattern, { cwd: root })) {
      const rel = raw.split(sep).join("/");
      if (!statSync(join(root, rel)).isFile()) continue;
      if (excludeSelftest && rel.startsWith(SELFTEST_PREFIX)) continue;
      if (excludeNonCode && NON_CODE_SUFFIXES.some((suffix) => rel.endsWith(suffix))) continue;
      if (!seen.has(rel)) seen.set(rel, { rel, text: readFileSync(join(root, rel), "utf8") });
    }
  }
  return [...seen.values()].sort((a, b) => (a.rel < b.rel ? -1 : a.rel > b.rel ? 1 : 0));
}

/* ── 축 1: JS 가 만드는 id 사이트 ────────────────────────────────────
 *
 * AST 가 리터럴 노드를 고르고, 속성 판독은 **앵커 정규식**이다. 「AST 로 닫힌다」가 아니다 —
 * 그 자백이 사각 프로브의 존재 이유다. 앵커 `(?<![\w-])` 가 `xid="`·`data-row-id="` 같은
 * 다른 속성명을 배제한다. 오늘 그런 속성은 0건이지만 **오늘 0인 것과 앞으로도 0인 것은 다르다**.
 *
 * 단위는 이름이 아니라 **사이트**다. 완전 동적 3건은 이름이 소스에 없으므로 이름을 단위로
 * 잡으면 그 셋이 영영 미분류이거나 조용히 빠진다.
 */
const ID_ATTR = /(?<![\w-])id="([^"]*)$|(?<![\w-])id="([^"]*)"/g;

function jsTemplateIds(root, patterns, options) {
  const rows = [];
  for (const { rel, text } of sources(root, patterns, options)) {
    if (!OXC_SUFFIXES.has(extname(rel))) continue;
    const lineOf = lineIndex(text);
    const program = parseAst(text, { sourceFilename: rel });
    walk(program, (node) => {
      if (node.type === "TemplateLiteral") {
        for (const quasi of node.quasis) {
          const raw = quasi.value?.raw ?? "";
          ID_ATTR.lastIndex = 0;
          for (const match of raw.matchAll(ID_ATTR)) {
            const dynamic = match[1] !== undefined;
            const value = dynamic ? match[1] : match[2];
            rows.push(
              `${rel}:${lineOf(quasi.start + match.index)}:`
              + `${dynamic ? "dynamic" : "static"}:${value}`,
            );
          }
        }
      }
      /* 홑따옴표 JS 문자열 안의 큰따옴표 속성(`el.innerHTML = '<div id="x">'`)은
         템플릿 리터럴이 아니라 Literal 로 온다. 이 패스를 지우면 그것이 새 사각이 된다. */
      if (node.type === "Literal" && typeof node.value === "string") {
        ID_ATTR.lastIndex = 0;
        for (const match of node.value.matchAll(ID_ATTR)) {
          if (match[2] === undefined) continue;
          rows.push(`${rel}:${lineOf(node.start)}:static:${match[2]}`);
        }
      }
    });
  }
  return rows.sort();
}

/* ── 축 2: 모듈 스코프 가변 상태 ─────────────────────────────────────
 *
 * 스코프 = Program 최상위 ∪ **export 된 최상위 함수**(= 구성 1회 팩토리)의 body 최상위.
 * 구조분해는 바인딩 이름을 전부 편다. `const` 는 세지 않는다 — 가변성이 병이라는 기존 판단을
 * 승계한다(완료된 범용 DOM census가 쓰던 가변 상태 예산과 같은 전제).
 *
 * 사각: 「비-export 최상위 함수」를 지역으로 보는 판단. 그 함수가 사실 1회 호출 팩토리면 놓친다.
 * `exported` 조건을 뒤집으면 그 사각의 **오늘 크기**가 나온다 — 그것이 `js_nonexported_fn_state`.
 */
function bindingNames(pattern, out = []) {
  if (!pattern) return out;
  switch (pattern.type) {
    case "Identifier":
      out.push(pattern);
      break;
    case "ObjectPattern":
      for (const property of pattern.properties) {
        bindingNames(property.value ?? property.argument, out);
      }
      break;
    case "ArrayPattern":
      for (const element of pattern.elements) bindingNames(element, out);
      break;
    case "AssignmentPattern":
      bindingNames(pattern.left, out);
      break;
    case "RestElement":
      bindingNames(pattern.argument, out);
      break;
    default:
      break;
  }
  return out;
}

/** `exported` 를 뒤집으면 사각 프로브가 된다 — 한 함수가 값과 그 값의 사각을 함께 낸다. */
function topLevelFunctionBody(statement, { exported }) {
  const isExport = statement.type === "ExportNamedDeclaration"
    || statement.type === "ExportDefaultDeclaration";
  if (isExport !== exported) return null;
  const declaration = isExport ? statement.declaration : statement;
  return declaration?.type === "FunctionDeclaration" ? declaration.body.body : null;
}

function mutableDeclarators(body) {
  return (body || [])
    .filter((s) => s.type === "VariableDeclaration" && s.kind !== "const")
    .flatMap((s) => s.declarations.flatMap((d) => bindingNames(d.id)));
}

function jsModuleState(root, patterns, options = {}) {
  const { exported = true, includeProgram = true, ...scopeOptions } = options;
  const rows = [];
  for (const { rel, text } of sources(root, patterns, scopeOptions)) {
    if (!OXC_SUFFIXES.has(extname(rel))) continue;
    const lineOf = lineIndex(text);
    const program = parseAst(text, { sourceFilename: rel });
    const hits = [
      ...(includeProgram ? mutableDeclarators(program.body) : []),
      ...program.body.flatMap(
        (s) => mutableDeclarators(topLevelFunctionBody(s, { exported })),
      ),
    ];
    for (const identifier of hits) {
      rows.push(`${rel}:${lineOf(identifier.start)} ${identifier.name}`);
    }
  }
  return rows.sort();
}

/* ── 명시 제외 축의 크기 ─────────────────────────────────────────────
 *
 * `frontend/src/selftest/**` 를 축에서 빼면서 **크기는 잰다**. 제외가 조용하면 「미분류 0」이
 * 거짓말이 되므로, 세 성격(구성 지점 · 모듈 상태 · id 사이트)을 한 목록으로 낸다.
 */
function selftestSurface(root) {
  const rows = [];
  for (const { rel, text } of sources(root, SELFTEST_SCOPE)) {
    const lineOf = lineIndex(text);
    for (const [index, line] of text.split("\n").entries()) {
      if (/^export function /.test(line)) rows.push(`export-function:${rel}:${index + 1}`);
    }
    const program = parseAst(text, { sourceFilename: rel });
    for (const identifier of [
      ...mutableDeclarators(program.body),
      ...program.body.flatMap((s) => mutableDeclarators(topLevelFunctionBody(s, { exported: true }))),
    ]) {
      rows.push(`module-state:${rel}:${lineOf(identifier.start)} ${identifier.name}`);
    }
  }
  for (const site of jsTemplateIds(root, SELFTEST_SCOPE)) rows.push(`id-site:${site}`);
  return rows.sort();
}

/* ── 축 3: JS/TS가 DOM에 심는 data-* ────────────────────────────────
 *
 * 정적 index.html의 data-*는 html.parser가 이름 축으로 센다. 이 축은 그 바깥, 즉 제품
 * JS/TS가 런타임에 **생산하는** 속성만 센다. 소비(`dataset` read·getAttribute·selector)는
 * 소유권 이동 대상이 아니므로 제외한다. 같은 파일에서 같은 이름을 여러 번 생산해도 소유
 * 단위는 하나다. 반대로 같은 이름을 다른 화면 파일이 생산하면 R4 인계가 다르므로 별개다.
 *
 * oxc `parseAst`는 TypeScript syntax를 받지 않는다. 이 축은 이미 devDependency인
 * TypeScript compiler API로 JS/TS를 함께 파싱한다 — root.ts의 type 선언을 regex/strip으로
 * 우회하면 정확히 이 축이 닫으려는 조용한 사각이 되기 때문이다.
 */
const MARKUP_DATA_ATTR = /[\s<](data-[a-z][a-z0-9-]*)(?=\s|=|\/?>|$)/g;
const BARE_MARKUP_DATA_ATTR = /^(data-[a-z][a-z0-9-]*)(?=\s|=|$)/g;
const DYNAMIC_MARKUP_DATA_ATTR = /(?:^|[\s<])data-$/;

function unwrapExpression(node) {
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

function literalString(node, bindings, seen = new Set()) {
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

function constStringBindings(sourceFile) {
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

function propertyName(node, bindings) {
  if (ts.isPropertyAccessExpression(node)) return node.name.text;
  if (ts.isElementAccessExpression(node)) {
    return literalString(node.argumentExpression, bindings);
  }
  return null;
}

function objectPropertyName(node, bindings) {
  const name = node.name;
  if (!name) return null;
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) {
    return name.text;
  }
  if (ts.isComputedPropertyName(name)) return literalString(name.expression, bindings);
  return null;
}

function assignmentOperator(kind) {
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

function datasetAttributeName(target, bindings) {
  const current = unwrapExpression(target);
  if (!current || (!ts.isPropertyAccessExpression(current) && !ts.isElementAccessExpression(current))) {
    return null;
  }
  if (!isDatasetObject(current.expression, bindings)) return null;
  const key = propertyName(current, bindings);
  if (key === null) return "<dynamic>";
  return `data-${key.replace(/([A-Z])/g, "-$1").toLowerCase()}`;
}

function stringTokenText(node) {
  const stringKinds = new Set([
    ts.SyntaxKind.StringLiteral,
    ts.SyntaxKind.NoSubstitutionTemplateLiteral,
    ts.SyntaxKind.TemplateHead,
    ts.SyntaxKind.TemplateMiddle,
    ts.SyntaxKind.TemplateTail,
  ]);
  return stringKinds.has(node.kind) && typeof node.text === "string" ? node.text : null;
}

function tsBindingIdentifiers(name, out = []) {
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

function hasExportModifier(node) {
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

function tsModuleState(sourceFile, rel, lineOf, { exported, includeProgram }) {
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

function tsIdSite(rel, sourceFile, lineOf, node, valueNode, bindings) {
  const value = literalString(valueNode, bindings);
  const current = unwrapExpression(valueNode);
  const prefix = value === null && current && ts.isTemplateExpression(current)
    ? current.head.text
    : "";
  return `${rel}:${lineOf(node.getStart(sourceFile))}:${value === null ? "dynamic" : "static"}:`
    + `${value ?? prefix}`;
}

function normalizedNodeText(node, sourceFile) {
  return node ? node.getText(sourceFile).replace(/\s+/g, "") : "<default>";
}

function symbolProvenance(checker, node) {
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

function collectIterationBindings(sourceFile, checker) {
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

function expressionIdentity(node, checker, sourceFile, iterationBindings = new Map()) {
  const current = unwrapExpression(node);
  if (!current) return "<missing>";
  if (ts.isIdentifier(current)) {
    return iterationBindings.get(aliasKey(current, checker, sourceFile))
      ?? `symbol:${symbolProvenance(checker, current)
        ?? `${sourceFile.fileName}:${current.getStart(sourceFile)}`}`;
  }
  if (ts.isPropertyAccessExpression(current) || ts.isElementAccessExpression(current)) {
    const nameNode = ts.isPropertyAccessExpression(current)
      ? current.name
      : current.argumentExpression;
    return [
      "member",
      expressionIdentity(current.expression, checker, sourceFile, iterationBindings),
      propertyName(current, new Map()) ?? normalizedNodeText(nameNode, sourceFile),
      symbolProvenance(checker, nameNode) ?? "<unresolved-property>",
    ].join(":");
  }
  if (current.kind === ts.SyntaxKind.ThisKeyword) {
    let owner = current.parent;
    while (owner && !ts.isFunctionLike(owner) && !ts.isClassLike(owner)) owner = owner.parent;
    return `this:${sourceFile.fileName}:${owner?.getStart(sourceFile) ?? 0}`;
  }
  if (ts.isArrowFunction(current) || ts.isFunctionExpression(current)) {
    return `function-literal:${sourceFile.fileName}:${current.getStart(sourceFile)}`;
  }
  return `expression:${sourceFile.fileName}:${current.getStart(sourceFile)}:${current.kind}`;
}

const DOM_FACTORY_NAMES = new Set(["createElement", "createElementNS", "insertAdjacentHTML"]);

function aliasKey(identifier, checker, sourceFile) {
  return symbolProvenance(checker, identifier)
    ?? `${sourceFile.fileName}:${identifier.getStart(sourceFile)}`;
}

function domFactoryOrigin(node, aliases, checker, sourceFile, bindings) {
  const current = unwrapExpression(node);
  if (!current) return null;
  if (ts.isIdentifier(current)) return aliases.get(aliasKey(current, checker, sourceFile)) ?? null;
  if (ts.isPropertyAccessExpression(current) || ts.isElementAccessExpression(current)) {
    const name = propertyName(current, bindings);
    if (DOM_FACTORY_NAMES.has(name)) {
      return normalizedNodeText(current, sourceFile);
    }
    return null;
  }
  if (ts.isCallExpression(current)) {
    const callee = unwrapExpression(current.expression);
    if (
      callee
      && (ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee))
      && propertyName(callee, bindings) === "bind"
    ) {
      return domFactoryOrigin(callee.expression, aliases, checker, sourceFile, bindings);
    }
  }
  return null;
}

function bindingElementPropertyName(element, bindings) {
  const node = element.propertyName ?? element.name;
  if (ts.isIdentifier(node) || ts.isStringLiteral(node) || ts.isNumericLiteral(node)) {
    return node.text;
  }
  if (ts.isComputedPropertyName(node)) return literalString(node.expression, bindings);
  return null;
}

function collectDomFactoryAliases(sourceFile, checker, bindings) {
  const aliases = new Map();
  const candidates = [];
  function collect(node) {
    if (ts.isVariableDeclaration(node) || ts.isBinaryExpression(node)) candidates.push(node);
    node.forEachChild(collect);
  }
  collect(sourceFile);

  let changed = true;
  while (changed) {
    changed = false;
    for (const candidate of candidates) {
      if (ts.isVariableDeclaration(candidate)) {
        if (candidate.initializer && ts.isIdentifier(candidate.name)) {
          const origin = domFactoryOrigin(
            candidate.initializer, aliases, checker, sourceFile, bindings,
          );
          const key = aliasKey(candidate.name, checker, sourceFile);
          if (origin !== null && aliases.get(key) !== origin) {
            aliases.set(key, origin);
            changed = true;
          }
        }
        if (
          candidate.initializer
          && ts.isObjectBindingPattern(candidate.name)
        ) {
          for (const element of candidate.name.elements) {
            const name = bindingElementPropertyName(element, bindings);
            if (!DOM_FACTORY_NAMES.has(name)) continue;
            for (const identifier of tsBindingIdentifiers(element.name)) {
              const key = aliasKey(identifier, checker, sourceFile);
              const origin = `${normalizedNodeText(candidate.initializer, sourceFile)}.${name}`;
              if (aliases.get(key) !== origin) {
                aliases.set(key, origin);
                changed = true;
              }
            }
          }
        }
        continue;
      }
      if (
        candidate.operatorToken.kind === ts.SyntaxKind.EqualsToken
        && ts.isIdentifier(candidate.left)
      ) {
        const origin = domFactoryOrigin(candidate.right, aliases, checker, sourceFile, bindings);
        const key = aliasKey(candidate.left, checker, sourceFile);
        if (origin !== null && aliases.get(key) !== origin) {
          aliases.set(key, origin);
          changed = true;
        }
      }
    }
  }
  return aliases;
}

function invokedDomFactory(callee, aliases, checker, sourceFile, bindings) {
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

function typescriptAxes(root) {
  const members = new Set();
  const dynamic = new Set();
  const templateIds = [];
  const moduleState = [];
  const nonexportedState = [];
  const directDom = [];
  const listenerPairs = new Map();
  const scopedSources = sources(root, PRODUCT_SCOPE, {
    excludeSelftest: true,
    excludeNonCode: true,
  });
  const api = new TypeScriptAPI({ cwd: resolve(root) });
  let snapshot;
  try {
    const files = scopedSources.map(({ rel }) => resolve(root, rel).split(sep).join("/"));
    snapshot = api.updateSnapshot({ openFiles: files });

    for (const { rel, text } of scopedSources) {
      const file = resolve(root, rel).split(sep).join("/");
      const project = snapshot.getDefaultProjectForFile(file);
      const sourceFile = project?.program.getSourceFile(file);
      if (!sourceFile) throw new Error(`TypeScript AST를 읽지 못한 파일: ${rel}`);
      const checker = project.checker;
      const bindings = constStringBindings(sourceFile);
      const domFactoryAliases = collectDomFactoryAliases(sourceFile, checker, bindings);
      const iterationBindings = collectIterationBindings(sourceFile, checker);
      const lineOf = lineIndex(text);
      // JS/MJS는 OXC 축이 이미 소유한다. 그 밖의 **모든 감산 결과**는 TS AST 축이 맡고,
      // TS API가 못 읽는 새 형식은 위 sourceFile 부재에서 조용하지 않게 실패한다.
      const usesTsOwnershipAxes = !OXC_SUFFIXES.has(extname(rel));
      const isReactHost = REACT_HOST_PREFIXES.some((prefix) => rel.startsWith(prefix));
      if (usesTsOwnershipAxes) {
        moduleState.push(...tsModuleState(sourceFile, rel, lineOf, {
          exported: true,
          includeProgram: true,
        }));
        nonexportedState.push(...tsModuleState(sourceFile, rel, lineOf, {
          exported: false,
          includeProgram: false,
        }));
      }
      const add = (name) => {
        if (name?.startsWith("data-")) members.add(`${rel}:${name}`);
      };
      const gap = (form, node) => {
        dynamic.add(`${form}:${rel}:${lineOf(node.getStart(sourceFile))}`);
      };

      function visit(node) {
        const token = stringTokenText(node);
        if (token !== null) {
          /* HTML 조각 안의 속성만 본다. 보통 prop 문자열인 `className: "... data-x"`를
             markup으로 오인하면 CSS class가 semantic data-* 생산자로 둔갑한다. */
          if (token.includes("<")) {
            MARKUP_DATA_ATTR.lastIndex = 0;
            for (const match of token.matchAll(MARKUP_DATA_ATTR)) add(match[1]);
          }
          const literal = node.parent && ts.isTemplateExpression(node.parent) ? node.parent : node;
          const parent = literal.parent;
          const isMarkupFragment = parent && (
            (ts.isVariableDeclaration(parent) && parent.initializer === literal)
            || (ts.isArrowFunction(parent) && parent.body === literal)
          );
          if (isMarkupFragment) {
            BARE_MARKUP_DATA_ATTR.lastIndex = 0;
            for (const match of token.matchAll(BARE_MARKUP_DATA_ATTR)) add(match[1]);
          }
          if (
            (node.kind === ts.SyntaxKind.TemplateHead || node.kind === ts.SyntaxKind.TemplateMiddle)
            && DYNAMIC_MARKUP_DATA_ATTR.test(token)
          ) {
            gap("dynamic-markup-name", node);
          }
          if (usesTsOwnershipAxes) {
            ID_ATTR.lastIndex = 0;
            for (const match of token.matchAll(ID_ATTR)) {
              const isDynamic = match[1] !== undefined;
              templateIds.push(
                `${rel}:${lineOf(node.getStart(sourceFile) + match.index)}:`
                + `${isDynamic ? "dynamic" : "static"}:${isDynamic ? match[1] : match[2]}`,
              );
            }
          }
        }

        if (ts.isCallExpression(node)) {
          const callee = unwrapExpression(node.expression);
          const called = callee && (
            ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee)
          ) ? propertyName(callee, bindings) : null;
          if (called === "setAttribute" && node.arguments.length > 0) {
            const name = literalString(node.arguments[0], bindings);
            if (name === null) gap("dynamic-set-attribute", node.arguments[0]);
            else add(name.toLowerCase());
          }

          const factory = callee && ts.isIdentifier(callee) ? callee.text : null;
          /* `h`는 R4 screen component의 얇은 createElement 별칭이다. 인자 순서가 같은 이
             호출을 빼면 실제 React producer 75곳이 소유권 축에서 통째로 사라진다. */
          if (["createElement", "el", "h"].includes(factory) && node.arguments.length > 1) {
            const props = unwrapExpression(node.arguments[1]);
            if (props && ts.isObjectLiteralExpression(props)) {
              for (const prop of props.properties) {
                if (ts.isSpreadAssignment(prop)) {
                  gap("jsx-spread", prop);
                  continue;
                }
                add(objectPropertyName(prop, bindings));
                if (
                  usesTsOwnershipAxes
                  && objectPropertyName(prop, bindings)?.toLowerCase() === "id"
                ) {
                  const valueNode = ts.isPropertyAssignment(prop) ? prop.initializer : null;
                  templateIds.push(tsIdSite(
                    rel, sourceFile, lineOf, prop, valueNode, bindings,
                  ));
                }
              }
            }
          }

          /* R5-99 B1 — DOM 생성 술어는 **제품 폐포 전체**를 본다. 종전에는 REACT_HOST_PREFIXES
             3-prefix 로 가려 출하 번들에 실리는 frontend/js·src 루트 모듈 13이 무방비였고,
             실 위반 표본(bridge.js 의 createElement)이 exit 0 으로 통과했다. React 밖 제품
             코드의 직접 DOM 생성도 R5 뒤에는 전부 위반이므로 가릴 이유 자체가 없다. */
          if (callee) {
            const domFactory = invokedDomFactory(
              callee, domFactoryAliases, checker, sourceFile, bindings,
            );
            if (domFactory !== null) {
              directDom.push(
                `${rel}:${lineOf(node.getStart(sourceFile))}:${domFactory}`,
              );
            }
            /* 리스너 대칭 잔차는 계속 host 정의역이다 — React effect cleanup 계약이 겨누는
               것이고, 제품 전역 attach 총량은 별도 계측(listener-attach-sites)이 든다. */
            if (
              isReactHost
              && (ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee))
              && (called === "addEventListener" || called === "removeEventListener")
            ) {
                const signature = [
                  rel,
                  expressionIdentity(
                    callee.expression, checker, sourceFile, iterationBindings,
                  ),
                  normalizedNodeText(node.arguments[0], sourceFile),
                  expressionIdentity(
                    node.arguments[1], checker, sourceFile, iterationBindings,
                  ),
                  normalizedNodeText(node.arguments[2], sourceFile),
                ].join("|");
                const pair = listenerPairs.get(signature) ?? { adds: [], removes: [] };
                const entry = {
                  rel,
                  line: lineOf(node.getStart(sourceFile)),
                  text: node.getText(sourceFile).replace(/\s+/g, " "),
                };
                pair[called === "addEventListener" ? "adds" : "removes"].push(entry);
                listenerPairs.set(signature, pair);
            }
          }
        }

        if (
          ts.isBinaryExpression(node)
          && assignmentOperator(node.operatorToken.kind)
        ) {
          const name = datasetAttributeName(node.left, bindings);
          if (name === "<dynamic>") gap("computed-dataset", node.left);
          else add(name);
          {
            /* R5-99 B1 — innerHTML/outerHTML 대입도 제품 폐포 전체. */
            const targetName = propertyName(unwrapExpression(node.left), bindings);
            if (targetName === "innerHTML" || targetName === "outerHTML") {
              directDom.push(
                `${rel}:${lineOf(node.getStart(sourceFile))}:${node.left.getText(sourceFile)}`,
              );
            }
          }
        }

        if (ts.isJsxAttribute(node) && ts.isIdentifier(node.name)) add(node.name.text);
        if (
          usesTsOwnershipAxes
          && ts.isJsxAttribute(node)
          && ts.isIdentifier(node.name)
          && node.name.text.toLowerCase() === "id"
        ) {
          const valueNode = node.initializer && ts.isJsxExpression(node.initializer)
            ? node.initializer.expression
            : node.initializer;
          templateIds.push(tsIdSite(rel, sourceFile, lineOf, node, valueNode, bindings));
        }
        if (ts.isJsxSpreadAttribute(node)) gap("jsx-spread", node);
        node.forEachChild(visit);
      }
      visit(sourceFile);
    }
  } finally {
    snapshot?.dispose();
    api.close();
  }
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
  return {
    members: [...members].sort(),
    dynamic: [...dynamic].sort(),
    templateIds: templateIds.sort(),
    moduleState: moduleState.sort(),
    nonexportedState: nonexportedState.sort(),
    directDom: directDom.sort(),
    cleanupGaps: cleanupGaps.sort(),
  };
}

/* ── 실행 ─────────────────────────────────────────────────────────── */

const { repoRoot: root } = parseArgs(process.argv.slice(2));

const typescript = typescriptAxes(root);
const oxcOptions = { excludeSelftest: true, excludeNonCode: true };

const payload = {
  js_template_ids: [
    ...jsTemplateIds(root, PRODUCT_SCOPE, oxcOptions),
    ...typescript.templateIds,
  ].sort(),
  js_module_state: [
    ...jsModuleState(root, PRODUCT_SCOPE, { exported: true, ...oxcOptions }),
    ...typescript.moduleState,
  ].sort(),
  /* 사각 프로브 — 비-export 최상위 함수의 body 최상위 let/var. Program 최상위는 빼야
     값 축과 겹치지 않는다. 값 축과 **같은 범위**를 봐야 그 차이가 사각이다. */
  js_nonexported_fn_state: [
    ...jsModuleState(root, PRODUCT_SCOPE, {
      exported: false,
      includeProgram: false,
      ...oxcOptions,
    }),
    ...typescript.nonexportedState,
  ].sort(),
  selftest_surface: selftestSurface(root),
  js_planted_data_attrs: typescript.members,
  js_data_attr_dynamic: typescript.dynamic,
  react_direct_dom_mutations: typescript.directDom,
  react_listener_cleanup_gaps: typescript.cleanupGaps,
};

process.stdout.write(`${JSON.stringify(payload, null, 1)}\n`);
