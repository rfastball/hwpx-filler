/* runtime adapter + typed bridge client 단위 계약 (R2-02 · #406).
 *
 * `.ts` 모듈을 그대로 싣는다 — Node 24 type stripping 이 제품 파일을 무변환으로 실어야
 * node 게이트·tsc·Vite 빌드가 같은 파일을 본다(react_root.test.js 와 같은 규약).
 *
 * ## 무엇을 지키는가
 *
 * 어댑터의 변환 대상은 웹→Python 경로의 실패 셋**뿐**이다(패킷 rev2 §4.2-1):
 * ① dispatch 거절 봉투(`{name, message}`) → typed 오류, **원문 보존**
 * ② `"ERROR:"` 문자열 규약 → typed 결과, 원문 그대로
 * ③ 호스트 메서드 부재(종전 TypeError) → loud typed 오류
 * 그 밖의 실패는 변환하지 않고 그대로 던져진다 — 감싸면 실제 결함이 정상 거절로
 * 위장한다(app.py dispatch 독스트링과 같은 근거). 각 갈래를 합성 표본으로 고정하고,
 * near-miss 음성(규약 밖 문자열·정상 반환)이 조용히 통과하는지 함께 센다.
 *
 * client 는 전송 표면까지다: 이름이 생성 계약의 유니온으로 좁혀지고, 타입을 우회한
 * 런타임 호출(계약 밖 이름·host-internal)은 시끄럽게 거절된다. payload 값 검증은
 * 하지 않는다 — 키 집합 거절의 정본은 Python `validate_dispatch` 하나다. */
import test from "node:test";
import assert from "node:assert/strict";

import { createRuntimeAdapter } from "../../frontend/src/runtime/adapter.ts";
import { createBridgeClient } from "../../frontend/src/runtime/client.ts";
import {
  DISPATCH_REJECTION_KEY,
  HOST_INTERNAL_METHODS,
  HOST_METHODS,
} from "../../frontend/src/contract/contract.gen.ts";

/** 호스트 창 대역 — api 를 주면 주입 완료 상태, 안 주면 부재 상태다. */
function makeWin(api) {
  const listeners = [];
  const win = {
    addEventListener(type, fn, options) { listeners.push({ type, fn, options }); },
  };
  if (api !== undefined) win.pywebview = { api };
  return { win, listeners };
}

function adapterWith(api) {
  const { win, listeners } = makeWin(api);
  return { adapter: createRuntimeAdapter({ win }), win, listeners };
}

/* ══════════════ 생성 계약의 소비 형태 ══════════════ */

test("생성 계약 — 메서드 전수는 내부 표면을 포함하고, 내부 표면은 그 부분집합이다", () => {
  assert.equal(HOST_METHODS.length, 24, "WebFrontend 공개 표면은 24 다(패킷 §2.1)");
  for (const name of ["initial", "dispatch", "generate", "close_guard_state"]) {
    assert.ok(HOST_METHODS.includes(name), `${name} 이 HOST_METHODS 에 없습니다`);
  }
  for (const name of HOST_INTERNAL_METHODS) {
    assert.ok(HOST_METHODS.includes(name),
      `host-internal ${name} 이 공개 표면 밖입니다 — 기록이 표면과 어긋났습니다`);
  }
});

/* ══════════════ ready — 판정과 대기 ══════════════ */

test("hostReady — 주입 전 거짓, 주입 후 참(재시도·캐시 없는 순간 판정)", () => {
  const absent = adapterWith(undefined);
  assert.equal(absent.adapter.hostReady(), false);

  const present = adapterWith({});
  assert.equal(present.adapter.hostReady(), true);
});

test("구성은 부작용이 없다 — 리스너 부착은 whenReady 호출이 진다", async () => {
  const { adapter, listeners, win } = adapterWith(undefined);
  assert.equal(listeners.length, 0, "구성만으로 리스너가 붙었습니다");

  let resolved = false;
  const waiting = adapter.whenReady().then(() => { resolved = true; });
  assert.equal(listeners.length, 1);
  assert.equal(listeners[0].type, "pywebviewready");
  assert.deepEqual(listeners[0].options, { once: true });
  assert.equal(resolved, false, "호스트가 없는데 준비가 해소됐습니다");

  win.pywebview = { api: {} };
  listeners[0].fn();
  await waiting;
  assert.equal(resolved, true);
});

test("whenReady — 이미 주입돼 있으면 리스너 없이 즉시 해소된다", async () => {
  const { adapter, listeners } = adapterWith({});
  await adapter.whenReady();
  assert.equal(listeners.length, 0, "주입 완료 상태에서 리스너가 붙었습니다");
});

/* ══════════════ call — 성공 통과와 실패 변환 셋 ══════════════ */

test("성공 반환은 무가공 통과한다 — 인자·this 결속 포함", async () => {
  const calls = [];
  const sentinel = { rows: 3 };
  const { adapter } = adapterWith({
    generate(screen, confirm) { calls.push([this, screen, confirm]); return sentinel; },
  });

  const result = await adapter.call("generate", ["job", true]);

  assert.deepEqual(result, { ok: true, value: sentinel });
  assert.equal(result.value, sentinel, "반환을 감싸거나 복사하면 안 된다");
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1], "job");
  assert.equal(calls[0][2], true);
});

test("① 거절 봉투 → typed 오류, name·message **원문 보존**", async () => {
  const rejection = { name: "ValueError", message: "미등록 키=['typo']" };
  const { adapter } = adapterWith({
    dispatch: () => ({ [DISPATCH_REJECTION_KEY]: rejection }),
  });

  const result = await adapter.call("dispatch", ["job", "refresh", { typo: 1 }]);

  assert.equal(result.ok, false);
  assert.equal(result.failure.kind, "dispatch-rejected");
  assert.equal(result.failure.name, "ValueError");
  assert.equal(result.failure.message, "미등록 키=['typo']", "message 는 원문 그대로여야 한다");
});

