/* R1-02 소유권 인벤토리 — 축 2(모듈 스코프 가변 상태)의 oxc(JS/MJS) 쪽.
 *
 * 스코프 = Program 최상위 ∪ **export 된 최상위 함수**(= 구성 1회 팩토리)의 body 최상위.
 * 구조분해는 바인딩 이름을 전부 편다. `const` 는 세지 않는다 — 가변성이 병이라는 기존 판단을
 * 승계한다. 사각: 「비-export 최상위 함수」를 지역으로 보는 판단 — `exported` 를 뒤집으면
 * 그 사각의 오늘 크기가 `js_nonexported_fn_state` 로 나온다.
 */
import { extname } from "node:path";
import { parseAst } from "./runtime.mjs";
import { lineIndex, OXC_SUFFIXES, sources } from "./scope.mjs";

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

export { bindingNames, topLevelFunctionBody, mutableDeclarators, jsModuleState };
