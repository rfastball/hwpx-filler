/* 전역 `pywebview` 접촉 allowlist (R2-02 · #406) — 「닿는 파일」 전수를 핀으로 지킨다.
 *
 * ## 왜 리터럴 검색이 아니라 AST 인가
 *
 * selftest 층은 전역을 리터럴로 만지지 않는다 — 주입 별칭(`win.pywebview` ·
 * `ctx.win.pywebview`)으로 닿는다(패킷 rev2 §2). `window.pywebview` 문자열 검색은 그
 * 사이트들에서 0 을 보고, 그 0 은 「안 닿는다」와 구별되지 않는다. 반대로 날텍스트 검색은
 * 주석·문자열의 언급(`runner.js` 의 호스트 op 주석, `schema.js` 의 note 문자열)을 실물로
 * 센다. 그래서 술어는 **프로퍼티 접근**이다: 수신자가 무엇이든 `.pywebview` 에 닿으면
 * 접촉이고, 산문은 AST 에 없다(n10 전역 위생과 같은 논거).
 *
 * `.ts` 는 oxc 가 `lang` 옵션으로 파싱한다(착수 실측 — 무옵션 `parseAst` 는 TS 문법에서
 * 죽는다). 파서 부재·파싱 실패는 스킵이 아니라 실패다.
 *
 * ## 비교 상대는 게이트 안 핀 목록이다
 *
 * n07 의 테스트측 재진술 = 드리프트 게이트 관행 그대로(패킷 rev2 §4.2-3). 신규 파일이
 * 전역에 닿으면 핀에 없어 빨갛고, 핀에 있는 파일이 접촉을 잃으면 등재가 실물을 앞질러
 * 빨갛다 — 양방향 전수 대조다. `docs/UI_CONTRACT.md` 의 통로 문장은 이 실측의 재서술이다. */
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

/** `pywebview` 에 닿아도 되는 파일 **전수** — 실측 고정(패킷 rev1 §2.3 + 이 단계의 신설 1).
 *  이 목록을 넓히는 diff 만이 새 접촉을 연다. 신규 제품 통로는 adapter 하나다 — 화면·
 *  feature 가 여기 들어오려 하면 그것이 곧 「component 의 직접 전역 접근」 위반이다. */
const ALLOWED = [
  "js/app.js",                                   // 존재 판정 한 줄(라우팅 준비 가드)
  "js/bridge.js",                                // legacy 단일 백엔드 통로(28 사이트)
  "js/screens/editor.js",                        // 존재 판정 한 줄(부팅 재진입 가드)
  "src/runtime/adapter.ts",                      // 신규 통로의 유일한 소유자(R2-02)
  "src/selftest/boot.js",                        // 주입 별칭 준비 대기
  "src/selftest/probes/boot_routing_overlay.js", // 프로브의 api 판독·호출
  "src/selftest/probes/persistence_geometry.js", // 주입 별칭 준비 판정 둘
];

/* ══════════════ 스캐너 — 수신자 불문 `.pywebview` 프로퍼티 접촉 ══════════════ */

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
 *  `x[name]` 이 pywebview 를 가리키려면 그 이름이 어딘가 리터럴로 있고 그쪽이 잡힌다). */
function staticKey(property, computed) {
  if (!computed && property.type === "Identifier") return property.name;
  if (property.type === "Literal" && typeof property.value === "string") return property.value;
  return null;
}

/** 소스 한 편의 `pywebview` 접촉 자리(줄 번호 목록) — 주입 별칭·구조분해 포함. */
export function pywebviewTouchSites(source, filename) {
  let program;
  try {
    program = parseAst(source, { lang: filename.endsWith(".ts") ? "ts" : "js" });
  } catch (thrown) {
    throw new Error(`${filename} 파싱 실패 — 게이트가 볼 수 없는 파일입니다: ${thrown.message}`);
  }
  const sites = [];
  const lineOf = (node) => source.slice(0, node.start).split("\n").length;

  const visit = (node) => {
    if (node.type === "MemberExpression"
      && staticKey(node.property, node.computed) === "pywebview") {
      sites.push(lineOf(node));
    }
    /* `const { pywebview } = win` — 멤버 접근 없이 같은 전역을 손에 넣는 우회다. */
    if (node.type === "ObjectPattern") {
      for (const prop of node.properties) {
        if (prop.type === "Property" && staticKey(prop.key, prop.computed) === "pywebview") {
          sites.push(lineOf(prop));
        }
      }
    }
    for (const child of childNodes(node)) visit(child);
  };
  visit(program);
  return sites;
}

/* ══════════════ 전반부 — 합성 표본으로 증명하는 검출력 ══════════════ */

