/* 등록 데이터 풀의 **동사 한 벌**(`createPoolVerbs`) — 두 호스트가 같은 보호를 받는가.
 *
 * 처음 재던 것은 연타 차단 하나였다: 다이얼로그는 마운트 중임을 `busyReason` 으로
 * 말하지만 그 술어는 「사용」 하나만 덮는다 — 삭제·보관·중복 정리의 두 번째 클릭이 그대로
 * 나가면 확인 모달이 두 벌 서거나 같은 지문으로 두 번 확정된다. 표지를 몸통이 들어야 두
 * 호스트가 같은 보호를 받는다(호스트별 재구현 0).
 *
 * 고르기 열 공용 ⑤ 리뷰에서 **분기표·검토 왕복·통지 동사·세션 행 이어붙이기**가 같은 이유로
 * 여기 모였다(두 호스트가 글자 하나 다르지 않은 사본을 각자 들고 있었다). 그 넷도 이 파일이
 * 진다 — 호스트 파일은 이제 포트만 준다.
 *
 * (같은 그림을 그리는가는 `pool_column.test.js` 가 진다 — 두 관심사가 갈린 것이 이 파일이
 * `pool_list.ts` 에서 떨어져 나온 이유다.) */
import test from "node:test";
import assert from "node:assert/strict";

import {
  createPoolVerbs, mergeSessionRow, poolHeadSub,
} from "../../frontend/src/screens/pool_verbs.ts";

/** 몸통이 요구하는 포트 전수를 채운 최소 배선 — 시험이 재는 축만 `overrides` 로 갈아끼운다.
 *  전수를 채우는 이유는 계약과 같다: 포트가 늘면 여기가 먼저 부러져야 한다. */
function wire(overrides = {}) {
  const trace = { sent: [], errors: [], used: [], relinked: [], revealed: [], detailed: [] };
  const wired = createPoolVerbs({
    dispatch: async (screen, action, payload) => {
      trace.sent.push([screen, action, payload]);
      return {};
    },
    modal: { confirm: async () => false },
    onError: (message) => trace.errors.push(message),
    onUse: (row) => { trace.used.push(row.key); },
    openRelink: (row) => { trace.relinked.push(row); },
    poolSnapshot: () => null,
    reveal: (path) => { trace.revealed.push(path); },
    openDetail: (key, trigger) => { trace.detailed.push([key, trigger]); },
    ...overrides,
  });
  return { trace, ...wired };
}

test("동사 연타는 한 번만 발신된다 — in-flight 표지는 몸통이 든다", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const sent = [];
  const errors = [];
  const verbs = wire({
    dispatch: async (screen, action, payload) => {
      sent.push([screen, action, payload]);
      await gate;
      return {};
    },
    onError: (message) => errors.push(message),
  });

  /* 같은 틱의 두 번째 클릭 — 표지가 첫 await 앞에서 서므로 여기로 새지 않는다. */
  const first = verbs.poolAction("archive", { key: "k1" });
  const second = verbs.poolAction("archive", { key: "k1" });
  await second;
  assert.equal(sent.length, 1, "연타가 두 번 발신됐습니다");
  assert.equal(errors.length, 1, "두 번째 클릭이 조용히 삼켜졌습니다");
  assert.ok(errors[0].includes("아직 끝나지 않았습니다"), errors[0]);

  release();
  await first;
  /* 끝나면 다시 받는다 — 표지가 걸린 채 남으면 화면이 영영 잠긴다. */
  await verbs.poolAction("archive", { key: "k1" });
  assert.equal(sent.length, 2, "왕복이 끝났는데도 다음 동사를 거절했습니다");
});

test("중복 정리도 같은 표지를 공유한다 — 두 벌 확인 모달을 세우지 않는다", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const sent = [];
  const errors = [];
  const verbs = wire({
    dispatch: async (screen, action) => { sent.push(action); await gate; return {}; },
    onError: (message) => errors.push(message),
  });

  const first = verbs.resolveDuplicate("k1");
  await verbs.poolAction("delete", { key: "k2" });   // 다른 동사도 같은 표지를 본다
  assert.deepEqual(sent, ["resolve_duplicate"]);
  assert.equal(errors.length, 1);
  release();
  await first;
});

test("호스트 사유가 있으면 그것이 먼저다 — 몸통 문안이 덮지 않는다", async () => {
  const errors = [];
  const verbs = wire({
    onError: (message) => errors.push(message),
    busyReason: () => "불러오는 중입니다. 끝날 때까지 닫을 수 없습니다.",
  });
  await verbs.poolAction("archive", { key: "k1" });
  assert.deepEqual(errors, ["불러오는 중입니다. 끝날 때까지 닫을 수 없습니다."]);
});

/* ── 검토 왕복 — 프리필 재료의 출처이자 키 대조의 자리 ─────────────────────────── */

