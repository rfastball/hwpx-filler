/* R4-03 — 실행 정체 reducer(`frontend/src/screens/job_run_state.ts`)의 불변식.
 *
 * 이 파일이 재는 것은 **귀속**이다. 도착한 응답이 지금 기다리는 그 실행의 것인가.
 * legacy `job.js` 는 그 질문 자체가 없었다(`generating` 불리언 + `RESULT` 변수). 세 창이
 * 실제로 열려 있었고, 셋 다 관측 가능한 자리가 아니라 단위로 잴 수 없었다:
 *
 *  1. 성공만 반환 전 full push 를 낸다 — 덮어쓰기·거절 갈래는 push 가 없다.
 *  2. 덮어쓰기 확인은 호출을 둘로 만든다 — 둘을 다른 실행으로 세면 첫 응답이 둘째를 덮는다.
 *  3. 진행 델타는 direct 와 다른 채널이라 순서 보장이 없다 — 완료를 진행 중으로 되돌린다.
 *
 * 패킷 rev2 §3.1(규칙 7) · §3.2(우선순위 9) · §4(수명) · rev7 §3(토큰)이 목차다.
 * 음성 fixture 는 패킷 §9 의 열두 갈래를 그대로 세운다.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  acceptDirect, acceptFull, acceptProgress, beginRun, bumpEpoch, closeResult,
  createTokenFactory, disposeBySession, endRun, initialRunState, isForeignResult,
  sessionKeyOf,
} from "../../frontend/src/screens/job_run_state.ts";

/** 최소 세션 스냅샷 — 지문 6성분만 실은 것. 값의 출처는 전부 Python 이다. */
function snap(overrides = {}) {
  return {
    has_job: true, job_name: "공고서", data_mount: "m1", out_dir: "C:\\out",
    selection_key: "s1", rules_key: "r1", last_run_job: "공고서",
    ...overrides,
  };
}

/** full 하나를 들인 상태 — 이후 전이의 공통 출발점. */
function seeded(overrides = {}) {
  return acceptFull(initialRunState(), snap(overrides));
}

/** 한 번의 완주 실행을 태워 결과가 선 상태를 만든다. */
function withResult(state, token = "t1", result = { ok: true, status: "ok", title: "완료" }) {
  const running = beginRun(state, token);
  return acceptDirect(running, { ...result, run_token: token });
}

/* ================= 토큰 발급 ================= */

test("새 의도마다 충돌 없는 토큰이 난다", () => {
  const next = createTokenFactory();
  const tokens = new Set(Array.from({ length: 200 }, () => next()));
  assert.equal(tokens.size, 200);
  assert.ok([...tokens].every((t) => typeof t === "string" && t.length > 0));
});

/* ================= 규칙 1·2 — op 정체와 덮어쓰기 왕복 ================= */

test("규칙 2 — 덮어쓰기 확인 재호출은 같은 op 다(토큰이 유지되고 running 이 안 끝난다)", () => {
  const state = beginRun(seeded(), "t1");
  const asked = acceptDirect(state, { ok: false, needs_overwrite: true, total: 2, run_token: "t1" });
  assert.equal(asked.running, true, "확인 대기 중에도 실행은 살아 있다");
  assert.equal(asked.active.runToken, "t1");
  assert.equal(asked.result, null, "확인 요구는 결과가 아니다");

  const committed = acceptDirect(asked, { ok: true, status: "ok", title: "완료", run_token: "t1" });
  assert.equal(committed.running, false);
  assert.equal(committed.result.title, "완료");
});

test("규칙 3 — 확인 취소는 op 만 끝내고 직전 결과를 지우지 않는다", () => {
  const done = withResult(seeded(), "t1", { ok: true, status: "ok", title: "1차 완료" });
  const second = beginRun(done, "t2");
  const cancelled = endRun(second);
  assert.equal(cancelled.running, false);
  assert.equal(cancelled.active, null);
  assert.equal(cancelled.result.title, "1차 완료", "사용자가 치우라고 한 적이 없다");
});

/* ================= 규칙 5·6 — 늦은 응답 ================= */

test("규칙 5·6 — 새 op 뒤 도착한 옛 direct 는 결과를 바꾸지 않고 진단으로 남는다", () => {
  const first = beginRun(seeded(), "t1");
  const second = beginRun(first, "t2");
  const late = acceptDirect(second, { ok: true, status: "ok", title: "옛 실행", run_token: "t1" });
  assert.equal(late.result, null, "옛 응답이 결과를 만들지 않는다");
  assert.equal(late.running, true, "현재 op 는 계속 돈다");
  assert.equal(late.discarded.length, 1);
  assert.equal(late.discarded[0].token, "t1");
  assert.match(late.discarded[0].reason, /다른 실행/);
});

