/* N-10 전역 위생 — 제품이 만드는 창 전역이 **정확히 셋**이라는 것의 정적 증거.
 *
 * ## 무엇을 지키는가
 *
 * N-04~N-09 는 전역 소비를 하나씩 승계처로 옮겼고, 그 전환기 동안 `compat.js` 가 임시 별칭
 * 스물일곱(`window.Modal`·`window.Nav`·`window.__push` …)의 **단일 생산자**였다. N-10 은 그
 * 스물일곱을 지우고 파일 자체를 은퇴시킨다. 그래서 최종 형상의 전역은 셋뿐이다:
 *
 *   - `window.pywebview`   — pywebview 런타임이 주입한다(제품 코드가 만들지 않는다)
 *   - `window.__hwpx`      — 제품 공개 API. 생산자는 `frontend/src/bootstrap.js` 하나(D-06)
 *   - `window.__hwpxTest`  — 명시적 selftest 실행에서만. 생산자는 `selftest/api.js` 하나(D-07)
 *
 * 이 사실은 **정적으로** 물어야 한다. 런타임 순회로는 못 센다 — `defineProperty` 로 열거 불가
 * 하게 심은 이름은 `Object.keys(window)` 에 안 나오고, 조건부 설치는 그 조건을 안 만족한
 * 실행에서 영영 안 보인다. "안 보였다" 와 "없다" 를 같은 것으로 읽는 것이 이 저장소가 반복해
 * 만난 결함류다([[declaration-lives-result-dies]]).
 *
 * ## 이 파일이 두 겹인 이유 — 검출력 없는 게이트는 게이트가 아니다
 *
 * 「window.X = 가 0건이다」 같은 단언은 **스캐너가 아무것도 못 볼 때도** 초록이다. 정규식이
 * 대괄호 표기를 못 보든, 파일 목록이 비었든, 결과는 같은 초록이다. U2 §2.11 이 그 표본이다 —
 * 눌림 계약이 초록인 동안 실제 기하는 13.65px 어긋나 있었다.
 *
 * 그래서 전반부는 **합성 fixture 로 검출력을 증명**한다. 형태마다 양성 대조(발화해야 한다)와
 * 음성 대조(near-miss 에서 조용해야 한다)를 짝으로 세운다. 후반부만 실 제품 트리에 건다.
 * 전반부는 저장소 상태와 무관하게 자족적이라 **언제나** 초록이어야 한다.
 *
 * ## 왜 정규식이 아니라 AST 인가
 *
 * 이 저장소의 주석은 죽은 이름을 일부러 보존한다(`bootstrap.js` 머리말이 사라진 별칭 스물일곱을
 * 이름으로 적고, `index.html` 주석이 `window.__push` 를 적는다). 날텍스트로 세면 그 산문이 전부
 * 위반이 되고, 그러면 결정 배경을 못 적게 된다 — CSS 계약이 `strip_comments` 를 두는 이유와 같다.
 * 반대로 주석만 걷는 정규식은 지역 이름 `window`(프로브가 만드는 가짜 창)를 진짜 전역과
 * 구별하지 못한다. 두 거짓을 동시에 없애려면 스코프를 아는 파서가 필요하고, `vite` 가 내주는
 * `parseAst`(oxc)를 쓴다 — 새 의존이 아니다. CI 세 잡 모두 pytest 앞에서 `npm ci` 를 돌므로
 * 부재는 스킵 사유가 아니라 실패다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { dirname as posixDirname, join as posixJoin, normalize as posixNormalize }
  from "node:path/posix";
import { pathToFileURL } from "node:url";

/* 산출물의 물리 위치는 **빌드 설정이 단일 출처**다. 여기서 `build/web` 을 다시 조립하면
   `outDir` 을 옮기는 날 이 게이트만 옛 자리를 보며 초록으로 남는다. */
import viteConfig from "../../vite.config.mjs";

/* 파서는 `vite`(oxc)가 내준다 — `package.json` 에 이미 있는 devDependency 라 새 의존이 아니다.
   정적 import 로 적으면 부재가 파일 평가 단계에서 `ERR_MODULE_NOT_FOUND` 로 터져 "왜" 가 안
   보인다. 조용히 스킵하지 않되 **사유는 말하고** 죽는다. */
let parseAst;
try {
  ({ parseAst } = await import("vite"));
} catch (thrown) {
  throw new Error(
    "프런트 툴체인(`vite`)을 못 불렀습니다 — `npm ci` 가 먼저입니다. 이 게이트를 도는 잡"
    + "(CI 의 pytest-contract)은 pytest 앞에서 그것을 돌리므로 부재는 스킵 사유가 아니라 "
    + `실패입니다: ${thrown.message}`,
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   스캐너 — 소스 한 편을 받아 "이 파일이 만드는 제품 전역과 금지 구문" 을 신고한다.
   ══════════════════════════════════════════════════════════════════════════ */

/** 창을 가리키는 최상위 이름. `self`·`top`·`parent` 는 제품 코드가 한 번도 쓰지 않으므로
 *  넣지 않는다 — 쓰기 시작하면 이 집합을 늘리는 것이 그 변경의 일부다. */
const GLOBAL_ROOTS = new Set(["window", "globalThis"]);

/** 제품이 예약한 전역 이름 대역. 수신자가 지역 식별자여도 **이 이름을 심으면** 제품 전역의
 *  생산이다(`selftest/api.js` 가 주입받은 `win` 에 `__hwpxTest` 를 심는 실제 형태). */
const RESERVED_PREFIX = "__hwpx";

const FUNCTION_TYPES = new Set([
  "FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression",
]);

/** 새 스코프를 여는 노드. 클래스는 제품에 없고 `window` 라는 클래스 이름도 없으므로 뺀다. */
const SCOPE_TYPES = new Set([
  "Program", "FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression",
  "BlockStatement", "StaticBlock", "ForStatement", "ForInStatement", "ForOfStatement",
  "CatchClause",
]);

function isFunctionNode(node) {
  return FUNCTION_TYPES.has(node.type);
}

/** ESTree 자식 노드 열거 — 노드 종류표를 들지 않는다(파서가 노드를 추가해도 안 새게). */
function childNodes(node) {
  const out = [];
  for (const key of Object.keys(node)) {
    if (key === "type" || key === "start" || key === "end" || key === "loc") continue;
    const value = node[key];
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item && typeof item === "object" && typeof item.type === "string") out.push(item);
      }
    } else if (value && typeof value === "object" && typeof value.type === "string") {
      out.push(value);
    }
  }
  return out;
}

/** 바인딩 패턴에서 이름을 긁는다(구조분해·기본값·rest 포함). */
function bindingNames(pattern, into) {
  if (!pattern || typeof pattern !== "object") return;
  switch (pattern.type) {
    case "Identifier": into.add(pattern.name); break;
    case "ObjectPattern":
      for (const prop of pattern.properties) {
        bindingNames(prop.type === "RestElement" ? prop.argument : prop.value, into);
      }
      break;
    case "ArrayPattern":
      for (const el of pattern.elements) bindingNames(el, into);
      break;
    case "AssignmentPattern": bindingNames(pattern.left, into); break;
    case "RestElement": bindingNames(pattern.argument, into); break;
    default: break;
  }
}

/** 이 스코프 노드가 **직접** 도입하는 이름들. `var` 의 함수 스코프 승격까지는 흉내 내지
 *  않는다 — 그 정밀도가 필요한 형태(`{ var window = …; } window.X = 1;`)는 제품에도
 *  fixture 에도 없고, 부족하면 거짓 **양성** 쪽으로 틀리므로 조용히 새지 않는다. */
