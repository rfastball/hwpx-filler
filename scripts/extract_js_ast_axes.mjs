/* R1-02 소유권 인벤토리 — 프런트 JS 두 축을 **AST 로** 뽑는 유일한 추출기.
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
import { readFileSync, globSync } from "node:fs";
import { join, sep } from "node:path";

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

/** 멤버 키는 **저장소 상대 POSIX 경로**다 — OS 마다 달라지면 원장이 못 산다. */
function sources(root, pattern) {
  return globSync(pattern, { cwd: root })
    .map((rel) => rel.split(sep).join("/"))
    .sort()
    .map((rel) => ({ rel, text: readFileSync(join(root, rel), "utf8") }));
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

function jsTemplateIds(root) {
  const rows = [];
  for (const { rel, text } of sources(root, "frontend/js/**/*.js")) {
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
 * 승계한다(`tests/test_web_dom_contract.py` 의 예산 계약과 같은 전제).
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

function jsModuleState(root, patterns, { exported = true, includeProgram = true } = {}) {
  const rows = [];
  for (const pattern of patterns) {
    for (const { rel, text } of sources(root, pattern)) {
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
  }
  return rows.sort();
}

/* ── 실행 ─────────────────────────────────────────────────────────── */

const { repoRoot: root } = parseArgs(process.argv.slice(2));

const payload = {
  js_template_ids: jsTemplateIds(root),
  js_module_state: jsModuleState(
    root,
    ["frontend/js/**/*.js", "frontend/src/*.js"],
    { exported: true },
  ),
  /* 사각 프로브 — 비-export 최상위 함수의 body 최상위 let/var. Program 최상위는 빼야
     값 축과 겹치지 않는다. */
  js_nonexported_fn_state: jsModuleState(
    root,
    ["frontend/js/**/*.js"],
    { exported: false, includeProgram: false },
  ),
};

process.stdout.write(`${JSON.stringify(payload, null, 1)}\n`);
