/* 등록 데이터 풀의 **관리 동사 한 벌**(`createPoolVerbs`) — 두 호스트가 같은 보호를 받는가.
 *
 * 이 파일이 재는 것은 연타 차단 하나다: 다이얼로그는 마운트 중임을 `busyReason` 으로
 * 말하지만 그 술어는 「사용」 하나만 덮는다 — 삭제·보관·중복 정리의 두 번째 클릭이 그대로
 * 나가면 확인 모달이 두 벌 서거나 같은 지문으로 두 번 확정된다. 표지를 몸통이 들어야 두
 * 호스트가 같은 보호를 받는다(호스트별 재구현 0).
 *
 * (같은 그림을 그리는가는 `pool_column.test.js` 가 진다 — 두 관심사가 갈린 것이 이 파일이
 * `pool_list.ts` 에서 떨어져 나온 이유다.) */
import test from "node:test";
import assert from "node:assert/strict";

import { createPoolVerbs } from "../../frontend/src/screens/pool_verbs.ts";

test("동사 연타는 한 번만 발신된다 — in-flight 표지는 몸통이 든다", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const sent = [];
  const errors = [];
  const verbs = createPoolVerbs({
    dispatch: async (screen, action, payload) => {
      sent.push([screen, action, payload]);
      await gate;
      return {};
    },
    modal: { confirm: async () => false },
    onError: (message) => errors.push(message),
    onUse: () => {},
    openRelink: () => {},
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
  const verbs = createPoolVerbs({
    dispatch: async (screen, action) => { sent.push(action); await gate; return {}; },
    modal: { confirm: async () => false },
    onError: (message) => errors.push(message),
    onUse: () => {},
    openRelink: () => {},
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
  const verbs = createPoolVerbs({
    dispatch: async () => ({}),
    modal: { confirm: async () => false },
    onError: (message) => errors.push(message),
    onUse: () => {},
    openRelink: () => {},
    busyReason: () => "불러오는 중입니다. 끝날 때까지 닫을 수 없습니다.",
  });
  await verbs.poolAction("archive", { key: "k1" });
  assert.deepEqual(errors, ["불러오는 중입니다. 끝날 때까지 닫을 수 없습니다."]);
});
