/* 예약 전역 접촉 allowlist (R2-02 · #406 → #490 가족 일반화) — 「닿는 파일」 전수를 핀으로 지킨다.
 *
 * ## 왜 리터럴 검색이 아니라 AST 인가
 *
 * selftest 층은 전역을 리터럴로 만지지 않는다 — 주입 별칭(`win.pywebview` ·
 * `ctx.win.pywebview`)으로 닿는다(패킷 rev2 §2). `window.pywebview` 문자열 검색은 그
 * 사이트들에서 0 을 보고, 그 0 은 「안 닿는다」와 구별되지 않는다. 반대로 날텍스트 검색은
 * 주석·문자열의 언급(`runner.js` 의 호스트 op 주석, `schema.js` 의 note 문자열)을 실물로
 * 센다. 그래서 술어는 **프로퍼티 접근**이다: 수신자가 무엇이든 예약 이름에 닿으면
 * 접촉이고, 산문은 AST 에 없다(n10 전역 위생과 같은 논거).
 *
 * ## 가족 일반화 (#490 F1)
 *
 * 종전에는 `pywebview` 하나만 봤다 — 생산자 게이트(pytest)는 `__hwpx` 계열의 **생산**만
 * 보고, 이미 등재된 파일에 `window.__hwpx` **판독**을 넣으면 전 게이트가 초록이었다
 * (R2-99 F1 실측). 술어를 「이름 열거」에서 「가족」으로 바꾼다: `pywebview` 정확 일치 +
 * `__hwpx` 접두 전부. 이름·allowlist 의 정본은 `tests/static_closure_contract.json`
 * 하나이고 pytest 쪽 결선 테스트가 같은 파일을 읽는다 — 다음 전역에서 「형제를 안
 * 넓힌다」가 재발하지 않게 표에 없는 가족 이름의 접촉은 allowlist 없이 무조건 위반이다.
 *
 * `.ts` 는 oxc 가 `lang` 옵션으로 파싱한다(착수 실측 — 무옵션 `parseAst` 는 TS 문법에서
 * 죽는다). 파서 부재·파싱 실패는 스킵이 아니라 실패다.
 *
 * ## 비교 상대는 계약 파일의 핀 목록이다
 *
 * 신규 파일이 전역에 닿으면 핀에 없어 빨갛고, 핀에 있는 파일이 접촉을 잃으면 등재가
 * 실물을 앞질러 빨갛다 — 양방향 전수 대조다. `docs/UI_CONTRACT.md` 의 통로 문장은 이
 * 실측의 재서술이다. */
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";

/* 파서는 `vite`(oxc)가 내준다 — n10 과 같은 규약: 조용히 스킵하지 않되 사유는 말하고 죽는다. */
let parseAst;
try {
  ({ parseAst } = await import("vite"));
} catch (thrown) {
  throw new Error(
    "프런트 툴체인(`vite`)을 못 불렀습니다 — `npm ci` 가 먼저입니다. 이 게이트를 도는 잡은 "
    + `pytest 앞에서 그것을 돌리므로 부재는 스킵 사유가 아니라 실패입니다: ${thrown.message}`,
  );
}

const FRONTEND = new URL("../../frontend/", import.meta.url);

/** 정적 폐포 계약의 단일 출처(#490) — 예약 전역 가족·allowlist 와 수집 감산 목록.
 *  pytest 쪽(`test_reserved_global_contract_is_single_sourced` · `_frontend_sources`)이
 *  같은 파일을 읽는다. 이 목록을 넓히는 diff 만이 새 접촉을 연다 — 신규 제품 통로는
 *  adapter 하나다: 화면·feature 가 여기 들어오려 하면 그것이 곧 「component 의 직접 전역
 *  접근」 위반이다. */
const CONTRACT = JSON.parse(
  readFileSync(new URL("../static_closure_contract.json", import.meta.url), "utf8"),
);
const RESERVED = CONTRACT.reserved_globals;
const NON_CODE_SUFFIXES = CONTRACT.non_code_suffixes;

