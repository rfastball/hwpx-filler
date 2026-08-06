/* R4-03 — 저수준 `RelinkPort` React 구현(`frontend/src/screens/job_relink.ts`)의 계약.
 *
 * 이 파일이 재는 것은 **결과 계약 하나**와 **순서**다. rev7 §2 가 고정한 것:
 *
 *  - 결과는 `Promise<boolean>` 만이다. descriptor·`ERROR:`·null 은 SheetPicker 계약이고
 *    여기 적용하지 않는다 — 두 계약이 섞이면 호출자가 어느 쪽으로 읽을지 모른다.
 *  - 취소·거절·예외는 전부 false, 커밋 성사만 true.
 *  - `notify` 는 선택 인자다(없어도 동작한다). 실패의 loud alert 는 서비스 자기 채널이라
 *    호출자가 콜백을 안 줘도 조용해지지 않는다.
 *  - pick → needs-confirm → confirm=true 커밋 순서.
 *
 * 음성 fixture(rev4): confirm 생략, cancel 뒤 커밋, false 뒤 후속, 미등재 소비자.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createJobRelink } from "../../frontend/src/screens/job_relink.ts";

/** 호스트 왕복 대역 — 실제 client 와 같은 `HostResult` 모양을 낸다. */
function harness(script = {}) {
  const calls = [];
  const alarms = [];
  const client = {
    invoke(method, ...args) {
      calls.push({ method, args });
      if (method === "pick_template_path") {
        if (script.pickThrows) return Promise.reject(new Error("피커 폭발"));
        // `??` 로 기본값을 주면 **명시한 `undefined`** 가 기본값으로 되살아나 취소 갈래를
        // 못 잰다(대역이 재려는 것을 스스로 지운다). 지정 여부는 키 존재로 가른다.
        const picked = "picked" in script ? script.picked : "C:\\t\\new.hwpx";
        return Promise.resolve({ ok: true, value: picked });
      }
      throw new Error(`예상 밖 invoke: ${method}`);
    },
    dispatch(screen, action, payload) {
      calls.push({ screen, action, payload });
      const queue = script.dispatch ?? [];
      const next = queue.shift();
      if (next === undefined) throw new Error("dispatch 대본이 비었다");
      if (next instanceof Error) return Promise.reject(next);
      return Promise.resolve({ ok: true, value: next });
    },
  };
  const modal = {
    confirm(spec) {
      calls.push({ confirm: spec });
      return Promise.resolve(script.confirmAnswer ?? true);
    },
  };
  const port = createJobRelink({ client, modal, alarm: (m) => alarms.push(m) });
  return { port, calls, alarms };
}

const notes = () => {
  const seen = [];
  const notify = (message, kind) => seen.push({ message, kind });
  return { seen, notify };
};

/* ================= 성사 경로 ================= */

test("확인 없는 커밋 — pick → dispatch → true", async () => {
  const { port, calls } = harness({ dispatch: [{ ok: true, restated: "'A' 를 다시 연결했습니다." }] });
  const { seen, notify } = notes();
  assert.equal(await port.relinkTemplate("job", "A", notify), true);
  assert.equal(calls[0].method, "pick_template_path");
  assert.deepEqual(calls[1].payload, { name: "A", path: "C:\\t\\new.hwpx" });
  assert.deepEqual(seen, [{ message: "'A' 를 다시 연결했습니다.", kind: "ok" }]);
});

test("needs-confirm 커밋 — 재진술 확인 뒤에만 confirm=true 가 나간다", async () => {
  const { port, calls } = harness({
    dispatch: [
      { needs_confirm: true, confirm_text: "필드 3개가 사라집니다." },
      { ok: true, restated: "다시 연결했습니다." },
    ],
  });
  assert.equal(await port.relinkTemplate("job", "A"), true);
  const dispatches = calls.filter((c) => c.action === "relink_template");
  assert.equal(dispatches.length, 2);
  assert.equal(dispatches[0].payload.confirm, undefined, "1차는 확인 없이 묻는다");
  assert.equal(dispatches[1].payload.confirm, true, "2차만 커밋이다");
  const confirmed = calls.find((c) => c.confirm);
  assert.match(confirmed.confirm.body, /필드 3개가 사라집니다/, "백엔드 재진술을 그대로 보인다");
  // 순서: 피커 → 1차 → 확인 → 2차.
  assert.deepEqual(
    calls.map((c) => c.method ?? (c.confirm ? "confirm" : c.action)),
    ["pick_template_path", "relink_template", "confirm", "relink_template"],
  );
});

