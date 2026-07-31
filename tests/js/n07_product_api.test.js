/* 버전 있는 제품 파사드(N-07 lane F) 계약 테스트.
 *
 * 이 경계는 Python 이 웹을 부르는 **유일한 통로**가 될 자리라, 여기서 세는 것은 거동보다
 * 계약의 형태다: 서술자의 글자 하나, 실패 코드의 값, 반환 객체의 직렬화 가능성이 그대로
 * Python 어댑터의 분기 조건이 된다. 그래서 deep-equal 로 전수를 못박는다.
 *
 * 두 축이 특히 조용히 썩기 쉬워 구조로 잡는다:
 *   ① 광고한 능력에 핸들러가 없는 상태 — 목록을 손으로 두 벌 적으면 생긴다. 그래서
 *      "핸들러를 하나도 주입하지 않은 파사드"에서 **모든 광고 능력**이 unknown 이 아니라
 *      handler_unavailable 을 돌려주는지를 본다(같은 레지스트리에서 나온다는 실행 증거).
 *   ② 내부 이름 누출 — 서술자·실패 객체를 JSON 으로 굳혀 금지 이름 목록과 대조한다.
 *
 * DOM 도 window 도 세우지 않는다. 이 모듈이 그것들을 모른다는 것이 경계의 요점이다.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC_URL = new URL("../../frontend/src/product_api.js", import.meta.url);
const SRC = readFileSync(SRC_URL, "utf8");

const mod = await import("../../frontend/src/product_api.js");
const { createProductApi, PRODUCT_ERROR_CODES } = mod;

const CAPABILITIES = ["snapshot", "close-request", "preferences", "notice"];

const DESCRIPTOR = {
  protocol: "hwpx-product",
  version: 1,
  capabilities: CAPABILITIES,
};

/** 밖으로 새면 안 되는 내부 이름 — 화면 id·모듈/서비스 이름·DOM id·호스트 이름. */
const FORBIDDEN = [
  "AppCloseGuard", "Theme", "Personalization", "JobScreen", "LibraryScreen", "EditorScreen",
  "WorkbenchScreen", "DataPicker", "EditorEntry", "Nav", "Bridge", "Modal", "SurfaceSheet",
  "pywebview", "evaluate_js", "__push", "overlayRoot", "scr-job", "hwpxfiller", "webapp",
];

/** 사건별 유효 payload — 계약 그대로. */
const VALID = {
  "snapshot": { screen: "job", snapshot: { rows: 2 } },
  "close-request": { state: { armed: true, reasons: ["진행 중인 작업"] } },
  "preferences": { personalization: { font_scale: "large", master_width: 240 }, theme: "dark" },
  "notice": { message: "[hwpx] 저장에 실패했습니다" },
};

/** 기본 대역 — 호출을 기록하고, preferences 는 적용 조각을 보고한다. */
function makeHandlers(overrides) {
  const seen = [];
  const handlers = {
    "snapshot": (payload) => { seen.push(["snapshot", payload]); },
    "close-request": (payload) => { seen.push(["close-request", payload]); return Promise.resolve(); },
    "preferences": (payload) => {
      seen.push(["preferences", payload]);
      const applied = ["personalization"];
      if (payload.theme === "light" || payload.theme === "dark") applied.push("theme");
      return applied;
    },
    "notice": (payload) => { seen.push(["notice", payload]); },
  };
  Object.assign(handlers, overrides || {});
  return { handlers, seen };
}