/** 가족 술어 — 계약의 이름 열거보다 넓다: 표에 없는 `__hwpx*` 접촉도 잡혀야
 *  「다음 전역」에서 같은 결함이 재발하지 않는다. */
function reservedName(key) {
  if (key === "pywebview" || (typeof key === "string" && key.startsWith("__hwpx"))) return key;
  return null;
}

/* ══════════════ 스캐너 — 수신자 불문 예약 이름 프로퍼티 접촉 ══════════════ */

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

/** 정적으로 확정되는 프로퍼티 키 — 못 푸는 계산 키는 null(여기선 접촉 아님으로 남는다:
 *  `x[name]` 이 예약 이름을 가리키려면 그 이름이 어딘가 리터럴로 있고 그쪽이 잡힌다). */
function staticKey(property, computed) {
  if (!computed && property.type === "Identifier") return property.name;
  if (property.type === "Literal" && typeof property.value === "string") return property.value;
  return null;
}

function langOf(filename) {
  if (filename.endsWith(".tsx")) return "tsx";
  if (filename.endsWith(".ts")) return "ts";
  return "js";
}

/** 소스 한 편의 예약 전역 접촉 자리 — `{ line, name }` 목록. 주입 별칭·구조분해 포함. */
export function reservedTouchSites(source, filename) {
  let program;
  try {
    program = parseAst(source, { lang: langOf(filename) });
  } catch (thrown) {
    throw new Error(`${filename} 파싱 실패 — 게이트가 볼 수 없는 파일입니다: ${thrown.message}`);
  }
  const sites = [];
  const lineOf = (node) => source.slice(0, node.start).split("\n").length;

  const visit = (node) => {
    if (node.type === "MemberExpression") {
      const name = reservedName(staticKey(node.property, node.computed));
      if (name !== null) sites.push({ line: lineOf(node), name });
    }
    /* `const { pywebview } = win` — 멤버 접근 없이 같은 전역을 손에 넣는 우회다. */
    if (node.type === "ObjectPattern") {
      for (const prop of node.properties) {
        if (prop.type === "Property") {
          const name = reservedName(staticKey(prop.key, prop.computed));
          if (name !== null) sites.push({ line: lineOf(prop), name });
        }
      }
    }
    for (const child of childNodes(node)) visit(child);
  };
  visit(program);
  return sites;
}

function sitesOf(source, filename, name) {
  return reservedTouchSites(source, filename).filter((site) => site.name === name);
}

/* ══════════════ 전반부 — 합성 표본으로 증명하는 검출력 ══════════════ */

test("검출력 — 직접·주입 별칭·이중 별칭·구조분해·대괄호 접촉을 전부 문다", () => {
  assert.equal(
    sitesOf('window.pywebview.api.initial("job");', "a.js", "pywebview").length, 1,
    "직접 접촉(window.pywebview)을 놓쳤습니다",
  );
  assert.equal(
    sitesOf(
      "function f(win){ return win.pywebview && win.pywebview.api; }", "b.js", "pywebview",
    ).length, 2,
    "주입 별칭(win.) 접촉을 놓쳤습니다 — 리터럴-전용 술어의 사각입니다",
  );
  assert.equal(
    sitesOf(
      "function g(ctx){ const api = ctx.win.pywebview && ctx.win.pywebview.api; return api; }",
      "c.js", "pywebview",
    ).length, 2,
    "이중 주입 별칭(ctx.win.) 접촉을 놓쳤습니다",
  );
  assert.equal(
    sitesOf("export function h(win){ const { pywebview } = win; return pywebview; }",
      "d.js", "pywebview").length, 1,
    "구조분해 접촉을 놓쳤습니다",
  );
  assert.equal(
    sitesOf('function k(host){ return host["pywebview"].api; }', "e.js", "pywebview").length, 1,
    "대괄호 리터럴 접촉을 놓쳤습니다",
  );
});

