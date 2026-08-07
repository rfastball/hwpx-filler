/* R4-04 — legacy PathTrack의 최종 후계 PathActions.
 *
 * UI 이벤트가 호출하는 순수 공개 경계 ``invokePathAction``을 직접 실행한다. 성공/host 거절/
 * transport 예외/복사 완료 callback을 같은 typed client 대역으로 재므로 React 훅이나 DOM
 * 렌더러의 우연한 동작에 기대지 않는다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { invokePathAction } from "../../frontend/src/screens/path_actions.ts";

const SOURCE = readFileSync(
  new URL("../../frontend/src/screens/path_actions.ts", import.meta.url),
  "utf8",
);

test("PathActions는 BridgeClient를 주입받고 legacy bridge/pathtrack에 직접 닿지 않는다", () => {
  assert.match(SOURCE, /import\s+type\s+{\s*BridgeClient\s*}/);
  assert.match(SOURCE, /client:\s*BridgeClient/);
  assert.match(SOURCE, /export\s+type\s+PathAction\s*=\s*"open"\s*\|\s*"reveal"\s*\|\s*"copy"/);
  assert.doesNotMatch(SOURCE, /createBridge|\.\.\/\.\.\/js\/pathtrack|window\.pywebview/);
});

test("open/reveal은 typed client의 정확한 메서드·경로로 가고 성공은 notify하지 않는다", async () => {
  const calls = [];
  const notices = [];
  const client = {
    async invoke(method, path) {
      calls.push([method, path]);
      return { ok: true, value: null };
    },
  };
  assert.equal(await invokePathAction({
    client, path: "C:\\산출\\결과.hwpx", action: "open",
    notify: (message) => notices.push(message),
  }), true);
  assert.equal(await invokePathAction({
    client, path: "C:\\산출\\결과.hwpx", action: "reveal",
    notify: (message) => notices.push(message),
  }), true);

  assert.deepEqual(calls, [
    ["open_path", "C:\\산출\\결과.hwpx"],
    ["reveal_path", "C:\\산출\\결과.hwpx"],
  ]);
  assert.deepEqual(notices, []);
});

test("host 거절과 promise 예외는 false와 이유 notify로 시끄럽게 끝난다", async () => {
  const notices = [];
  const rejected = await invokePathAction({
    client: {
      async invoke() {
        return { ok: false, failure: { message: "소유 경로가 아닙니다" } };
      },
    },
    path: "C:\\outside",
    action: "open",
    notify: (message) => notices.push(message),
  });
  const broken = await invokePathAction({
    client: { invoke: async () => { throw new Error("브리지 끊김"); } },
    path: "C:\\owned",
    action: "reveal",
    notify: (message) => notices.push(message),
  });

  assert.equal(rejected, false);
  assert.equal(broken, false);
  assert.deepEqual(notices, [
    "열기 실패: 소유 경로가 아닙니다",
    "브리지 끊김",
  ]);
});

test("copy 성공은 copy_path 뒤 onCopied를 정확히 한 번 부른다", async () => {
  const calls = [];
  const notices = [];
  let copied = 0;
  const ok = await invokePathAction({
    client: {
      async invoke(method, path) {
        calls.push([method, path]);
        return { ok: true, value: null };
      },
    },
    path: "C:\\owned",
    action: "copy",
    notify: (message) => notices.push(message),
    onCopied: () => { copied += 1; },
  });

  assert.equal(ok, true);
  assert.deepEqual(calls, [["copy_path", "C:\\owned"]]);
  assert.equal(copied, 1);
  assert.deepEqual(notices, []);
});

test("copy 실패는 onCopied를 부르지 않는다", async () => {
  const notices = [];
  let copied = 0;
  const ok = await invokePathAction({
    client: {
      async invoke() {
        return { ok: false, failure: { message: "복사 거절" } };
      },
    },
    path: "C:\\outside",
    action: "copy",
    notify: (message) => notices.push(message),
    onCopied: () => { copied += 1; },
  });

  assert.equal(ok, false);
  assert.equal(copied, 0);
  assert.deepEqual(notices, ["경로 복사 실패: 복사 거절"]);
});
