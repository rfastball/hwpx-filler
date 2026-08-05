/* overlay 엔진 계약 전수 (R3-01 · #410) — 판정층을 주입 기록자로 직접 잰다(DOM 0).
 *
 * 이 파일이 재는 것은 modal.js 에서 엔진으로 올라온 **판정**이다: 중첩 스택·닫힘 정착
 * 순서·복귀 승계(최상위만)·promise 직렬화·Escape/Tab/IME 판정·keydown 시점·구독 수명.
 * DOM 집행(클래스·전이·포커스 실이동)은 집행자 몫이라 여기 없다 — 그 절반은 개정된
 * n05_overlay(파사드+집행)와 실 WebView2 게이트가 진다. */
import test from "node:test";
import assert from "node:assert/strict";

import { createOverlayEngine } from "../../frontend/src/overlay/engine.ts";

/** 기록자 집행자 — 호출 순서가 곧 증거다. */
function recorder(log, name) {
  return {
    show: (depth) => log.push(`${name}.show(${depth})`),
    beginClose: () => log.push(`${name}.beginClose`),
    finishClose: () => log.push(`${name}.finishClose`),
    focusInitial: () => log.push(`${name}.focusInitial`),
    trapTab: (backward) => log.push(`${name}.trapTab(${backward})`),
    restoreFocus: () => log.push(`${name}.restoreFocus`),
  };
}

test("공개 표면은 계약 표와 정확히 같다", () => {
  const engine = createOverlayEngine();
  assert.deepEqual(Object.keys(engine).sort(), [
    "acquireDialog", "depth", "handleKeydown", "isDialogPending", "isOpen",
    "keydownWanted", "open", "releaseDialog", "requestClose", "settleClose",
    "subscribe", "trapTab",
  ]);
  for (const key of Object.keys(engine)) assert.equal(typeof engine[key], "function");
});

test("open — show(depth)→focusInitial 순서, 이중 open 은 스택을 늘리지 않는다", () => {
  const engine = createOverlayEngine();
  const log = [];
  const a = { host: "A", executor: recorder(log, "A") };
  assert.equal(engine.open(a), true);
  assert.deepEqual(log, ["A.show(0)", "A.focusInitial"]);
  assert.equal(engine.open(a), false, "같은 host 이중 open 은 무시(멱등)");
  assert.equal(engine.depth(), 1);
  assert.equal(engine.isOpen("A"), true);

  const b = { host: "B", executor: recorder(log, "B") };
  engine.open(b);
  assert.deepEqual(log.slice(2), ["B.show(1)", "B.focusInitial"], "중첩 층위가 depth 로 내려간다");
  assert.equal(engine.depth(), 2);
});

test("keydownWanted — 첫 open 에 서고 스택이 빌 때 내린다(현 부착 의미 보존)", () => {
  const engine = createOverlayEngine();
  const log = [];
  assert.equal(engine.keydownWanted(), false);
  engine.open({ host: "A", executor: recorder(log, "A") });
  assert.equal(engine.keydownWanted(), true);
  engine.requestClose("A");
  assert.equal(engine.keydownWanted(), true, "퇴장 중에도 스택에 있으므로 유지");
  engine.settleClose("A");
  assert.equal(engine.keydownWanted(), false);
});

test("requestClose — 미등록 ignored / beforeClose false 소비 / 퇴장 중 재입력 소비", () => {
  const engine = createOverlayEngine();
  const log = [];
  assert.equal(engine.requestClose("ghost"), "ignored");

  let allow = false;
  engine.open({ host: "A", executor: recorder(log, "A"), beforeClose: () => allow });
  assert.equal(engine.requestClose("A"), "consumed", "dirty 가드가 닫기 요청을 소비한다");
  assert.equal(log.includes("A.beginClose"), false);

  allow = true;
  assert.equal(engine.requestClose("A"), "closing");
  assert.deepEqual(log.slice(-1), ["A.beginClose"]);
  assert.equal(engine.requestClose("A"), "consumed", "퇴장 중 재입력은 한 번만 정착");
});