test("검출력 — 형제 전역(__hwpx 가족)의 판독을 같은 술어가 문다(#490 F1)", () => {
  assert.equal(
    sitesOf("const api = window.__hwpx; api.dispatch();", "a.ts", "__hwpx").length, 1,
    "window.__hwpx 판독을 놓쳤습니다 — R2-99 F1 이 잡은 바로 그 사각입니다",
  );
  assert.equal(
    sitesOf("function f(win){ return win.__hwpx && win.__hwpx.version; }", "b.js", "__hwpx")
      .length, 2,
    "주입 별칭의 __hwpx 판독을 놓쳤습니다",
  );
  assert.equal(
    sitesOf("const { __hwpx } = window; void __hwpx;", "c.js", "__hwpx").length, 1,
    "구조분해 __hwpx 를 놓쳤습니다",
  );
  assert.equal(
    sitesOf('const t = window["__hwpxTest"];', "d.js", "__hwpxTest").length, 1,
    "대괄호 리터럴 __hwpxTest 를 놓쳤습니다",
  );
  /* 표에 없는 가족 이름 — allowlist 로 열 수 없는 무조건 위반으로 잡혀야 「다음 전역」이
     조용히 자라지 않는다. */
  const rogue = reservedTouchSites("const x = window.__hwpxRogue;", "e.js");
  assert.deepEqual(rogue.map((site) => site.name), ["__hwpxRogue"],
    "미등재 가족 이름(__hwpxRogue)의 접촉을 놓쳤습니다");
});

test("검출력 — `.ts` 를 실제로 파싱해 문다(무옵션 parseAst 는 TS 에서 죽는다 — 착수 실측)", () => {
  const ts = [
    "type Host = { pywebview?: { api?: Record<string, unknown> } };",
    "export function ready(win: Host): boolean {",
    "  return win.pywebview !== undefined && win.pywebview.api !== undefined;",
    "}",
  ].join("\n");
  assert.equal(sitesOf(ts, "f.ts", "pywebview").length, 2, "TS 소스의 접촉을 놓쳤습니다");

  /* 이 양성의 전제 자체를 고정한다: TS 문법이 js 파서로는 안 읽힌다 — `lang` 분기가
     장식이 아니라 실질이라는 증거다. */
  assert.throws(() => reservedTouchSites(ts, "f.js"), /파싱 실패/);
});

test("검출력 음성 — 주석·문자열·유사 이름은 한 건도 물지 않는다", () => {
  assert.deepEqual(
    reservedTouchSites("/* window.pywebview 와 window.__hwpx 를 언급하는 주석 */ const x = 1;", "a.js"), [],
    "주석 언급을 실물로 셌습니다 — 결정 배경을 못 적게 됩니다",
  );
  assert.deepEqual(
    reservedTouchSites('const note = "pywebview window.get_current_url()";', "b.js"), [],
    "문자열 언급을 실물로 셌습니다(schema.js 의 note 가 이 형태입니다)",
  );
  assert.deepEqual(
    reservedTouchSites('const g = "__hwpxTest";', "c.js"), [],
    "문자열 리터럴 값(__hwpxTest — api.js 의 SELFTEST_GLOBAL 형태)을 접촉으로 셌습니다",
  );
  assert.deepEqual(
    reservedTouchSites("function f(win){ return win.pywebviewer.api; }", "d.js"), [],
    "유사 이름(pywebviewer)을 접촉으로 셌습니다",
  );
  assert.deepEqual(
    reservedTouchSites("const y = window.__hwp; const z = win.hwpx;", "e.js"), [],
    "유사 이름(__hwp·hwpx)을 가족으로 셌습니다",
  );
});

/* ══════════════ 후반부 — 실 제품 트리의 전수 대조 ══════════════ */

