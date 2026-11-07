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
 * Node·npm 은 이 저장소의 빌드 전제조건이고 이 추출기를 부르는 CI 잡은 먼저 프런트 툴체인을
 * 설치한다.
 *
 * ## 이 파일이 저장소 안에 있어야 하는 이유
 *
 * 스크래치패드에 두면 Node 가 `vite` 를 해소하지 못한다(`ERR_MODULE_NOT_FOUND`, 실증).
 * 추출기는 `node_modules` 와 같은 트리에 살아야 한다.
 *
 * ## 파일 분리(책임 분리)
 *
 * 모듈 문장 예산을 넘겨 `scripts/extract_js_ast/*.mjs` 로 쪼갰다 — 파서 로딩(`runtime.mjs`) ·
 * 범위·경로·정규식(`scope.mjs`) · JS/MJS 쪽 모듈 상태(`js_axes.mjs`) · TS AST 1차 판독(`ts_core.mjs`) ·
 * 심볼 신원(`identity.mjs`) · DOM 팩토리 별칭(`dom_factory.mjs`) · 리스너 짝짓기(`listener_tracking.mjs`) ·
 * `typescriptAxes`의 방문자 판독(`visit_handlers.mjs`). `domFactoryOrigin`·`expressionIdentity`·
 * `jsTemplateIds` 세 함수는 평평한 분배 표로 이미 사유가 선 상시 예외라 여기 그대로 남는다 —
 * 원장 ident(`scripts/extract_js_ast_axes.mjs::<이름>`)가 이 파일 이름에 묶여 있어서다.
 *
 * ## 출력
 *
 * stdout 에 JSON 하나. 키는 축 이름이고 값은 **정렬된 멤버 키 배열**이다. 멤버 키가 원장의
 * 노드 좌표와 같은 문자열이라 폐포(M−C·C−M)가 집합 연산으로 닫힌다.
 *
 *   node scripts/extract_js_ast_axes.mjs [--repo-root <path>]
 */
import { extname, resolve, sep } from "node:path";
import { parseAst, ts, TypeScriptAPI } from "./extract_js_ast/runtime.mjs";
import {
  lineIndex, OXC_SUFFIXES, PRODUCT_SCOPE, REACT_HOST_PREFIXES, SELFTEST_SCOPE, sources, walk,
  ID_ATTR,
} from "./extract_js_ast/scope.mjs";
import { jsModuleState, mutableDeclarators, topLevelFunctionBody } from "./extract_js_ast/js_axes.mjs";
import {
  constStringBindings, normalizedNodeText, propertyName, tsModuleState, unwrapExpression,
} from "./extract_js_ast/ts_core.mjs";
import { collectDomFactoryAliases } from "./extract_js_ast/dom_factory.mjs";
import { aliasKey, collectIterationBindings, symbolProvenance } from "./extract_js_ast/identity.mjs";
import { computeCleanupGaps } from "./extract_js_ast/listener_tracking.mjs";
import {
  handleAssignment, handleCallExpression, handleJsxAttribute, handleStringToken,
} from "./extract_js_ast/visit_handlers.mjs";

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

/* ── 축 1: JS 가 만드는 id 사이트 ────────────────────────────────────
 *
 * AST 가 리터럴 노드를 고르고, 속성 판독은 **앵커 정규식**이다. 「AST 로 닫힌다」가 아니다 —
 * 그 자백이 사각 프로브의 존재 이유다. 앵커 `(?<![\w-])` 가 `xid="`·`data-row-id="` 같은
 * 다른 속성명을 배제한다. 오늘 그런 속성은 0건이지만 **오늘 0인 것과 앞으로도 0인 것은 다르다**.
 *
 * 단위는 이름이 아니라 **사이트**다. 완전 동적 3건은 이름이 소스에 없으므로 이름을 단위로
 * 잡으면 그 셋이 영영 미분류이거나 조용히 빠진다.
 *
 * 상시 예외(복잡도 13): 2개 노드 종류(TemplateLiteral·Literal) 독립 추출 — `scripts/extract_js_ast`
 * 로 이식해도 ident 가 바뀌므로 이 파일에 둔다.
 */
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
 *
 * `domFactoryOrigin`·`expressionIdentity` 는 평평한 분배 표(AST 노드 종류별 독립 분기)라
 * 상시 예외로 이 파일에 남는다 — `scripts/extract_js_ast/dom_factory.mjs`의
 * `collectDomFactoryAliases`·`invokedDomFactory`, `identity.mjs`의 `collectIterationBindings`가
 * 이 둘을 되부른다(순환 의존, 런타임 호출 시점에만 쓰여 안전하다).
 */
const DOM_FACTORY_NAMES = new Set(["createElement", "createElementNS", "insertAdjacentHTML"]);

export function domFactoryOrigin(node, aliases, checker, sourceFile, bindings) {
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

export function expressionIdentity(node, checker, sourceFile, iterationBindings = new Map()) {
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

      const ctx = {
        rel, sourceFile, lineOf, bindings, usesTsOwnershipAxes, isReactHost,
        domFactoryAliases, checker, iterationBindings, add, gap,
        templateIds, directDom, listenerPairs,
      };

      function visit(node) {
        handleStringToken(node, ctx);
        handleCallExpression(node, ctx);
        handleAssignment(node, ctx);
        handleJsxAttribute(node, ctx);
        node.forEachChild(visit);
      }
      visit(sourceFile);
    }
  } finally {
    snapshot?.dispose();
    api.close();
  }
  return {
    members: [...members].sort(),
    dynamic: [...dynamic].sort(),
    templateIds: templateIds.sort(),
    moduleState: moduleState.sort(),
    nonexportedState: nonexportedState.sort(),
    directDom: directDom.sort(),
    cleanupGaps: computeCleanupGaps(listenerPairs).sort(),
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
