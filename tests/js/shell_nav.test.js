/* 셸 상태기계 계약 전수 (R3-02 · #411) — 판정층을 주입 기록자로 직접 잰다(DOM 0).
 *
 * 이 파일이 재는 것은 app.js 에서 상태기계로 올라온 **판정**이다: 랜딩·전환·몰입 이탈
 * 위임·force 재진입·ready 게이트·재당김 규약·닫기 직렬화·구독 수명. DOM 집행(클래스·속성
 * 토글·브리지 발신·재진술)은 집행 adapter 몫이라 여기 없다 — 그 절반은 개정된 n06(파사드
 * +집행)과 실 WebView2 게이트(test_react_shell_live)가 진다. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  DEFAULT_SCREEN,
  IMMERSIVE_SURFACES,
  REFRESH_ON_NAV,
  createShellNav,
} from "../../frontend/src/shell/nav.ts";

const SRC_URL = new URL("../../frontend/src/shell/nav.ts", import.meta.url);
const SRC = readFileSync(SRC_URL, "utf8");

/** 기록자 집행자 — 호출 순서가 곧 증거다. */
function recorder(log, overrides = {}) {
  return {
    delegateLeave: (from, to) => { log.push(`delegateLeave(${from}→${to})`); return true; },
    reclaimSurfaces: () => log.push("reclaimSurfaces"),
    applyScreen: (id) => log.push(`applyScreen(${id})`),
    dispatchRefresh: (id) => { log.push(`dispatchRefresh(${id})`); return Promise.resolve({}); },
    notifyRefreshFailure: (error) => log.push(`notifyRefreshFailure(${String(error && error.message || error)})`),
    rerenderEditor: () => log.push("rerenderEditor"),
    ...overrides,
  };
}

