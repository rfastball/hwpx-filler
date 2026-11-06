/* 설치 Chrome 자원 게이트(tests/browser)의 결정론적 입력 계약 — 브라우저 없이 돈다.
 * - 코퍼스의 실습 표본 사본은 학습자가 여는 출하 템플릿과 한 바이트도 다르지 않아야
 *   rhwp 왕복 판정(#1022)이 그 파일의 것이 된다.
 * - 루프백 서버는 Chrome 이 막는 포트를 받지 않고, 점유된 포트는 다시 고른다. */
import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { createServer } from "node:http";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { CHROME_SAFE_PORT_ATTEMPTS, CHROME_SAFE_PORT_BASE, CHROME_SAFE_PORT_SPAN, corpus, listenChromeSafe, repo }
  from "../browser/browser_probe.js";

const QUICKSTART_CASES = ["구매요청서.hwpx", "발주요청서.hwpx"];

test("quickstart corpus samples are byte copies of the shipped templates", () => {
  const shipped = resolve(repo, "examples/quickstart-101/templates");
  const names = readdirSync(shipped);
  for (const name of QUICKSTART_CASES) {
    assert.ok(names.includes(name), `shipped template missing: ${name}`);
    assert.ok(readFileSync(resolve(corpus, "quickstart", name)).equals(readFileSync(resolve(shipped, name))),
      `tests/corpus/quickstart/${name} 가 출하 템플릿과 다릅니다 — 표본을 다시 만들었다면 코퍼스 사본도 갱신하세요.`);
  }
});

class FakeServer extends EventEmitter {
  constructor(refuse) {
    super();
    this.refuse = refuse;
    this.requested = [];
  }

  listen(port) {
    this.requested.push(port);
    queueMicrotask(() => (this.refuse(this.requested.length)
      ? this.emit("error", Object.assign(new Error("port in use"), { code: "EADDRINUSE" }))
      : this.emit("listening")));
  }
}

test("loopback retries busy ports inside the Chrome-safe dynamic range", async () => {
  assert.ok(CHROME_SAFE_PORT_BASE > 10080 && CHROME_SAFE_PORT_BASE + CHROME_SAFE_PORT_SPAN - 1 === 65535);
  const choices = [0, CHROME_SAFE_PORT_SPAN - 1];
  const busyOnce = new FakeServer((count) => count === 1);
  assert.equal(await listenChromeSafe(busyOnce, { random: () => choices.shift() }), 65535);
  assert.deepEqual(busyOnce.requested, [49152, 65535]);
  assert.equal(busyOnce.listenerCount("error") + busyOnce.listenerCount("listening"), 0);

  const busy = new FakeServer(() => true);
  await assert.rejects(listenChromeSafe(busy, { random: () => 0 }), (error) => {
    assert.match(error.message, new RegExp(`after ${CHROME_SAFE_PORT_ATTEMPTS} attempts`, "u"));
    assert.equal(error.cause?.code, "EADDRINUSE");
    return true;
  });
  assert.deepEqual(busy.requested, Array(CHROME_SAFE_PORT_ATTEMPTS).fill(49152));
});

test("a real occupied loopback port is skipped", async () => {
  const holder = createServer();
  const taken = await listenChromeSafe(holder);
  const server = createServer();
  try {
    let first = true;
    const port = await listenChromeSafe(server, {
      random: (span) => (first ? ((first = false), taken - CHROME_SAFE_PORT_BASE) : Math.floor(Math.random() * span)),
    });
    assert.notEqual(port, taken);
    assert.ok(port >= CHROME_SAFE_PORT_BASE && port <= 65535);
    assert.equal(server.address().port, port);
  } finally {
    await new Promise((done) => server.close(() => done()));
    await new Promise((done) => holder.close(() => done()));
  }
});