test("검토 왕복은 자기가 세운 상세만 돌려준다 — 남의 항목은 사유를 남기고 null", async () => {
  /* 왕복 사이에 다른 push 가 끼면 스냅샷의 상세가 남의 것일 수 있다. 그 값을 프리필로
     쓰면 사람이 겨눈 적 없는 등록을 덮어쓴다 — 키 대조가 그 자리를 막는다. */
  const mine = wire({ poolSnapshot: () => ({ detail: { key: "d1", name: "7월목록" } }) });
  assert.deepEqual(await mine.review("d1"), { key: "d1", name: "7월목록" });
  assert.deepEqual(mine.trace.sent, [["pool", "review", { key: "d1" }]]);
  assert.deepEqual(mine.trace.errors, []);

  const stale = wire({ poolSnapshot: () => ({ detail: { key: "d9" } }) });
  assert.equal(await stale.review("d1"), null);
  assert.equal(stale.trace.errors.length, 1, "남의 상세를 조용히 돌려줬습니다");
  assert.ok(stale.trace.errors[0].includes("다시 고르세요"), stale.trace.errors[0]);

  const gone = wire({ poolSnapshot: () => ({}) });
  assert.equal(await gone.review("d1"), null);
  assert.equal(gone.trace.errors.length, 1, "상세 부재가 조용히 삼켜졌습니다");
});

/* ── 분기표 — 두 호스트가 지나는 **닫힌 집합** 하나 ──────────────────────────── */

test("행 동사는 포트로 갈린다 — 경로 문·상세 시트·상태 동사", async () => {
  const h = wire();
  const trigger = { id: "trigger" };
  await h.runVerb("reveal", { key: "d1", path: "C:/x.xlsx" }, trigger);
  assert.deepEqual(h.trace.revealed, ["C:/x.xlsx"]);

  await h.runVerb("detail", { key: "d1" }, trigger);
  assert.deepEqual(h.trace.detailed, [["d1", trigger]]);

  /* 상태 동사는 `act:` 접두어를 벗고 그대로 `pool` 채널로 나간다(링1 이 낸 키 그대로). */
  await h.runVerb("act:archive", { key: "d1" }, trigger);
  assert.deepEqual(h.trace.sent, [["pool", "archive", { key: "d1" }]]);
});

test("「다시 연결」의 프리필은 검토 왕복이 낸 상세다 — 열 행이 아니다", async () => {
  /* 열 행은 `path`·`sheet`·`note` 를 들지 않는다(계약이 좁다). 행을 그대로 넘기면 폼이
     빈 칸으로 서고, 그 빈 칸으로 확정하면 등록이 조용히 지워진다. */
  const detail = { key: "d1", name: "7월목록", path: "C:/x.xlsx", sheet: "물품", note: "" };
  const h = wire({ poolSnapshot: () => ({ detail }) });
  await h.runVerb("act:relink", { key: "d1", name: "7월목록" }, null);
  assert.deepEqual(h.trace.relinked, [detail]);
});

test("모르는 동사는 던진다 — 착지가 호스트마다 갈리므로 삼키지 않는다", async () => {
  const h = wire();
  await assert.rejects(
    () => h.runVerb("없는동사", { key: "d1" }, null),
    /알 수 없는 데이터 동사입니다: 없는동사/);
  assert.deepEqual(h.trace.sent, [], "모르는 동사가 발신됐습니다");
});

/* ── 존 통지 동사 ────────────────────────────────────────────────────────── */

test("통지 동사는 `pool/resolve_duplicate` 로 나가고 미지 키는 같은 채널로 시끄럽다", async () => {
  const h = wire();
  h.noticeAction("resolve_duplicate", { keep: "d1" });
  await new Promise((resolve) => { setTimeout(resolve, 0); });
  assert.deepEqual(h.trace.sent, [["pool", "resolve_duplicate", { keep: "d1" }]]);

  h.noticeAction("없는통지동사", {});
  assert.equal(h.trace.errors.length, 1, "미지 통지 키가 조용히 떨어졌습니다");
  assert.ok(h.trace.errors[0].includes("알 수 없는 통지 동사"), h.trace.errors[0]);
});

/* ── 세션 행 이어붙이기 — 순수 함수(판정 0) ─────────────────────────────────── */

test("세션 행은 목록 맨 위에 선다 — 열의 나머지 축은 그대로 통과한다", () => {
  const column = { rows: [{ key: "d1" }], notices: [{ text: "x" }], count_label: "1개" };
  const merged = mergeSessionRow(column, { key: "session" });
  assert.deepEqual(merged.rows.map((row) => row.key), ["session", "d1"]);
  assert.deepEqual(merged.notices, [{ text: "x" }]);
  assert.equal(merged.count_label, "1개", "열의 개수 문안은 Python 것 그대로여야 합니다");
  /* 원본을 건드리지 않는다 — 같은 스냅샷을 두 번 그리면 세션 행이 두 번 쌓인다. */
  assert.deepEqual(column.rows.map((row) => row.key), ["d1"]);
});

test("열이 아직 안 왔어도 세션 행은 목록에 선다 — 아는 사실을 감추지 않는다", () => {
  const merged = mergeSessionRow(null, { key: "session" });
  assert.deepEqual(merged.rows.map((row) => row.key), ["session"]);
  assert.deepEqual(merged.notices, []);
  assert.equal(mergeSessionRow(null, null), null);
  assert.deepEqual(mergeSessionRow({ rows: [{ key: "d1" }] }, null).rows.map((r) => r.key), ["d1"]);
});

test("열 머리 부제는 「읽는 중」과 「0개」를 구별한다", () => {
  assert.equal(poolHeadSub(null), "읽는 중…");
  assert.equal(poolHeadSub({ count_label: "" }), "");
  assert.equal(poolHeadSub({ count_label: "2개" }), "2개");
});