function declaredIn(node) {
  const names = new Set();
  if (isFunctionNode(node)) {
    if (node.id) names.add(node.id.name);
    for (const param of node.params) bindingNames(param, names);
  }
  if (node.type === "CatchClause") bindingNames(node.param, names);
  if (node.type === "ForStatement" && node.init && node.init.type === "VariableDeclaration") {
    for (const d of node.init.declarations) bindingNames(d.id, names);
  }
  if ((node.type === "ForInStatement" || node.type === "ForOfStatement")
    && node.left && node.left.type === "VariableDeclaration") {
    for (const d of node.left.declarations) bindingNames(d.id, names);
  }

  let body = [];
  if (node.type === "Program" || node.type === "BlockStatement" || node.type === "StaticBlock") {
    body = node.body;
  } else if (isFunctionNode(node) && node.body && node.body.type === "BlockStatement") {
    body = node.body.body;
  }
  for (const stmt of body) {
    if (stmt.type === "VariableDeclaration") {
      for (const d of stmt.declarations) bindingNames(d.id, names);
    } else if (stmt.type === "FunctionDeclaration" && stmt.id) {
      names.add(stmt.id.name);
    } else if (stmt.type === "ClassDeclaration" && stmt.id) {
      names.add(stmt.id.name);
    } else if (stmt.type === "ImportDeclaration") {
      for (const spec of stmt.specifiers) names.add(spec.local.name);
    }
  }
  return names;
}

function resolves(scope, name) {
  for (let s = scope; s !== null; s = s.parent) if (s.names.has(name)) return true;
  return false;
}

/** 모듈 최상단 `const X = "문자열"` 표. 이름 상수로 심는 전역을 풀기 위한 것이다
 *  (`Object.defineProperty(win, SELFTEST_GLOBAL, …)`). */
function topLevelStringConstants(program) {
  const table = new Map();
  for (const raw of program.body) {
    const stmt = raw.type === "ExportNamedDeclaration" && raw.declaration
      ? raw.declaration : raw;
    if (stmt.type !== "VariableDeclaration") continue;
    for (const decl of stmt.declarations) {
      if (decl.id.type !== "Identifier" || !decl.init) continue;
      if (decl.init.type === "Literal" && typeof decl.init.value === "string") {
        table.set(decl.id.name, decl.init.value);
      }
    }
  }
  return table;
}

/** 프로퍼티 키를 **정적으로** 확정한다. 못 하면 `null` — 호출자가 그 무지를 시끄럽게 진다. */
function staticKey(node, computed, constants) {
  if (!computed) {
    if (node.type === "Identifier") return node.name;
    if (node.type === "Literal" && typeof node.value === "string") return node.value;
    return null;
  }
  if (node.type === "Literal" && typeof node.value === "string") return node.value;
  if (node.type === "TemplateLiteral" && node.expressions.length === 0) {
    /* ESTree 의 TemplateElement 는 `{value: {raw, cooked}}` 다 — 한 겹 안이라 놓치기 쉽고,
       놓치면 `undefined` 가 이름 행세를 한다(그 조용한 통과가 정확히 이 게이트의 적이다). */
    const cooked = node.quasis[0].value.cooked;
    return typeof cooked === "string" ? cooked : null;
  }
  if (node.type === "Identifier" && constants.has(node.name)) return constants.get(node.name);
  return null;
}

/** 괄호·단항·시퀀스·await 껍질을 벗겨 알맹이 식을 꺼낸다(IIFE 변형 흡수용). */
function unwrapExpression(node) {
  let cur = node;
  for (;;) {
    if (cur.type === "UnaryExpression" || cur.type === "AwaitExpression") { cur = cur.argument; continue; }
    if (cur.type === "SequenceExpression") { cur = cur.expressions[cur.expressions.length - 1]; continue; }
    return cur;
  }
}

function isObjectStatic(node, scope, member) {
  return node.type === "MemberExpression" && !node.computed
    && node.object.type === "Identifier" && node.object.name === "Object"
    && !resolves(scope, "Object")
    && node.property.type === "Identifier" && node.property.name === member;
}

/**
 * 소스 한 편을 훑는다.
 *
 * 돌려주는 것:
 *   - `globalWrites`  : 창(전역 루트)에 **이름을 세운** 자리 `{name, kind, line}`
 *   - `unknownWrites` : 창에 세우긴 하는데 **이름을 정적으로 못 푸는** 자리 — 무지의 신고
 *   - `globalReads`   : 창의 프로퍼티를 읽은 이름들(쓰기도 여기 포함된다)
 *   - `globalAliases` : 창을 지역 이름에 담은 자리 — 위 전부를 우회하는 구멍
 *   - `reservedInstalls`: 수신자가 무엇이든 `__hwpx*` 이름을 심은 자리
 *   - `topLevelIifes` : 모듈 최상단 즉시 실행
 *   - `imports`       : 정적·동적 import 지정자
 */