test("세션이 바뀐 뒤 오는 direct 는 무시된다", () => {
  const running = beginRun(seeded(), "t1");
  const moved = acceptFull(running, snap({ data_mount: "m2" }));
  const late = acceptDirect(moved, { ok: true, status: "ok", title: "남의 데이터", run_token: "t1" });
  assert.equal(late.result, null);
  assert.match(late.discarded.at(-1).reason, /세션/);
});

test("화면 세대가 오르면 앞선 실행의 응답이 한 번에 남이 된다", () => {
  const running = beginRun(seeded(), "t1");
  const reentered = bumpEpoch(running);
  const late = acceptDirect(reentered, { ok: true, status: "ok", run_token: "t1" });
  assert.equal(late.result, null);
  assert.match(late.discarded.at(-1).reason, /활성 실행|화면 세대/);
});

test("빈 토큰·토큰 없는 direct 는 반영되지 않는다", () => {
  const running = beginRun(seeded(), "t1");
  for (const bad of [{ ok: true }, { ok: true, run_token: "" }]) {
    const out = acceptDirect(running, bad);
    assert.equal(out.result, null);
    assert.equal(out.discarded.length, 1);
  }
});

/* ================= §3.2 — full / progress / direct 우선순위 ================= */

test("full push 는 결과를 만들지도 덮지도 않는다", () => {
  const done = withResult(seeded(), "t1", { ok: true, status: "ok", title: "완료" });
  const pushed = acceptFull(done, snap());
  assert.equal(pushed.result.title, "완료");
  assert.equal(pushed.lastFull.job_name, "공고서");

  const bare = acceptFull(initialRunState(), snap());
  assert.equal(bare.result, null, "push 만으로 결과가 생기지 않는다");
});

test("진행 델타는 lastFull 을 덮지 않는다", () => {
  const running = beginRun(seeded(), "t1");
  const ticked = acceptProgress(running, { done: 1, total: 3, run_token: "t1" });
  assert.equal(ticked.lastFull.job_name, "공고서");
  assert.deepEqual(ticked.progress, { done: 1, total: 3, run_token: "t1" });
});

test("성공 full push 가 direct 반환보다 먼저 와도 direct 가 뒤에 정상 착지한다", () => {
  const running = beginRun(seeded(), "t1");
  // Python `generate` 는 성공 시 **반환 전에** push 한다 — 그 순서를 그대로 태운다.
  const pushedFirst = acceptFull(running, snap({ last_run_job: "공고서" }));
  const landed = acceptDirect(pushedFirst, { ok: true, status: "ok", title: "완료", run_token: "t1" });
  assert.equal(landed.result.title, "완료");
  assert.equal(landed.running, false);
});

test("no-push 갈래(덮어쓰기·거절)도 direct 만으로 UI 가 선다", () => {
  const running = beginRun(seeded(), "t1");
  const rejected = acceptDirect(running, {
    ok: false, rejected: true, level: "warn", title: "생성하지 않았습니다", run_token: "t1",
  });
  assert.equal(rejected.result.rejected, true, "push 없이도 결과 자리가 선다");
  assert.equal(rejected.running, false);
});

test("terminal barrier — 완료 뒤 같은 토큰의 늦은 진행은 완료를 되돌리지 않는다", () => {
  const done = withResult(seeded(), "t1");
  const late = acceptProgress(done, { done: 2, total: 3, run_token: "t1" });
  assert.equal(late.running, false);
  assert.equal(late.progress, null, "완료 결과 옆에 진행바가 되살아나지 않는다");
  assert.match(late.discarded.at(-1).reason, /종료된/);
});

test("옛 토큰의 진행 델타는 새 실행의 진행을 뒤로 돌리지 않는다", () => {
  const first = beginRun(seeded(), "t1");
  const second = beginRun(first, "t2");
  const ticked = acceptProgress(second, { done: 5, total: 5, run_token: "t2" });
  const stale = acceptProgress(ticked, { done: 1, total: 9, run_token: "t1" });
  assert.deepEqual(stale.progress, { done: 5, total: 5, run_token: "t2" });
  assert.match(stale.discarded.at(-1).reason, /다른 실행/);
});

/* ================= §4 — 결과 수명 ================= */

