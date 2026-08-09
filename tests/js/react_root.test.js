/* React root 상태기계·요소 배선 계약 (R2-01 · #405).

   `root.ts` 는 React 를 import 하지 않는 순수 상태기계다 — 여기서 **주입 기록자**로
   그 기계를 직접 잰다: createRoot 요청이 정확히 한 번인가, 커밋-키 가드가 무는가,
   unmount 정산이 정확히 한 번인가. 렌더 실물은 흉내 내지 않는다(가짜 React 금지 —
   기록자는 호출 사실만 기록한다). 실 WebView2 커밋의 증거는
   `tests/test_web_selftest_gate.py`, 마커 판정은 이 파일의 runtime-marker 계약이 진다.

   `.ts` 모듈을 그대로 싣는 것 자체가 계약의 일부다: Node 24 의 type stripping 이 제품
   파일을 무변환으로 실어야 node 게이트와 Vite 빌드가 같은 파일을 본다(`.tsx` 는 이
   단계에서 닫혀 있다 — 패킷 rev2 L16 B2). */
import test from "node:test";
import assert from "node:assert/strict";

import {
  createReactRootController,
  MOUNT_MARKER_ATTRIBUTE,
} from "../../frontend/src/react/root.ts";
import { createAppElement, ReactErrorBoundary } from "../../frontend/src/react/boundary.ts";
import {
  PRODUCT_SCREEN_IDS,
  createProductScreenVisibility,
} from "../../frontend/src/screens/product_screens.ts";
import {
  SCREEN_LIFECYCLE_OWNER_IDS,
  createScreenLifecycleRegistry,
} from "../../frontend/src/screens/screen_lifecycle_registry.ts";
import { judgeReactRuntime } from "../../frontend/src/selftest/probes/react_runtime.js";

/* 커밋 마커를 받는 최소 컨테이너 대역 — 속성 저장소 하나뿐, 거동 판정은 없다. */
function fakeContainer() {
  const attrs = new Map();
  return {
    setAttribute: (key, value) => attrs.set(key, String(value)),
    removeAttribute: (key) => attrs.delete(key),
    getAttribute: (key) => (attrs.has(key) ? attrs.get(key) : null),
  };
}

/* 주입 기록자 — 실 React 없이 「무엇이 몇 번 요청됐는가」만 기록한다. */
function recorder() {
  const calls = { createRoot: 0, rendered: [], unmount: 0 };
  return {
    calls,
    createRoot: () => {
      calls.createRoot += 1;
      return {
        render: (element) => calls.rendered.push(element),
        unmount: () => {
          calls.unmount += 1;
        },
      };
    },
  };
}

function controllerWith(rec, alarms = []) {
  return createReactRootController({
    createRoot: rec.createRoot,
    /* 요소 계약의 축소판 — 최외곽 값이 `onCommit` 을 실어 나른다(root.ts 의 요소 계약). */
    createAppElement: ({ onCommit }) => ({ onCommit }),
    alarm: (message) => alarms.push(message),
  });
}

test("부팅 한 번에 createRoot 요청·렌더가 정확히 한 번씩이다", () => {
  const rec = recorder();
  const controller = controllerWith(rec);
  const container = fakeContainer();

  assert.equal(controller.boot(container), true);

  assert.equal(rec.calls.createRoot, 1);
  assert.equal(rec.calls.rendered.length, 1);
  assert.equal(typeof rec.calls.rendered[0].onCommit, "function");
  //: 커밋 전이다 — 마커도 가드도 아직이다(커밋-키: 요청은 열쇠가 아니다).
  assert.equal(controller.isCommitted(), false);
  assert.equal(container.getAttribute(MOUNT_MARKER_ATTRIBUTE), null);
});

test("커밋이 마커를 심고, 커밋된 마운트가 살아 있는 동안의 재부팅은 throw 다", () => {
  const rec = recorder();
  const controller = controllerWith(rec);
  const container = fakeContainer();
  controller.boot(container);

  //: 기록자가 커밋 성공을 시뮬레이트한다 — 실 React 에선 effect 가 이 콜백을 부른다.
  rec.calls.rendered[0].onCommit();

  assert.equal(controller.isCommitted(), true);
  assert.equal(container.getAttribute(MOUNT_MARKER_ATTRIBUTE), "1");
  assert.throws(
    () => controller.boot(fakeContainer()),
    /이미 커밋된 채 살아 있습니다/,
    "커밋된 마운트 위의 재부팅이 조용히 지나갔습니다 — 두 번째 실행 경로입니다.",
  );
});