export function scanSource(source, filename = "<입력>") {
  let program;
  try {
    /* `.ts`/`.tsx` 는 lang 옵션이 있어야 파싱된다(무옵션 parseAst 는 TS 문법에서 죽는다 —
       allowlist 게이트 착수 실측과 같다). 미지 확장자는 js 로 시도하고, 실패는 스킵이
       아니라 실패다. */
    const lang = filename.endsWith(".tsx") ? "tsx" : filename.endsWith(".ts") ? "ts" : "js";
    program = parseAst(source, { lang });
  } catch (thrown) {
    throw new Error(`${filename} 파싱 실패 — 게이트가 볼 수 없는 파일입니다: ${thrown.message}`);
  }

  const constants = topLevelStringConstants(program);
  const found = {
    globalWrites: [], unknownWrites: [], globalReads: [], globalAliases: [],
    reservedInstalls: [], topLevelIifes: [], imports: [],
  };
  const lineOf = (node) => source.slice(0, node.start).split("\n").length;

  /* TS erasable 래퍼는 투명하다(#490 검증 라운드 실측) — `.ts` 의 자연형은 캐스트를
     지나므로(`(window as Record<string, unknown>).x = 1`; 캐스트 없는 창 확장은 strict
     tsc 가 형식 오류로 먼저 문다), 래퍼를 안 벗기면 수집만 넓힌 채 술어가 `.ts` 전역
     생산을 영영 못 본다 — 선언은 살고 결과는 죽는 그 결함류다. */
  const unwrap = (node) => {
    let current = node;
    while (current && (current.type === "TSAsExpression"
      || current.type === "TSSatisfiesExpression"
      || current.type === "TSNonNullExpression"
      || current.type === "ParenthesizedExpression")) {
      current = current.expression;
    }
    return current;
  };
  const isRoot = (rawNode, scope) => {
    const node = unwrap(rawNode);
    return node.type === "Identifier"
      && GLOBAL_ROOTS.has(node.name) && !resolves(scope, node.name);
  };

  const addWrite = (name, kind, node, receiver) => {
    if (name === null) {
      found.unknownWrites.push({ kind, line: lineOf(node), receiver });
      return;
    }
    if (receiver === "global") found.globalWrites.push({ name, kind, line: lineOf(node) });
    if (name.startsWith(RESERVED_PREFIX)) {
      found.reservedInstalls.push({ name, kind, receiver, line: lineOf(node) });
    }
  };

  const visit = (node, scope, inFunction) => {
    /* ── 창 프로퍼티 판독(쓰기의 상위집합) ── */
    if (node.type === "MemberExpression" && isRoot(node.object, scope)) {
      const name = staticKey(node.property, node.computed, constants);
      if (name !== null) found.globalReads.push({ name, line: lineOf(node) });
    }

    /* ── ①②③ 대입 쓰기 ── */
    if (node.type === "AssignmentExpression" && node.left.type === "MemberExpression"
      && isRoot(node.left.object, scope)) {
      addWrite(
        staticKey(node.left.property, node.left.computed, constants),
        node.left.computed ? "bracket-assign" : "dot-assign", node, "global",
      );
    }

    /* ── ①②③ 갱신 쓰기 ──
       `window.Leak++` 는 대입 연산자가 아니지만, 부재 프로퍼티를 읽은 뒤
       `NaN`을 다시 써 own 전역을 만든다. 판독으로만 세면 임의 전역이
       실제로 생겨도 allowlist 게이트가 초록이 된다. */
    if (node.type === "UpdateExpression" && node.argument.type === "MemberExpression"
      && isRoot(node.argument.object, scope)) {
      addWrite(
        staticKey(node.argument.property, node.argument.computed, constants),
        node.argument.computed ? "bracket-update" : "dot-update", node, "global",
      );
    }

    /* ── ⑩ 창을 지역 이름에 담는다 ── */
    if (node.type === "VariableDeclarator" && node.init && isRoot(node.init, scope)) {
      found.globalAliases.push({ name: node.id.name, line: lineOf(node) });
    }
    if (node.type === "AssignmentExpression" && node.left.type === "Identifier"
      && isRoot(node.right, scope)) {
      found.globalAliases.push({ name: node.left.name, line: lineOf(node) });
    }

    /* ── ④⑤⑪ Object.assign / defineProperty(-ies) ── */
    if (node.type === "CallExpression") {
      const target = node.arguments[0];
      const receiverOf = (arg) => {
        if (!arg) return null;
        if (isRoot(arg, scope)) return "global";
        /* 지역 식별자 수신자 — 주입받은 창일 수 있다. 이름 축(예약 대역)으로만 센다. */
        return arg.type === "Identifier" ? "injected" : null;
      };
      if (isObjectStatic(node.callee, scope, "assign")) {
        const receiver = receiverOf(target);
        if (receiver !== null) {
          for (const arg of node.arguments.slice(1)) {
            if (arg.type === "ObjectExpression") {
              for (const prop of arg.properties) {
                if (prop.type === "SpreadElement") { addWrite(null, "object-assign", arg, receiver); continue; }
                addWrite(staticKey(prop.key, prop.computed, constants), "object-assign", arg, receiver);
              }
            } else if (receiver === "global") {
              addWrite(null, "object-assign", arg, receiver);
            }
          }
        }
      }
      if (isObjectStatic(node.callee, scope, "defineProperty")) {
        const receiver = receiverOf(target);
        if (receiver !== null) {
          addWrite(
            staticKey(node.arguments[1], true, constants), "define-property", node, receiver,
          );
        }
      }
      if (isObjectStatic(node.callee, scope, "defineProperties")) {
        const receiver = receiverOf(target);
        const descriptors = node.arguments[1];
        if (receiver !== null) {
          if (descriptors && descriptors.type === "ObjectExpression") {
            for (const prop of descriptors.properties) {
              addWrite(
                prop.type === "SpreadElement"
                  ? null : staticKey(prop.key, prop.computed, constants),
                "define-properties", node, receiver,
              );
            }
          } else {
            addWrite(null, "define-properties", node, receiver);
          }
        }
      }
    }

    /* ── ⑦ 모듈 최상단 IIFE ── */
    if (node.type === "ExpressionStatement" && !inFunction) {
      const expr = unwrapExpression(node.expression);
      if (expr.type === "CallExpression" && isFunctionNode(expr.callee)) {
        found.topLevelIifes.push({
          line: lineOf(node),
          arrow: expr.callee.type === "ArrowFunctionExpression",
        });
      }
    }

    /* ── ⑧⑨ import ── */
    if ((node.type === "ImportDeclaration" || node.type === "ExportNamedDeclaration"
      || node.type === "ExportAllDeclaration") && node.source) {
      found.imports.push(node.source.value);
    }
    if (node.type === "ImportExpression" && node.source
      && node.source.type === "Literal" && typeof node.source.value === "string") {
      found.imports.push(node.source.value);
    }
  };

  const walk = (node, scope, inFunction) => {
    visit(node, scope, inFunction);
    const childScope = SCOPE_TYPES.has(node.type)
      ? { names: declaredIn(node), parent: scope } : scope;
    const childInFunction = inFunction || isFunctionNode(node);
    for (const child of childNodes(node)) walk(child, childScope, childInFunction);
  };

  walk(program, null, false);
  return found;
}

/** HTML 의 `<script>` 를 읽는다. 주석은 **먼저 걷는다** — `index.html` 은 역사 서사를 주석으로
 *  보존하고, 그 안에 옛 클래식 스크립트 예시가 들어 있다. */
export function scanHtmlScripts(html) {
  const code = html.replace(/<!--[\s\S]*?-->/g, "");
  return [...code.matchAll(/<script\b([^>]*)>/gi)].map((match) => {
    const attrs = match[1];
    const type = /\btype\s*=\s*["']([^"']*)["']/i.exec(attrs);
    const src = /\bsrc\s*=\s*["']([^"']*)["']/i.exec(attrs);
    const kind = type === null ? null : type[1].trim().toLowerCase();
    return { type: kind, src: src === null ? null : src[1], classic: kind !== "module" };
  });
}

/** HTML 시작 태그의 인라인 이벤트 속성을 읽는다.
 *
 *  `onclick="window.Leak = 1"` 같은 속성은 `<script>` 가 아니라 위 스캐너의
 *  AST에 절대 닿지 않지만 브라우저에서는 클래식 스크립트로 실행된다.
 *  제품 HTML은 그 표면을 사용하지 않으므로 속성 이름을 실행 여부와 관계없이
 *  금지한다. 주석의 역사 서술은 스크립트 태그 스캐너와 같이 먼저 걷는다. */
export function scanHtmlEventHandlers(html) {
  const code = html.replace(/<!--[\s\S]*?-->/g, "");
  const handlers = [];
  for (const tag of code.matchAll(/<([A-Za-z][\w:-]*)\b([^>]*)>/g)) {
    const tagName = tag[1].toLowerCase();
    for (const attr of tag[2].matchAll(/(?:^|\s)(on[a-z][\w:-]*)\s*=/gi)) {
      handlers.push({ tag: tagName, attribute: attr[1].toLowerCase() });
    }
  }
  return handlers;
}

/* ══════════════════════════════════════════════════════════════════════════
   전반부 — fixture 로 증명하는 검출력. 저장소 상태와 무관하게 자족적이다.
   ══════════════════════════════════════════════════════════════════════════ */

const FIXTURES = new URL("./fixtures/n10/", import.meta.url);

function fixture(relative) {
  const url = new URL(relative, FIXTURES);
  assert.ok(existsSync(url), `fixture 가 없습니다: ${relative} — 대조가 통째로 무효입니다.`);
  return readFileSync(url, "utf8");
}

function scanFixture(relative) {
  return scanSource(fixture(relative), relative);
}

const names = (writes) => writes.map((w) => w.name).sort();

test("검출력 ① — `window.X = …` 를 문다 / 지역 `window` 는 물지 않는다", () => {
  const hit = scanFixture("pos/window_dot.js");
  assert.deepEqual(names(hit.globalWrites), ["Leak"]);
  assert.equal(hit.globalWrites[0].kind, "dot-assign");

  /* 음성 대조 — 텍스트는 같고 가리키는 것이 다르다. 스코프를 보는 스캐너만 통과한다. */
  const miss = scanFixture("neg/local_window.js");
  assert.deepEqual(miss.globalWrites, [], "지역 이름 `window` 를 전역으로 셌습니다.");
  assert.deepEqual(miss.unknownWrites, []);
});

test("검출력 ② — `globalThis.X = …` 를 문다 / 라벨·지역은 물지 않는다", () => {
  const hit = scanFixture("pos/global_this.js");
  assert.deepEqual(names(hit.globalWrites), ["Leak"]);

  const miss = scanFixture("neg/local_window.js");
  assert.deepEqual(miss.globalWrites, []);
});