function makeNav(overrides = {}) {
  const log = [];
  const nav = createShellNav();
  nav.bindExecutor(recorder(log, overrides));
  return { nav, log };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

/* ══════════════ 1. 공개 표면·정본 데이터 ══════════════ */

test("공개 표면은 계약 표와 정확히 같다", () => {
  const nav = createShellNav();
  assert.deepEqual(Object.keys(nav).sort(), [
    "beginClosePrompt", "bindExecutor", "currentScreen", "endClosePrompt",
    "go", "isClosePromptPending", "isRoutingReady", "markReady", "refresh", "subscribe",
  ]);
  for (const key of Object.keys(nav)) assert.equal(typeof nav[key], "function");
});

test("정본 데이터 — DEFAULT_SCREEN·REFRESH_ON_NAV·IMMERSIVE_SURFACES 의 값과 동결", () => {
  assert.equal(DEFAULT_SCREEN, "job", "R-info 결정 1: 콜드 부팅 랜딩은 작업");
  assert.deepEqual([...REFRESH_ON_NAV], ["library", "job"]);
  assert.deepEqual(
    IMMERSIVE_SURFACES.map((im) => [im.id, im.cls]),
    [["editor", "editor-open"], ["workbench", "workbench-open"]],
    "몰입 표면 단일 목록(F6) — 위임 판정과 셸 은닉 집행이 같은 행을 읽는다",
  );
  assert.equal(Object.isFrozen(REFRESH_ON_NAV), true);
  assert.equal(Object.isFrozen(IMMERSIVE_SURFACES), true);
  for (const im of IMMERSIVE_SURFACES) assert.equal(Object.isFrozen(im), true);
});

/* ══════════════ 2. 결속 규율 ══════════════ */

test("bindExecutor 는 정확히 1회 — 두 번째 결속은 throw(두 번째 실행 경로 금지)", () => {
  const { nav } = makeNav();
  assert.throws(() => nav.bindExecutor(recorder([])), /이미 결속/);
});

test("결속 전 판정 요청은 loud throw 다 — 조용한 무동작 랜딩 금지", async () => {
  const nav = createShellNav();
  assert.throws(() => nav.go("job"), /결속되지 않았습니다/);
  // refresh 의 가드 경로(ready 전)는 집행에 닿지 않으므로 무동작 이행 약속이 옳다 —
  // throw 는 판정이 집행에 도달하는 순간(ready + 화이트리스트)에만 선다.
  assert.equal(await nav.refresh("job"), null);
  nav.markReady();
  assert.throws(() => nav.refresh("job"), /결속되지 않았습니다/);
});

/* ══════════════ 3. 랜딩·전환·동기성 ══════════════ */

test("go 는 synchronous 다 — 반환값 undefined·회수→상태→집행 순서가 동기 완료", () => {
  const { nav, log } = makeNav();
  const out = nav.go(DEFAULT_SCREEN);
  assert.equal(out, undefined, "go() 를 비동기로 바꾸면 반환값 무시 호출부가 순서를 잃는다");
  assert.deepEqual(log, ["reclaimSurfaces", `applyScreen(${DEFAULT_SCREEN})`],
    "await 없이 즉시 집행돼 있다 — React 재렌더 경유 없음(ready 전이라 재당김·재렌더 발신 없음)");
  assert.equal(nav.currentScreen(), DEFAULT_SCREEN);
});

test("랜딩 전 currentScreen 은 null — 랜딩은 구성이 아니라 go 가 찍는다", () => {
  const nav = createShellNav();
  assert.equal(nav.currentScreen(), null);
});

/* ══════════════ 4. 몰입 이탈 위임 ══════════════ */

test("몰입 화면에서 나가는 go 는 위임 후 전환 중단, force 는 위임 생략", () => {
  const { nav, log } = makeNav();
  nav.go("editor");
  assert.equal(nav.currentScreen(), "editor");

  log.length = 0;
  nav.go("job");
  assert.deepEqual(log, ["delegateLeave(editor→job)"], "이탈은 소유 화면에 위임된다");
  assert.equal(nav.currentScreen(), "editor", "전환 중단 — 처분이 끝나면 force 로 되돌아온다");

  log.length = 0;
  nav.go("job", { force: true });
  assert.deepEqual(log, ["reclaimSurfaces", "applyScreen(job)"],
    "force 재진입은 위임을 생략한다(ready 전이라 재렌더 없음)");
  assert.equal(nav.currentScreen(), "job");
});

test("workbench 도 동형이다 — 몰입 목록이 판정을 소유한다(F6)", () => {
  const { nav, log } = makeNav();
  nav.go("workbench");
  log.length = 0;
  nav.go("library");
  assert.deepEqual(log, ["delegateLeave(workbench→library)"]);
  assert.equal(nav.currentScreen(), "workbench");
});

test("위임 불성립(leaveTo 부재 — delegateLeave false)이면 전환을 계속한다(fallthrough 보존)", () => {
  const { nav, log } = makeNav({ delegateLeave: (from, to) => { log.push(`delegateLeave(${from}→${to})`); return false; } });
  nav.go("editor");
  log.length = 0;
  nav.go("job");
  assert.deepEqual(log, ["delegateLeave(editor→job)", "reclaimSurfaces", "applyScreen(job)"],
    "가드 없는 몰입 표면이 항행을 막는 새 상태를 만들지 않는다(ready 전이라 재렌더 없음)");
  assert.equal(nav.currentScreen(), "job");
});

test("몰입 화면 자신으로의 go(같은 id)는 위임 없이 재집행이다", () => {
  const { nav, log } = makeNav();
  nav.go("editor");
  log.length = 0;
  nav.go("editor");
  assert.deepEqual(log, ["reclaimSurfaces", "applyScreen(editor)"]);
});

/* ══════════════ 5. ready 게이트·재당김 규약 ══════════════ */

test("가드 — ready 전·비화이트리스트는 무동작 이행 약속(null), 집행자 발신 0", async () => {
  const { nav, log } = makeNav();
  assert.equal(await nav.refresh("job"), null, "ready 전");
  nav.markReady();
  assert.equal(await nav.refresh("editor"), null, "화이트리스트 밖");
  assert.deepEqual(log, [], "둘 다 dispatchRefresh 0 — 호스트 가용성 판독까지 가지 않는다");
});

test("ready 후 화이트리스트 재당김은 집행자에게 위임되고 그 이행 약속을 그대로 돌려준다", async () => {
  const sentinel = { notice: null };
  const { nav, log } = makeNav({
    dispatchRefresh: (id) => { log.push(`dispatchRefresh(${id})`); return Promise.resolve(sentinel); },
  });
  nav.markReady();
  assert.equal(await nav.refresh("library"), sentinel);
  assert.deepEqual(log, ["dispatchRefresh(library)"]);
});

test("ready 후 전환은 자동 재당김을 쏘고, refreshed:true 는 쏘지 않는다", async () => {
  const { nav, log } = makeNav();
  nav.markReady();
  nav.go("library");
  await tick();
  assert.deepEqual(log, ["reclaimSurfaces", "applyScreen(library)", "dispatchRefresh(library)"]);

  log.length = 0;
  nav.go("job", { refreshed: true });
  await tick();
  assert.deepEqual(log, ["reclaimSurfaces", "applyScreen(job)", "rerenderEditor"],
    "호출자가 전환 전에 이미 기다린 경우(refreshed) 왕복을 두 벌 만들지 않는다 — job 착지 재렌더는 돈다");
});

test("자동 재당김 실패는 원 error 그대로 실패 재진술 포트로 내려간다(조용한 삼킴 금지)", async () => {
  const { nav, log } = makeNav({
    dispatchRefresh: (id) => { log.push(`dispatchRefresh(${id})`); return Promise.reject(new Error("재당김 사망")); },
  });
  nav.markReady();
  nav.go("library");
  await tick();
  assert.deepEqual(log, [
    "reclaimSurfaces", "applyScreen(library)", "dispatchRefresh(library)",
    "notifyRefreshFailure(재당김 사망)",
  ]);
});

test("ready 전 전환은 DOM 랜딩 집행만 — 재당김·재렌더 발신 0", () => {
  const { nav, log } = makeNav();
  nav.go("job");
  nav.go("library");
  assert.deepEqual(log, [
    "reclaimSurfaces", "applyScreen(job)",
    "reclaimSurfaces", "applyScreen(library)",
  ], "ready 전에는 dispatchRefresh 도 rerenderEditor 도 돌지 않는다");
});

test("job 착지 시 rerenderEditor — ready 후에만, job 외 착지는 없음(#138 리뷰 F12)", () => {
  const { nav, log } = makeNav();
  nav.markReady();
  nav.go("library");
  assert.equal(log.includes("rerenderEditor"), false);
  log.length = 0;
  nav.go("job");
  assert.deepEqual(log.filter((entry) => entry === "rerenderEditor"), ["rerenderEditor"]);
});

/* ══════════════ 6. markReady ══════════════ */

test("markReady — ready 전이는 1회 통지, 재발화는 상태 무변화·통지 없음(재주행은 시퀀서 소유)", () => {
  const { nav } = makeNav();
  const events = [];
  nav.subscribe(() => events.push(nav.isRoutingReady()));
  assert.equal(nav.isRoutingReady(), false);
  nav.markReady();
  assert.equal(nav.isRoutingReady(), true);
  nav.markReady();
  assert.deepEqual(events, [true], "재발화 통지가 두 벌이면 구독자가 유령 전이를 본다");
});

/* ══════════════ 7. 닫기 직렬화 ══════════════ */

test("beginClosePrompt 는 단일 실행 — 미결 중 재진입 거절, end 후 새 판정 허용", () => {
  const { nav } = makeNav();
  assert.equal(nav.beginClosePrompt(), true);
  assert.equal(nav.isClosePromptPending(), true);
  assert.equal(nav.beginClosePrompt(), false, "미결 중 2차는 거절 — 모달을 다시 세우지 않는다");
  nav.endClosePrompt();
  assert.equal(nav.isClosePromptPending(), false);
  assert.equal(nav.beginClosePrompt(), true, "다음 X 는 새 상태를 다시 판정한다");
  nav.endClosePrompt();
});

test("미보유 endClosePrompt 는 throw — begin/end 는 짝이어야 한다", () => {
  const { nav } = makeNav();
  assert.throws(() => nav.endClosePrompt(), /짝이어야 합니다/);
});

/* ══════════════ 8. 구독 수명 ══════════════ */

test("구독 — 전환·ready 전이에 통지, 해제 후 통지 없음, 이중 해제는 throw(store 규율)", () => {
  const { nav } = makeNav();
  let seen = 0;
  const unsubscribe = nav.subscribe(() => { seen += 1; });
  nav.go("job");
  nav.markReady();
  assert.equal(seen, 2, "전환 1 + ready 전이 1");
  unsubscribe();
  nav.go("library");
  assert.equal(seen, 2, "해제 뒤 통지 없음");
  assert.throws(unsubscribe, /정확히 1회/);
});

test("위임 중단 전환은 통지하지 않는다 — 상태가 변하지 않았다", () => {
  const { nav } = makeNav();
  nav.go("editor");
  let seen = 0;
  nav.subscribe(() => { seen += 1; });
  nav.go("job"); // 위임·중단
  assert.equal(seen, 0);
});

/* ══════════════ 9. 음성 — 소스 형상 ══════════════ */

test("음성 — DOM·전역·React·pywebview 접촉 0(판정층 순수성)", () => {
  // 전역 이름 needle 은 주석까지 문다(표기 자체 금지 — n06 규율). React 는 산문 언급이
  // 정당하므로 실행 접촉형(import 지정자·요소 생성)만 문다.
  for (const forbidden of ["document.", "window.", "globalThis", "pywebview"]) {
    assert.equal(SRC.includes(forbidden), false, `nav.ts 에 ${forbidden} 금지 — 집행은 adapter 몫`);
  }
  for (const forbidden of ['from "react"', "createElement"]) {
    assert.equal(SRC.includes(forbidden), false, `nav.ts 에 ${forbidden} 금지 — React 결합은 host 몫`);
  }
});

test("음성 — 정본 문자열이 이 파일에 산다(원문 핀 이동의 착지 증거)", () => {
  assert.ok(SRC.includes('export const DEFAULT_SCREEN = "job"'));
  assert.ok(/REFRESH_ON_NAV[^=]*=\s*Object\.freeze\(\["library", "job"\]\)/.test(SRC));
  assert.ok(SRC.includes('{ id: "editor", cls: "editor-open" }'));
  assert.ok(SRC.includes('{ id: "workbench", cls: "workbench-open" }'));
  assert.ok(SRC.includes("routingReady"), "ready 게이트 식별자의 새 거처");
  assert.ok(SRC.includes("closePromptPending"), "닫기 직렬화 식별자의 새 거처");
});