test("커밋이 성립하지 않은 환경에선 가드가 무장되지 않는다(합성 루트 반복 부팅의 형상)", () => {
  const rec = recorder();
  const controller = controllerWith(rec);

  //: bootstrap.test.js 는 한 모듈 인스턴스에서 bootProduct() 를 여러 번 부른다 — 그
  //: 환경에선 커밋이 성립하지 않으므로 요청-키였다면 여기서 죽는다(L16 N1).
  for (let round = 0; round < 3; round += 1) {
    assert.equal(controller.boot(fakeContainer()), true);
  }
  assert.equal(rec.calls.createRoot, 3);
});

test("unmount 는 정확히 1회 정산이고, 정산할 것이 없는 호출은 throw 다", () => {
  const rec = recorder();
  const controller = controllerWith(rec);
  const container = fakeContainer();
  controller.boot(container);
  rec.calls.rendered[0].onCommit();

  controller.unmount();

  assert.equal(rec.calls.unmount, 1);
  assert.equal(controller.isCommitted(), false);
  assert.equal(container.getAttribute(MOUNT_MARKER_ATTRIBUTE), null,
    "정산 뒤에도 커밋 마커가 남아 있습니다 — 죽은 마운트가 산 것으로 읽힙니다.");
  assert.throws(() => controller.unmount(), /정확히 1회/,
    "이중 정산이 조용히 지나갔습니다.");
  assert.equal(rec.calls.unmount, 1, "이중 정산이 기반 unmount 를 두 번 불렀습니다.");
  //: 정산 뒤의 재부팅은 정상 경로다 — 가드는 「살아 있는 커밋」에만 문다.
  assert.equal(controller.boot(container), true);
});

test("createRoot 실패는 경보 후 false 다 — 조용한 폴백도, 예외 탈출도 없다", () => {
  const alarms = [];
  const controller = createReactRootController({
    createRoot: () => {
      throw new Error("대역 DOM 거절");
    },
    createAppElement: ({ onCommit }) => ({ onCommit }),
    alarm: (message) => alarms.push(message),
  });

  assert.equal(controller.boot(fakeContainer()), false);

  assert.equal(alarms.length, 1);
  assert.match(alarms[0], /React root 부팅 실패/);
  //: 실패한 부팅은 상태를 남기지 않는다 — 재시도가 새 요청으로 선다.
  assert.equal(controller.boot(fakeContainer()), false);
  assert.equal(alarms.length, 2);
});

test("실물 요소 배선 — 경계가 최외곽이고 다섯 자식이 요소 계약대로 실려 있다", () => {
  const onCommit = () => {};
  const alarm = () => {};
  const store = { channels: [], subscriber: () => () => () => {}, revision: () => 0 };
  const reflectStoreRevision = () => {};
  const overlay = { doc: {}, notify: () => {} };
  const shell = {
    nav: { markReady: () => {} },
    attachments: [],
    catchUp: [],
    boot: { win: { addEventListener: () => {}, removeEventListener: () => {} },
      hostReady: () => false, initSequence: [] },
  };
  const screens = { doc: {}, portals: [] };

  const element = createAppElement({
    onCommit, alarm, store, reflectStoreRevision, overlay, shell, screens,
  });

  assert.equal(element.type, ReactErrorBoundary,
    "최외곽 요소가 오류 경계가 아닙니다 — 렌더 실패가 경계 밖으로 샙니다.");
  assert.equal(element.props.alarm, alarm);
  assert.equal(element.props.onCommit, onCommit,
    "커밋 신호가 최외곽 props 에 없습니다 — 렌더 실물 없는 기록자가 커밋 경로에 닿지 못합니다.");
  /* 마운트·store·overlay·shell·screen portal host가
     각각 독립 자식이다. */
  const children = element.props.children;
  assert.equal(Array.isArray(children), true, "신호 자식이 배열이 아닙니다 — 형제 자식이 사라졌습니다.");
  assert.equal(children.length, 5,
    "자식이 정확히 다섯(MountSignal·StoreSignal·OverlayHost·ShellHost·ScreenMigrationHost)이어야 합니다.");
  const [mountSignal, storeSignal, overlayHost, shellHost, screenHost] = children;
  assert.equal(typeof mountSignal.type, "function", "마운트 신호 자식이 없습니다.");
  assert.equal(mountSignal.props.onCommit, onCommit);
  assert.equal(typeof storeSignal.type, "function", "store 신호 자식이 없습니다.");
  assert.equal(storeSignal.props.store, store,
    "StoreSignal 이 주입된 store 와 다른 객체를 받았습니다.");
  assert.equal(storeSignal.props.reflectStoreRevision, reflectStoreRevision,
    "StoreSignal 의 반영 sink 가 주입된 콜백이 아닙니다 — DOM 직접 판독으로 흐른 자리입니다.");
  assert.equal(typeof overlayHost.type, "function", "overlay host 자식이 없습니다.");
  assert.equal(overlayHost.props.doc, overlay.doc,
    "OverlayHost 가 주입된 overlay 포트와 다른 doc 을 받았습니다.");
  assert.equal(overlayHost.props.notify, overlay.notify,
    "OverlayHost 의 notify 가 주입된 콜백이 아닙니다 — 실패 재진술이 다른 통로로 샙니다.");
  assert.equal(typeof shellHost.type, "function", "shell host 자식이 없습니다.");
  assert.equal(shellHost.props.nav, shell.nav,
    "ShellHost 가 주입된 상태기계와 다른 객체를 받았습니다.");
  assert.equal(shellHost.props.attachments, shell.attachments,
    "ShellHost 의 리스너 서술이 주입분과 다릅니다 — adapter 캡처 시점 계약이 깨집니다.");
  assert.equal(shellHost.props.boot, shell.boot,
    "ShellHost 의 부팅 서술이 주입분과 다릅니다 — 시퀀서가 다른 세계를 봅니다.");
  assert.equal(typeof screenHost.type, "function", "screen portal host 자식이 없습니다.");
  assert.equal(screenHost.props.doc, screens.doc);
  assert.equal(screenHost.props.portals, screens.portals);
});