test("검출력 ③ — 대괄호 쓰기를 문다(문자열·템플릿), 계산된 이름은 **무지로 신고**한다", () => {
  const hit = scanFixture("pos/bracket_literal.js");
  assert.deepEqual(names(hit.globalWrites), ["Leak", "LeakTemplate"]);
  for (const write of hit.globalWrites) assert.equal(write.kind, "bracket-assign");

  /* 계산된 이름은 조용히 넘기지 않는다 — 그 침묵이 곧 눈먼 자리다. */
  const dynamic = scanFixture("pos/bracket_computed.js");
  assert.deepEqual(dynamic.globalWrites, []);
  assert.equal(dynamic.unknownWrites.length, 2,
    "계산된 전역 쓰기를 무지로 신고하지 못했습니다.");

  /* 음성 대조 — 창 **판독**은 쓰기가 아니다. */
  const read = scanFixture("neg/window_read.js");
  assert.deepEqual(read.globalWrites, []);
  assert.deepEqual(read.unknownWrites, []);
  assert.ok(read.globalReads.some((r) => r.name === "Leak"),
    "판독 축이 죽어 있습니다 — 별칭 27 의 '판독 0' 계약이 무효가 됩니다.");
});

test("검출력 ③-다 — `window.X++` 갱신도 전역 쓰기로 문다", () => {
  const hit = scanFixture("pos/window_update.js");
  assert.deepEqual(names(hit.globalWrites), ["Leak", "LeakBracket"]);
  assert.deepEqual(hit.globalWrites.map((w) => w.kind).sort(), ["bracket-update", "dot-update"]);
  assert.ok(hit.globalReads.some((r) => r.name === "Leak"),
    "갱신 표현식의 읽기 성질도 사라졌습니다.");
});

test("검출력 ④ — `Object.assign(window, …)` 를 문다 / 다른 수신자는 물지 않는다", () => {
  const hit = scanFixture("pos/object_assign.js");
  assert.deepEqual(names(hit.globalWrites), ["Leak", "LeakTwo"]);

  const miss = scanFixture("neg/assign_other_target.js");
  assert.deepEqual(miss.globalWrites, []);
  assert.deepEqual(miss.unknownWrites, []);
  assert.deepEqual(miss.reservedInstalls, []);
});

test("검출력 ⑤ — `Object.defineProperty(window, …)` 를 문다 / 다른 객체는 물지 않는다", () => {
  const hit = scanFixture("pos/define_property.js");
  assert.deepEqual(names(hit.globalWrites), ["Leak"]);
  assert.equal(hit.globalWrites[0].kind, "define-property");

  const miss = scanFixture("neg/define_property_other.js");
  assert.deepEqual(miss.globalWrites, []);
  assert.deepEqual(miss.reservedInstalls, [],
    "예약 대역 밖의 이름을 지역 객체에 심은 것을 위반으로 셌습니다.");
});

test("검출력 ⑥ — 클래식 `<script>` 를 문다 / `type=module` 과 주석은 물지 않는다", () => {
  const hit = scanHtmlScripts(fixture("pos/classic_script.html"));
  assert.equal(hit.length, 2);
  assert.deepEqual(hit.map((s) => s.classic), [true, true],
    "src 형태·인라인 형태의 클래식 스크립트를 놓쳤습니다.");

  const miss = scanHtmlScripts(fixture("neg/module_script.html"));
  assert.equal(miss.length, 1, "주석 속 옛 스크립트 예시를 실물로 셌습니다.");
  assert.equal(miss[0].classic, false);
  assert.equal(miss[0].type, "module");
});

test("검출력 ⑥-나 — 인라인 `on*` 핸들러를 문다 / 주석·data 속성은 물지 않는다", () => {
  const hit = scanHtmlEventHandlers(fixture("pos/inline_handler.html"));
  assert.deepEqual(hit, [
    { tag: "button", attribute: "onclick" },
    { tag: "input", attribute: "onchange" },
  ]);

  const miss = scanHtmlEventHandlers(fixture("neg/module_script.html"));
  assert.deepEqual(miss, [], "주석이나 data-onclick 속성을 실행 핸들러로 세셨습니다.");
});

test("검출력 ⑦ — 최상단 IIFE 를 문다(함수·화살표·단항) / 함수 안의 것은 물지 않는다", () => {
  const classic = scanFixture("pos/top_iife.js");
  assert.equal(classic.topLevelIifes.length, 2, "단항으로 감싼 IIFE 를 놓쳤습니다.");

  const arrow = scanFixture("pos/top_iife_arrow.js");
  assert.equal(arrow.topLevelIifes.length, 1);
  assert.equal(arrow.topLevelIifes[0].arrow, true);

  const miss = scanFixture("neg/nested_iife.js");
  assert.deepEqual(miss.topLevelIifes, [], "함수 안의 즉시 실행을 최상단으로 셌습니다.");
});

test("검출력 ⑧ — import 순환을 문다 / 다이아몬드는 물지 않는다", () => {
  const cycles = fixtureCycles("pos/cycle_a.js");
  assert.equal(cycles.length >= 1, true, "a ↔ b 순환을 놓쳤습니다.");
  assert.ok(cycles[0].join(" -> ").includes("cycle_b.js"));

  const clean = fixtureCycles("neg/acyclic_a.js");
  assert.deepEqual(clean, [], "같은 잎을 두 번 방문한 것을 순환으로 셌습니다.");
});

test("검출력 ⑨ — `compat.js` 의 재등장과 참조를 문다 / `compatibility.js` 는 물지 않는다", () => {
  /* 파일 이름 축 — 접두 일치가 아니라 **이름 자체**로 센다. */
  const inPos = readdirSync(new URL("pos/", FIXTURES));
  const inNeg = readdirSync(new URL("neg/", FIXTURES));
  assert.deepEqual(inPos.filter(isCompatFile), ["compat.js"]);
  assert.deepEqual(inNeg.filter(isCompatFile), [],
    "`compatibility.js` 를 `compat.js` 로 셌습니다.");

  /* 참조 축 — import 지정자만 본다. 주석의 옛 이름은 계약이 아니다. */
  assert.deepEqual(
    scanFixture("pos/compat_import.js").imports.filter(isCompatSpecifier),
    ["./compat.js"],
  );
  assert.deepEqual(
    scanFixture("neg/compat_mention_import.js").imports.filter(isCompatSpecifier),
    [], "주석이 `compat.js` 를 언급했다는 이유로 발화했습니다.",
  );
});

test("검출력 ⑩ — 창을 지역 이름에 담는 우회를 문다 / 인자로 넘기는 것은 물지 않는다", () => {
  const hit = scanFixture("pos/global_alias.js");
  assert.deepEqual(hit.globalAliases.map((a) => a.name), ["w"]);

  const miss = scanFixture("neg/alias_passing.js");
  assert.deepEqual(miss.globalAliases, [],
    "`{ win: window }` 주입을 별칭으로 셌습니다 — N-09 설계 자체가 그 형태입니다.");
});

test("검출력 ⑪ — 주입받은 창에 심는 예약 이름을 **이름 축으로** 문다", () => {
  const hit = scanFixture("pos/reserved_key_indirect.js");
  assert.deepEqual(hit.globalWrites, [], "지역 수신자를 전역 쓰기로 셌습니다.");
  assert.deepEqual(hit.reservedInstalls.map((r) => r.name), ["__hwpxTest"]);
  assert.equal(hit.reservedInstalls[0].receiver, "injected");

  const miss = scanFixture("neg/define_property_other.js");
  assert.deepEqual(miss.reservedInstalls, []);
});

test("검출력 — 주석·문자열 속 전역 쓰기는 **한 건도** 물지 않는다", () => {
  const miss = scanFixture("neg/comment_and_string.js");
  assert.deepEqual(miss.globalWrites, []);
  assert.deepEqual(miss.unknownWrites, []);
  assert.deepEqual(miss.globalReads, []);
  assert.deepEqual(miss.reservedInstalls, []);
  assert.deepEqual(miss.globalAliases, []);

  /* 음성 대조의 음성 대조 — 이 fixture 에 실제로 그 텍스트가 들어 있는지 먼저 확인한다.
     텍스트가 없으면 위 다섯 단언은 아무것도 증명하지 않는다(공허한 초록). */
  const text = fixture("neg/comment_and_string.js");
  assert.ok(text.includes("window.Leak = 1"), "near-miss 텍스트가 fixture 에서 사라졌습니다.");
  assert.ok(text.includes("globalThis.Leak = 1"));
});

