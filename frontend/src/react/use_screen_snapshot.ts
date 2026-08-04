/* 화면 스냅샷 hook (R2-03 · #407) — store 와 React 를 잇는 유일한 결합면.

   store(`state/store.ts`)는 React 를 모르고, component 는 store 내부를 모른다 — 이 파일이
   그 사이를 `useSyncExternalStore` **위임**으로 잇는다. Strict Mode 의 구독→해제→재구독,
   remount, 동시성 tearing 은 React 가 소유한 문제이고, store 는 그 계약(해제 가능한 구독·
   getSnapshot 참조 안정)만 지면 된다. 외부 상태 라이브러리 채택이 아니다 — React 내장
   API 다(ADR-09 「요구 증명 전 라이브러리 금지」 준수).

   ## subscribe 는 채널별 안정 참조여야 한다

   `useSyncExternalStore` 는 subscribe **함수 참조**가 렌더마다 바뀌면 매 렌더 해제→재구독
   한다(getSnapshot 참조는 무관). 그래서 subscribe 는 인라인 클로저가 아니라 store 의
   채널별 고정 바인딩(`store.subscriber(screen)`)이다 — 참조 동일성 자체가 계약이고 node
   테스트가 직접 묻는다(주입 기록자는 실 렌더 루프가 없어 재구독 요동을 못 보므로).

   ## 검증의 분업 (R2-01 선례)

   결속의 옳음(subscribe/getSnapshot 이 store 표면에 옳게 붙는가)은 `bindScreenSnapshot`
   을 node 가 직접 잰다. 실 React 렌더 루프 위에서 실제로 도는가는 이 hook 을 소비하는
   유일한 실물(`boundary.ts` 의 StoreSignal)을 실 WebView2 게이트가 마커 되읽기로 잰다. */
import { useSyncExternalStore } from "react";
import type { ScreenName } from "../contract/contract.gen.ts";
import type { SnapshotListener, SnapshotStore } from "../state/store.ts";

/** hook 이 `useSyncExternalStore` 에 넘기는 결속 쌍 — 순수 함수라 node 가 직접 잰다. */
export function bindScreenSnapshot(store: SnapshotStore, screen: ScreenName): {
  subscribe: (listener: SnapshotListener) => () => void;
  getSnapshot: () => unknown;
} {
  return {
    subscribe: store.subscriber(screen),
    getSnapshot: () => store.get(screen),
  };
}

/** 화면 채널 하나의 최신 스냅샷을 구독한다 — 도착 전엔 `null`. */
export function useScreenSnapshot(store: SnapshotStore, screen: ScreenName): unknown {
  const binding = bindScreenSnapshot(store, screen);
  return useSyncExternalStore(binding.subscribe, binding.getSnapshot);
}