function makeApi(overrides) {
  const bag = makeHandlers(overrides);
  return { api: createProductApi({ handlers: bag.handlers }), seen: bag.seen };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

/* ══════════════ 1. 공개 표면·서술자 ══════════════ */

test("공개 표면 — named export 만, default 없음, 메서드는 describe·deliver 둘뿐", () => {
  assert.deepEqual(Object.keys(mod).sort(), ["PRODUCT_ERROR_CODES", "createProductApi"]);
  assert.equal(mod.default, undefined, "export default 금지");

  const { api } = makeApi();
  assert.deepEqual(Object.keys(api), ["describe", "deliver"]);
});

test("describe() 서술자는 능력 순서까지 정확히 못박힌다", () => {
  const { api } = makeApi();

  assert.deepEqual(api.describe(), DESCRIPTOR);
  assert.deepEqual(api.describe().capabilities, CAPABILITIES,
    "능력 순서는 계약이다 — 정렬·재배치 금지");
});

test("describe() 는 매번 새 객체를 준다 — 호출자가 내부 상태를 흔들 수 없다", () => {
  const { api } = makeApi();
  const first = api.describe();

  first.version = 99;
  first.capabilities.push("oops");
  first.capabilities[0] = "mutated";

  assert.deepEqual(api.describe(), DESCRIPTOR);
  assert.notEqual(api.describe().capabilities, first.capabilities);
});

test("서술자는 자기 파사드에서만 나온다 — 손으로 적은 두 번째 목록이 소스에 없다", () => {
  const literal = /\[\s*"snapshot"\s*,\s*"close-request"\s*,\s*"preferences"\s*,\s*"notice"\s*\]/;
  assert.equal(literal.test(SRC), false,
    "능력 목록은 레지스트리 키에서 파생돼야 한다 — 중복 목록은 반드시 갈라진다");
});

/* ══════════════ 2. 라우팅 — 네 사건 ══════════════ */

for (const event of CAPABILITIES) {
  test(`deliver 가 ${event} 를 그 이름의 핸들러로, payload 를 그대로 넘긴다`, async () => {
    const { api, seen } = makeApi();
    const payload = VALID[event];

    const result = api.deliver({ version: 1, event, payload });

    await tick();  // notice 는 다음 태스크로 미룬다.
    assert.equal(seen.length, 1);
    assert.equal(seen[0][0], event);
    assert.equal(seen[0][1], payload, "payload 는 사본이 아니라 그 객체다");
    assert.equal(result.ok, true);
    assert.equal(result.event, event);
  });
}

test("성공 결과 형태 — 네 사건 전수", async () => {
  const { api } = makeApi();

  assert.deepEqual(api.deliver({ version: 1, event: "snapshot", payload: VALID["snapshot"] }),
    { ok: true, event: "snapshot" });
  assert.deepEqual(api.deliver({ version: 1, event: "close-request", payload: VALID["close-request"] }),
    { ok: true, event: "close-request", started: true });
  assert.deepEqual(api.deliver({ version: 1, event: "preferences", payload: VALID["preferences"] }),
    { ok: true, event: "preferences", applied: ["personalization", "theme"] });
  assert.deepEqual(api.deliver({ version: 1, event: "notice", payload: VALID["notice"] }),
    { ok: true, event: "notice", scheduled: true });
  await tick();
});

test("snapshot 의 screen 은 불투명한 라우팅 값이다 — 해석하지 않는다", () => {
  const { api, seen } = makeApi();

  const result = api.deliver({
    version: 1, event: "snapshot", payload: { screen: "미지의화면", snapshot: null },
  });

  assert.deepEqual(result, { ok: true, event: "snapshot" });
  assert.deepEqual(seen[0][1], { screen: "미지의화면", snapshot: null });
});

test("preferences — 테마 없는 요청은 personalization 만 적용으로 재진술한다", () => {
  const { api } = makeApi();
  const payload = { personalization: { font_scale: "normal", master_width: 240 } };

  assert.deepEqual(api.deliver({ version: 1, event: "preferences", payload }),
    { ok: true, event: "preferences", applied: ["personalization"] });
  assert.deepEqual(api.deliver({
    version: 1, event: "preferences", payload: { ...payload, theme: null },
  }), { ok: true, event: "preferences", applied: ["personalization"] },
  "theme:null 은 '저장 테마 없음' 이다 — 거절이 아니라 미적용");
});

test("preferences — 어느 조각이 적용되지 못했는지 이름으로 지목한다", () => {
  const onlyPersonalization = makeApi({ "preferences": () => ["personalization"] });
  assert.deepEqual(onlyPersonalization.api.deliver({
    version: 1, event: "preferences", payload: VALID["preferences"],
  }), {
    ok: false,
    code: PRODUCT_ERROR_CODES.HANDLER_UNAVAILABLE,
    event: "preferences",
    applied: ["personalization"],
    missing: ["theme"],
  });

  const none = makeApi({ "preferences": () => [] });
  assert.deepEqual(none.api.deliver({
    version: 1, event: "preferences", payload: VALID["preferences"],
  }), {
    ok: false,
    code: PRODUCT_ERROR_CODES.HANDLER_UNAVAILABLE,
    event: "preferences",
    applied: [],
    missing: ["personalization", "theme"],
  });

  const mute = makeApi({ "preferences": () => undefined });
  assert.deepEqual(mute.api.deliver({
    version: 1, event: "preferences", payload: VALID["preferences"],
  }).missing, ["personalization", "theme"],
  "보고 없는 핸들러는 '전부 적용됨' 으로 추측되지 않는다");
});

test("notice — deliver 는 알림 해소를 기다리지 않고 먼저 돌아온다", async () => {
  const fired = [];
  const { api } = makeApi({ "notice": (payload) => fired.push(payload.message) });

  const result = api.deliver({ version: 1, event: "notice", payload: VALID["notice"] });

  assert.deepEqual(result, { ok: true, event: "notice", scheduled: true });
  assert.deepEqual(fired, [], "핸들러 호출 자체가 다음 태스크로 미뤄진다(블로킹 alert 대비)");

  await tick();
  assert.deepEqual(fired, ["[hwpx] 저장에 실패했습니다"]);
});

test("close-request — 비동기 모달을 시작만 하고 promise 를 돌려주지 않는다", () => {
  let resolveIt;
  const { api } = makeApi({
    "close-request": () => new Promise((resolve) => { resolveIt = resolve; }),
  });

  const result = api.deliver({ version: 1, event: "close-request", payload: VALID["close-request"] });

  assert.equal(result instanceof Promise, false);
  assert.deepEqual(result, { ok: true, event: "close-request", started: true });
  resolveIt();
});

/* ══════════════ 3. 능력 목록 = 핸들러 표(구조) ══════════════ */

test("광고한 능력은 전부 라우트가 있다 — 핸들러 0 이면 unknown 이 아니라 unavailable 이다", () => {
  const bare = createProductApi();

  for (const event of bare.describe().capabilities) {
    const result = bare.deliver({ version: 1, event, payload: VALID[event] });
    assert.deepEqual(result, {
      ok: false, code: PRODUCT_ERROR_CODES.HANDLER_UNAVAILABLE, event,
    }, `${event} 이 광고돼 있는데 라우트가 없다`);
  }
});

test("광고하지 않은 이름은 전부 unknown_event 다 — 능력 목록이 곧 라우팅 표다", () => {
  const { api } = makeApi();
  const advertised = new Set(api.describe().capabilities);

  for (const name of ["push", "close", "prefs", "alert", "describe", "toString", "constructor",
    "__proto__", "snapshots", "Snapshot"]) {
    if (advertised.has(name)) continue;
    const result = api.deliver({ version: 1, event: name, payload: {} });
    assert.equal(result.ok, false);
    assert.equal(result.code, PRODUCT_ERROR_CODES.UNKNOWN_EVENT, `${name} 이 라우팅됐다`);
    assert.deepEqual(result.capabilities, CAPABILITIES);
  }
});

/* ══════════════ 4. 시끄러운 실패 전수 ══════════════ */

test("실패 코드 상수는 값이 계약이다", () => {
  assert.deepEqual(PRODUCT_ERROR_CODES, {
    MALFORMED_REQUEST: "malformed_request",
    UNSUPPORTED_VERSION: "unsupported_version",
    UNKNOWN_EVENT: "unknown_event",
    MALFORMED_PAYLOAD: "malformed_payload",
    HANDLER_UNAVAILABLE: "handler_unavailable",
    HANDLER_FAILED: "handler_failed",
  });
  assert.equal(Object.isFrozen(PRODUCT_ERROR_CODES), true);
});

test("요청 형태 불량 — 객체가 아니거나 event 가 문자열이 아니다", () => {
  const { api, seen } = makeApi();

  for (const bad of [undefined, null, 0, "snapshot", [], [1, 2]]) {
    assert.deepEqual(api.deliver(bad), {
      ok: false, code: PRODUCT_ERROR_CODES.MALFORMED_REQUEST, event: null, field: "request",
    }, `요청 ${JSON.stringify(bad) ?? "undefined"} 이 통과했다`);
  }
  assert.deepEqual(api.deliver(), {
    ok: false, code: PRODUCT_ERROR_CODES.MALFORMED_REQUEST, event: null, field: "request",
  }, "무인자 호출");

  for (const bad of [undefined, null, 7, {}, ["snapshot"]]) {
    assert.deepEqual(api.deliver({ version: 1, event: bad, payload: {} }), {
      ok: false, code: PRODUCT_ERROR_CODES.MALFORMED_REQUEST, event: null, field: "event",
    });
  }
  assert.deepEqual(api.deliver({ version: 1, event: "", payload: {} }), {
    ok: false, code: PRODUCT_ERROR_CODES.MALFORMED_REQUEST, event: null, field: "event",
  });
  assert.deepEqual(seen, [], "형태 불량 요청은 어떤 핸들러에도 닿지 않는다");
});

test("미지 버전은 v1 로 강등되지 않는다 — 조용한 대체 0", () => {
  const { api, seen } = makeApi();

  for (const version of [undefined, null, 0, 2, "1", 1.5, NaN, true, {}]) {
    const result = api.deliver({ version, event: "snapshot", payload: VALID["snapshot"] });
    assert.deepEqual(result, {
      ok: false,
      code: PRODUCT_ERROR_CODES.UNSUPPORTED_VERSION,
      event: "snapshot",
      supported: [1],
    }, `version=${String(version)} 이 v1 로 처리됐다`);
  }
  assert.deepEqual(seen, [], "미지 버전은 핸들러에 닿지 않는다");

  // 버전 판정이 사건 판정보다 **먼저**다 — 미지 버전의 요청은 해석 자체를 하지 않는다.
  assert.equal(api.deliver({ version: 2, event: "없는사건", payload: {} }).code,
    PRODUCT_ERROR_CODES.UNSUPPORTED_VERSION);
  assert.equal(api.deliver({ version: 2, event: 7, payload: {} }).event, null,
    "문자열이 아닌 사건은 되돌리지 않는다");
});

test("payload 형태 불량 — 사건별로 어긋난 필드를 지목한다", () => {
  const { api, seen } = makeApi();
  const cases = [
    ["snapshot", undefined, "payload"],
    ["snapshot", null, "payload"],
    ["snapshot", [], "payload"],
    ["snapshot", { snapshot: {} }, "screen"],
    ["snapshot", { screen: "", snapshot: {} }, "screen"],
    ["snapshot", { screen: 7, snapshot: {} }, "screen"],
    ["snapshot", { screen: "job" }, "snapshot"],
    ["close-request", {}, "state"],
    ["close-request", { state: null }, "state"],
    ["close-request", { state: "armed" }, "state"],
    ["preferences", {}, "personalization"],
    ["preferences", { personalization: null }, "personalization"],
    ["preferences", { personalization: "large" }, "personalization"],
    ["preferences", { personalization: {}, theme: "sepia" }, "theme"],
    ["preferences", { personalization: {}, theme: 1 }, "theme"],
    ["notice", {}, "message"],
    ["notice", { message: "" }, "message"],
    ["notice", { message: 7 }, "message"],
  ];

  for (const [event, payload, field] of cases) {
    assert.deepEqual(api.deliver({ version: 1, event, payload }), {
      ok: false, code: PRODUCT_ERROR_CODES.MALFORMED_PAYLOAD, event, field,
    }, `${event} / ${JSON.stringify(payload)}`);
  }
  assert.deepEqual(seen, [], "형태 불량 payload 는 핸들러에 닿지 않는다");
});

test("핸들러 부재는 조용한 무동작이 아니라 구조화된 실패다(종전 falsy no-op 의 후계)", () => {
  for (const event of CAPABILITIES) {
    const partial = createProductApi({ handlers: { [event]: null } });
    assert.deepEqual(partial.deliver({ version: 1, event, payload: VALID[event] }), {
      ok: false, code: PRODUCT_ERROR_CODES.HANDLER_UNAVAILABLE, event,
    });
  }
  assert.deepEqual(
    createProductApi({}).deliver({ version: 1, event: "notice", payload: VALID["notice"] }),
    { ok: false, code: PRODUCT_ERROR_CODES.HANDLER_UNAVAILABLE, event: "notice" },
  );
});

test("핸들러가 던지면 성공으로 삼키지 않고 handler_failed 로 바꾼다", () => {
  const boom = () => { throw new Error("JobScreen.renderResult 가 없습니다"); };
  for (const event of ["snapshot", "close-request", "preferences"]) {
    const { api } = makeApi({ [event]: boom });
    const result = api.deliver({ version: 1, event, payload: VALID[event] });
    assert.deepEqual(result, {
      ok: false, code: PRODUCT_ERROR_CODES.HANDLER_FAILED, event,
    });
    assert.equal(JSON.stringify(result).includes("JobScreen"), false,
      "예외 메시지는 내부 이름을 물고 온다 — 결과에 싣지 않는다");
  }
});

test("ok 가 참인 실패는 없다 — 실패 전수의 불변식", () => {
  const { api } = makeApi({ "snapshot": () => { throw new Error("x"); } });
  const failures = [
    api.deliver(null),
    api.deliver({ version: 2, event: "snapshot", payload: VALID["snapshot"] }),
    api.deliver({ version: 1, event: "없는사건", payload: {} }),
    api.deliver({ version: 1, event: "notice", payload: {} }),
    api.deliver({ version: 1, event: "snapshot", payload: VALID["snapshot"] }),
    createProductApi().deliver({ version: 1, event: "notice", payload: VALID["notice"] }),
  ];

  for (const failure of failures) {
    assert.equal(failure.ok, false);
    assert.equal(typeof failure.code, "string");
    assert.equal(Object.values(PRODUCT_ERROR_CODES).includes(failure.code), true,
      `안정 코드 밖의 값: ${failure.code}`);
  }
  assert.equal(new Set(failures.map((f) => f.code)).size, 6, "여섯 결함류가 서로 구별된다");
});

/* ══════════════ 5. 직렬화·누출 ══════════════ */

test("deliver 결과는 동기 · JSON 왕복 가능하다(Python 이 await 하지 않는다)", async () => {
  const { api } = makeApi();
  const results = [
    api.deliver({ version: 1, event: "snapshot", payload: VALID["snapshot"] }),
    api.deliver({ version: 1, event: "close-request", payload: VALID["close-request"] }),
    api.deliver({ version: 1, event: "preferences", payload: VALID["preferences"] }),
    api.deliver({ version: 1, event: "notice", payload: VALID["notice"] }),
    api.deliver(null),
    api.deliver({ version: 3, event: "snapshot", payload: {} }),
    api.deliver({ version: 1, event: "없는사건", payload: {} }),
    api.deliver({ version: 1, event: "preferences", payload: {} }),
    createProductApi().deliver({ version: 1, event: "notice", payload: VALID["notice"] }),
  ];

  for (const result of results) {
    assert.equal(result instanceof Promise, false, "deliver 는 promise 를 돌려주지 않는다");
    assert.equal(typeof result.then, "undefined", "thenable 도 아니다");
    assert.deepEqual(JSON.parse(JSON.stringify(result)), result);
  }
  await tick();
});

test("서술자·실패 객체 어디에도 내부 이름이 없다", () => {
  const { api } = makeApi({ "snapshot": () => { throw new Error("Theme 부재"); } });
  const payloads = [
    api.describe(),
    api.deliver(null),
    api.deliver({ version: 9, event: "snapshot", payload: {} }),
    api.deliver({ version: 1, event: "unknown-thing", payload: {} }),
    api.deliver({ version: 1, event: "preferences", payload: { personalization: 1 } }),
    api.deliver({ version: 1, event: "close-request", payload: { state: 1 } }),
    api.deliver({ version: 1, event: "snapshot", payload: VALID["snapshot"] }),
    createProductApi().deliver({ version: 1, event: "close-request", payload: VALID["close-request"] }),
  ];

  for (const payload of payloads) {
    const json = JSON.stringify(payload);
    for (const name of FORBIDDEN) {
      assert.equal(json.includes(name), false, `내부 이름 누출: ${name} in ${json}`);
    }
  }
});

/* ══════════════ 6. 소스 음성 계약 ══════════════ */

test("소스 — 전역 쓰기 0, default export 0, 테스트 훅 0", () => {
  assert.deepEqual(SRC.match(/^\s*(?:window|globalThis)\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/gm) || [],
    [], "이 모듈은 전역을 만들지 않는다 — 설치는 중앙 compat 의 몫이다(D-05)");
  assert.equal(SRC.includes("export default"), false);
  assert.equal(SRC.includes("__hwpxTest"), false, "테스트 훅은 N-09 소관이다");
  assert.equal(SRC.match(/^\(function \(\) \{/m), null);
});

test("소스 — 내부 이름을 상수로 들고 있지 않다", () => {
  for (const name of ["AppCloseGuard", "JobScreen", "LibraryScreen", "EditorScreen",
    "WorkbenchScreen", "pywebview", "overlayRoot", "__push"]) {
    assert.equal(SRC.includes(name), false, `소스가 내부 이름을 안다: ${name}`);
  }
});