/* ══════════════════════════════════════════════════════════════════════════
   후반부 — 실 제품 트리. 전반부가 증명한 검출력을 그대로 건다.
   ══════════════════════════════════════════════════════════════════════════ */

const FRONTEND = new URL("../../frontend/", import.meta.url);

/** 제품 코드가 만들어도 되는 전역 — 전수. `pywebview` 는 런타임 주입이라 여기 없다. */
const ALLOWED_GLOBALS = ["__hwpx", "__hwpxTest"];

/** N-10 이 지우는 임시 별칭 스물일곱 — 전수를 적는다. 목록을 세지 않으면 "몇 개가 남았는지"
 *  를 아무도 못 말하고, 그때 단조 감소 계측(#372 D-05)이 사라진다. */
const DEAD_ALIASES = [
  "Copy", "escHtml", "Guard", "SegView", "Popover", "Preserve", "Intent", "UndoToast",
  "Modal", "SurfaceSheet", "GroupList", "Theme", "Personalization", "SheetPicker",
  "PathTrack", "Relink", "DataZone", "DataPicker", "EditorEntry", "LibraryScreen",
  "EditorScreen", "JobScreen", "WorkbenchScreen", "Nav", "AppCloseGuard", "Bridge", "__push",
];

/** 수집은 감산형이다(#490 F2) — 확장자 열거가 아니라 계약의 non_code_suffixes 만 뺀다.
 *  이 게이트가 「제품이 만드는 창 전역」의 유일한 정적 집행자라, `.js` 열거로 두면 `.ts`
 *  서브트리의 전역 생산이 그물 밖에서 자란다(#490 검증 라운드 B1 실측 — `.ts` 에 신규
 *  전역을 넣어도 전 게이트 초록이었다). allowlist 게이트와 같은 계약 파일을 읽는다. */
const NON_CODE_SUFFIXES = JSON.parse(
  readFileSync(new URL("../static_closure_contract.json", import.meta.url), "utf8"),
).non_code_suffixes;

function listSources(relativeDir) {
  const out = [];
  const walkDir = (rel) => {
    const url = new URL(rel, FRONTEND);
    if (!existsSync(url)) return;
    for (const entry of readdirSync(url, { withFileTypes: true })) {
      if (entry.isDirectory()) walkDir(`${rel}${entry.name}/`);
      else if (!NON_CODE_SUFFIXES.some((suffix) => entry.name.endsWith(suffix))) {
        out.push(`${rel}${entry.name}`);
      }
    }
  };
  walkDir(relativeDir);
  return out.sort();
}

const PRODUCT_FILES = [...listSources("src/"), ...listSources("js/")];

const PRODUCT = new Map(
  PRODUCT_FILES.map((rel) => [rel, readFileSync(new URL(rel, FRONTEND), "utf8")]),
);

const SCANS = new Map([...PRODUCT].map(([rel, src]) => [rel, scanSource(src, rel)]));

test("공허 방지 — 스캔 대상이 실재한다(양성 대조)", () => {
  /* 목록이 비면 아래 "0건" 단언은 전부 초록이다. 그 초록은 아무 뜻이 없다. */
  assert.ok(PRODUCT_FILES.length >= 30,
    `제품 JS 를 ${PRODUCT_FILES.length} 개밖에 못 찾았습니다 — 경로가 어긋났습니다.`);
  assert.ok(PRODUCT_FILES.includes("src/main.js"));
  assert.ok(PRODUCT_FILES.includes("src/selftest/api.js"));
  assert.ok(PRODUCT_FILES.some((rel) => rel.startsWith("js/screens/")));
  for (const [rel, source] of PRODUCT) {
    assert.ok(source.length > 0, `${rel} 이 비었습니다.`);
  }

  /* 스캐너가 이 트리에서 **실제로 무언가를 본다**는 증거. 전부 0 이면 파서가 죽었거나
     경로가 틀린 것이고, 그 둘은 계약 위반 없음과 구별되지 않는다. */
  const totalReads = [...SCANS.values()].reduce((n, s) => n + s.globalReads.length, 0);
  assert.ok(totalReads > 10, `창 판독을 ${totalReads} 건밖에 못 봤습니다 — 스캐너가 멀었습니다.`);
});

test("검출력 — `.ts` 캐스트 래퍼를 지나는 창 쓰기·판독을 문다(#490)", () => {
  /* `.ts` 의 자연형 — 캐스트 없는 창 확장은 strict tsc 가 형식 오류로 먼저 무므로,
     이 게이트가 실제로 만날 형태는 래퍼를 지난 쪽이다. 래퍼가 투명하지 않으면 수집을
     `.ts` 로 넓힌 것이 선언으로만 남는다(위 unwrap 주석). */
  const cast = scanSource(
    "export function leak(): void {\n"
    + "  (window as unknown as Record<string, unknown>).probeNewGlobal = 1;\n"
    + "}\n",
    "probe.ts",
  );
  assert.deepEqual(cast.globalWrites.map((w) => w.name), ["probeNewGlobal"],
    "TSAsExpression 래퍼를 지난 창 쓰기를 놓쳤습니다");

  const nonNull = scanSource("const v = window!.name;\n", "probe2.ts");
  assert.deepEqual(nonNull.globalReads.map((r) => r.name), ["name"],
    "TSNonNullExpression 래퍼를 지난 창 판독을 놓쳤습니다");

  /* 음성 — 지역으로 가려진 이름은 래퍼를 벗겨도 창이 아니다. */
  const shadowed = scanSource(
    "export function f(window: { x: number }): number { return (window as { x: number }).x; }\n",
    "probe3.ts",
  );
  assert.deepEqual(shadowed.globalReads, [], "가려진 window 매개변수를 창으로 오인했습니다");
});

test("제품이 만드는 전역은 정확히 `__hwpx`·`__hwpxTest` 둘뿐이다", () => {
  const direct = new Map();
  const unknown = [];
  for (const [rel, scan] of SCANS) {
    for (const write of scan.globalWrites) {
      if (!direct.has(write.name)) direct.set(write.name, []);
      direct.get(write.name).push(`${rel}:${write.line}`);
    }
    for (const write of scan.unknownWrites) {
      if (write.receiver === "global") unknown.push(`${rel}:${write.line}(${write.kind})`);
    }
  }

  /* 이름을 못 푸는 전역 쓰기가 하나라도 있으면 위 표는 전수가 아니다 — 조용히 넘기지 않는다. */
  assert.deepEqual(unknown, [],
    `이름을 정적으로 못 푸는 전역 쓰기가 있습니다: ${unknown.join(", ")}`);

  /* 직접 쓰기는 `__hwpx` 하나다. `__hwpxTest` 는 주입받은 창에 심으므로 직접 축엔 안 나온다 —
     그 비대칭이 곧 "시험 훅은 제품 표면이 아니다" 라는 설계의 정적 얼굴이다. */
  assert.deepEqual([...direct.keys()].sort(), ["__hwpx"],
    `제품이 만드는 직접 전역이 __hwpx 하나가 아닙니다: ${JSON.stringify([...direct])}`);

  const reserved = new Set();
  for (const scan of SCANS.values()) for (const r of scan.reservedInstalls) reserved.add(r.name);
  assert.deepEqual([...reserved].sort(), ALLOWED_GLOBALS,
    "예약 대역에 심는 이름이 `__hwpx`·`__hwpxTest` 둘과 다릅니다.");
});

test("`window.__hwpx` 의 생산자는 `src/bootstrap.js` **하나**다", () => {
  const producers = [];
  for (const [rel, scan] of SCANS) {
    for (const write of scan.globalWrites) {
      if (write.name === "__hwpx") producers.push(`${rel}:${write.line}`);
    }
  }
  assert.equal(producers.length, 1, `__hwpx 생산자가 하나가 아닙니다: ${producers.join(", ")}`);
  assert.ok(producers[0].startsWith("src/bootstrap.js:"),
    `__hwpx 생산자가 합성 루트가 아닙니다: ${producers[0]}`);
});