/** 수집도 감산형이다(#490 F2) — 확장자 열거가 아니라 `frontend/**` 전 파일에서 계약의
 *  non_code_suffixes 만 뺀다. 새 코드 형식(`.tsx` 등)은 자동 편입되어 이 게이트가
 *  파싱한다 — 미지 형식의 파싱 실패는 스킵이 아니라 실패다(pytest 수집기와 같은 자세). */
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

test("계약 결선 — 이름 전수·allowlist 실재가 pytest 쪽과 같은 파일에서 나온다", () => {
  assert.deepEqual(Object.keys(RESERVED).sort(), ["__hwpx", "__hwpxTest", "pywebview"],
    "계약의 예약 전역 이름 전수가 어긋납니다 — pytest 결선 테스트와 같은 정본입니다");
  for (const name of Object.keys(RESERVED)) {
    assert.ok(reservedName(name) !== null,
      `${name}: 가족 술어가 계약 이름을 못 뭅니다 — 술어와 계약을 한 변경으로 넓히세요`);
  }
});

test("실 트리 — 예약 전역에 닿는 파일 전수가 가족별 핀 목록과 정확히 같다", () => {
  const files = listSources("");

  /* 공허 방지 — 목록이 비면 아래 대조는 아무 뜻이 없다(n10 과 같은 양성 대조). */
  assert.ok(files.length >= 40, `프런트 소스를 ${files.length}장밖에 못 찾았습니다`);
  assert.ok(files.includes("js/bridge.js"));
  assert.ok(files.includes("src/runtime/adapter.ts"), "`.ts` 가 수집 집합에 안 들었습니다");

  const touched = new Map();  // 이름 → Map(파일 → 줄 목록)
  for (const rel of files) {
    const sites = reservedTouchSites(readFileSync(new URL(rel, FRONTEND), "utf8"), rel);
    for (const { line, name } of sites) {
      if (!touched.has(name)) touched.set(name, new Map());
      const perFile = touched.get(name);
      perFile.set(rel, [...(perFile.get(rel) ?? []), line]);
    }
  }

  /* 표에 없는 가족 이름의 접촉 = allowlist 로 열 수 없는 무조건 위반. */
  const unknown = [...touched.keys()].filter((name) => !(name in RESERVED));
  assert.deepEqual(unknown, [],
    `계약에 없는 예약 이름에 닿는 코드가 있습니다: ${unknown.join(", ")} — `
    + "tests/static_closure_contract.json 과 양쪽 술어를 한 변경으로 넓히세요");

  for (const [name, allowlist] of Object.entries(RESERVED)) {
    const actual = [...(touched.get(name) ?? new Map()).keys()].sort();
    assert.deepEqual(actual, allowlist, [
      `\`${name}\` 접촉 파일 전수가 핀과 다릅니다.`,
      "새 파일이 늘었다면: 그 접촉이 정말 필요한지 먼저 묻고(신규 통로는 runtime/adapter.ts",
      "하나가 원칙), 필요하면 계약 파일의 핀과 docs/UI_CONTRACT.md 의 통로 문장을 함께 갱신하세요.",
      "핀의 파일이 사라졌다면: 등재가 실물을 앞지른 것이니 핀을 지우세요.",
    ].join("\n"));
  }

  /* 스캐너가 이 트리에서 실제로 접촉을 **많이** 본다는 증거 — bridge.js 하나만도 28 사이트다.
     전부 한두 건이면 파서가 절반만 보고 있는 것이고, 그것은 위반 0 과 구별되지 않는다. */
  const pywebview = touched.get("pywebview");
  const total = [...pywebview.values()].reduce((n, lines) => n + lines.length, 0);
  assert.ok(total >= 35, `pywebview 접촉 자리를 ${total}건밖에 못 봤습니다 — 스캐너가 멀었습니다`);
  assert.ok(pywebview.get("js/bridge.js").length >= 25,
    "bridge.js 의 접촉이 기대보다 적습니다 — 스캐너가 절반만 보고 있습니다");
});
