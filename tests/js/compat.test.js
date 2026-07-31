/* 중앙 호환 계층 계약 — 별칭은 정확히 넷, 정확히 한 번, export 와 같은 객체.

   compat 은 "동작을 바꾸지 않는 파일"이라 동작 테스트로는 보이지 않는다. 여기서 세는 것은
   결과가 아니라 **생산 자리와 횟수**다(#372 D-05). */
import test from "node:test";
import assert from "node:assert/strict";

import { Copy } from "../../frontend/js/copy.js";
import { escHtml } from "../../frontend/js/esc.js";
import { Guard } from "../../frontend/js/guard.js";
import { SegView } from "../../frontend/js/segview.js";

const COMPAT = "../../frontend/src/compat.js";
const LEAVES = ["copy.js", "esc.js", "guard.js", "segview.js"];
const ALIASES = ["Copy", "Guard", "SegView", "escHtml"];

/* Node 에는 window 가 없다. 테스트가 심는 이 stub 은 제품 전역이 아니므로 매 테스트 뒤
   반드시 걷는다 — 남겨두면 다음 테스트의 "전역 0" 관측을 오염시킨다. */
function useWindowStub(t) {
  const had = Object.hasOwn(globalThis, "window");
  const previous = globalThis.window;
  globalThis.window = {};
  t.after(() => {
    if (had) globalThis.window = previous;
    else delete globalThis.window;
  });
  return globalThis.window;
}

test("전역 프로브가 실제 쓰기를 잡는다(양성 대조)", async (t) => {
  const stub = useWindowStub(t);

  await import("data:text/javascript,window.__probeControl = 1;");

  assert.deepEqual(Object.keys(stub), ["__probeControl"]);
});

test("잎 모듈은 import 만으로 전역을 만들지 않는다", async (t) => {
  const stub = useWindowStub(t);

  // 캐시 우회 쿼리가 없으면 상단 static import 로 이미 평가된 모듈을 다시 받아
  // 프로브가 아무것도 관측하지 못한 채 초록이 된다.
  for (const [index, leaf] of LEAVES.entries()) {
    await import(`../../frontend/js/${leaf}?leaf-global-probe=${index}`);
  }

  assert.deepEqual(Object.keys(stub), []);
});

test("compat 이 네 별칭을 만들고 반복 import 는 상태를 늘리지 않는다", async (t) => {
  const stub = useWindowStub(t);
  assert.deepEqual(Object.keys(stub), []);

  const first = await import(COMPAT);
  const installed = Object.keys(stub).sort();

  assert.deepEqual(installed, ALIASES);
  assert.equal(stub.Copy, Copy);
  assert.equal(stub.escHtml, escHtml);
  assert.equal(stub.Guard, Guard);
  assert.equal(stub.SegView, SegView);

  const second = await import(COMPAT);

  assert.equal(second, first, "ESM 캐시 히트여야 한다 — 본문이 두 번 돌면 안 된다");
  assert.deepEqual(Object.keys(stub).sort(), installed);
  assert.equal(stub.Copy, Copy);
  assert.equal(stub.escHtml, escHtml);
  assert.equal(stub.Guard, Guard);
  assert.equal(stub.SegView, SegView);
});

test("compat 은 자체 상태나 새 표면을 갖지 않는다", async (t) => {
  useWindowStub(t);

  const module = await import(COMPAT);

  assert.deepEqual(Object.keys(module), [], "compat 은 아무것도 export 하지 않는다");
});