test("`window.__hwpxTest` 의 생산자는 `src/selftest/api.js` 하나이고 **조건부**다", () => {
  const sites = [];
  for (const [rel, scan] of SCANS) {
    for (const install of scan.reservedInstalls) {
      if (install.name === "__hwpxTest") sites.push({ rel, ...install });
    }
  }
  assert.equal(sites.length, 1, `__hwpxTest 생산자가 하나가 아닙니다: ${JSON.stringify(sites)}`);
  assert.equal(sites[0].rel, "src/selftest/api.js");
  assert.equal(sites[0].kind, "define-property",
    "`defineProperty` 가 아닌 방식으로 심고 있습니다 — 재정의 불가 계약이 깨집니다.");

  /* 조건부인가. "설치 함수 안에 있다" 로는 부족하다 — 그 함수가 무조건 설치하면 조건부가
     아니다. 그래서 ①모듈 최상단 실행이 아니고 ②설치 지점 **앞에** 이른 반환 가드가 있으며
     ③호출자도 최상단이 아니라 능력 술어 뒤에 있다, 셋을 함께 센다. */
  const api = PRODUCT.get("src/selftest/api.js");
  const install = installSite(api);
  assert.ok(install.insideFunction,
    "`__hwpxTest` 설치가 모듈 최상단에 있습니다 — 부팅만으로 시험 훅이 섭니다.");
  assert.ok(install.guardsBefore >= 3,
    `설치 앞의 이른 반환 가드가 ${install.guardsBefore} 개뿐입니다 — 무조건 설치입니다.`);

  /* 호출자 축 — `boot.js` 가 호스트 능력 술어 뒤에서만 부른다. 이 축이 없으면 "가드는 있는데
     아무도 그 앞의 조건을 안 본다" 는 상태가 초록으로 남는다. */
  const boot = PRODUCT.get("src/selftest/boot.js");
  assert.ok(boot.includes("testHost.available()"),
    "부팅 배선이 호스트 능력 술어를 읽지 않습니다 — 활성화 조건이 사라졌습니다.");
  const bootCall = callSite(boot, "installSelftestApi");
  assert.ok(bootCall.insideFunction,
    "`installSelftestApi` 호출이 모듈 최상단입니다 — 평가만으로 설치가 시도됩니다.");

  /* `api.js` 는 페이지 쪽에서 만들 수 있는 조건을 **한 글자도** 읽지 않는다. */
  const scan = SCANS.get("src/selftest/api.js");
  for (const read of scan.globalReads) {
    assert.notEqual(read.name, "location", "설치 조건에 URL 이 끼어들었습니다.");
  }
});

test("`compat.js` 는 파일로도 참조로도 남아 있지 않다", () => {
  const offenders = PRODUCT_FILES.filter((rel) => isCompatFile(rel.split("/").pop()));
  assert.deepEqual(offenders, [], `compat.js 가 되살아났습니다: ${offenders.join(", ")}`);

  const refs = [];
  for (const [rel, scan] of SCANS) {
    for (const spec of scan.imports) if (isCompatSpecifier(spec)) refs.push(`${rel} -> ${spec}`);
  }
  assert.deepEqual(refs, [], `compat.js 참조가 남았습니다: ${refs.join(", ")}`);

  /* 양성 대조 — 이름 축 검사가 실제로 파일 이름을 보고 있다는 증거. 이것이 없으면
     `PRODUCT_FILES` 가 비어도 위 두 단언은 초록이다. */
  assert.ok(PRODUCT_FILES.includes("src/bootstrap.js"),
    "합성 루트가 없습니다 — 이름 축 검사가 아무 파일도 안 보고 있습니다.");
});

test("`index.html` 의 스크립트는 `type=module` **하나**뿐이다", () => {
  const html = readFileSync(new URL("index.html", FRONTEND), "utf8");
  assert.ok(html.length > 1000, "index.html 을 못 읽었습니다.");

  const scripts = scanHtmlScripts(html);
  assert.equal(scripts.length, 1, `스크립트가 ${scripts.length} 개입니다: ${JSON.stringify(scripts)}`);
  assert.equal(scripts[0].classic, false);
  assert.equal(scripts[0].type, "module");
  assert.equal(scripts[0].src, "./src/main.js",
    "entry 가 합성 루트를 부르는 `src/main.js` 가 아닙니다.");

  const handlers = scanHtmlEventHandlers(html);
  assert.deepEqual(handlers, [],
    `제품 HTML에 인라인 이벤트 핸들러가 있습니다: ${JSON.stringify(handlers)}`);
});

test("모듈 최상단 IIFE 가 0 이다 — 부팅은 평가가 아니라 호출이 진다", () => {
  const offenders = [];
  for (const [rel, scan] of SCANS) {
    for (const iife of scan.topLevelIifes) offenders.push(`${rel}:${iife.line}`);
  }
  assert.deepEqual(offenders, [], `최상단 IIFE 가 남았습니다: ${offenders.join(", ")}`);

  /* 양성 대조 — 최상단 표현식 자체는 존재한다(`main.js` 의 `bootProduct()`). 스캐너가
     최상단을 실제로 보고 있다는 증거이고, 없으면 "0건" 은 눈먼 초록이다. */
  assert.ok(PRODUCT.get("src/main.js").includes("bootProduct();"),
    "entry 의 단일 부팅 호출이 사라졌습니다.");
});

test("`src/main.js` 에서 도달하는 그래프에 순환도 외부 지정자도 없다", () => {
  const { cycles, bare, visited } = traverse("src/main.js");
  assert.deepEqual(cycles.map((c) => c.join(" -> ")), [], "import 순환이 있습니다.");
  assert.deepEqual(bare, [], `외부 지정자가 있습니다: ${bare.join(", ")}`);

  /* 순회가 실제로 그래프를 걸었다는 증거 — 두 노드만 밟고 끝나면 "순환 0" 은 공허하다. */
  assert.ok(visited.size >= 30, `도달 모듈이 ${visited.size} 개뿐입니다 — 배선이 끊겼습니다.`);
  assert.ok(visited.has("src/bootstrap.js"), "entry 가 합성 루트에 닿지 않습니다.");
  assert.ok(visited.has("src/selftest/api.js"), "시험 능력이 그래프에 닿지 않습니다.");
  assert.ok(visited.has("js/screens/job.js"), "화면이 그래프에 닿지 않습니다.");
});

test("죽은 별칭 스물일곱이 쓰기로도 판독으로도 남아 있지 않다", () => {
  assert.equal(DEAD_ALIASES.length, 27, "별칭 전수가 스물일곱이 아닙니다.");
  const dead = new Set(DEAD_ALIASES);

  const offenders = [];
  for (const [rel, scan] of SCANS) {
    for (const write of scan.globalWrites) {
      if (dead.has(write.name)) offenders.push(`쓰기 ${rel}:${write.line} window.${write.name}`);
    }
    /* 판독까지 세는 이유: 생산자가 사라져도 소비자가 남으면 그 소비는 런타임에 `undefined`
       를 읽고 조용히 죽는다. 그 침묵은 "기능이 없다" 로도 "버그" 로도 안 보인다. */
    for (const read of scan.globalReads) {
      if (dead.has(read.name)) offenders.push(`판독 ${rel}:${read.line} window.${read.name}`);
    }
    for (const alias of scan.globalAliases) {
      offenders.push(`창 별칭 ${rel}:${alias.line} const ${alias.name} = window`);
    }
  }
  assert.deepEqual(offenders, [], `임시 별칭이 살아 있습니다:\n  ${offenders.join("\n  ")}`);

  /* 양성 대조 — 같은 스캐너가 옛 형상을 보면 스물일곱을 전부 문다. 이 대조가 없으면
     위 "0건" 은 "스캐너가 이름을 하나도 못 본다" 와 구별되지 않는다. */
  const legacy = scanSource(
    DEAD_ALIASES.map((name) => `window.${name} = 1;`).join("\n"), "<옛 compat.js 재현>",
  );
  assert.deepEqual(names(legacy.globalWrites), [...DEAD_ALIASES].sort(),
    "스캐너가 옛 별칭 형상을 못 뭅니다 — 위 0건은 눈먼 초록입니다.");
});