test("검출력 — 직접·주입 별칭·이중 별칭·구조분해·대괄호 접촉을 전부 문다", () => {
  assert.equal(
    pywebviewTouchSites('window.pywebview.api.initial("job");', "a.js").length, 1,
    "직접 접촉(window.pywebview)을 놓쳤습니다",
  );
  assert.equal(
    pywebviewTouchSites(
      "function f(win){ return win.pywebview && win.pywebview.api; }", "b.js",
    ).length, 2,
    "주입 별칭(win.) 접촉을 놓쳤습니다 — 리터럴-전용 술어의 사각입니다",
  );
  assert.equal(
    pywebviewTouchSites(
      "function g(ctx){ const api = ctx.win.pywebview && ctx.win.pywebview.api; return api; }",
      "c.js",
    ).length, 2,
    "이중 주입 별칭(ctx.win.) 접촉을 놓쳤습니다",
  );
  assert.equal(
    pywebviewTouchSites("export function h(win){ const { pywebview } = win; return pywebview; }",
      "d.js").length, 1,
    "구조분해 접촉을 놓쳤습니다",
  );
  assert.equal(
    pywebviewTouchSites('function k(host){ return host["pywebview"].api; }', "e.js").length, 1,
    "대괄호 리터럴 접촉을 놓쳤습니다",
  );
});

test("검출력 — `.ts` 를 실제로 파싱해 문다(무옵션 parseAst 는 TS 에서 죽는다 — 착수 실측)", () => {
  const ts = [
    "type Host = { pywebview?: { api?: Record<string, unknown> } };",
    "export function ready(win: Host): boolean {",
    "  return win.pywebview !== undefined && win.pywebview.api !== undefined;",
    "}",
  ].join("\n");
  assert.equal(pywebviewTouchSites(ts, "f.ts").length, 2, "TS 소스의 접촉을 놓쳤습니다");

  /* 이 양성의 전제 자체를 고정한다: TS 문법이 js 파서로는 안 읽힌다 — `lang` 분기가
     장식이 아니라 실질이라는 증거다. */
  assert.throws(() => pywebviewTouchSites(ts, "f.js"), /파싱 실패/);
});

test("검출력 음성 — 주석·문자열·유사 이름은 한 건도 물지 않는다", () => {
  assert.deepEqual(
    pywebviewTouchSites("/* window.pywebview 를 언급하는 주석 */ const x = 1;", "a.js"), [],
    "주석 언급을 실물로 셌습니다 — 결정 배경을 못 적게 됩니다",
  );
  assert.deepEqual(
    pywebviewTouchSites('const note = "pywebview window.get_current_url()";', "b.js"), [],
    "문자열 언급을 실물로 셌습니다(schema.js 의 note 가 이 형태입니다)",
  );
  assert.deepEqual(
    pywebviewTouchSites("function f(win){ return win.pywebviewer.api; }", "c.js"), [],
    "유사 이름(pywebviewer)을 접촉으로 셌습니다",
  );
});

/* ══════════════ 후반부 — 실 제품 트리의 전수 대조 ══════════════ */

function listSources(relativeDir) {
  const out = [];
  const walkDir = (rel) => {
    const url = new URL(rel, FRONTEND);
    if (!existsSync(url)) return;
    for (const entry of readdirSync(url, { withFileTypes: true })) {
      if (entry.isDirectory()) walkDir(`${rel}${entry.name}/`);
      else if (entry.name.endsWith(".js") || entry.name.endsWith(".ts")) {
        out.push(`${rel}${entry.name}`);
      }
    }
  };
  walkDir(relativeDir);
  return out.sort();
}

test("실 트리 — `pywebview` 에 닿는 파일 전수가 핀 목록과 정확히 같다", () => {
  const files = [...listSources("src/"), ...listSources("js/")];

  /* 공허 방지 — 목록이 비면 아래 대조는 아무 뜻이 없다(n10 과 같은 양성 대조). */
  assert.ok(files.length >= 40, `프런트 소스를 ${files.length}장밖에 못 찾았습니다`);
  assert.ok(files.includes("js/bridge.js"));
  assert.ok(files.includes("src/runtime/adapter.ts"), "`.ts` 가 수집 집합에 안 들었습니다");

  const touched = new Map();
  for (const rel of files) {
    const sites = pywebviewTouchSites(readFileSync(new URL(rel, FRONTEND), "utf8"), rel);
    if (sites.length > 0) touched.set(rel, sites);
  }

  assert.deepEqual([...touched.keys()].sort(), ALLOWED, [
    "`pywebview` 접촉 파일 전수가 핀과 다릅니다.",
    "새 파일이 늘었다면: 그 접촉이 정말 필요한지 먼저 묻고(신규 통로는 runtime/adapter.ts",
    "하나가 원칙), 필요하면 여기 핀과 docs/UI_CONTRACT.md 의 통로 문장을 함께 갱신하세요.",
    "핀의 파일이 사라졌다면: 등재가 실물을 앞지른 것이니 핀을 지우세요.",
  ].join("\n"));

  /* 스캐너가 이 트리에서 실제로 접촉을 **많이** 본다는 증거 — bridge.js 하나만도 28 사이트다.
     전부 한두 건이면 파서가 절반만 보고 있는 것이고, 그것은 위반 0 과 구별되지 않는다. */
  const total = [...touched.values()].reduce((n, sites) => n + sites.length, 0);
  assert.ok(total >= 35, `접촉 자리를 ${total}건밖에 못 봤습니다 — 스캐너가 멀었습니다`);
  assert.ok(touched.get("js/bridge.js").length >= 25,
    "bridge.js 의 접촉이 기대보다 적습니다 — 스캐너가 절반만 보고 있습니다");
});
