/* 스냅샷 store 계약 (R2-03 · #407).

   `state/store.ts` 는 React 도 DOM 도 모르는 순수 모듈이다 — 여기서 직접 만들어 계약
   전수를 잰다: 도착 순 보관·참조 안정·해제 가능한 구독·이중 해제 throw·리스너 격리·
   당김 revision 가드·계약 유도 채널. React 결합은 화면 runtime model의 안정된 결속 쌍
   (`subscribe/getSnapshot`)까지를 여기서 재고, 실 React 렌더 루프 위의 실물 증거는
   `tests/test_react_store_live.py` 의 마커 되읽기가 진다(R2-01 검증 분업 선례).

   `.ts` 를 확장자 그대로 싣는 것 자체가 계약이다 — Node 24 type stripping 이 제품
   파일을 무변환으로 실어야 node 게이트와 Vite 빌드가 같은 파일을 본다. */
import test from "node:test";
import assert from "node:assert/strict";

import {
  SNAPSHOT_CHANNELS,
  createSnapshotStore,
} from "../../frontend/src/state/store.ts";
import { createScreenRuntime } from "../../frontend/src/screens/runtime.ts";
import { SCREEN_ACTIONS } from "../../frontend/src/contract/contract.gen.ts";

function storeWith(alarms = []) {
  return createSnapshotStore({ alarm: (message) => alarms.push(message) });
}

test("채널 정의역은 생성 계약의 화면 유니온에서 유도된다 — 손 목록이 아니다", () => {
  assert.deepEqual([...SNAPSHOT_CHANNELS], Object.keys(SCREEN_ACTIONS),
    "store 채널이 contract.gen.ts 화면 집합과 갈렸습니다 — 어느 쪽이 손 목록이 됐습니다.");
  const store = storeWith();
  assert.equal(store.channels, SNAPSHOT_CHANNELS);
});

test("ingest 는 도착 순 last-delivery 이고 get 은 참조 그대로다", () => {
  const store = storeWith();
  const first = { rows: 1 };
  const second = { rows: 2 };

  assert.equal(store.get("job"), null, "도착 전 채널은 null 이어야 합니다.");
  assert.equal(store.revision("job"), 0);

  store.ingest("job", first);
  assert.equal(store.get("job"), first, "저장이 사본을 만들었습니다 — getSnapshot 참조 안정이 깨집니다.");
  assert.equal(store.revision("job"), 1);

  store.ingest("job", second);
  assert.equal(store.get("job"), second);
  assert.equal(store.revision("job"), 2);
  //: 채널은 서로 독립이다.
  assert.equal(store.get("library"), null);
  assert.equal(store.revision("library"), 0);
});

test("부분 스냅샷(progress 델타)을 병합하지 않는다 — 전송-충실이 계약이다", () => {
  const store = storeWith();
  const full = { rows: [1, 2, 3], gate: { enabled: true } };
  const delta = { progress: { done: 1, total: 3 } };

  store.ingest("job", full);
  store.ingest("job", delta);

  //: 병합이 있었다면 rows 가 살아 있다 — 그 「친절」이 곧 두 번째 판정자다(패킷 §6).
  assert.equal(store.get("job"), delta,
    "store 가 부분 스냅샷을 병합했습니다 — 값 해석은 소비 화면의 도메인입니다.");
});

test("구독은 등록 수만큼이고 통지는 등록마다 1회다", () => {
  const store = storeWith();
  let calls = 0;
  const listener = () => { calls += 1; };

  const un1 = store.subscribe("job", listener);
  const un2 = store.subscribe("job", listener);
  assert.equal(store.listenerCount("job"), 2,
    "같은 함수의 두 번째 구독이 접혔습니다 — 등록마다 자기 해제가 서야 합니다(Strict Mode 형상).");

  store.ingest("job", { rows: 1 });
  assert.equal(calls, 2);

  un1();
  store.ingest("job", { rows: 2 });
  assert.equal(calls, 3);
  assert.equal(store.listenerCount("job"), 1);
  un2();
  assert.equal(store.listenerCount("job"), 0);
});

test("해제 뒤 listener 0·통지 0, 재구독은 정확히 하나로 되살아난다(remount 형상)", () => {
  const store = storeWith();
  let calls = 0;
  const unsubscribe = store.subscribe("editor", () => { calls += 1; });

  unsubscribe();
  assert.equal(store.listenerCount("editor"), 0, "unmount 뒤 listener 가 남았습니다 — #407 불변식 위반.");
  store.ingest("editor", { a: 1 });
  assert.equal(calls, 0, "해제된 구독이 통지를 받았습니다.");

  //: 재마운트 — 새 등록 하나가 서고 통지도 하나다.
  store.subscribe("editor", () => { calls += 1; });
  store.ingest("editor", { a: 2 });
  assert.equal(calls, 1);
  assert.equal(store.listenerCount("editor"), 1);
});