/* ══════════════════════════════════════════════════════════════════════════
   후반부 ② — 출하 산출물. 봉인은 **정체성**을 지키지 **성질**을 지키지 않는다.
   ══════════════════════════════════════════════════════════════════════════

   위 검사는 전부 `frontend/` 를 본다. 그런데 사용자에게 가는 것은 그 트리가 아니라
   `build/web/` 의 번들이고, 둘 사이에는 번들러가 있다. `web-artifact-seal.json` 은 그 번들의
   바이트가 **예상대로임**을 증명하지만 그 바이트에 클래식 스크립트나 새 전역이 없다는 것은
   증명하지 않는다 — 봉인이 지키는 것은 정체성이지 성질이다.

   런타임 층도 이 자리를 못 메운다. 두 겹 다 구조적으로 못 본다:

     - 전역 델타(`test_selftest_run_adds_exactly_one_global_over_a_normal_run`)는 정상 실행과
       시험 실행의 **상대 뺄셈**이다. 번들이 양쪽에 똑같이 새는 이름을 만들면 차집합이 그대로라
       침묵한다.
     - `resources_same_origin`·`forbidden_resources` 는 오리진 축이다. 동일 오리진 클래식
       `<script>` 는 forbidden 이 아니므로 그대로 통과한다.

   그래서 같은 스캐너를 산출물에 한 번 더 겨눈다. 지금 값이 0인 시점이 이 게이트를 세우기
   가장 싼 때다 — vite 업그레이드·플러그인 추가·의존 변경이 산출물에만 무언가를 넣는 날,
   정적 층은 source 를 보느라 침묵하고 런타임 층은 위 두 이유로 못 본다.

   스캔 대상은 디스크 글롭이 아니라 **봉인이 열거한 파일**이다. 그래야 "무엇을 검사했는가" 와
   "무엇을 실었는가" 가 같은 목록이 된다. */

/** 출하 산출물 뿌리. 경로는 `vite.config.mjs` 의 `build.outDir` 이 단일 출처다. */
const ARTIFACT = new URL(`${pathToFileURL(viteConfig.build.outDir).href}/`);

const SEAL_FILENAME = "web-artifact-seal.json";

/** 봉인 목록대로 산출물을 읽고 판다. 부재는 **스킵 사유가 아니라 실패**다 — 이 게이트를 도는
 *  자리(`test.ps1` 과 CI 의 `pytest-contract`)는 앞서 빌드하거나 봉인된 산출물을 내려받으므로,
 *  없다는 것은 "검사할 게 없다" 가 아니라 "검사해야 할 것이 사라졌다" 다. */
function loadShipped() {
  const sealUrl = new URL(SEAL_FILENAME, ARTIFACT);
  if (!existsSync(sealUrl)) {
    throw new Error(
      `봉인된 산출물이 없습니다: ${sealUrl.pathname}. 이 게이트는 출하되는 바이트를 검사하므로 `
      + "부재는 스킵 사유가 아니라 실패입니다 — `npm run build` 가 먼저입니다.",
    );
  }
  const seal = JSON.parse(readFileSync(sealUrl, "utf8"));
  const listed = seal.output.files;

  /* 봉인 목록과 디스크가 어긋나면 아래 전부가 다른 것을 검사하게 된다. `verify:web` 이 지는
     책임이지만, 이 게이트가 **자기가 읽은 바이트**로 한 번 더 확인한다. */
  const bytes = new Map();
  for (const entry of listed) {
    const url = new URL(entry.path, ARTIFACT);
    if (!existsSync(url)) throw new Error(`봉인이 열거한 파일이 디스크에 없습니다: ${entry.path}`);
    const raw = readFileSync(url);
    if (raw.length !== entry.size) {
      throw new Error(
        `봉인과 디스크의 크기가 다릅니다: ${entry.path} — 봉인 ${entry.size} / 디스크 ${raw.length}`,
      );
    }
    bytes.set(entry.path, raw);
  }

  const js = new Map();
  for (const entry of listed) {
    /* `.vite/manifest.json` 은 빌드 메타라 제품 코드가 아니다. */
    if (!entry.path.endsWith(".js") || entry.path.startsWith(".vite/")) continue;
    const source = bytes.get(entry.path).toString("utf8");
    js.set(entry.path, { source, scan: scanSource(source, `build/web/${entry.path}`) });
  }
  const htmlEntry = listed.find((entry) => entry.path === "index.html");
  if (htmlEntry === undefined) throw new Error("봉인에 `index.html` 이 없습니다.");

  return { seal, listed, js, html: bytes.get("index.html").toString("utf8") };
}

let shippedCache = null;
function shipped() {
  if (shippedCache === null) shippedCache = loadShipped();
  return shippedCache;
}

test("공허 방지 — 봉인 목록대로 출하 산출물을 읽고 실제로 판다(양성 대조)", () => {
  const { listed, js, html } = shipped();

  assert.ok(listed.length >= 4,
    `봉인이 파일을 ${listed.length} 개밖에 열거하지 않습니다 — 산출물이 반쪽입니다.`);
  assert.ok(js.size >= 1, "출하 JS 를 하나도 못 찾았습니다 — 아래 0건 단언이 전부 눈먼 초록입니다.");
  assert.ok(html.length > 1000, "출하 `index.html` 을 못 읽었습니다.");

  const totalBytes = [...js.values()].reduce((n, f) => n + f.source.length, 0);
  assert.ok(totalBytes > 100000,
    `출하 JS 가 ${totalBytes} 바이트뿐입니다 — 제품 번들이 아닙니다.`);

  /* 스캐너가 이 번들에서 **실제로 무언가를 본다**는 증거. 전부 0 이면 파서가 죽은 것이고,
     그 침묵은 계약 위반 없음과 구별되지 않는다(source 축과 같은 논거). */
  const totalReads = [...js.values()].reduce((n, f) => n + f.scan.globalReads.length, 0);
  assert.ok(totalReads > 10,
    `번들에서 창 판독을 ${totalReads} 건밖에 못 봤습니다 — 스캐너가 멀었습니다.`);
});

test("출하 `index.html` 의 스크립트도 `type=module` 하나뿐이다", () => {
  const { html } = shipped();

  const scripts = scanHtmlScripts(html);
  assert.equal(scripts.length, 1,
    `출하 HTML 의 스크립트가 ${scripts.length} 개입니다: ${JSON.stringify(scripts)}`);
  assert.equal(scripts[0].classic, false, "번들러가 클래식 스크립트를 주입했습니다.");
  assert.equal(scripts[0].type, "module");

  /* 인라인 스크립트는 `src` 가 없다. 번들러 폴리필·프리로드 헬퍼가 들어오는 통상 경로가
     여기라, 태그 수만 세면 놓친다. */
  assert.ok(scripts[0].src !== null, "출하 HTML 에 인라인 스크립트가 있습니다.");
  assert.ok(scripts[0].src.startsWith("./assets/"),
    `출하 entry 가 번들 자산을 가리키지 않습니다: ${scripts[0].src}`);

  const handlers = scanHtmlEventHandlers(html);
  assert.deepEqual(handlers, [],
    `출하 HTML 에 인라인 이벤트 핸들러가 있습니다: ${JSON.stringify(handlers)}`);
});