/* ================= false 갈래 넷 ================= */

test("피커 취소는 아무것도 부르지 않고 false", async () => {
  for (const picked of [null, "", undefined]) {
    const { port, calls, alarms } = harness({ picked, dispatch: [] });
    const { seen, notify } = notes();
    assert.equal(await port.relinkTemplate("job", "A", notify), false);
    assert.equal(calls.filter((c) => c.action).length, 0, "백엔드에 아무것도 안 나간다");
    assert.deepEqual(seen, [], "취소는 조용하다(사용자가 방금 취소했다)");
    assert.deepEqual(alarms, []);
  }
});

test("재진술 확인 취소는 커밋을 내지 않고 false", async () => {
  const { port, calls } = harness({
    dispatch: [{ needs_confirm: true, confirm_text: "위험" }],
    confirmAnswer: false,
  });
  const { seen, notify } = notes();
  assert.equal(await port.relinkTemplate("job", "A", notify), false);
  assert.equal(calls.filter((c) => c.action === "relink_template").length, 1, "커밋은 안 나간다");
  assert.deepEqual(seen, [{ message: "다시 연결을 취소했습니다.", kind: "cancel" }]);
});

test("컨트롤러 거절은 loud alert + error 통지 + false", async () => {
  const { port, alarms } = harness({ dispatch: [{ ok: false, error: "템플릿을 읽을 수 없습니다." }] });
  const { seen, notify } = notes();
  assert.equal(await port.relinkTemplate("library", "A", notify), false);
  assert.deepEqual(alarms, ["템플릿을 읽을 수 없습니다."], "거절은 시끄럽다");
  assert.deepEqual(seen, [{ message: "다시 연결 실패: 템플릿을 읽을 수 없습니다.", kind: "error" }]);
});

test("예외는 삼키지 않고 false — 성사 여부를 모르는 채 true 를 내지 않는다", async () => {
  const { port, alarms } = harness({ pickThrows: true, dispatch: [] });
  assert.equal(await port.relinkTemplate("job", "A"), false);
  assert.equal(alarms.length, 1);
  assert.match(alarms[0], /피커 폭발/);
});

/* ================= notify 는 선택 인자 ================= */

test("notify 없이도 전 갈래가 돈다 — 실패의 loud 는 서비스 자기 채널이라 살아 있다", async () => {
  const ok = harness({ dispatch: [{ ok: true, restated: "R" }] });
  assert.equal(await ok.port.relinkTemplate("job", "A"), true);

  const bad = harness({ dispatch: [{ ok: false, error: "E" }] });
  assert.equal(await bad.port.relinkTemplate("job", "A"), false);
  assert.deepEqual(bad.alarms, ["E"], "콜백을 안 줬다고 실패가 조용해지지 않는다");
});

/* ================= 결과 계약 폐색 ================= */

test("결과는 boolean 만이다 — SheetPicker 3형(descriptor·ERROR:·null)이 새지 않는다", async () => {
  const shapes = [
    { ok: true, restated: "R" },
    { ok: false, error: "E" },
    { ok: true, descriptor: { path: "p" } },
    {},
  ];
  for (const shape of shapes) {
    const { port } = harness({ dispatch: [shape] });
    const out = await port.relinkTemplate("job", "A");
    assert.equal(typeof out, "boolean", `${JSON.stringify(shape)} → boolean`);
  }
});

test("미등재 소비자 화면은 시끄럽게 거절한다", async () => {
  const { port, alarms } = harness({ dispatch: [] });
  assert.equal(await port.relinkTemplate("editor", "A"), false);
  assert.match(alarms[0], /등재되지 않은 소비자 화면/);
});