test("settleClose — 겹침 정산 1회, 순서는 finishClose→제거→복귀→onClose", () => {
  const engine = createOverlayEngine();
  const log = [];
  engine.open({
    host: "A", executor: recorder(log, "A"),
    onClose: () => log.push("A.onClose"),
  });
  engine.requestClose("A");
  assert.equal(engine.settleClose("A"), true);
  assert.equal(engine.settleClose("A"), false, "전이 종료·안전망 겹침은 1회만 정산");
  assert.deepEqual(log, [
    "A.show(0)", "A.focusInitial", "A.beginClose",
    "A.finishClose", "A.restoreFocus", "A.onClose",
  ]);
  assert.equal(engine.depth(), 0);
});

test("중첩 — 최상위 정산만 복귀를 집행하고, 하위 정산은 초점을 빼앗지 않는다", () => {
  const engine = createOverlayEngine();
  const log = [];
  engine.open({ host: "form", executor: recorder(log, "form") });
  engine.open({ host: "confirm", executor: recorder(log, "confirm") });

  engine.requestClose("form");
  engine.settleClose("form");
  assert.equal(log.includes("form.restoreFocus"), false,
    "하위 모달을 프로그램적으로 닫아도 새 최상위의 초점을 빼앗지 않는다");

  engine.requestClose("confirm");
  engine.settleClose("confirm");
  assert.equal(log.includes("confirm.restoreFocus"), true, "최상위 정산은 복귀를 집행한다");
});

test("직렬화 — acquire 배타·release 짝, 미보유 release 는 throw", () => {
  const engine = createOverlayEngine();
  assert.equal(engine.isDialogPending(), false);
  assert.equal(engine.acquireDialog(), true);
  assert.equal(engine.acquireDialog(), false, "미결 위에 두 번째 다이얼로그를 얹지 않는다");
  assert.equal(engine.isDialogPending(), true);
  engine.releaseDialog();
  assert.equal(engine.isDialogPending(), false);
  assert.throws(() => engine.releaseDialog(), /짝이어야/);
});

test("handleKeydown — 빈 스택 none·IME 통과·퇴장 중 소비·Escape 최상위·Tab 방향", () => {
  const engine = createOverlayEngine();
  const log = [];
  assert.deepEqual(engine.handleKeydown({ key: "Escape" }), { kind: "none" });

  engine.open({ host: "A", executor: recorder(log, "A") });
  engine.open({ host: "B", executor: recorder(log, "B") });

  assert.deepEqual(engine.handleKeydown({ key: "Escape", isComposing: true }), { kind: "none" },
    "IME 조합 중 Escape 는 조합 취소가 먼저다");
  assert.deepEqual(engine.handleKeydown({ key: "Escape", keyCode: 229 }), { kind: "none" });

  assert.deepEqual(engine.handleKeydown({ key: "Escape" }), { kind: "escape", host: "B" },
    "Escape 는 최상위만 겨눈다");
  assert.deepEqual(engine.handleKeydown({ key: "Tab", shiftKey: true }),
    { kind: "trap", host: "B", backward: true });
  assert.deepEqual(engine.handleKeydown({ key: "a" }), { kind: "none" });

  engine.requestClose("B");
  assert.deepEqual(engine.handleKeydown({ key: "Escape" }), { kind: "consume" },
    "퇴장 중 Escape·Tab 은 소비만 하고 다시 닫지 않는다");
  assert.deepEqual(engine.handleKeydown({ key: "Tab" }), { kind: "consume" });
});

test("trapTab 위임 — 등록된 host 의 집행자로 방향이 전달된다", () => {
  const engine = createOverlayEngine();
  const log = [];
  engine.open({ host: "A", executor: recorder(log, "A") });
  engine.trapTab("A", true);
  engine.trapTab("ghost", false);
  assert.deepEqual(log.slice(-1), ["A.trapTab(true)"]);
});

test("구독 — 열기·닫힘 요청·정산이 통지하고, 해제는 등록마다 1회(이중 해제 throw)", () => {
  const engine = createOverlayEngine();
  const log = [];
  let events = 0;
  const unsubscribe = engine.subscribe(() => { events += 1; });
  engine.open({ host: "A", executor: recorder(log, "A") });
  engine.requestClose("A");
  engine.settleClose("A");
  assert.equal(events, 3);
  unsubscribe();
  engine.open({ host: "B", executor: recorder(log, "B") });
  assert.equal(events, 3, "해제 후 통지 0");
  assert.throws(() => unsubscribe(), /정확히 1회/);
});