test("출하 번들이 만드는 전역도 정확히 `__hwpx`·`__hwpxTest` 둘뿐이다", () => {
  const { js } = shipped();

  const direct = new Map();
  const unknown = [];
  const aliases = [];
  const reserved = new Set();
  for (const [rel, { scan }] of js) {
    for (const write of scan.globalWrites) {
      if (!direct.has(write.name)) direct.set(write.name, []);
      direct.get(write.name).push(`${rel}:${write.line}`);
    }
    for (const write of scan.unknownWrites) {
      if (write.receiver === "global") unknown.push(`${rel}:${write.line}(${write.kind})`);
    }
    for (const alias of scan.globalAliases) aliases.push(`${rel}:${alias.line}`);
    for (const install of scan.reservedInstalls) reserved.add(install.name);
  }

  assert.deepEqual(unknown, [],
    `번들에 이름을 정적으로 못 푸는 전역 쓰기가 있습니다: ${unknown.join(", ")}`);
  assert.deepEqual(aliases, [],
    `번들이 창을 지역 이름에 담습니다 — 위 축을 통째로 우회합니다: ${aliases.join(", ")}`);
  assert.deepEqual([...direct.keys()].sort(), ["__hwpx"],
    `번들이 만드는 직접 전역이 __hwpx 하나가 아닙니다: ${JSON.stringify([...direct])}`);

  /* 허용 목록은 source 축과 **같은 상수**를 쓴다. 두 층이 각자 목록을 들면 갈라지고, 그때
     어느 쪽이 정본인지 아무도 못 말한다. */
  assert.deepEqual([...reserved].sort(), ALLOWED_GLOBALS,
    "번들이 예약 대역에 심는 이름이 `__hwpx`·`__hwpxTest` 둘과 다릅니다.");
});

test("출하 번들 최상단에 IIFE 가 0 이다", () => {
  const { js } = shipped();

  const offenders = [];
  for (const [rel, { scan }] of js) {
    for (const iife of scan.topLevelIifes) offenders.push(`${rel}:${iife.line}`);
  }
  assert.deepEqual(offenders, [], `번들 최상단 IIFE 가 있습니다: ${offenders.join(", ")}`);

  /* 양성 대조 — 같은 번들 뒤에 최상단 IIFE 를 한 줄 붙이면 정확히 하나가 늘어야 한다.
     fixture 대조는 "스캐너가 IIFE 를 문다" 를 증명하고, 이 대조는 "스캐너가 **이 번들의**
     최상단을 보고 있다" 를 증명한다. 후자가 없으면 위 0건은 파싱만 성공한 초록일 수 있다. */
  for (const [rel, { source, scan }] of js) {
    const probed = scanSource(`${source}\n(function () {})();\n`, `<${rel}+iife>`);
    assert.equal(probed.topLevelIifes.length, scan.topLevelIifes.length + 1,
      `${rel} 의 최상단을 스캐너가 못 보고 있습니다 — 위 0건은 눈먼 초록입니다.`);
  }
});

test("죽은 별칭 스물일곱이 출하 번들에도 없다", () => {
  const { js } = shipped();
  const dead = new Set(DEAD_ALIASES);

  const offenders = [];
  for (const [rel, { scan }] of js) {
    for (const write of scan.globalWrites) {
      if (dead.has(write.name)) offenders.push(`쓰기 ${rel}:${write.line} window.${write.name}`);
    }
    /* 판독까지 세는 이유는 source 축과 같다 — 생산자가 없는데 소비자가 남으면 런타임에
       `undefined` 를 읽고 조용히 죽는다. 번들에서는 그 소비가 트리셰이킹으로도 안 사라진다
       (`treeshake: false`). */
    for (const read of scan.globalReads) {
      if (dead.has(read.name)) offenders.push(`판독 ${rel}:${read.line} window.${read.name}`);
    }
  }
  assert.deepEqual(offenders, [],
    `번들에 임시 별칭이 살아 있습니다:\n  ${offenders.join("\n  ")}`);
});

/* ══════════════════════════════════════════════════════════════════════════
   보조
   ══════════════════════════════════════════════════════════════════════════ */

function isCompatFile(basename) {
  return basename === "compat.js";
}

function isCompatSpecifier(spec) {
  return spec.split("/").pop() === "compat.js";
}

/** 그래프 순회 — `tests/test_frontend_build_graph.py` 의
 *  `test_whole_frontend_graph_from_the_entry_has_no_cycles_and_no_bare_specifiers` 와 같은
 *  방문 표시 규약(0 미방문 / 1 도는 중 / 2 끝남)을 쓴다. 두 상태로 나누지 않으면 다이아몬드가
 *  거짓 순환이 된다(음성 대조 ⑧이 그 자리를 지킨다). */
function walkGraph(entry, read) {
  const seen = new Map();
  const visited = new Set();
  const cycles = [];
  const bare = [];

  const visit = (node, trail) => {
    if (seen.get(node) === 1) { cycles.push([...trail, node]); return; }
    if (seen.get(node) === 2) return;
    seen.set(node, 1);
    visited.add(node);
    const source = read(node);
    if (source !== null) {
      for (const spec of scanSource(source, node).imports) {
        if (spec.startsWith(".")) {
          visit(posixNormalize(posixJoin(posixDirname(node), spec)), [...trail, node]);
        } else if (!spec.endsWith(".css")) {
          bare.push(`${node} -> ${spec}`);
        }
      }
    }
    seen.set(node, 2);
  };

  visit(entry, []);
  return { cycles, bare, visited };
}

function traverse(entry) {
  return walkGraph(entry, (node) => {
    const url = new URL(node, FRONTEND);
    return node.endsWith(".js") && existsSync(url) ? readFileSync(url, "utf8") : null;
  });
}

function fixtureCycles(entry) {
  return walkGraph(entry, (node) => {
    const url = new URL(node, FIXTURES);
    return node.endsWith(".js") && existsSync(url) ? readFileSync(url, "utf8") : null;
  }).cycles;
}

/** `Object.defineProperty(<이름>, …)` 한 자리의 위치·가드 상황. */
function installSite(source) {
  const program = parseAst(source);
  const constants = topLevelStringConstants(program);
  let result = null;

  const search = (node, functionStack) => {
    if (node.type === "CallExpression"
      && node.callee.type === "MemberExpression" && !node.callee.computed
      && node.callee.object.type === "Identifier" && node.callee.object.name === "Object"
      && node.callee.property.name === "defineProperty") {
      const key = staticKey(node.arguments[1], true, constants);
      if (key !== null && key.startsWith(RESERVED_PREFIX)) {
        const holder = functionStack[functionStack.length - 1] || null;
        result = {
          insideFunction: holder !== null,
          guardsBefore: holder === null ? 0 : countEarlyReturnsBefore(holder, node.start),
        };
      }
    }
    const stack = isFunctionNode(node) ? [...functionStack, node] : functionStack;
    for (const child of childNodes(node)) search(child, stack);
  };

  search(program, []);
  assert.ok(result !== null, "예약 이름을 심는 `defineProperty` 자리를 못 찾았습니다.");
  return result;
}

/** 함수 안에서, 주어진 위치 **앞에** 끝나는 「조건 → 이른 반환」 가드 수. */
function countEarlyReturnsBefore(fn, offset) {
  let count = 0;
  const search = (node) => {
    if (node.type === "IfStatement" && node.end < offset && hasReturn(node)) count += 1;
    for (const child of childNodes(node)) search(child);
  };
  search(fn);
  return count;
}

function hasReturn(node) {
  if (node.type === "ReturnStatement") return true;
  if (isFunctionNode(node)) return false;
  return childNodes(node).some(hasReturn);
}

/** 이름으로 부르는 호출 한 자리가 함수 안에 있는지. */
function callSite(source, calleeName) {
  const program = parseAst(source);
  let found = null;
  const search = (node, inFunction) => {
    if (node.type === "CallExpression" && node.callee.type === "Identifier"
      && node.callee.name === calleeName) {
      found = { insideFunction: inFunction };
    }
    const next = inFunction || isFunctionNode(node);
    for (const child of childNodes(node)) search(child, next);
  };
  search(program, false);
  assert.ok(found !== null, `${calleeName} 호출 자리를 못 찾았습니다.`);
  return found;
}