test("제품 배선은 컨테이너 부재를 침묵으로 접지 않는다", async () => {
  const { bootReactRoot, REACT_ROOT_ID } = await import("../../frontend/src/react/boot.ts");
  const alarms = [];

  const booted = bootReactRoot({
    doc: { getElementById: () => null },
    alarm: (message) => alarms.push(message),
    store: { channels: [], subscriber: () => () => () => {}, revision: () => 0 },
    overlay: { doc: {}, notify: () => {} },
  });

  assert.equal(booted, false);
  assert.equal(alarms.length, 1);
  assert.match(alarms[0], new RegExp(REACT_ROOT_ID),
    "경보가 어느 컨테이너가 없는지 이름을 대지 않습니다.");
});

test("제품 화면 visibility는 한 활성 화면만 동기 발행한다", () => {
  assert.deepEqual([...PRODUCT_SCREEN_IDS], ["library", "job", "editor", "workbench"]);
  assert.equal(Object.isFrozen(PRODUCT_SCREEN_IDS), true);

  const visibility = createProductScreenVisibility("job");
  const seen = [];
  const release = visibility.subscribe(() => seen.push(visibility.getSnapshot()));
  visibility.activate("library");
  visibility.activate("library");
  visibility.activate("editor");
  assert.deepEqual(seen, ["library", "editor"]);
  assert.throws(() => visibility.activate("settings"), /알 수 없는 제품 화면/);
  release();
  visibility.activate("workbench");
  assert.deepEqual(seen, ["library", "editor"]);
});

test("화면 lifecycle registry는 owner만 위임하고 중복·해제 뒤 호출을 거절한다", () => {
  assert.deepEqual([...SCREEN_LIFECYCLE_OWNER_IDS], ["editor", "workbench"]);
  const registry = createScreenLifecycleRegistry();
  const calls = [];
  const release = registry.register("editor", {
    leaveTo: (target) => calls.push(["leave", target]),
    rerender: () => calls.push(["rerender"]),
  });
  assert.equal(registry.delegateLeave("library", "job"), false);
  assert.equal(registry.delegateLeave("editor", "job"), true);
  assert.equal(registry.rerender("editor"), true);
  assert.deepEqual(calls, [["leave", "job"], ["rerender"]]);
  assert.throws(() => registry.register("editor", {}), /중복 등록/);
  assert.throws(() => registry.register("settings", {}), /집합 밖 등록/);
  release();
  assert.throws(() => registry.delegateLeave("editor", "job"), /해제된 뒤 호출/);
  assert.throws(release, /두 번 해제/);
});

test("React runtime marker 판정은 commit·revision·단일 root 세 축을 모두 문다", () => {
  assert.equal(judgeReactRuntime({ mounted: "1", store_rev: "12", roots: 1 }), null);
  for (const [value, reason] of [
    [{ mounted: "0", store_rev: "12", roots: 1 }, /data-react-mounted/],
    [{ mounted: "1", store_rev: "stale", roots: 1 }, /data-react-store-rev/],
    [{ mounted: "1", store_rev: "12", roots: 2 }, /정확히 1/],
  ]) {
    assert.match(judgeReactRuntime(value), reason);
  }
});