test("① 이름 없는 봉투는 JS Error 기본 이름으로 — bridge.js 와 같은 규약", async () => {
  const { adapter } = adapterWith({
    dispatch: () => ({ [DISPATCH_REJECTION_KEY]: { message: "사유" } }),
  });

  const result = await adapter.call("dispatch", ["job", "refresh", {}]);

  assert.equal(result.failure.kind, "dispatch-rejected");
  assert.equal(result.failure.name, "Error");
});

test("① 손상 봉투는 거절로도 성공으로도 접지 않는다 — 제 이름의 실패다", async () => {
  for (const broken of [null, "문자열", { message: 5 }, {}]) {
    const { adapter } = adapterWith({
      dispatch: () => ({ [DISPATCH_REJECTION_KEY]: broken }),
    });
    const result = await adapter.call("dispatch", ["job", "refresh", {}]);
    assert.equal(result.ok, false);
    assert.equal(result.failure.kind, "rejection-envelope-malformed",
      `손상 봉투(${JSON.stringify(broken)})가 다른 판정으로 샜습니다`);
  }
});

test('② "ERROR:" 문자열 규약 → typed 결과, 원문 그대로', async () => {
  const { adapter } = adapterWith({ open_path: () => "ERROR: 소유 경로가 아닙니다" });

  const result = await adapter.call("open_path", ["C:\\x"]);

  assert.equal(result.ok, false);
  assert.equal(result.failure.kind, "host-error-string");
  assert.equal(result.failure.message, "ERROR: 소유 경로가 아닙니다");
});

test("② near-miss 음성 — 규약 밖 문자열·null 은 성공 값 그대로다", async () => {
  for (const value of ["갑근세.hwpx", "중간에 ERROR: 가 있는 문자열", null, false, 0]) {
    const { adapter } = adapterWith({ open_path: () => value });
    const result = await adapter.call("open_path", ["C:\\x"]);
    assert.deepEqual(result, { ok: true, value },
      `규약 밖 반환(${JSON.stringify(value)})을 실패로 재해석했습니다`);
  }
});

test("③ 메서드 부재 → loud typed 오류(종전엔 소비자 자리의 TypeError 였다)", async () => {
  const { adapter } = adapterWith({});

  const result = await adapter.call("generate", ["job", false]);

  assert.equal(result.ok, false);
  assert.equal(result.failure.kind, "method-missing");
  assert.equal(result.failure.method, "generate");
});

test("호스트 부재 → loud typed 오류 — 부재와 거절은 다른 사건이다", async () => {
  const { adapter } = adapterWith(undefined);

  const result = await adapter.call("initial", ["job"]);

  assert.equal(result.ok, false);
  assert.equal(result.failure.kind, "host-absent");
});

test("예상 밖 실패는 변환하지 않는다 — 동기 throw 도 비동기 거절도 그대로 던져진다", async () => {
  const sync = adapterWith({ generate: () => { throw new Error("실제 결함"); } });
  await assert.rejects(() => sync.adapter.call("generate", ["job", false]), /실제 결함/);

  const async_ = adapterWith({ generate: () => Promise.reject(new Error("transport 결함")) });
  await assert.rejects(() => async_.adapter.call("generate", ["job", false]), /transport 결함/);
});

/* ══════════════ client — 유니온으로 좁혀진 전송 표면 ══════════════ */

function clientWith(api) {
  const { adapter } = adapterWith(api);
  return createBridgeClient({ adapter });
}

test("dispatch — 화면·액션·payload 를 그대로 싣고, 미지정 payload 는 빈 객체다", async () => {
  const calls = [];
  const client = clientWith({
    dispatch: (...args) => { calls.push(args); return { done: true }; },
  });

  await client.dispatch("job", "refresh");
  await client.dispatch("job", "toggle_record", { index: 1, value: true });

  assert.deepEqual(calls, [
    ["job", "refresh", {}],
    ["job", "toggle_record", { index: 1, value: true }],
  ]);
});

test("dispatch — Python 거절 봉투가 client 표면에서 typed 실패로 돌아온다(왕복 통합)", async () => {
  const client = clientWith({
    dispatch: () => ({
      [DISPATCH_REJECTION_KEY]: { name: "ValueError", message: "등록되지 않은 화면: 'ghost'" },
    }),
  });

  const result = await client.dispatch("job", "refresh");

  assert.equal(result.ok, false);
  assert.equal(result.failure.kind, "dispatch-rejected");
  assert.equal(result.failure.message, "등록되지 않은 화면: 'ghost'");
});

test("initial — 화면 이름 하나를 싣는 부팅 당김이다", async () => {
  const calls = [];
  const client = clientWith({ initial: (screen) => { calls.push(screen); return { s: 1 }; } });

  const result = await client.initial("job");

  assert.deepEqual(calls, ["job"]);
  assert.deepEqual(result, { ok: true, value: { s: 1 } });
});

test("invoke — 계약 밖 이름은 호스트에 닿기 전에 시끄럽게 거절된다", () => {
  const client = clientWith({});

  assert.throws(() => client.invoke("ghost_method"), /계약\(HOST_METHODS\)에 없는/);
});

test("invoke — host-internal 은 client 표면이 아니다(웹 소비자 0 의 기록을 지킨다)", () => {
  const calls = [];
  const client = clientWith({ close_guard_state: () => { calls.push(1); return {}; } });

  assert.throws(() => client.invoke("close_guard_state"), /host-internal/);
  assert.equal(calls.length, 0, "거절 전에 호스트가 불렸습니다");
});