test("작업 전환·데이터 교체는 결과를 초기화하고 퇴장 주체를 낸다", () => {
  const done = withResult(seeded(), "t1");
  for (const [label, next] of [
    ["작업 전환", snap({ job_name: "다른작업", last_run_job: "공고서" })],
    ["데이터 교체", snap({ data_mount: "m2" })],
  ]) {
    const out = acceptFull(done, next);
    assert.equal(out.result, null, `${label} 은 결과를 초기화한다`);
    assert.equal(out.resultFingerprint, null);
  }

  const disposal = disposeBySession(done, sessionKeyOf(snap()), sessionKeyOf(snap({ data_mount: "m2" })));
  assert.equal(disposal.kind, "reset");
  assert.equal(disposal.exitOwner, "공고서", "퇴장 한 줄이 주체를 안다");
});

test("개명은 전환이 아니다 — 주체가 이름을 추종하면 결과가 산다", () => {
  const done = withResult(seeded(), "t1");
  // 이름만 바뀌고 `last_run_job` 이 새 이름을 따라왔다 = 같은 작업이다.
  const renamed = acceptFull(done, snap({ job_name: "공고서(수정)", last_run_job: "공고서(수정)" }));
  assert.notEqual(renamed.result, null, "개명은 파기가 아니다");
  assert.equal(renamed.result.stale, true, "다만 강등은 된다");
});

test("선택·규칙·저장 폴더 변경은 결과를 남기고 강등만 한다", () => {
  const done = withResult(seeded(), "t1", {
    ok: true, status: "ok", title: "완료", failures: [{ index: 1 }], failed_selectable: 1,
  });
  for (const [label, next] of [
    ["선택", snap({ selection_key: "s2" })],
    ["규칙", snap({ rules_key: "r2" })],
    ["저장 폴더", snap({ out_dir: "D:\\other" })],
  ]) {
    const out = acceptFull(done, next);
    assert.notEqual(out.result, null, `${label} 변경은 결과를 지우지 않는다`);
    assert.equal(out.result.stale, true, `${label} 변경은 강등한다`);
    assert.deepEqual(out.result.failures, [{ index: 1 }], "증거 행은 그대로 남는다");
    assert.equal(out.result.failed_selectable, 1);
  }
});

test("작업·데이터 불변 재푸시(탭 복귀)는 결과를 유지한다", () => {
  const done = withResult(seeded(), "t1");
  const back = acceptFull(done, snap());
  assert.equal(back.result.title, "완료");
  assert.notEqual(back.result.stale, true, "변한 게 없으면 강등도 아니다");
});

test("실행 중 도착한 full push 는 자기 결과를 강등시키지 않는다", () => {
  // 런 자신이 만든 세션 변화(`last_run_job` 스탬프)로 자기 결과를 강등하는 자기모순 차단.
  const done = withResult(seeded({ last_run_job: "" }), "t1");
  const running = beginRun(done, "t2");
  const selfPush = acceptFull(running, snap({ last_run_job: "공고서", selection_key: "s9" }));
  assert.notEqual(selfPush.result, null);
  assert.notEqual(selfPush.result.stale, true);
});

test("명시 파기는 결과·진행을 비운다", () => {
  const done = withResult(seeded(), "t1");
  const closed = closeResult(done);
  assert.equal(closed.result, null);
  assert.equal(closed.progress, null);
  assert.equal(closed.resultFingerprint, null);
});

test("남의 작업 결과는 증거를 남기되 남으로 판정된다", () => {
  const mine = withResult(seeded(), "t1");
  assert.equal(isForeignResult(mine), false);

  const foreign = acceptFull(mine, snap({ job_name: "다른작업", last_run_job: "다른작업" }));
  const stillThere = withResult(foreign, "t2");
  const moved = { ...stillThere, lastFull: snap({ job_name: "제3작업", last_run_job: "다른작업" }) };
  assert.equal(isForeignResult(moved), true);
  assert.notEqual(moved.result, null, "행동만 걷고 증거는 남긴다");
});

/* ================= 판정 비재조립 ================= */

test("Python 이 낸 판정 필드를 reducer 가 다시 만들지 않는다", () => {
  const payload = {
    ok: false, status: "failed", level: "danger", title: "T", summary: "S",
    failures: [{ index: 3, reason: "R" }], failed_selectable: 7,
    fill_notes: ["n"], revisions: { template: 2, binding: 5 }, run_token: "t1",
  };
  const out = acceptDirect(beginRun(seeded(), "t1"), payload);
  for (const key of Object.keys(payload)) {
    assert.deepEqual(out.result[key], payload[key], `${key} 는 그대로 통과한다`);
  }
});