test("이중 해제는 throw 다 — 침묵 무동작이 아니다", () => {
  const store = storeWith();
  const unsubscribe = store.subscribe("job", () => {});
  unsubscribe();

  assert.throws(() => unsubscribe(), /정확히 1회/,
    "이중 해제가 조용히 지나갔습니다 — root.ts 이중 정산과 같은 엄격도여야 합니다.");
  //: throw 가 다른 등록을 건드리지 않는다.
  store.subscribe("job", () => {});
  assert.equal(store.listenerCount("job"), 1);
});

test("리스너 예외는 경보로 재진술되고 나머지 통지는 계속된다(격리)", () => {
  const alarms = [];
  const store = storeWith(alarms);
  const order = [];
  store.subscribe("job", () => { order.push("first"); throw new Error("소비자 결함"); });
  store.subscribe("job", () => { order.push("second"); });

  //: ingest 자신은 던지지 않는다 — 이 호출이 renderers 체인의 legacy render 앞자리다.
  store.ingest("job", { rows: 1 });

  assert.deepEqual(order, ["first", "second"],
    "던지는 리스너가 형제 통지를 죽였습니다 — legacy render 까지 같은 사슬로 죽는 자리입니다.");
  assert.equal(alarms.length, 1);
  assert.match(alarms[0], /job/, "경보가 어느 채널에서 실패했는지 이름을 대지 않습니다.");
  assert.match(alarms[0], /소비자 결함/);
});

test("당김 착지 — 빈 채널의 당김은 정본이고, push 뒤의 낡은 당김은 적용되지 않는다", () => {
  const store = storeWith();

  //: 부팅 형상 — 당김 시작 시점 revision 0, 그 사이 push 없음 → 적용.
  const since = store.revision("library");
  const applied = store.ingestPulled("library", { boot: true }, since);
  assert.deepEqual(applied, { applied: true, revision: 1 });
  assert.deepEqual(store.get("library"), { boot: true });

  //: 경합 형상 — 당김이 나가 있는 동안 push 가 착지했다 → 낡은 당김은 정본 역전이라 기각.
  const raceSince = store.revision("library");
  store.ingest("library", { newer: true });
  const rejected = store.ingestPulled("library", { stale: true }, raceSince);
  assert.equal(rejected.applied, false,
    "push 뒤의 낡은 당김이 적용됐습니다 — 최신 상태가 과거로 되감깁니다.");
  assert.equal(rejected.revision, store.revision("library"),
    "기각 반환이 현재 revision 을 알리지 않습니다 — 호출자가 재당김을 판단할 수 없습니다.");
  assert.deepEqual(store.get("library"), { newer: true }, "기각인데 값이 바뀌었습니다.");
});

test("subscriber 는 채널별 안정 참조다 — useSyncExternalStore 재구독 요동의 방어선", () => {
  const store = storeWith();

  assert.equal(store.subscriber("job"), store.subscriber("job"),
    "같은 채널의 subscribe 참조가 호출마다 다릅니다 — 매 렌더 해제→재구독이 됩니다.");
  assert.notEqual(store.subscriber("job"), store.subscriber("library"));

  //: 안정 참조 경로도 같은 등록·해제 계약을 진다.
  let calls = 0;
  const unsubscribe = store.subscriber("job")(() => { calls += 1; });
  store.ingest("job", { rows: 1 });
  unsubscribe();
  store.ingest("job", { rows: 2 });
  assert.equal(calls, 1);
});

test("계약 밖 채널은 시끄럽게 거절된다 — 빈 채널로 접히면 구독자가 영영 기다린다", () => {
  const store = storeWith();

  for (const call of [
    () => store.ingest("ghost", {}),
    () => store.get("ghost"),
    () => store.revision("ghost"),
    () => store.subscribe("ghost", () => {}),
    () => store.subscriber("ghost"),
    () => store.listenerCount("ghost"),
    () => store.ingestPulled("ghost", {}, 0),
  ]) {
    assert.throws(call, /계약\(SCREEN_ACTIONS\)에 없는 채널/);
  }
  assert.throws(() => store.subscribe("job", null), /함수가 아닙니다/);
});

test("화면 runtime model이 안정된 subscribe/getSnapshot 결속을 직접 낸다", () => {
  const store = storeWith();
  const runtime = createScreenRuntime({ client: { initial: assert.fail }, store });
  const binding = runtime.model("workbench");

  assert.equal(binding.subscribe, runtime.model("workbench").subscribe,
    "화면 model의 subscribe가 안정 참조가 아닙니다 — 인라인 클로저는 재구독 요동을 만듭니다.");

  const snapshot = { open: true };
  store.ingest("workbench", snapshot);
  assert.equal(binding.getSnapshot(), snapshot,
    "getSnapshot이 화면 runtime에 착지한 마지막 도착 참조를 돌려주지 않습니다.");

  //: 결속을 통한 구독도 해제 계약을 진다.
  let calls = 0;
  const unsubscribe = binding.subscribe(() => { calls += 1; });
  store.ingest("workbench", { open: false });
  unsubscribe();
  store.ingest("workbench", { open: true });
  assert.equal(calls, 1);
  assert.equal(runtime.listenerCount("workbench"), 0);
  runtime.dispose();
  assert.equal(store.listenerCount("workbench"), 0);
});
